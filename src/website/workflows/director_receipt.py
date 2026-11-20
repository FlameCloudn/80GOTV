"""Durable terminal receipts for the original director outbox."""

import hashlib
import json

from src.website.domains.matches.series import get_series_result
from src.website.domains.operations import run_control as operations
from src.website.domains.operations.live_log import record_ingest_status
from src.website.domains.operations.live_service import read_ingest_number
from src.website.domains.operations.projection import (
    live_schema_ready,
    load_snapshot,
    parse_session_id,
    register_director_session,
    require_start_authorization,
    resolve_run,
    resolve_schedule,
    run_lineup,
)
from src.website.domains.statistics import statistics
from src.website.runtime.host import HostError

_EXPLICIT_COUNTS = {
    "roundsPlayed": "rounds_played",
    "kills": "kills",
    "deaths": "deaths",
    "assists": "assists",
    "firstKills": "first_kill_count",
    "firstDeaths": "first_death_count",
    "mvpCount": "mvp_count",
    "clutchesWon": "clutches_won",
    "tradeKills": "trade_kills",
    "tradeDeaths": "trade_deaths",
    "bombPlants": "bomb_plants",
    "bombDefuses": "bomb_defuses",
    "flashAssists": "flash_assists",
}


def _adopt_player_fields(conn, run_id, result_id, payload_players, stats, lineup):
    participation = {
        row["player_id"]: row["is_current"]
        for row in conn.execute(
            "SELECT player_id,is_current FROM run_participations WHERE map_run_id=?", (run_id,)
        )
    }
    reports = []
    candidates = []
    new_participation = False
    for raw, stat in zip(payload_players, stats):
        steam_id = stat["steam_id"]
        member = lineup[steam_id]
        player_id = member["player_id"]
        fields = {
            field: stat[field]
            for key, field in _EXPLICIT_COUNTS.items()
            if raw.get(key) is not None
        }
        # The existing endpoint parser validates these inputs but returns their derived rates.
        if raw.get("damage") is not None:
            fields["damage"] = float(raw["damage"])
        if raw.get("kastRounds") is not None:
            fields["kast_rounds"] = int(float(raw["kastRounds"]))
        if raw.get("headshots") is not None:
            fields["headshot_kills"] = int(float(raw["headshots"]))
        candidates.append({"player_id": player_id, "steam_id": steam_id, "fields": fields})
        report = {
            "player_id": player_id,
            "steam_id": steam_id,
            "applied_fields": [],
            "conflicts": {},
        }
        reports.append(report)
        if participation.get(player_id) == 0:
            report["status"] = "participation_protected"
            continue
        if player_id not in participation:
            if not any(fields.values()):
                report["status"] = "participation_unproven"
                continue
            operations.record_participation(
                conn, run_id, player_id, member["match_participant_id"], source="director"
            )
            new_participation = True
        adopted = statistics.apply_fields(
            conn,
            run_id,
            player_id,
            "all",
            fields,
            source={"kind": "director", "ref": result_id, "method": "terminal"},
            actor="director",
        )
        report.update(
            status=adopted["status"],
            applied_fields=sorted(adopted["changes"]) if adopted["applied"] else [],
            conflicts={
                key: {
                    "current": item["before"],
                    "reported": item["after"],
                    "source": item["previous_source"]["source"],
                }
                for key, item in adopted["conflicts"].items()
            },
        )
    return candidates, reports, new_participation


def receive_director_result(conn, match_id, map_name, payload, stats, score1, score2):
    if not live_schema_ready(conn):
        require_start_authorization(conn, match_id)
    result_id = payload.get("result_id")
    if result_id is not None and (not isinstance(result_id, str) or len(result_id.strip()) > 120):
        raise HostError("结算编号格式错误", 400)
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    fingerprint = hashlib.blake2s(canonical.encode("utf-8")).hexdigest()
    result_id = (result_id or "").strip() or fingerprint
    prior = conn.execute(
        """SELECT payload_fingerprint,response FROM live_director_receipts
           WHERE match_id=? AND result_id=?""",
        (match_id, result_id),
    ).fetchone()
    if prior:
        if prior["payload_fingerprint"] != fingerprint:
            raise HostError("同一结算编号的内容不同，请检查导播数据")
        return dict(json.loads(prior["response"]), applied=False, map_applied=False, duplicate=True)

    require_start_authorization(conn, match_id)
    slot = read_ingest_number(payload, "map_slot", 1, 5, integer=True)
    expected_run = read_ingest_number(payload, "map_run_id", 1, 2**53 - 1, integer=True)
    seq = read_ingest_number(payload, "frame_seq", 0, 2**53 - 1, integer=True)
    revision = read_ingest_number(payload, "expected_revision", 0, 2**53 - 1, integer=True)
    session = parse_session_id(payload.get("session_id"), match_id)
    plan = resolve_schedule(conn, match_id, map_name, slot)
    scheduled_id = plan["scheduled_map_id"]
    run = resolve_run(conn, scheduled_id, expected_run, session_id=session)
    if not run:
        raise HostError("尚未确认这张图实际开打，请先核对本局开局再重发结算")
    run_id = run["map_run_id"]

    lineup = run_lineup(conn, run_id)
    if {stat["steam_id"] for stat in stats} != lineup.keys():
        raise HostError("地图结算须包含本局批准的两队各五名选手")
    for stat in stats:
        side = {"home": "team1", "away": "team2"}[lineup[stat["steam_id"]]["side_key"]]
        if stat["team_side"] != side:
            raise HostError("地图结算的队伍归属与本局名单不一致")

    snapshot = load_snapshot(conn, match_id)
    if snapshot.get("map_run_id") == run_id:
        active_session = snapshot.get("gsi_session_id")
        if active_session and active_session != session:
            raise HostError("地图结算会话与本局正在使用的导播会话不一致")
        observed = snapshot.get("observed_score")
        if observed and (score1 < observed[0] or score2 < observed[1]):
            raise HostError("最终比分早于本局已接收的比分，请核对开局与报文顺序")
    if (
        seq is not None
        and session
        and conn.execute(
            """SELECT 1 FROM live_director_receipts WHERE match_id=? AND session_id=?
           AND frame_seq>=? LIMIT 1""",
            (match_id, session, seq),
        ).fetchone()
    ):
        raise HostError("较旧的地图结算被拒绝")

    from src.website.domains.matches.results import confirm_map, read_results

    candidates, reports, new_participation = _adopt_player_fields(
        conn, run_id, result_id, payload["players"], stats, lineup
    )
    outcome = confirm_map(
        conn,
        match_id,
        scheduled_id,
        run_id,
        score1,
        score2,
        actor="director",
        source="director",
        expected_revision=revision,
        terminal_receipt=result_id,
    )
    series = read_results(conn, match_id)
    winner, _ = get_series_result(series["bo_format"], series["score1"], series["score2"])
    series_complete = winner is not None
    if payload.get("series_complete") and not series_complete:
        raise HostError("系列赛尚未决胜，不能标记为已完成")

    recorded = {
        row[0]
        for row in conn.execute(
            "SELECT round_number FROM map_run_rounds WHERE map_run_id=?", (run_id,)
        )
    }
    missing = set(range(1, score1 + score2 + 1)) - recorded
    for number in sorted(missing):
        operations.record_round(conn, run_id, number, source="director")
    published = {
        row["player_id"]: json.loads(row["overall_json"])
        for row in conn.execute(
            """SELECT player_id,overall_json FROM official_player_map_stats
               WHERE scheduled_map_id=? AND map_run_id=?""",
            (scheduled_id, run_id),
        )
    }
    players = []
    for report in reports:
        if not report["applied_fields"]:
            continue
        member = lineup[report["steam_id"]]
        shown = published.get(member["player_id"], {})
        players.append(
            {
                **{
                    key: shown.get(key)
                    for key in ("kills", "deaths", "assists", "adr", "kast", "impact", "rating")
                },
                "steam_id": report["steam_id"],
                "name": member["name"],
                "team_side": "t1" if member["side_key"] == "home" else "t2",
            }
        )
    applied = bool(outcome["applied"] or players or new_participation or missing)
    has_conflicts = any(
        report["conflicts"] or report["status"] == "participation_protected" for report in reports
    )
    receipt = {
        "ok": True,
        "match_id": match_id,
        "map_name": plan["map_name"],
        "map_slot": plan["legacy_slot"],
        "result_id": result_id,
        "map_run_id": run_id,
        "applied": applied,
        "map_applied": outcome["applied"],
        "saved": len(players),
        "players": players,
        "statistics": reports,
        "series_complete": series_complete,
    }
    if not applied:
        receipt["reason"] = "pending_field_review" if has_conflicts else "already_confirmed"

    if session:
        register_director_session(
            conn, scheduled_id, run_id, session, reason="Director terminal report"
        )
    conn.execute(
        """INSERT INTO live_director_receipts(match_id,result_id,scheduled_map_id,map_run_id,
               session_id,frame_seq,payload_fingerprint,players_candidate,response)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (
            match_id,
            result_id,
            scheduled_id,
            run_id,
            session or None,
            seq,
            fingerprint,
            json.dumps(candidates, ensure_ascii=False, separators=(",", ":")),
            json.dumps(receipt, ensure_ascii=False, separators=(",", ":")),
        ),
    )
    record_ingest_status(
        conn, "director_result", "ok", "已记录本局导播结算回执", match_id, plan["map_name"]
    )
    return receipt
