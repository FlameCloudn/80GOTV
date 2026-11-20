"""Record historical Director map results and their statistical revision."""

import hashlib
import json
from datetime import datetime, timezone

from src.website.domains.demos.demo_parser import normalize_map_name
from src.website.domains.matches.match_roster_service import (
    freeze_match_roster,
    resolve_match_roster,
)
from src.website.domains.matches.match_utils import (
    build_raw_maps,
    calculate_map_wins,
    get_bo_max_maps,
)
from src.website.domains.matches.series import get_series_result
from src.website.domains.operations.legacy_live_state import _active_map_slots, _sanitize_live_state
from src.website.domains.operations.live_log import record_ingest_status
from src.website.domains.operations.live_service import (
    parse_director_player_stat as _live_player_stat,
)
from src.website.domains.operations.live_service import read_ingest_number as _bounded_number
from src.website.domains.statistics.performance_service import refresh_player_performance
from src.website.domains.statistics.stats_calc import HLTV2_ESTIMATE_METHOD
from src.website.domains.statistics.stats_storage import insert_match_stat
from src.website.runtime.host import HostError, is_managed_match
from src.website.workflows.director_receipt import receive_director_result
from src.website.workflows.recorded_map_result import sync_match_scores
from src.website.workflows.recorded_player import resolve_recorded_player


def record_broadcast_map_result(conn, payload, match_id):
    raw_map_name = payload.get("map_name")
    map_name = raw_map_name.strip() if isinstance(raw_map_name, str) else ""
    players = payload.get("players")
    if (
        not map_name
        or len(map_name) > 80
        or not isinstance(players, list)
        or not 1 <= len(players) <= 12
    ):
        raise HostError("地图或选手数据不完整", 400)
    if any(
        not isinstance(player, dict) or player.get("team_side") not in ("team1", "team2")
        for player in players
    ):
        raise HostError("选手队伍归属无效", 400)
    supplied_ids = [str(player.get("steam_id") or "").strip() for player in players]
    if any(
        not isinstance(player.get("steam_id"), (str, int))
        or isinstance(player.get("steam_id"), bool)
        for player in players
    ) or any(not steam_id or len(steam_id) > 64 for steam_id in supplied_ids):
        raise HostError("选手 Steam ID 无效", 400)
    if len(set(supplied_ids)) != len(supplied_ids):
        raise HostError("地图结算包含重复 Steam ID", 409)
    if any(
        not isinstance(player.get("name"), str)
        or not player["name"].strip()
        or len(player["name"]) > 80
        for player in players
    ):
        raise HostError("选手名称无效，未保存本次结算", 400)
    team1_score = _bounded_number(payload, "team1_score", 0, 100, integer=True)
    team2_score = _bounded_number(payload, "team2_score", 0, 100, integer=True)
    if team1_score is None or team2_score is None or team1_score == team2_score:
        raise HostError("最终地图比分不能为空或平局", 400)
    if "series_complete" in payload and not isinstance(payload["series_complete"], bool):
        raise HostError("系列赛结束标记无效", 400)
    stats = [_live_player_stat(player) for player in players]
    if is_managed_match(conn, match_id):
        conn.execute("BEGIN IMMEDIATE")
        return receive_director_result(
            conn, match_id, map_name, payload, stats, team1_score, team2_score
        )
    conn.execute("UPDATE matches SET status=status WHERE id=?", (match_id,))
    match = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
    if not match:
        raise HostError("比赛不存在", 404)
    if match["status"] == "cancelled":
        raise HostError("比赛已取消，拒绝覆盖统计数据", 409)

    roster = resolve_match_roster(conn, match)
    locked_roster = set(roster["steam_ids"]) if roster["locked"] else set()
    known_sides = {
        steam_id: "team1" if side == "t1" else "team2"
        for steam_id, side in roster["side_by_steam_id"].items()
    }
    if any(
        known_sides.get(steam_id) not in (None, player["team_side"])
        for steam_id, player in zip(supplied_ids, players)
    ):
        raise HostError("选手队伍归属与比赛名单不一致", 409)
    if locked_roster:
        locked_sides = known_sides
        if len(players) != 10:
            raise HostError("网站已锁定十人名单，地图结算必须包含两队各五人", 409)
        supplied_ids = [str(player.get("steam_id") or "").strip() for player in players]
        if any(not steam_id for steam_id in supplied_ids) or len(set(supplied_ids)) != 10:
            raise HostError("地图结算包含缺失或重复 Steam ID", 409)
        if set(supplied_ids) != locked_roster:
            raise HostError("地图结算名单与网站锁定名单不一致", 409)
        if any(
            locked_sides.get(str(player.get("steam_id")).strip()) != player.get("team_side")
            for player in players
        ):
            raise HostError("地图结算队伍归属与网站名单不一致", 409)

    map_names = [match[f"map{slot}"] for slot in range(1, 6)]
    active_slots = _active_map_slots(match)
    requested_slot = payload.get("map_slot")
    if requested_slot is not None:
        requested_slot = _bounded_number(payload, "map_slot", 1, 5, integer=True)
        assert requested_slot is not None
        configured = map_names[requested_slot - 1]
        if not configured or normalize_map_name(configured) != normalize_map_name(map_name):
            raise HostError("地图槽位与地图名称不一致", 409)
        matching_slots = [requested_slot - 1]
    else:
        matching_slots = [
            index
            for index, configured in enumerate(map_names)
            if index in active_slots
            and configured
            and normalize_map_name(configured) == normalize_map_name(map_name)
        ]
    if not matching_slots or matching_slots[0] not in active_slots:
        raise HostError("推送地图不在该比赛赛程中", 409)
    if len(matching_slots) > 1:
        raise HostError("同名地图存在多个槽位，请明确指定地图槽位", 409)
    map_slot = matching_slots[0]
    db_map_name = map_names[map_slot]
    if (
        not locked_roster
        and conn.execute(
            """SELECT 1 FROM match_stats WHERE match_id=? AND map_name=?
           AND COALESCE(data_status, 'final')='final' LIMIT 1""",
            (match_id, db_map_name),
        ).fetchone()
    ):
        raise HostError("本场十人名单尚未完整确认，保留原正式统计", 409)
    if not stats:
        raise HostError("没有可保存的选手", 400)
    if locked_roster and len(stats) != 10:
        raise HostError("地图结算中有选手数据无法识别，保留原统计", 409)

    result_id = str(payload.get("result_id") or "").strip()
    if len(result_id) > 120:
        raise HostError("结算编号过长", 400)
    payload_fingerprint = hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()
    if not result_id:
        result_id = payload_fingerprint
    existing_live = conn.execute(
        "SELECT live_state FROM live_match_data WHERE match_id=?", (match_id,)
    ).fetchone()
    existing_state = {}
    if existing_live and existing_live["live_state"]:
        try:
            existing_state = json.loads(existing_live["live_state"])
        except (TypeError, ValueError, json.JSONDecodeError):
            existing_state = {}
    previous_result = (
        existing_state.get("latest_map_result") if isinstance(existing_state, dict) else None
    )
    stored_results = (
        existing_state.get("map_results", []) if isinstance(existing_state, dict) else []
    )
    if not isinstance(stored_results, list):
        stored_results = []
    incoming_session = str(payload.get("session_id") or "").strip()
    active_session = (
        str(existing_state.get("gsi_session_id") or "").strip()
        if isinstance(existing_state, dict)
        else ""
    )
    duplicate_result = next(
        (
            item
            for item in stored_results
            if isinstance(item, dict) and item.get("result_id") == result_id
        ),
        None,
    )
    if isinstance(duplicate_result, dict) or (
        isinstance(previous_result, dict) and previous_result.get("result_id") == result_id
    ):
        confirmed_result = (
            duplicate_result if isinstance(duplicate_result, dict) else previous_result
        )
        assert isinstance(confirmed_result, dict)
        recorded_players = {
            str(player.get("steam_id")): player
            for player in confirmed_result.get("players", [])
            if isinstance(player, dict)
        }
        legacy_conflict = not confirmed_result.get("payload_fingerprint") and (
            set(recorded_players) != set(supplied_ids)
            or any(
                stat[field] is not None
                and recorded_players.get(stat["steam_id"], {}).get(field) != stat[field]
                for stat in stats
                for field in ("kills", "deaths", "assists", "adr", "kast")
            )
        )
        if (
            legacy_conflict
            or confirmed_result.get("map_slot") != map_slot
            or confirmed_result.get("team1_score") != team1_score
            or confirmed_result.get("team2_score") != team2_score
            or confirmed_result.get("payload_fingerprint", payload_fingerprint)
            != payload_fingerprint
        ):
            raise HostError("同一结算编号的内容不同，请检查导播数据", 409)
        return {
            "ok": True,
            "duplicate": True,
            "match_id": match_id,
            "map_name": confirmed_result.get("map_name") or map_name,
            "map_slot": map_slot + 1,
            "result_id": result_id,
            "applied": False,
            "saved": len(confirmed_result.get("players") or []),
            "players": confirmed_result.get("players") or [],
            "series_complete": confirmed_result.get("series_complete", False),
        }
    calibrated_demo = conn.execute(
        """SELECT 1 FROM match_stats WHERE match_id=? AND map_name=?
           AND data_source IN ('demo','demo_review')
           AND COALESCE(data_status,'final')='final' LIMIT 1""",
        (match_id, db_map_name),
    ).fetchone()
    if calibrated_demo:
        return {
            "ok": True,
            "match_id": match_id,
            "map_name": db_map_name,
            "map_slot": map_slot + 1,
            "result_id": result_id,
            "applied": False,
            "reason": "demo_authoritative",
        }
    if active_session and incoming_session and active_session != incoming_session:
        raise HostError("地图结算会话与当前导播会话不一致", 409)
    if active_session and not incoming_session:
        raise HostError("当前比赛已有导播会话，拒绝无会话结算覆盖", 409)
    frame_seq = payload.get("frame_seq")
    if match["status"] == "completed":
        raise HostError("比赛已结束，拒绝新的导播结算覆盖", 409)
    if frame_seq is not None:
        frame_seq = _bounded_number(payload, "frame_seq", 0, 2**53 - 1, integer=True)
        assert frame_seq is not None
        try:
            previous_seq_raw = (
                previous_result.get("frame_seq")
                if isinstance(previous_result, dict)
                and previous_result.get("session_id") is not None
                and str(previous_result["session_id"]) == incoming_session
                else None
            )
            previous_seq = int(str(previous_seq_raw)) if previous_seq_raw is not None else None
        except (TypeError, ValueError):
            previous_seq = None
        if previous_seq is not None and frame_seq <= previous_seq:
            raise HostError("较旧的地图结算被拒绝", 409)

    decided, _ = get_series_result(match["bo_format"], match["team1_score"], match["team2_score"])
    if decided and not (match[f"map{map_slot + 1}_t1"] or match[f"map{map_slot + 1}_t2"]):
        raise HostError("系列赛已决出胜负，不能再增加新的地图", 409)
    projected = dict(match)
    projected[f"map{map_slot + 1}_t1"] = team1_score
    projected[f"map{map_slot + 1}_t2"] = team2_score
    unconfirmed = (
        existing_state.get("unconfirmed_map_slots", []) if isinstance(existing_state, dict) else []
    )
    unconfirmed = (
        set(unconfirmed)
        if isinstance(unconfirmed, list) and all(isinstance(slot, int) for slot in unconfirmed)
        else set()
    )
    unconfirmed.discard(map_slot)
    raw_maps = [
        (name, score1, score2, active and slot not in unconfirmed)
        for slot, (name, score1, score2, active) in enumerate(
            build_raw_maps(projected, include_picked_by=False)
        )
    ]
    wins1, wins2 = calculate_map_wins(projected, raw_maps)
    wins_needed = get_bo_max_maps(match["bo_format"]) // 2 + 1
    if max(wins1, wins2) > wins_needed or min(wins1, wins2) >= wins_needed:
        raise HostError("地图结果与系列赛赛制冲突", 409)
    series_complete = bool(get_series_result(match["bo_format"], wins1, wins2)[0])
    if payload.get("series_complete") and not series_complete:
        raise HostError("系列赛尚未决胜，不能标记为已完成", 409)

    affected_player_ids = {
        row["player_id"]
        for row in conn.execute(
            """SELECT DISTINCT player_id FROM match_stats
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
    saved_players = []
    for stat in stats:
        stat["_data_source"] = "director_final" if locked_roster else "director_live"
        stat["_data_status"] = "final" if locked_roster else "provisional"
        stat["_data_version"] = int(previous_version or 0) + 1
        db_player = resolve_recorded_player(conn, stat)
        if not db_player:
            raise HostError("选手无法完整识别，本次结算未保存", 409)
        is_team1 = stat["team_side"] == "team1"
        team_id = match["team1_id"] if is_team1 else match["team2_id"]
        if not team_id or int(team_id) < 1:
            team_id = None
        match_side = "t1" if is_team1 else "t2"
        insert_match_stat(
            conn,
            match_id,
            db_player["id"],
            team_id,
            match_side,
            stat,
            db_map_name,
        )
        affected_player_ids.add(db_player["id"])
        saved_players.append(
            {
                "steam_id": stat["steam_id"],
                "name": db_player["nickname"],
                "team_side": match_side,
                "kills": stat["kills"],
                "deaths": stat["deaths"],
                "assists": stat["assists"],
                "adr": stat["adr"],
                "kast": stat["kast"],
                "impact": stat["impact"],
                "rating": stat["rating"],
            }
        )

    if locked_roster and len(saved_players) != 10:
        raise HostError("无法完整解析网站锁定的十名选手，原统计未替换", 409)

    if not sync_match_scores(
        conn,
        match_id,
        map_slot,
        {"team_a_score": team1_score, "team_b_score": team2_score},
        True,
    ):
        raise HostError("地图比分无法保存，本次结算未保存", 409)
    refresh_player_performance(conn, affected_player_ids)
    if locked_roster:
        freeze_match_roster(conn, match, confirmed=True)

    existing = conn.execute(
        "SELECT live_state FROM live_match_data WHERE match_id=?", (match_id,)
    ).fetchone()
    merged = {}
    if existing and existing["live_state"]:
        try:
            merged = json.loads(existing["live_state"])
        except (TypeError, ValueError):
            pass
    merged = _sanitize_live_state(merged)
    result_record = {
        "result_id": result_id,
        "payload_fingerprint": payload_fingerprint,
        "session_id": incoming_session,
        "frame_seq": frame_seq,
        "map_name": db_map_name,
        "map_slot": map_slot,
        "team1_score": team1_score,
        "team2_score": team2_score,
        "series_complete": series_complete,
        "rating_method": HLTV2_ESTIMATE_METHOD,
        "data_source": "director_final" if locked_roster else "director_live",
        "data_status": "final" if locked_roster else "provisional",
        "players": saved_players,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }
    merged["latest_map_result"] = result_record
    merged["map_results"] = [
        item
        for item in stored_results
        if isinstance(item, dict) and item.get("map_slot") != map_slot
    ] + [result_record]
    conn.execute(
        """
        INSERT INTO live_match_data(match_id, live_state)
        VALUES(?, ?)
        ON CONFLICT(match_id) DO UPDATE SET live_state=excluded.live_state, updated_at=CURRENT_TIMESTAMP
        """,
        (match_id, json.dumps(merged, ensure_ascii=False)),
    )
    record_ingest_status(
        conn,
        "director_result",
        "ok",
        f"{db_map_name} 已保存 {len(saved_players)} 名选手 Rating",
        match_id,
        db_map_name,
    )
    return {
        "ok": True,
        "match_id": match_id,
        "map_name": db_map_name,
        "map_slot": map_slot + 1,
        "result_id": result_id,
        "applied": True,
        "saved": len(saved_players),
        "players": saved_players,
        "series_complete": series_complete,
    }
