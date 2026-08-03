"""Player nickname history and duplicate-profile helpers."""

import json

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

    record_player_nickname(conn, target_id, target["nickname"], "website")
    record_player_nickname(conn, target_id, source["nickname"], "merge")
    for alias in conn.execute(
        "SELECT nickname, source FROM player_nickname_history WHERE player_id=?", (source_id,)
    ).fetchall():
        record_player_nickname(conn, target_id, alias["nickname"], alias["source"] or "merge")

    # If both profiles appear on the same map, keep the richer row instead of double counting.
    source_stats = conn.execute(
        "SELECT * FROM match_stats WHERE player_id=?", (source_id,)
    ).fetchall()
    stat_columns = [
        "team_id",
        "kills",
        "deaths",
        "assists",
        "adr",
        "kpr",
        "dpr",
        "rating",
        "impact",
        "kast",
        "headshot_percentage",
        "clutches_won",
        "side",
        "t_rating",
        "ct_rating",
        "t_kills",
        "ct_kills",
        "t_deaths",
        "ct_deaths",
        "t_adr",
        "ct_adr",
        "multi1k",
        "multi2k",
        "multi3k",
        "multi4k",
        "multi5k",
        "first_kills",
        "first_deaths",
        "mvp_count",
        "utility_damage",
        "enemies_flashed",
        "flash_count",
        "he_count",
        "smoke_count",
        "molotov_count",
        "trade_kills",
        "trade_deaths",
        "bomb_plants",
        "bomb_defuses",
        "utility_damage_per_round",
        "rounds_played",
        "damage_delta_per_round",
        "rws_basic",
        "clutch_1v1",
        "clutch_1v2",
        "clutch_1v3",
        "clutch_1v4",
        "clutch_1v5",
        "flash_blinded_seconds",
        "flash_enemy_seconds",
        "flash_assists",
    ]
    for stat in source_stats:
        existing = conn.execute(
            """
            SELECT * FROM match_stats
            WHERE player_id=? AND match_id=?
              AND COALESCE(map_name, '')=COALESCE(?, '')
            LIMIT 1
        """,
            (target_id, stat["match_id"], stat["map_name"]),
        ).fetchone()
        if not existing:
            conn.execute("UPDATE match_stats SET player_id=? WHERE id=?", (target_id, stat["id"]))
            continue
        source_weight = (
            int(stat["kills"] or 0) + int(stat["deaths"] or 0) + int(stat["assists"] or 0)
        )
        target_weight = (
            int(existing["kills"] or 0)
            + int(existing["deaths"] or 0)
            + int(existing["assists"] or 0)
        )
        if source_weight > target_weight:
            assignments = ", ".join(f"{column}=?" for column in stat_columns)
            conn.execute(
                f"UPDATE match_stats SET {assignments} WHERE id=?",
                tuple(stat[column] for column in stat_columns) + (existing["id"],),
            )
        conn.execute("DELETE FROM match_stats WHERE id=?", (stat["id"],))

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
