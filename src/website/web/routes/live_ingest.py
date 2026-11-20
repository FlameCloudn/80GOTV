"""Authenticate and validate the website's machine-facing live routes."""

import hmac
import json
from datetime import datetime, timezone

from flask import jsonify, request

from config import Config
from src.website.domains.matches.bracket_service import BracketDependencyError
from src.website.domains.matches.match_roster_service import resolve_match_roster
from src.website.domains.matches.opponents import supplement_temp_teams
from src.website.domains.operations.legacy_gsi import store_gsi_frame
from src.website.domains.operations.legacy_live_state import _strip_gsi_auth
from src.website.domains.operations.live_service import IngestValidationError, has_nonfinite_number
from src.website.domains.operations.live_service import read_ingest_number as _bounded_number
from src.website.domains.operations.projection import (
    director_receipts_for_run,
    live_schema_ready,
    start_projection,
)
from src.website.runtime.database import get_db
from src.website.runtime.host import HostError, is_managed_match
from src.website.runtime.rate_limiter import rate_limit
from src.website.web.access import admin_required
from src.website.web.routing import site_routes
from src.website.workflows.broadcast_result import record_broadcast_map_result
from src.website.workflows.gotv_statistics import store_gotv_statistics


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
    except (HostError, BracketDependencyError) as exc:
        conn.rollback()
        return _receiver_error("live", str(exc), exc.status if isinstance(exc, HostError) else 409)
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


@site_routes.route("/api/gsi/receive", methods=["POST"])
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

    return _run_with_database(store_gsi_frame, data, map_name)


@site_routes.route("/api/broadcast/matches/<int:match_id>/live", methods=["POST"])
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
    return _run_with_database(store_gsi_frame, data, map_name, match_id)


@site_routes.route("/api/broadcast/matches/<int:match_id>/connection-test", methods=["GET"])
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
    conn.execute("BEGIN")
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
    if is_managed_match(conn, match_id):
        start = start_projection(conn, match_id)
    else:
        start = {
            "ready_for_start": roster_locked
            and bp_state.get("status") == "completed"
            and str(match.get("status") or "").lower() not in {"completed", "cancelled"}
        }
    return jsonify(
        {
            "ok": True,
            "match_id": match["id"],
            "team1_name": match["team1_name"],
            "team2_name": match["team2_name"],
            "bp_revision": int(bp_state.get("revision", 0) or 0),
            "roster_locked": roster_locked,
            "roster_issues": roster["issues"],
            **start,
            "server_time": datetime.now(timezone.utc).isoformat(),
        }
    )


@site_routes.route("/api/broadcast/matches/<int:match_id>/map-result", methods=["POST"])
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
    return _run_with_database(record_broadcast_map_result, payload, match_id)


@site_routes.get("/admin/matches/<int:match_id>/operations/runs/<int:run_id>/director-receipts")
@admin_required
def admin_director_receipts(match_id, run_id):
    return _run_with_database(_read_director_receipts, match_id, run_id)


def _read_director_receipts(conn, match_id, run_id):
    conn.execute("BEGIN")
    if not is_managed_match(conn, match_id) or not live_schema_ready(conn):
        raise HostError("该比赛没有托管导播回执", 404)
    return jsonify(ok=True, receipts=director_receipts_for_run(conn, match_id, run_id))


@site_routes.route("/api/gotv/stats", methods=["POST"])
def gotv_stats_receiver():
    """
    GOTV 实时数据接收端点
    integrations/gotv_relay/relay.py 定时解析 demo 并 POST 选手统计数据到此端点
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
        store_gotv_statistics,
        match_id,
        players,
        map_name,
        team_a_name,
        team_b_name,
        team_a_score,
        team_b_score,
        rounds_count,
        halftime,
        payload.get("map_run_id"),
    )
