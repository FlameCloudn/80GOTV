"""Player nickname history and duplicate-profile helpers."""

import json
from collections import defaultdict

from services.performance_service import refresh_player_performance


def record_player_nickname(conn, player_id, nickname, source="website"):
    """保存一个选手曾经使用过的昵称；重复昵称不会反复写入。"""
    nickname = str(nickname or "").strip()
    if not player_id or not nickname:
        return
    conn.execute(
        """INSERT OR IGNORE INTO player_nickname_history(player_id, nickname, source)
           VALUES(?,?,?)""",
        (player_id, nickname, source),
    )


def update_player_nickname(conn, player_id, nickname, source="website"):
    """修改网站正式昵称，并保留修改前后的昵称记录。"""
    nickname = str(nickname or "").strip()
    if not player_id or not nickname:
        return
    current = conn.execute("SELECT nickname FROM players WHERE id=?", (player_id,)).fetchone()
    if current:
        record_player_nickname(conn, player_id, current["nickname"], "website")
        conn.execute("UPDATE players SET nickname=? WHERE id=?", (nickname, player_id))
        record_player_nickname(conn, player_id, nickname, source)


def record_observed_player_nickname(conn, steam_id, nickname, source):
    """记录 GSI、GOTV 或 Demo 中看到的 Steam 昵称，不覆盖网站正式昵称。"""
    steam_id = str(steam_id or "").strip()
    nickname = str(nickname or "").strip()
    if not steam_id or not nickname:
        return None
    player = conn.execute(
        "SELECT id, nickname FROM players WHERE steam_id=?", (steam_id,)
    ).fetchone()
    if not player:
        return None
    record_player_nickname(conn, player["id"], player["nickname"], "website")
    record_player_nickname(conn, player["id"], nickname, source)
    return player


def load_unique_player_alias_ids(conn):
    """读取不会和其他选手冲突的历史昵称，用于 Demo 兜底识别。"""
    rows = conn.execute("SELECT player_id, nickname FROM player_nickname_history").fetchall()
    aliases = {}
    for row in rows:
        key = str(row["nickname"] or "").strip().casefold()
        if key:
            aliases.setdefault(key, set()).add(row["player_id"])
    return {
        nickname: next(iter(player_ids))
        for nickname, player_ids in aliases.items()
        if len(player_ids) == 1
    }


def _replace_temp_player_id(raw_value, source_id, target_id):
    try:
        player_ids = json.loads(raw_value) if raw_value else []
    except (TypeError, ValueError):
        return raw_value
    if not isinstance(player_ids, list):
        return raw_value
    replaced = []
    for player_id in player_ids:
        try:
            player_id = int(player_id)
        except (TypeError, ValueError):
            continue
        if player_id == source_id:
            player_id = target_id
        if player_id not in replaced:
            replaced.append(player_id)
    return json.dumps(replaced, ensure_ascii=False)


def merge_player_records(conn, source_id, target_id):
    """Merge an explicitly selected duplicate player into the retained profile."""
    source_id = int(source_id)
    target_id = int(target_id)
    if source_id == target_id:
        raise ValueError("不能将选手合并到自己")

    source = conn.execute("SELECT * FROM players WHERE id=?", (source_id,)).fetchone()
    target = conn.execute("SELECT * FROM players WHERE id=?", (target_id,)).fetchone()
    if not source or not target:
        raise ValueError("选手不存在")
    ranking_conflict = conn.execute(
        """SELECT 1 FROM yearly_top_players source
           JOIN yearly_top_players target ON source.year=target.year
           WHERE source.player_id=? AND target.player_id=? LIMIT 1""",
        (source_id, target_id),
    ).fetchone()
    if ranking_conflict:
        raise ValueError("两个选手档案在同一年各有年度排名，请先确认排名后再合并")

    record_player_nickname(conn, target_id, target["nickname"], "website")
    record_player_nickname(conn, target_id, source["nickname"], "merge")
    for alias in conn.execute(
        "SELECT nickname, source FROM player_nickname_history WHERE player_id=?", (source_id,)
    ).fetchall():
        record_player_nickname(conn, target_id, alias["nickname"], alias["source"] or "merge")

    # 只比较当前结果。历史版本保留原值，不再用旧的高击杀行覆盖新的有效结果。
    current_groups = defaultdict(list)
    for stat in conn.execute(
        """SELECT * FROM match_stats WHERE player_id IN (?, ?)
           AND COALESCE(data_status, 'final') <> 'superseded'""",
        (source_id, target_id),
    ).fetchall():
        current_groups[(stat["match_id"], str(stat["map_name"] or "").strip().casefold())].append(
            stat
        )

    def priority(stat):
        return (
            (stat["data_status"] or "final") == "final",
            int(stat["data_version"] or 1),
            int(stat["rounds_played"] or 0),
            sum(int(stat[field] or 0) for field in ("kills", "deaths", "assists")),
            stat["player_id"] == target_id,
            stat["id"],
        )

    for stats in current_groups.values():
        retained = max(stats, key=priority)
        for stat in stats:
            if stat["id"] != retained["id"]:
                conn.execute(
                    "UPDATE match_stats SET data_status='superseded' WHERE id=?", (stat["id"],)
                )
    conn.execute("UPDATE match_stats SET player_id=? WHERE player_id=?", (target_id, source_id))
    conn.execute(
        "UPDATE yearly_top_players SET player_id=? WHERE player_id=?", (target_id, source_id)
    )

    for medal in conn.execute(
        "SELECT * FROM player_medals WHERE player_id=?", (source_id,)
    ).fetchall():
        duplicate = conn.execute(
            """
            SELECT id FROM player_medals
            WHERE player_id=? AND type=?
              AND COALESCE(event_id, 0)=COALESCE(?, 0)
              AND COALESCE(match_id, 0)=COALESCE(?, 0)
        """,
            (target_id, medal["type"], medal["event_id"], medal["match_id"]),
        ).fetchone()
        if duplicate:
            conn.execute("DELETE FROM player_medals WHERE id=?", (medal["id"],))
        else:
            conn.execute(
                "UPDATE player_medals SET player_id=? WHERE id=?", (target_id, medal["id"])
            )

    for match in conn.execute(
        "SELECT id, team1_players, team2_players FROM matches "
        "WHERE team1_players IS NOT NULL OR team2_players IS NOT NULL"
    ).fetchall():
        team1_players = _replace_temp_player_id(match["team1_players"], source_id, target_id)
        team2_players = _replace_temp_player_id(match["team2_players"], source_id, target_id)
        conn.execute(
            "UPDATE matches SET team1_players=?, team2_players=? WHERE id=?",
            (team1_players, team2_players, match["id"]),
        )

    conn.execute(
        """
        UPDATE players SET
            real_name=COALESCE(NULLIF(real_name, ''), ?),
            team_id=COALESCE(team_id, ?),
            steam_id=COALESCE(NULLIF(steam_id, ''), ?),
            avatar=COALESCE(NULLIF(avatar, ''), ?)
        WHERE id=?
    """,
        (source["real_name"], source["team_id"], source["steam_id"], source["avatar"], target_id),
    )
    for column in ("killer_player_id", "victim_player_id", "assister_player_id"):
        conn.execute(
            f"UPDATE match_kill_events SET {column}=? WHERE {column}=?",
            (target_id, source_id),
        )
    conn.execute("DELETE FROM player_nickname_history WHERE player_id=?", (source_id,))
    conn.execute("DELETE FROM players WHERE id=?", (source_id,))
    refresh_player_performance(conn, [target_id])
    return {"source": source["nickname"], "target": target["nickname"]}
