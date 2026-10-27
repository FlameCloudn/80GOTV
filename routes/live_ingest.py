"""GSI and GOTV live-data receiving endpoints."""

import hashlib
import hmac
import json
from datetime import datetime, timezone

from flask import jsonify, request

from config import Config
from models import get_db
from routes.live import _gsi_team_mapping, _roster_side_by_steamid
from services.bracket_service import BracketDependencyError
from services.demo_service import (
    auto_create_user_from_demo,
    insert_match_stat,
    save_halftime_data,
    sync_match_scores,
)
from services.live_log_service import persist_live_match_events, record_ingest_status
from services.live_service import (
    IngestValidationError,
    _is_recent_iso_timestamp,
    _record_gsi_bomb_events,
    _record_gsi_deaths,
    _round_win_reason,
    _round_win_reason_code,
    has_nonfinite_number,
    update_unconfirmed_map_slots,
)
from services.live_service import (
    parse_director_player_stat as _live_player_stat,
)
from services.live_service import (
    read_ingest_number as _bounded_number,
)
from services.match_roster_service import freeze_match_roster, resolve_match_roster
from services.match_service import get_series_result, supplement_temp_teams
from services.performance_service import refresh_player_performance
from services.player_service import record_observed_player_nickname
from utils.demo_parser import normalize_map_name
from utils.match_utils import (
    build_raw_maps,
    calculate_map_wins,
    get_bo_max_maps,
    get_sql_match_live,
)
from utils.rate_limiter import rate_limit
from utils.stats_calc import (
    HLTV2_ESTIMATE_METHOD,
    calculate_rating,
    estimate_hltv2_impact,
    non_negative_impact,
)
from web_app import app, logger


def _valid_gsi_object(value):
    return value is None or isinstance(value, dict)


def _invalid_gsi_payload(data):
    """返回 GSI 数据损坏的原因；正常数据返回空字符串。"""
    if not isinstance(data, dict) or not data:
        return "无效数据"
    if has_nonfinite_number(data):
        return "实时数据不能包含无穷大或无效数字"
    for field in (
        "auth",
        "map",
        "allplayers",
        "bomb",
        "round",
        "previously",
        "phase_countdowns",
        "_80gotv",
    ):
        if not _valid_gsi_object(data.get(field)):
            return f"{field} 格式错误"
    map_data = data.get("map", {}) or {}
    for field in ("team_ct", "team_t"):
        if not _valid_gsi_object(map_data.get(field)):
            return f"map.{field} 格式错误"
    previously = data.get("previously", {}) or {}
    for field in ("round", "bomb"):
        if not _valid_gsi_object(previously.get(field)):
            return f"previously.{field} 格式错误"
    identity = data.get("_80gotv") or {}
    for field in ("team_ct", "team_t", "session_id"):
        if (
            field in identity
            and identity[field] is not None
            and not isinstance(identity[field], str)
        ):
            return f"{field} 格式错误"
    for field in ("round_events", "death_markers"):
        if field in identity and not isinstance(identity[field], list):
            return f"{field} 格式错误"
    for player in (data.get("allplayers", {}) or {}).values():
        if not isinstance(player, dict):
            return "allplayers 格式错误"
        for field in ("state", "match_stats", "weapons"):
            if not _valid_gsi_object(player.get(field)):
                return f"allplayers.{field} 格式错误"
        if any(not isinstance(weapon, dict) for weapon in (player.get("weapons") or {}).values()):
            return "武器数据格式错误"
    numeric_groups: list[tuple[dict[str, object], tuple[str, ...]]] = [(map_data, ("round",))]
    numeric_groups.extend(
        ((map_data.get(field) or {}), ("score",)) for field in ("team_ct", "team_t")
    )
    for player in (data.get("allplayers", {}) or {}).values():
        numeric_groups.append((player.get("state") or {}, ("health", "armor", "money")))
        numeric_groups.append(
            (player.get("match_stats") or {}, ("kills", "deaths", "assists", "damage"))
        )
    try:
        for values, fields in numeric_groups:
            for field in fields:
                if field in values:
                    if isinstance(values[field], bool) or not isinstance(
                        values[field], (int, float)
                    ):
                        return f"{field} 必须是有效数字"
                    _bounded_number(values, field, 0, 100000, integer=True)
    except IngestValidationError as exc:
        return str(exc)
    return ""


def _read_int(payload, field, default=0):
    try:
        return _bounded_number(payload, field, 0, 100000, integer=True, default=default)
    except IngestValidationError:
        return None


def _secret_matches(supplied, expected):
    """Compare text secrets safely, including hostile non-ASCII JSON values."""
    if not isinstance(supplied, str) or not isinstance(expected, str):
        return False
    return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))


def _strip_gsi_auth(payload):
    clean = dict(payload) if isinstance(payload, dict) else {}
    clean.pop("auth", None)
    return clean


def _sanitize_live_state(state):
    if not isinstance(state, dict):
        return {}
    clean = dict(state)
    if isinstance(clean.get("gsi"), dict):
        clean["gsi"] = _strip_gsi_auth(clean["gsi"])
    return clean


def _active_map_slots(match):
    return [
        slot
        for slot in range(get_bo_max_maps(match["bo_format"]))
        if slot < 2 or match[f"has_map{slot + 1}"]
    ]


def _match_team_for_gsi_side(data, side, side_mapping=None):
    identity = (data.get("_80gotv") or {}) if isinstance(data, dict) else {}
    mapped = (side_mapping or {}).get(side)
    if mapped not in {"team1", "team2"}:
        mapped = identity.get("team_ct" if side == "CT" else "team_t")
    if mapped == "team2":
        return "t2"
    if mapped == "team1":
        return "t1"
    return None


def _merge_app_live_events(merged, data, side_mapping=None, previous_side_mapping=None):
    """Merge canonical events prepared by the desktop app and deduplicate by round/id."""
    identity = (data.get("_80gotv") or {}) if isinstance(data, dict) else {}
    round_events = identity.get("round_events") if "round_events" in identity else None
    death_markers = identity.get("death_markers") if "death_markers" in identity else None

    if isinstance(round_events, list):
        by_key = {}
        for event in (
            (merged.get("round_history", []) or [])
            + (merged.get("overtime_history", []) or [])
            + round_events
        ):
            if not isinstance(event, dict):
                continue
            try:
                round_number = int(event.get("round_number", event.get("round", 0)) or 0)
            except (TypeError, ValueError):
                continue
            if not 1 <= round_number <= 48:
                continue
            normalized = dict(event)
            normalized["round"] = round_number
            normalized["round_number"] = round_number
            normalized.setdefault("id", f"round-{round_number}-{normalized.get('side', '')}")
            winner_side = str(normalized.get("winner_side") or normalized.get("side") or "").upper()
            if normalized.get("winner") not in ("t1", "t2") and winner_side in ("CT", "T"):
                stored = by_key.get(str(normalized["id"])) or next(
                    (
                        item
                        for item in by_key.values()
                        if item.get("round") == round_number and item.get("winner") in ("t1", "t2")
                    ),
                    {},
                )
                mapping = side_mapping
                if round_number == max(1, (data.get("map") or {}).get("round", 0)):
                    mapping = previous_side_mapping or side_mapping
                normalized["winner"] = stored.get("winner") or _match_team_for_gsi_side(
                    data, winner_side, mapping
                )
            by_key[str(normalized["id"])] = normalized
        ordered = sorted(
            by_key.values(), key=lambda item: (int(item.get("round", 0)), str(item.get("id", "")))
        )
        # A round has one winner; an app resend must replace the earlier partial event.
        by_round = {int(item["round"]): item for item in ordered}
        regulation = [by_round[number] for number in sorted(by_round) if number <= 24]
        overtime = [by_round[number] for number in sorted(by_round) if number > 24]
        merged["round_history"] = regulation[-24:]
        merged["overtime_history"] = overtime[-24:]

    if isinstance(death_markers, list):
        by_id = {}
        for marker in (
            merged.get("death_markers", merged.get("kill_markers", [])) or []
        ) + death_markers:
            if not isinstance(marker, dict):
                continue
            marker = dict(marker)
            try:
                round_number = int(marker.get("round_number", marker.get("round", 0)) or 0)
            except (TypeError, ValueError):
                continue
            if not 1 <= round_number <= 48:
                continue
            marker["round"] = round_number
            marker["round_number"] = round_number
            marker.setdefault(
                "id",
                f"death-{round_number}-{marker.get('steamid', '')}-{marker.get('captured_at_epoch', '')}",
            )
            by_id[str(marker["id"])] = marker
        merged["death_markers"] = list(by_id.values())[-10:]
        merged["kill_markers"] = merged["death_markers"]
    return isinstance(round_events, list), isinstance(death_markers, list)


def _receiver_error(source, message, status_code, match_id=None, map_name=""):
    """Reject bad input without letting public errors write to SQLite."""
    return jsonify({"ok": False, "msg": message}), status_code


def _run_with_database(callback, *args):
    """Run one ingest write and always release its database connection."""
    conn = get_db()
    try:
        result = callback(conn, *args)
        status = result[1] if isinstance(result, tuple) else getattr(result, "status_code", 200)
        if status >= 400:
            conn.rollback()
        else:
            conn.commit()
        return result
    except IngestValidationError as exc:
        conn.rollback()
        return _receiver_error("live", str(exc), 400)
    except BracketDependencyError as exc:
        conn.rollback()
        return _receiver_error("live", str(exc), 409)
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.route("/api/gsi/receive", methods=["POST"])
def gsi_receiver():
    """
    CS2 Game State Integration 接收端点
    服务端安装 GSI 配置后，CS2 会自动 POST JSON 到该端点
    GSI 配置示例 (gamestate_integration_80gotv.cfg):
      "80GOTV" http://<host>/api/gsi/receive
    """
    if not rate_limit("gsi_public", 1800, 60, by_ip=True):
        return jsonify({"ok": False, "msg": "请求过于频繁"}), 429

    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        return _receiver_error("gsi", "无效数据", 400)
    auth = data.get("auth")
    if not isinstance(auth, dict):
        return _receiver_error("gsi", "auth 格式错误", 400)

    # 先验证密钥，再检查和保存其余数据。
    gsi_token = auth.get("token", "")
    expected = Config.GSI_TOKEN
    if not expected:
        return _receiver_error("gsi", "服务器未配置 GSI_TOKEN", 503)
    if not _secret_matches(gsi_token, expected):
        if not rate_limit("gsi_bad_auth", 10, 60, by_ip=True):
            return jsonify({"ok": False, "msg": "请求过于频繁"}), 429
        return _receiver_error("gsi", "token 不匹配", 403)
    if not rate_limit("gsi_ingest", 900, 60, by_ip=True):
        return jsonify({"ok": False, "msg": "请求过于频繁"}), 429
    data = _strip_gsi_auth(data)
    invalid = _invalid_gsi_payload(data)
    if invalid:
        return _receiver_error("gsi", invalid, 400)

    # 尝试匹配比赛
    map_name = (data.get("map") or {}).get("name", "")
    if not isinstance(map_name, str) or not map_name.strip():
        return _receiver_error("gsi", "缺少地图名", 400)

    return _run_with_database(_save_gsi_payload, data, map_name)


@app.route("/api/broadcast/matches/<int:match_id>/live", methods=["POST"])
def broadcast_gsi_receiver(match_id):
    """Receive GSI forwarded by the local desktop manager for one selected match."""
    if not rate_limit("broadcast_gsi_public", 1800, 60, by_ip=True):
        return jsonify({"ok": False, "msg": "请求过于频繁"}), 429
    expected = Config.GSI_TOKEN
    supplied = request.headers.get("X-80GOTV-Token", "")
    if not expected:
        return _receiver_error("gsi", "服务器未配置 GSI_TOKEN", 503)
    if not _secret_matches(supplied, expected):
        return _receiver_error("gsi", "token 不匹配", 403)

    data = _strip_gsi_auth(request.get_json(force=True, silent=True))
    invalid = _invalid_gsi_payload(data)
    if invalid:
        return _receiver_error("gsi", invalid, 400)
    map_name = (data.get("map") or {}).get("name", "")
    if not isinstance(map_name, str) or not map_name.strip():
        return _receiver_error("gsi", "缺少地图名", 400)
    return _run_with_database(_save_gsi_payload, data, map_name, match_id)


@app.route("/api/broadcast/matches/<int:match_id>/connection-test", methods=["GET"])
def broadcast_connection_test(match_id):
    """Authenticate a director computer without changing any match data."""
    if not rate_limit("broadcast_connection_test", 60, 60, by_ip=True):
        return jsonify({"ok": False, "msg": "请求过于频繁"}), 429
    expected = Config.GSI_TOKEN
    supplied = request.headers.get("X-80GOTV-Token", "")
    if not expected:
        return _receiver_error("gsi", "服务器未配置 GSI_TOKEN", 503)
    if not _secret_matches(supplied, expected):
        return _receiver_error("gsi", "token 不匹配", 403)
    return _run_with_database(_probe_broadcast_match, match_id)


def _probe_broadcast_match(conn, match_id):
    """Return a small, non-sensitive identity check for the selected broadcast match."""
    match = conn.execute(
        """
        SELECT m.*,
               COALESCE(t1.name, '') AS team1_name,
               COALESCE(t1.short_name, '') AS t1s,
               COALESCE(t2.name, '') AS team2_name,
               COALESCE(t2.short_name, '') AS t2s
        FROM matches m
        LEFT JOIN teams t1 ON t1.id=m.team1_id
        LEFT JOIN teams t2 ON t2.id=m.team2_id
        WHERE m.id=?
        """,
        (match_id,),
    ).fetchone()
    if not match:
        return _receiver_error("gsi", "未找到比赛", 404, match_id)
    match = supplement_temp_teams(match, conn)

    roster = resolve_match_roster(conn, match)
    roster_locked = roster["locked"]
    bp_state = {}
    try:
        bp_state = json.loads(match["bp_state"] or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        bp_state = {}
    return jsonify(
        {
            "ok": True,
            "match_id": match["id"],
            "team1_name": match["team1_name"],
            "team2_name": match["team2_name"],
            "bp_revision": int(bp_state.get("revision", 0) or 0),
            "roster_locked": roster_locked,
            "roster_issues": roster["issues"],
            "ready_for_start": roster_locked
            and bp_state.get("status") == "completed"
            and str(match.get("status") or "").lower() not in {"completed", "cancelled"},
            "server_time": datetime.now(timezone.utc).isoformat(),
        }
    )


@app.route("/api/broadcast/matches/<int:match_id>/map-result", methods=["POST"])
def broadcast_map_result_receiver(match_id):
    """Store one map's final player stats sent by the desktop director app."""
    if not rate_limit("broadcast_map_result", 30, 60, by_ip=True):
        return jsonify({"ok": False, "msg": "请求过于频繁"}), 429
    expected = Config.GSI_TOKEN
    supplied = request.headers.get("X-80GOTV-Token", "")
    if not expected:
        return _receiver_error("map_result", "服务器未配置 GSI_TOKEN", 503, match_id)
    if not _secret_matches(supplied, expected):
        return _receiver_error("map_result", "token 不匹配", 403, match_id)
    payload = request.get_json(force=True, silent=True)
    if not isinstance(payload, dict):
        return _receiver_error("map_result", "无效数据", 400, match_id)
    if has_nonfinite_number(payload):
        return _receiver_error("map_result", "结算不能包含无穷大或无效数字", 400, match_id)
    return _run_with_database(_save_broadcast_map_result, payload, match_id)


def _save_broadcast_map_result(conn, payload, match_id):
    raw_map_name = payload.get("map_name")
    map_name = raw_map_name.strip() if isinstance(raw_map_name, str) else ""
    players = payload.get("players")
    if (
        not map_name
        or len(map_name) > 80
        or not isinstance(players, list)
        or not 1 <= len(players) <= 12
    ):
        return _receiver_error("map_result", "地图或选手数据不完整", 400, match_id, map_name)
    if any(
        not isinstance(player, dict) or player.get("team_side") not in ("team1", "team2")
        for player in players
    ):
        return _receiver_error("map_result", "选手队伍归属无效", 400, match_id, map_name)
    supplied_ids = [str(player.get("steam_id") or "").strip() for player in players]
    if any(
        not isinstance(player.get("steam_id"), (str, int))
        or isinstance(player.get("steam_id"), bool)
        for player in players
    ) or any(not steam_id or len(steam_id) > 64 for steam_id in supplied_ids):
        return _receiver_error("map_result", "选手 Steam ID 无效", 400, match_id, map_name)
    if len(set(supplied_ids)) != len(supplied_ids):
        return _receiver_error("map_result", "地图结算包含重复 Steam ID", 409, match_id, map_name)
    if any(
        not isinstance(player.get("name"), str)
        or not player["name"].strip()
        or len(player["name"]) > 80
        for player in players
    ):
        return _receiver_error(
            "map_result", "选手名称无效，未保存本次结算", 400, match_id, map_name
        )
    team1_score = _bounded_number(payload, "team1_score", 0, 100, integer=True)
    team2_score = _bounded_number(payload, "team2_score", 0, 100, integer=True)
    if team1_score is None or team2_score is None or team1_score == team2_score:
        return _receiver_error("map_result", "最终地图比分不能为空或平局", 400, match_id, map_name)
    if "series_complete" in payload and not isinstance(payload["series_complete"], bool):
        return _receiver_error("map_result", "系列赛结束标记无效", 400, match_id, map_name)
    stats = [_live_player_stat(player) for player in players]
    conn.execute("UPDATE matches SET status=status WHERE id=?", (match_id,))
    match = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
    if not match:
        return _receiver_error("map_result", "比赛不存在", 404, match_id, map_name)
    if match["status"] == "cancelled":
        return _receiver_error(
            "map_result", "比赛已取消，拒绝覆盖统计数据", 409, match_id, map_name
        )

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
        return _receiver_error(
            "map_result", "选手队伍归属与比赛名单不一致", 409, match_id, map_name
        )
    if locked_roster:
        locked_sides = known_sides
        if len(players) != 10:
            return _receiver_error(
                "map_result",
                "网站已锁定十人名单，地图结算必须包含两队各五人",
                409,
                match_id,
                map_name,
            )
        supplied_ids = [str(player.get("steam_id") or "").strip() for player in players]
        if any(not steam_id for steam_id in supplied_ids) or len(set(supplied_ids)) != 10:
            return _receiver_error(
                "map_result", "地图结算包含缺失或重复 Steam ID", 409, match_id, map_name
            )
        if set(supplied_ids) != locked_roster:
            return _receiver_error(
                "map_result", "地图结算名单与网站锁定名单不一致", 409, match_id, map_name
            )
        if any(
            locked_sides.get(str(player.get("steam_id")).strip()) != player.get("team_side")
            for player in players
        ):
            return _receiver_error(
                "map_result", "地图结算队伍归属与网站名单不一致", 409, match_id, map_name
            )

    map_names = [match[f"map{slot}"] for slot in range(1, 6)]
    active_slots = _active_map_slots(match)
    requested_slot = payload.get("map_slot")
    if requested_slot is not None:
        requested_slot = _bounded_number(payload, "map_slot", 1, 5, integer=True)
        assert requested_slot is not None
        configured = map_names[requested_slot - 1]
        if not configured or normalize_map_name(configured) != normalize_map_name(map_name):
            return _receiver_error(
                "map_result", "地图槽位与地图名称不一致", 409, match_id, map_name
            )
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
        return _receiver_error("map_result", "推送地图不在该比赛赛程中", 409, match_id, map_name)
    if len(matching_slots) > 1:
        return _receiver_error(
            "map_result", "同名地图存在多个槽位，请明确指定地图槽位", 409, match_id, map_name
        )
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
        return _receiver_error(
            "map_result", "本场十人名单尚未完整确认，保留原正式统计", 409, match_id, map_name
        )
    if not stats:
        return _receiver_error("map_result", "没有可保存的选手", 400, match_id, map_name)
    if locked_roster and len(stats) != 10:
        return _receiver_error(
            "map_result", "地图结算中有选手数据无法识别，保留原统计", 409, match_id, map_name
        )

    result_id = str(payload.get("result_id") or "").strip()
    if len(result_id) > 120:
        return _receiver_error("map_result", "结算编号过长", 400, match_id, map_name)
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
            return _receiver_error(
                "map_result", "同一结算编号的内容不同，请检查导播数据", 409, match_id, map_name
            )
        return jsonify(
            {
                "ok": True,
                "duplicate": True,
                "match_id": match_id,
                "map_name": confirmed_result.get("map_name") or map_name,
                "saved": len(confirmed_result.get("players") or []),
                "players": confirmed_result.get("players") or [],
                "series_complete": confirmed_result.get("series_complete", False),
            }
        )
    if active_session and incoming_session and active_session != incoming_session:
        return _receiver_error(
            "map_result", "地图结算会话与当前导播会话不一致", 409, match_id, map_name
        )
    if active_session and not incoming_session:
        return _receiver_error(
            "map_result", "当前比赛已有导播会话，拒绝无会话结算覆盖", 409, match_id, map_name
        )
    frame_seq = payload.get("frame_seq")
    if match["status"] == "completed":
        return _receiver_error(
            "map_result", "比赛已结束，拒绝新的导播结算覆盖", 409, match_id, map_name
        )
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
            return _receiver_error("map_result", "较旧的地图结算被拒绝", 409, match_id, map_name)

    decided, _ = get_series_result(match["bo_format"], match["team1_score"], match["team2_score"])
    if decided and not (match[f"map{map_slot + 1}_t1"] or match[f"map{map_slot + 1}_t2"]):
        return _receiver_error(
            "map_result", "系列赛已决出胜负，不能再增加新的地图", 409, match_id, map_name
        )
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
        return _receiver_error("map_result", "地图结果与系列赛赛制冲突", 409, match_id, map_name)
    series_complete = bool(get_series_result(match["bo_format"], wins1, wins2)[0])
    if payload.get("series_complete") and not series_complete:
        return _receiver_error(
            "map_result", "系列赛尚未决胜，不能标记为已完成", 409, match_id, map_name
        )

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
        db_player = auto_create_user_from_demo(conn, stat)
        if not db_player:
            return _receiver_error(
                "map_result", "选手无法完整识别，本次结算未保存", 409, match_id, map_name
            )
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
        return _receiver_error(
            "map_result", "无法完整解析网站锁定的十名选手，原统计未替换", 409, match_id, map_name
        )

    if not sync_match_scores(
        conn,
        match_id,
        map_slot,
        {"team_a_score": team1_score, "team_b_score": team2_score},
        True,
    ):
        return _receiver_error(
            "map_result", "地图比分无法保存，本次结算未保存", 409, match_id, map_name
        )
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
    return jsonify(
        {
            "ok": True,
            "match_id": match_id,
            "map_name": db_map_name,
            "saved": len(saved_players),
            "players": saved_players,
            "series_complete": series_complete,
        }
    )


def _save_gsi_payload(conn, data, map_name, forced_match_id=None):
    if forced_match_id is None:
        matches = conn.execute(
            f"""
            SELECT m.* FROM matches m
            WHERE ({get_sql_match_live()})
        """,
        ).fetchall()
        matches = [
            match
            for match in matches
            if any(
                normalize_map_name(match[f"map{slot + 1}"] or "") == normalize_map_name(map_name)
                for slot in _active_map_slots(match)
            )
        ]
    else:
        matches = conn.execute(
            "SELECT * FROM matches WHERE id=?",
            (forced_match_id,),
        ).fetchall()
        if matches and matches[0]["status"] in {"completed", "cancelled"}:
            return _receiver_error(
                "gsi", "比赛已结束或取消，拒绝覆盖直播数据", 409, forced_match_id
            )
        configured_maps = (
            [matches[0][f"map{slot + 1}"] for slot in _active_map_slots(matches[0])]
            if matches
            else []
        )
        configured_maps = [name for name in configured_maps if name]
        if matches and not any(
            normalize_map_name(name) == normalize_map_name(map_name) for name in configured_maps
        ):
            return _receiver_error(
                "gsi", "推送地图不在该比赛赛程中", 409, forced_match_id, map_name
            )

    if not matches:
        return _receiver_error("gsi", "未找到匹配的比赛", 404, map_name=map_name)
    if len(matches) > 1:
        return _receiver_error(
            "gsi", "存在多场同地图直播比赛，请管理员检查赛程", 409, map_name=map_name
        )
    match_id = matches[0]["id"]
    conn.execute("UPDATE matches SET status=status WHERE id=?", (match_id,))
    match = conn.execute(
        """
        SELECT m.*, t1.name AS scheduled_team1_name, t2.name AS scheduled_team2_name,
               t1.short_name AS scheduled_team1_short, t2.short_name AS scheduled_team2_short
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        WHERE m.id=?
        """,
        (match_id,),
    ).fetchone()
    if not match or match["status"] in ("completed", "cancelled"):
        return _receiver_error("gsi", "比赛已结束或取消，拒绝覆盖直播数据", 409, match_id, map_name)
    roster_side_by_steamid = _roster_side_by_steamid(conn, match) if match else {}
    side_mapping = _gsi_team_mapping(data, match, roster_side_by_steamid) if match else None

    # 合并已有 live_state（避免覆盖 GOTV 等其他数据）
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
    identity = (data.get("_80gotv") or {}) if isinstance(data, dict) else {}
    incoming_session = str(identity.get("session_id") or "").strip()
    incoming_seq = identity.get("frame_seq")
    if incoming_seq is not None:
        incoming_seq = _bounded_number(identity, "frame_seq", 0, 2**53 - 1, integer=True)
    previous_session = str(merged.get("gsi_session_id") or "").strip()
    previous_seq = merged.get("gsi_frame_seq")
    try:
        previous_seq = int(previous_seq) if previous_seq is not None else None
    except (TypeError, ValueError):
        previous_seq = None
    if incoming_session and previous_session and incoming_session != previous_session:
        if _is_recent_iso_timestamp(merged.get("gsi_received_at")):
            return _receiver_error(
                "gsi", "实时数据会话仍在使用，拒绝覆盖当前比赛，请稍后重试", 409, match_id, map_name
            )
        # 旧导播已断开超过有效期，新会话可以恢复；帧编号不能跨会话比较。
        previous_seq = None
    if previous_session and not incoming_session:
        return _receiver_error(
            "gsi", "导播实时会话正在负责本场比赛，备用 GSI 不得覆盖", 409, match_id, map_name
        )
    if incoming_session and incoming_seq is not None and previous_seq is not None:
        if incoming_seq < previous_seq:
            return _receiver_error("gsi", "较旧实时帧被拒绝", 409, match_id, map_name)
        if incoming_seq == previous_seq:
            return jsonify(
                {
                    "ok": True,
                    "duplicate": True,
                    "match_id": match_id,
                    "session_id": incoming_session,
                    "frame_seq": incoming_seq,
                }
            )
    for steamid, player in (data.get("allplayers", {}) or {}).items():
        record_observed_player_nickname(conn, steamid, player.get("name", ""), "gsi")
    previous_gsi = merged.get("gsi", {}) or {}
    previous_map_name = normalize_map_name((previous_gsi.get("map", {}) or {}).get("name", ""))
    if previous_gsi and not _is_recent_iso_timestamp(merged.get("gsi_received_at")):
        merged["gsi"] = {}
        previous_gsi = {}
    current_map_name = normalize_map_name(map_name)
    if previous_map_name and current_map_name and previous_map_name != current_map_name:
        for key in (
            "round_history",
            "overtime_history",
            "death_markers",
            "kill_markers",
            "kill_events",
            "bomb_events",
        ):
            merged[key] = []
        # 换图后的首帧不能与上一张图比较，否则会制造阵亡或漏掉下包事件。
        merged["gsi"] = {}
        previous_gsi = {}
    # APP 已经在本地按正式比赛缓存阵亡点；兼容旧 GSI 客户端时才使用
    # 服务端的帧差兜底，避免两套判断互相覆盖。
    if "death_markers" not in identity:
        _record_gsi_deaths(merged, data)
    _record_gsi_bomb_events(merged, data)
    previous_side_mapping = (
        _gsi_team_mapping(previous_gsi, match, roster_side_by_steamid) if previous_gsi else None
    )
    app_round_events, app_death_markers = _merge_app_live_events(
        merged,
        data,
        side_mapping,
        previous_side_mapping,
    )

    # 计算回合历史（每回合结束时记录胜负方）
    round_num = (data.get("map") or {}).get("round", 0)
    # In transition frames CS2 reports the newly-entered zero-based round while
    # `previously.round` describes the round that just finished. Some servers
    # briefly keep round 0 on the first result, so clamp that one to round 1.
    completed_round = max(1, round_num)
    if "round_history" not in merged:
        merged["round_history"] = []
    rh = merged["round_history"]
    # 检测新回合结束
    prev_round = (data.get("previously") or {}).get("round", {}) or {}
    prev_winner = prev_round.get("win_team", "")
    # 常规时间固定保留 24 个格子；加时单独保存，不能挤进常规栏。
    if "overtime_history" not in merged:
        merged["overtime_history"] = []
    overtime = merged["overtime_history"]
    if not isinstance(overtime, list):
        overtime = []
    if (
        (not app_round_events)
        and 1 <= completed_round <= 48
        and prev_winner
        and (
            (completed_round <= 24 and (not rh or rh[-1].get("round") != completed_round))
            or (
                completed_round > 24
                and (not overtime or overtime[-1].get("round") != completed_round)
            )
        )
    ):
        current_map = data.get("map", {}) or {}
        captured_at = datetime.now(timezone.utc)
        reason_code = _round_win_reason_code(data, previous_gsi, prev_winner)
        round_result = {
            "id": f"round-{completed_round}-{prev_winner.lower()}",
            "round": completed_round,
            "round_number": completed_round,
            "winner": _match_team_for_gsi_side(
                data, prev_winner, previous_side_mapping or side_mapping
            ),
            "side": prev_winner.lower(),
            "score_ct": (current_map.get("team_ct", {}) or {}).get("score", 0),
            "score_t": (current_map.get("team_t", {}) or {}).get("score", 0),
            "reason": _round_win_reason(data, previous_gsi, prev_winner),
            "reason_code": reason_code,
            "captured_at": captured_at.isoformat(),
            "captured_at_epoch": captured_at.timestamp(),
        }
        if completed_round <= 24:
            rh.append(round_result)
            if len(rh) > 24:
                rh = rh[-24:]
            merged["round_history"] = rh
        else:
            overtime.append(round_result)
            merged["overtime_history"] = overtime[-24:]

    # The app is authoritative for formal-match events. It may send an empty
    # event list while a frame is being skipped, so do not manufacture kills
    # or round results from that transient frame.
    if app_death_markers:
        merged["death_markers"] = merged.get("death_markers", [])[-10:]
        merged["kill_markers"] = merged["death_markers"]
    # Do not clear a previously persisted kill timeline just because this GSI
    # frame did not carry a new event.
    if not isinstance(merged.get("kill_events"), list):
        merged["kill_events"] = []

    merged["gsi"] = data
    if incoming_session:
        merged["gsi_session_id"] = incoming_session
    if incoming_seq is not None:
        merged["gsi_frame_seq"] = incoming_seq
    merged["gsi_received_at"] = datetime.now(timezone.utc).isoformat()
    if resolve_match_roster(conn, match)["locked"]:
        freeze_match_roster(conn, match, confirmed=True)
    persist_live_match_events(conn, match_id, merged)
    record_ingest_status(conn, "gsi", "ok", "观战账号数据正常", match_id, map_name)

    conn.execute(
        """
        INSERT INTO live_match_data(match_id, live_state)
        VALUES(?, ?)
        ON CONFLICT(match_id) DO UPDATE SET live_state=excluded.live_state, updated_at=CURRENT_TIMESTAMP
    """,
        (match_id, json.dumps(merged, ensure_ascii=False)),
    )

    return jsonify(
        {
            "ok": True,
            "match_id": match_id,
            "session_id": incoming_session or None,
            "frame_seq": incoming_seq,
        }
    )


@app.route("/api/gotv/stats", methods=["POST"])
def gotv_stats_receiver():
    """
    GOTV 实时数据接收端点
    gotv_relay/relay.py 定时解析 demo 并 POST 选手统计数据到此端点
    请求头: X-GOTV-Secret: Config.GOTV_SECRET
    """
    if not rate_limit("gotv_public", 300, 60, by_ip=True):
        return jsonify({"ok": False, "msg": "请求过于频繁"}), 429

    if not Config.GOTV_SECRET:
        return _receiver_error("gotv", "服务器未配置 GOTV_SECRET", 503)
    if not _secret_matches(request.headers.get("X-GOTV-Secret", ""), Config.GOTV_SECRET):
        if not rate_limit("gotv_bad_auth", 10, 60, by_ip=True):
            return jsonify({"ok": False, "msg": "请求过于频繁"}), 429
        return _receiver_error("gotv", "未授权", 403)
    if not rate_limit("gotv_ingest", 120, 60, by_ip=True):
        return jsonify({"ok": False, "msg": "请求过于频繁"}), 429
    payload = request.get_json(force=True, silent=True)
    if not isinstance(payload, dict) or not payload:
        return _receiver_error("gotv", "无效数据", 400)
    if has_nonfinite_number(payload):
        return _receiver_error("gotv", "统计数据不能包含无穷大或无效数字", 400)

    match_id = _read_int(payload, "match_id")
    players = payload.get("players", [])
    map_name = payload.get("map_name", "")
    team_a_name = payload.get("team_a_name", "")
    team_b_name = payload.get("team_b_name", "")
    team_a_score = _read_int(payload, "team_a_score")
    team_b_score = _read_int(payload, "team_b_score")
    rounds_count = _read_int(payload, "rounds_count")
    halftime = payload.get("halftime", {})

    if not match_id or not isinstance(players, list) or not 1 <= len(players) <= 12:
        return _receiver_error("gotv", "缺少 match_id 或 players", 400)
    if any(
        not isinstance(player, dict)
        or not isinstance(player.get("name"), str)
        or not player["name"].strip()
        or not str(player.get("steam_id") or "").strip()
        or not isinstance(player.get("steam_id"), (str, int))
        or isinstance(player.get("steam_id"), bool)
        or player.get("team_letter") not in ("A", "B")
        for player in players
    ):
        return _receiver_error("gotv", "players 格式错误", 400, match_id, map_name)
    ids = [str(player["steam_id"]).strip() for player in players]
    if len(set(ids)) != len(ids):
        return _receiver_error("gotv", "选手 Steam ID 重复", 409, match_id, map_name)
    if not isinstance(map_name, str) or not map_name.strip():
        return _receiver_error("gotv", "缺少地图名", 400, match_id)
    if not isinstance(team_a_name, str) or not isinstance(team_b_name, str):
        return _receiver_error("gotv", "队伍名格式错误", 400, match_id, map_name)
    if any(value is None or value < 0 for value in (team_a_score, team_b_score, rounds_count)):
        return _receiver_error("gotv", "比分或回合数格式错误", 400, match_id, map_name)
    if not isinstance(halftime, dict):
        return _receiver_error("gotv", "halftime 格式错误", 400, match_id, map_name)

    return _run_with_database(
        _save_gotv_payload,
        match_id,
        players,
        map_name,
        team_a_name,
        team_b_name,
        team_a_score,
        team_b_score,
        rounds_count,
        halftime,
    )


def _save_gotv_payload(
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
):
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
        return _receiver_error("gotv", "比赛不存在", 404, match_id, map_name)
    if match["status"] in {"completed", "cancelled"}:
        return _receiver_error(
            "gotv", "比赛已结束或取消，拒绝覆盖统计数据", 409, match_id, map_name
        )

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
            return _receiver_error(
                "gotv", "导播数据已负责本场比赛，GOTV 只能旁观不能覆盖", 409, match_id, map_name
            )

    # 查找地图槽位
    map_names = [match["map1"], match["map2"], match["map3"], match["map4"], match["map5"]]
    matching_slots = [
        slot
        for slot in _active_map_slots(match)
        if map_names[slot] and normalize_map_name(map_names[slot]) == normalize_map_name(map_name)
    ]
    if len(matching_slots) != 1:
        return _receiver_error("gotv", "推送地图不在该比赛赛程中", 409, match_id, map_name)
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
        return _receiver_error(
            "gotv",
            "该地图已有确认统计，请使用明确结算或 Demo 修订，不能被中途数据覆盖",
            409,
            match_id,
            map_name,
        )

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
        return _receiver_error(
            "gotv", "无法确认 GOTV 队伍对应关系，拒绝猜测覆盖", 409, match_id, map_name
        )
    known_sides = _roster_side_by_steamid(conn, match)
    for player in players:
        expected = "team1" if (player["team_letter"] == "A") == a_to_t1 else "team2"
        if known_sides.get(str(player["steam_id"]).strip()) not in (None, expected):
            return _receiver_error("gotv", "GOTV 队伍归属与比赛名单不一致", 409, match_id, map_name)

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
        db_player = auto_create_user_from_demo(conn, stat)
        if not db_player:
            return _receiver_error(
                "gotv", "选手无法完整识别，本次统计未保存", 409, match_id, map_name
            )
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
    return jsonify(
        {
            "ok": True,
            "map_slot": map_slot,
            "players_imported": imported,
            "players_created": created,
        }
    )
