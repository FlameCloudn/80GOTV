"""GSI and GOTV live-data receiving endpoints."""

import hmac
import json
from datetime import datetime, timezone

from flask import jsonify, request

from config import Config
from models import get_db
from services.demo_service import (
    auto_create_user_from_demo,
    insert_match_stat,
    save_halftime_data,
    sync_match_scores,
)
from services.live_log_service import persist_live_match_events, record_ingest_status
from services.live_service import (
    _record_gsi_bomb_events,
    _record_gsi_deaths,
    _round_win_reason,
    _round_win_reason_code,
)
from services.match_service import supplement_temp_teams
from services.performance_service import refresh_player_performance
from services.player_service import record_observed_player_nickname
from utils.demo_parser import match_map_slot, normalize_map_name
from utils.match_utils import get_sql_match_live
from utils.rate_limiter import rate_limit
from utils.stats_calc import calculate_impact, calculate_rating
from web_app import app, logger


def _valid_gsi_object(value):
    return value is None or isinstance(value, dict)


def _invalid_gsi_payload(data):
    """返回 GSI 数据损坏的原因；正常数据返回空字符串。"""
    if not isinstance(data, dict) or not data:
        return "无效数据"
    for field in ("auth", "map", "allplayers", "bomb", "round", "previously", "phase_countdowns"):
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
    for player in (data.get("allplayers", {}) or {}).values():
        if not isinstance(player, dict):
            return "allplayers 格式错误"
        for field in ("state", "match_stats", "weapons"):
            if not _valid_gsi_object(player.get(field)):
                return f"allplayers.{field} 格式错误"
    return ""


def _read_int(payload, field, default=0):
    try:
        return int(payload.get(field, default) or default)
    except (TypeError, ValueError):
        return None


def _secret_matches(supplied, expected):
    """Compare text secrets safely, including hostile non-ASCII JSON values."""
    if not isinstance(supplied, str) or not isinstance(expected, str):
        return False
    return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))


def _strip_gsi_auth(payload):
    clean = dict(payload or {})
    clean.pop("auth", None)
    return clean


def _sanitize_live_state(state):
    if not isinstance(state, dict):
        return {}
    clean = dict(state)
    if isinstance(clean.get("gsi"), dict):
        clean["gsi"] = _strip_gsi_auth(clean["gsi"])
    return clean


def _match_team_for_gsi_side(data, side):
    identity = data.get("_80gotv", {}) if isinstance(data, dict) else {}
    mapped = identity.get("team_ct" if side == "CT" else "team_t")
    if mapped == "team2":
        return "t2"
    return "t1" if mapped == "team1" or side == "CT" else "t2"


def _merge_app_live_events(merged, data):
    """Merge canonical events prepared by the desktop app and deduplicate by round/id."""
    identity = data.get("_80gotv", {}) if isinstance(data, dict) else {}
    round_events = identity.get("round_events") if "round_events" in identity else None
    death_markers = identity.get("death_markers") if "death_markers" in identity else None

    if isinstance(round_events, list):
        by_key = {}
        for event in (merged.get("round_history", []) or []) + round_events:
            if not isinstance(event, dict):
                continue
            try:
                round_number = int(event.get("round_number", event.get("round", 0)) or 0)
            except (TypeError, ValueError):
                continue
            if not 1 <= round_number <= 24:
                continue
            normalized = dict(event)
            normalized["round"] = round_number
            normalized["round_number"] = round_number
            winner_side = str(normalized.get("winner_side") or normalized.get("side") or "").upper()
            if normalized.get("winner") not in ("t1", "t2") and winner_side in ("CT", "T"):
                normalized["winner"] = _match_team_for_gsi_side(data, winner_side)
            normalized.setdefault("id", f"round-{round_number}-{normalized.get('side', '')}")
            by_key[str(normalized["id"])] = normalized
        ordered = sorted(
            by_key.values(), key=lambda item: (int(item.get("round", 0)), str(item.get("id", "")))
        )
        # A round has one winner; an app resend must replace the earlier partial event.
        by_round = {int(item["round"]): item for item in ordered}
        merged["round_history"] = [by_round[number] for number in sorted(by_round)][-24:]

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
            if not 1 <= round_number <= 24:
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
        return callback(conn, *args)
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
    map_name = data.get("map", {}).get("name", "")
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
    map_name = data.get("map", {}).get("name", "")
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
        SELECT m.id, m.team1_id, m.team2_id, m.team1_players, m.team2_players,
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
    return jsonify(
        {
            "ok": True,
            "match_id": match["id"],
            "team1_name": match["team1_name"],
            "team2_name": match["team2_name"],
            "server_time": datetime.now(timezone.utc).isoformat(),
        }
    )


def _bounded_number(payload, key, minimum=0, maximum=100000, integer=False):
    try:
        value = float(payload.get(key, 0) or 0)
    except (TypeError, ValueError):
        value = 0
    value = max(minimum, min(maximum, value))
    return int(round(value)) if integer else value


def _live_side_stat(payload):
    payload = payload if isinstance(payload, dict) else {}
    rounds = _bounded_number(payload, "roundsPlayed", 0, 100, integer=True)
    kills = _bounded_number(payload, "kills", 0, 500, integer=True)
    deaths = _bounded_number(payload, "deaths", 0, 500, integer=True)
    assists = _bounded_number(payload, "assists", 0, 500, integer=True)
    damage = _bounded_number(payload, "damage", 0, 100000)
    kast_rounds = min(rounds, _bounded_number(payload, "kastRounds", 0, 100, integer=True))
    adr = round(damage / rounds, 1) if rounds else 0
    kast = round(kast_rounds * 100 / rounds, 1) if rounds else 0
    rating, _, _ = calculate_rating(kills, deaths, rounds, adr=adr, kast=kast, impact=0)
    return {
        "kills": kills,
        "deaths": deaths,
        "assists": assists,
        "damage": damage,
        "rounds": rounds,
        "adr": adr,
        "kast": kast,
        "rating": rating,
    }


def _live_player_stat(payload):
    rounds = max(1, _bounded_number(payload, "roundsPlayed", 1, 100, integer=True))
    kills = _bounded_number(payload, "kills", 0, 500, integer=True)
    deaths = _bounded_number(payload, "deaths", 0, 500, integer=True)
    assists = _bounded_number(payload, "assists", 0, 500, integer=True)
    damage = _bounded_number(payload, "damage", 0, 100000)
    damage_taken = _bounded_number(payload, "damageTaken", 0, 100000)
    headshots = min(kills, _bounded_number(payload, "headshots", 0, 500, integer=True))
    kast_rounds = min(rounds, _bounded_number(payload, "kastRounds", 0, 100, integer=True))
    first_kills = _bounded_number(payload, "firstKills", 0, 100, integer=True)
    first_deaths = _bounded_number(payload, "firstDeaths", 0, 100, integer=True)
    multi = [
        _bounded_number(payload, f"multi{size}k", 0, 100, integer=True) for size in range(1, 6)
    ]
    clutches = [
        _bounded_number(payload, f"clutch1v{size}", 0, 100, integer=True) for size in range(1, 6)
    ]
    clutches_won = sum(clutches)
    adr = round(damage / rounds, 1)
    kast = round(kast_rounds * 100 / rounds, 1)
    impact = calculate_impact(
        first_kills,
        first_deaths,
        sum(multi[1:]),
        clutches_won,
        rounds,
    )
    rating, kpr, dpr = calculate_rating(
        kills,
        deaths,
        rounds,
        adr=adr,
        kast=kast,
        impact=impact,
    )
    t_stats = _live_side_stat(payload.get("tStats"))
    ct_stats = _live_side_stat(payload.get("ctStats"))
    utility_damage = _bounded_number(payload, "utilityDamage", 0, 100000)
    return {
        "steam_id": str(payload.get("steam_id") or "").strip(),
        "name": str(payload.get("name") or "").strip()[:80],
        "kills": kills,
        "deaths": deaths,
        "assists": assists,
        "adr": adr,
        "kpr": kpr,
        "dpr": dpr,
        "rating": rating,
        "impact": impact,
        "kast": kast,
        "headshot_percentage": round(headshots * 100 / kills, 1) if kills else 0,
        "clutches_won": clutches_won,
        "t_rating": t_stats["rating"],
        "ct_rating": ct_stats["rating"],
        "t_kills": t_stats["kills"],
        "ct_kills": ct_stats["kills"],
        "t_deaths": t_stats["deaths"],
        "ct_deaths": ct_stats["deaths"],
        "t_adr": t_stats["adr"],
        "ct_adr": ct_stats["adr"],
        "multi1k": multi[0],
        "multi2k": multi[1],
        "multi3k": multi[2],
        "multi4k": multi[3],
        "multi5k": multi[4],
        "first_kill_count": first_kills,
        "first_death_count": first_deaths,
        "mvp_count": _bounded_number(payload, "mvpCount", 0, 100, integer=True),
        "utility_damage": utility_damage,
        "trade_kills": _bounded_number(payload, "tradeKills", 0, 500, integer=True),
        "trade_deaths": _bounded_number(payload, "tradeDeaths", 0, 500, integer=True),
        "bomb_plants": _bounded_number(payload, "bombPlants", 0, 100, integer=True),
        "bomb_defuses": _bounded_number(payload, "bombDefuses", 0, 100, integer=True),
        "utility_damage_per_round": round(utility_damage / rounds, 1),
        "rounds_played": rounds,
        "damage_delta_per_round": round((damage - damage_taken) / rounds, 1),
        "rws_basic": round(_bounded_number(payload, "rwsBasic", 0, 100), 2),
        "clutch_1v1": clutches[0],
        "clutch_1v2": clutches[1],
        "clutch_1v3": clutches[2],
        "clutch_1v4": clutches[3],
        "clutch_1v5": clutches[4],
        "flash_assists": _bounded_number(payload, "flashAssists", 0, 500, integer=True),
        "team_side": str(payload.get("team_side") or ""),
    }


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
    return _run_with_database(_save_broadcast_map_result, payload, match_id)


def _save_broadcast_map_result(conn, payload, match_id):
    map_name = str(payload.get("map_name") or "").strip()[:80]
    players = payload.get("players")
    if not map_name or not isinstance(players, list) or not 1 <= len(players) <= 12:
        return _receiver_error("map_result", "地图或选手数据不完整", 400, match_id, map_name)
    if any(
        not isinstance(player, dict) or player.get("team_side") not in {"team1", "team2"}
        for player in players
    ):
        return _receiver_error("map_result", "选手队伍归属无效", 400, match_id, map_name)
    match = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
    if not match:
        return _receiver_error("map_result", "比赛不存在", 404, match_id, map_name)

    map_names = [match[f"map{slot}"] for slot in range(1, 6)]
    matching_slots = [
        index
        for index, configured in enumerate(map_names)
        if configured and normalize_map_name(configured) == normalize_map_name(map_name)
    ]
    if not matching_slots:
        return _receiver_error("map_result", "推送地图不在该比赛赛程中", 409, match_id, map_name)
    map_slot = matching_slots[0]
    db_map_name = map_names[map_slot]
    stats = [_live_player_stat(player) for player in players]
    stats = [stat for stat in stats if stat["steam_id"] and stat["name"]]
    if not stats:
        return _receiver_error("map_result", "没有可保存的选手", 400, match_id, map_name)

    affected_player_ids = {
        row["player_id"]
        for row in conn.execute(
            "SELECT DISTINCT player_id FROM match_stats WHERE match_id=? AND map_name=?",
            (match_id, db_map_name),
        ).fetchall()
        if row["player_id"]
    }
    conn.execute("DELETE FROM match_stats WHERE match_id=? AND map_name=?", (match_id, db_map_name))
    saved_players = []
    for stat in stats:
        db_player = auto_create_user_from_demo(conn, stat)
        if not db_player:
            continue
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

    team1_score = _bounded_number(payload, "team1_score", 0, 100, integer=True)
    team2_score = _bounded_number(payload, "team2_score", 0, 100, integer=True)
    sync_match_scores(
        conn,
        match_id,
        map_slot,
        {"team_a_score": team1_score, "team_b_score": team2_score},
        True,
    )
    refresh_player_performance(conn, affected_player_ids)

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
    merged["latest_map_result"] = {
        "map_name": db_map_name,
        "map_slot": map_slot,
        "team1_score": team1_score,
        "team2_score": team2_score,
        "series_complete": bool(payload.get("series_complete")),
        "players": saved_players,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }
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
    conn.commit()
    return jsonify(
        {
            "ok": True,
            "match_id": match_id,
            "map_name": db_map_name,
            "saved": len(saved_players),
            "players": saved_players,
        }
    )


def _save_gsi_payload(conn, data, map_name, forced_match_id=None):
    if forced_match_id is None:
        matches = conn.execute(
            f"""
            SELECT m.id FROM matches m
            WHERE ({get_sql_match_live()})
            AND (m.map1=? OR m.map2=? OR m.map3=? OR m.map4=? OR m.map5=?)
        """,
            (map_name, map_name, map_name, map_name, map_name),
        ).fetchall()
    else:
        matches = conn.execute(
            """SELECT id, status, map1, map2, map3, map4, map5
               FROM matches WHERE id=?""",
            (forced_match_id,),
        ).fetchall()
        if matches and matches[0]["status"] == "completed":
            return _receiver_error("gsi", "比赛已结束，拒绝覆盖直播数据", 409, forced_match_id)
        configured_maps = [matches[0][f"map{slot}"] for slot in range(1, 6)] if matches else []
        configured_maps = [name for name in configured_maps if name]
        if configured_maps and not any(
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
    for steamid, player in (data.get("allplayers", {}) or {}).items():
        record_observed_player_nickname(conn, steamid, player.get("name", ""), "gsi")

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
    previous_gsi = merged.get("gsi", {}) or {}
    previous_map_name = normalize_map_name((previous_gsi.get("map", {}) or {}).get("name", ""))
    current_map_name = normalize_map_name(map_name)
    if previous_map_name and current_map_name and previous_map_name != current_map_name:
        for key in ("round_history", "death_markers", "kill_markers", "kill_events", "bomb_events"):
            merged[key] = []
    # APP 已经在本地按正式比赛缓存阵亡点；兼容旧 GSI 客户端时才使用
    # 服务端的帧差兜底，避免两套判断互相覆盖。
    identity = data.get("_80gotv", {}) if isinstance(data, dict) else {}
    if "death_markers" not in identity:
        _record_gsi_deaths(merged, data)
    _record_gsi_bomb_events(merged, data)
    app_round_events, app_death_markers = _merge_app_live_events(merged, data)

    # 计算回合历史（每回合结束时记录胜负方）
    round_num = data.get("map", {}).get("round", 0)
    completed_round = round_num + 1
    if "round_history" not in merged:
        merged["round_history"] = []
    rh = merged["round_history"]
    # 检测新回合结束
    prev_round = data.get("previously", {}).get("round", {}) or {}
    prev_winner = prev_round.get("win_team", "")
    # MR12 常规时间只有 24 回合；加时不进入网页上的回合历史栏。
    if (
        (not app_round_events)
        and 1 <= completed_round <= 24
        and prev_winner
        and (not rh or rh[-1].get("round") != completed_round)
    ):
        current_map = data.get("map", {}) or {}
        captured_at = datetime.now(timezone.utc)
        reason_code = _round_win_reason_code(data, previous_gsi, prev_winner)
        rh.append(
            {
                "id": f"round-{completed_round}-{prev_winner.lower()}",
                "round": completed_round,
                "round_number": completed_round,
                "winner": _match_team_for_gsi_side(data, prev_winner),
                "side": prev_winner.lower(),
                "score_ct": (current_map.get("team_ct", {}) or {}).get("score", 0),
                "score_t": (current_map.get("team_t", {}) or {}).get("score", 0),
                "reason": _round_win_reason(data, previous_gsi, prev_winner),
                "reason_code": reason_code,
                "captured_at": captured_at.isoformat(),
                "captured_at_epoch": captured_at.timestamp(),
            }
        )
        if len(rh) > 24:
            rh = rh[-24:]
        merged["round_history"] = rh

    # The app is authoritative for formal-match events. It may send an empty
    # event list while a frame is being skipped, so do not manufacture kills
    # or round results from that transient frame.
    if app_death_markers:
        merged["death_markers"] = merged.get("death_markers", [])[-10:]
        merged["kill_markers"] = merged["death_markers"]
    merged["kill_events"] = []

    merged["gsi"] = data
    merged["gsi_received_at"] = datetime.now(timezone.utc).isoformat()
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
    conn.commit()

    return jsonify({"ok": True, "match_id": match_id})


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

    match_id = _read_int(payload, "match_id")
    players = payload.get("players", [])
    map_name = payload.get("map_name", "")
    team_a_name = payload.get("team_a_name", "")
    team_b_name = payload.get("team_b_name", "")
    team_a_score = _read_int(payload, "team_a_score")
    team_b_score = _read_int(payload, "team_b_score")
    rounds_count = _read_int(payload, "rounds_count")
    halftime = payload.get("halftime", {})

    if not match_id or not isinstance(players, list) or not players:
        return _receiver_error("gotv", "缺少 match_id 或 players", 400)
    if any(
        not isinstance(player, dict)
        or not isinstance(player.get("name"), str)
        or not player["name"].strip()
        for player in players
    ):
        return _receiver_error("gotv", "players 格式错误", 400, match_id, map_name)
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
    if match["status"] == "completed":
        return _receiver_error("gotv", "比赛已结束，拒绝覆盖统计数据", 409, match_id, map_name)

    # 查找地图槽位
    map_names = [match["map1"], match["map2"], match["map3"], match["map4"], match["map5"]]
    configured_maps = [name for name in map_names if name]
    if configured_maps and not any(
        normalize_map_name(name) == normalize_map_name(map_name) for name in configured_maps
    ):
        return _receiver_error("gotv", "推送地图不在该比赛赛程中", 409, match_id, map_name)
    map_slot = match_map_slot(map_name, map_names)

    # 使用数据库中已定义的地图名（回退到 demo 中的地图名）
    db_map_name = (
        map_names[map_slot] if 0 <= map_slot < len(map_names) and map_names[map_slot] else map_name
    )

    # 判断 A→T1 映射：比较 GOTV team_a name 与数据库中 team1 name
    t1_name = match["team1_name"] or ""
    a_to_t1 = (team_a_name.lower() == t1_name.lower()) if (team_a_name and t1_name) else True

    # 删除该比赛该地图的旧 match_stats（GOTV 推送的是累积数据）
    affected_player_ids = {
        row["player_id"]
        for row in conn.execute(
            """SELECT DISTINCT player_id
               FROM match_stats
               WHERE match_id=? AND map_name=?""",
            (match_id, db_map_name),
        ).fetchall()
        if row["player_id"]
    }
    conn.execute("DELETE FROM match_stats WHERE match_id=? AND map_name=?", (match_id, db_map_name))

    imported = 0
    created = 0
    t1_live_players = []
    t2_live_players = []
    for stat in players:
        db_player = auto_create_user_from_demo(conn, stat)
        if not db_player:
            continue
        if db_player.get("_new"):
            created += 1

        letter = stat.get("team_letter", "")
        is_t1 = (letter == "A") if a_to_t1 else (letter != "A")
        team_id = match["team1_id"] if is_t1 else match["team2_id"]
        live_team = t1_live_players if is_t1 else t2_live_players
        live_team.append(
            {
                "steamid": str(stat.get("steam_id", "")),
                "name": db_player["nickname"],
                "kills": stat.get("kills", 0),
                "deaths": stat.get("deaths", 0),
                "assists": stat.get("assists", 0),
                "adr": stat.get("adr", 0),
            }
        )

        stat = dict(stat)
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

    # 更新比分
    sync_match_scores(
        conn,
        match_id,
        map_slot,
        {
            "team_a_score": team_a_score,
            "team_b_score": team_b_score,
        },
        a_to_t1,
    )

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
        "team1_name": match["team1_name"] or team_a_name or "Team 1",
        "team2_name": match["team2_name"] or team_b_name or "Team 2",
        "t1_players": t1_live_players,
        "t2_players": t2_live_players,
        "rounds_count": rounds_count,
        "halftime": halftime,
        "player_count": len(players),
        "last_push": datetime.now().isoformat(),
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
    conn.commit()

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
