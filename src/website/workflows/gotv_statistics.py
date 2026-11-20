"""Record GOTV statistics and their live projection in one transaction."""

import json
import logging
from datetime import datetime

from src.website.domains.demos.demo_parser import normalize_map_name
from src.website.domains.operations.legacy_live_state import _active_map_slots, _sanitize_live_state
from src.website.domains.operations.live_log import record_ingest_status
from src.website.domains.operations.live_rosters import (
    roster_side_by_steamid as _roster_side_by_steamid,
)
from src.website.domains.operations.live_service import read_ingest_number as _bounded_number
from src.website.domains.operations.live_service import update_unconfirmed_map_slots
from src.website.domains.operations.live_sources import receive_gotv
from src.website.domains.statistics.performance_service import refresh_player_performance
from src.website.domains.statistics.stats_calc import (
    HLTV2_ESTIMATE_METHOD,
    calculate_rating,
    estimate_hltv2_impact,
    non_negative_impact,
)
from src.website.domains.statistics.stats_storage import insert_match_stat
from src.website.runtime.host import HostError, is_managed_match
from src.website.workflows.recorded_map_result import save_halftime_data
from src.website.workflows.recorded_player import resolve_recorded_player

logger = logging.getLogger("80gotv")


def store_gotv_statistics(
    conn,
    match_id,
    players,
    map_name,
    team_a_name,
    team_b_name,
    team_a_score,
    team_b_score,
    rounds_count,
    halftime,
    map_run_id=None,
):
    if is_managed_match(conn, match_id):
        expected = _bounded_number(
            {"map_run_id": map_run_id}, "map_run_id", 1, 2**53 - 1, integer=True
        )
        conn.execute("BEGIN IMMEDIATE")
        return receive_gotv(
            conn,
            match_id,
            map_name,
            players,
            team_a_name,
            team_b_name,
            team_a_score,
            team_b_score,
            rounds_count,
            halftime,
            expected,
        )
    conn.execute("UPDATE matches SET status=status WHERE id=?", (match_id,))
    match = conn.execute(
        """
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        WHERE m.id=?
    """,
        (match_id,),
    ).fetchone()
    if not match:
        raise HostError("比赛不存在", 404)
    if match["status"] in {"completed", "cancelled"}:
        raise HostError("比赛已结束或取消，拒绝覆盖统计数据", 409)

    live_row = conn.execute(
        "SELECT live_state FROM live_match_data WHERE match_id=?", (match_id,)
    ).fetchone()
    if live_row and live_row["live_state"]:
        try:
            live_state = json.loads(live_row["live_state"])
        except (TypeError, ValueError, json.JSONDecodeError):
            live_state = {}
        live_state = _sanitize_live_state(live_state)
        if live_state.get("gsi_session_id") or live_state.get("latest_map_result"):
            raise HostError("导播数据已负责本场比赛，GOTV 只能旁观不能覆盖", 409)

    # 查找地图槽位
    map_names = [match["map1"], match["map2"], match["map3"], match["map4"], match["map5"]]
    matching_slots = [
        slot
        for slot in _active_map_slots(match)
        if map_names[slot] and normalize_map_name(map_names[slot]) == normalize_map_name(map_name)
    ]
    if len(matching_slots) != 1:
        raise HostError("推送地图不在该比赛赛程中", 409)
    map_slot = matching_slots[0]

    # 使用数据库中已定义的地图名（回退到 demo 中的地图名）
    db_map_name = (
        map_names[map_slot] if 0 <= map_slot < len(map_names) and map_names[map_slot] else map_name
    )
    confirmed_stats = conn.execute(
        """SELECT 1 FROM match_stats WHERE match_id=? AND map_name=?
           AND COALESCE(data_status,'final')='final' LIMIT 1""",
        (match_id, db_map_name),
    ).fetchone()
    if confirmed_stats:
        raise HostError("该地图已有确认统计，请使用明确结算或 Demo 修订，不能被中途数据覆盖", 409)

    # 判断 A→T1 映射：比较 GOTV team_a name 与数据库中 team1 name
    t1_labels = {str(match[key] or "").strip().casefold() for key in ("team1_name", "t1s")}
    t2_labels = {str(match[key] or "").strip().casefold() for key in ("team2_name", "t2s")}
    t1_labels.discard("")
    t2_labels.discard("")
    team_a_key = str(team_a_name or "").strip().casefold()
    team_b_key = str(team_b_name or "").strip().casefold()
    if team_a_key in t1_labels and team_b_key in t2_labels:
        a_to_t1 = True
    elif team_a_key in t2_labels and team_b_key in t1_labels:
        a_to_t1 = False
    else:
        raise HostError("无法确认 GOTV 队伍对应关系，拒绝猜测覆盖", 409)
    known_sides = _roster_side_by_steamid(conn, match)
    for player in players:
        expected = "team1" if (player["team_letter"] == "A") == a_to_t1 else "team2"
        if known_sides.get(str(player["steam_id"]).strip()) not in (None, expected):
            raise HostError("GOTV 队伍归属与比赛名单不一致", 409)

    stats = []
    for player in players:
        stat = dict(player)
        for key in (
            "kills",
            "deaths",
            "assists",
            "rounds_played",
            "first_kill_count",
            "first_death_count",
            "mvp_count",
            "trade_kills",
            "trade_deaths",
            "bomb_plants",
            "bomb_defuses",
            "flash_assists",
            "multi1k",
            "multi2k",
            "multi3k",
            "multi4k",
            "multi5k",
            "clutches_won",
            "t_kills",
            "ct_kills",
            "t_deaths",
            "ct_deaths",
            "enemies_flashed",
            "flash_count",
            "he_count",
            "smoke_count",
            "molotov_count",
            "clutch_1v1",
            "clutch_1v2",
            "clutch_1v3",
            "clutch_1v4",
            "clutch_1v5",
        ):
            if key in stat:
                stat[key] = _bounded_number(stat, key, 0, 100000, integer=True)
        for key, maximum in (
            ("adr", 10000),
            ("kast", 100),
            ("headshot_percentage", 100),
            ("t_adr", 10000),
            ("ct_adr", 10000),
            ("t_rating", 100000),
            ("ct_rating", 100000),
            ("utility_damage", 100000),
            ("utility_damage_per_round", 100000),
            ("rws_basic", 100),
            ("flash_blinded_seconds", 100000),
            ("flash_enemy_seconds", 100000),
        ):
            if key in stat:
                stat[key] = _bounded_number(stat, key, 0, maximum)
        if "damage_delta_per_round" in stat:
            stat["damage_delta_per_round"] = _bounded_number(
                stat, "damage_delta_per_round", -100000, 100000
            )
        stat.setdefault("rounds_played", rounds_count)
        # Rating 按回归原值算（和 CSDA 一致）；保存的 Impact 最低记 0
        raw_impact = estimate_hltv2_impact(
            stat.get("kills"), stat.get("assists"), stat["rounds_played"]
        )
        stat["impact"] = non_negative_impact(raw_impact)
        stat["rating"], stat["kpr"], stat["dpr"] = calculate_rating(
            stat.get("kills"),
            stat.get("deaths"),
            stat["rounds_played"],
            adr=stat.get("adr"),
            kast=stat.get("kast"),
            impact=raw_impact,
        )
        if not stat["rounds_played"]:
            stat["rating"] = None
        stats.append(stat)

    # 删除该比赛该地图的旧 match_stats（GOTV 推送的是累积数据）
    affected_player_ids = {
        row["player_id"]
        for row in conn.execute(
            """SELECT DISTINCT player_id
               FROM match_stats
               WHERE match_id=? AND map_name=?
                 AND COALESCE(data_status, 'final') <> 'superseded'""",
            (match_id, db_map_name),
        ).fetchall()
        if row["player_id"]
    }
    previous_version = conn.execute(
        """SELECT COALESCE(MAX(data_version), 0) AS version
           FROM match_stats WHERE match_id=? AND map_name=?""",
        (match_id, db_map_name),
    ).fetchone()["version"]
    conn.execute(
        """UPDATE match_stats SET data_status='superseded'
           WHERE match_id=? AND map_name=?
             AND COALESCE(data_status, 'final') <> 'superseded'""",
        (match_id, db_map_name),
    )

    imported = 0
    created = 0
    t1_live_players = []
    t2_live_players = []
    for stat in stats:
        db_player = resolve_recorded_player(conn, stat)
        if not db_player:
            raise HostError("选手无法完整识别，本次统计未保存", 409)
        if db_player.get("_new"):
            created += 1

        letter = stat.get("team_letter", "")
        is_t1 = (letter == "A") if a_to_t1 else (letter != "A")
        team_id = match["team1_id"] if is_t1 else match["team2_id"]
        if not team_id or int(team_id) < 1:
            team_id = None
        live_team = t1_live_players if is_t1 else t2_live_players
        live_team.append(
            {
                "steamid": str(stat.get("steam_id", "")),
                "name": db_player["nickname"],
                "kills": stat.get("kills", 0),
                "deaths": stat.get("deaths", 0),
                "assists": stat.get("assists"),
                "adr": stat.get("adr"),
            }
        )

        stat = dict(stat)
        stat["_data_source"] = "gotv_relay"
        stat["_data_status"] = "provisional"
        stat["_data_version"] = int(previous_version or 0) + 1
        stat.setdefault("rounds_played", rounds_count)
        insert_match_stat(
            conn,
            match_id,
            db_player["id"],
            team_id,
            "t1" if is_t1 else "t2",
            stat,
            db_map_name,
        )
        affected_player_ids.add(db_player["id"])
        imported += 1

    # A cumulative relay frame is not a final map result.
    conn.execute(
        f"UPDATE matches SET map{map_slot + 1}_t1=?,map{map_slot + 1}_t2=? WHERE id=?",
        (
            team_a_score if a_to_t1 else team_b_score,
            team_b_score if a_to_t1 else team_a_score,
            match_id,
        ),
    )
    update_unconfirmed_map_slots(conn, match_id, map_slot, confirmed=False)

    # 保存半场数据
    if halftime and any(halftime.values()):
        save_halftime_data(conn, match_id, map_slot, {"info": {"halftime": halftime}}, a_to_t1)
    refresh_player_performance(conn, affected_player_ids)

    # 存储 GOTV 实时状态到 live_match_data（合并已有数据）
    gotv_state = {
        "map_name": db_map_name,
        "map_slot": map_slot,
        "team_a_score": team_a_score,
        "team_b_score": team_b_score,
        "team1_score": team_a_score if a_to_t1 else team_b_score,
        "team2_score": team_b_score if a_to_t1 else team_a_score,
        "team1_name": match["team1_name"] or team_a_name or "TBD",
        "team2_name": match["team2_name"] or team_b_name or "TBD",
        "t1_players": t1_live_players,
        "t2_players": t2_live_players,
        "rounds_count": rounds_count,
        "halftime": halftime,
        "player_count": len(players),
        "last_push": datetime.now().isoformat(),
        "rating_method": HLTV2_ESTIMATE_METHOD,
    }
    existing = conn.execute(
        "SELECT live_state FROM live_match_data WHERE match_id=?", (match_id,)
    ).fetchone()
    merged = {}
    if existing and existing["live_state"]:
        try:
            merged = json.loads(existing["live_state"])
        except (ValueError, TypeError):
            pass
    merged = _sanitize_live_state(merged)
    merged["gotv"] = gotv_state
    record_ingest_status(conn, "gotv", "ok", "GOTV Relay 数据正常", match_id, db_map_name)

    conn.execute(
        """
        INSERT INTO live_match_data(match_id, live_state)
        VALUES(?, ?)
        ON CONFLICT(match_id) DO UPDATE SET live_state=excluded.live_state, updated_at=CURRENT_TIMESTAMP
    """,
        (match_id, json.dumps(merged, ensure_ascii=False)),
    )

    logger.info(
        "[GOTV API] match#%s %s → slot %s: %s players, scores %s:%s (created %s)",
        match_id,
        map_name,
        map_slot,
        imported,
        team_a_score,
        team_b_score,
        created,
    )
    return {
        "ok": True,
        "map_slot": map_slot,
        "players_imported": imported,
        "players_created": created,
    }
