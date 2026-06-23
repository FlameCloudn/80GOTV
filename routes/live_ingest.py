"""GSI and GOTV live-data receiving endpoints."""

import hmac
import json
from datetime import datetime, timezone

from flask import jsonify, request

from config import Config
from models import get_db
from services.demo_service import auto_create_user_from_demo, save_halftime_data, sync_match_scores
from services.live_log_service import persist_live_match_events, record_ingest_status
from services.live_service import _record_gsi_bomb_events, _record_gsi_deaths, _round_win_reason
from services.player_service import record_observed_player_nickname
from utils.demo_parser import match_map_slot, normalize_map_name
from utils.match_utils import get_sql_match_live
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


def _receiver_error(source, message, status_code, match_id=None, map_name=""):
    """Remember receiver failures so admins can diagnose a disconnected feed."""
    conn = get_db()
    try:
        record_ingest_status(conn, source, "error", message, match_id, map_name)
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()
    return jsonify({"ok": False, "msg": message}), status_code


@app.route("/api/gsi/receive", methods=["POST"])
def gsi_receiver():
    """
    CS2 Game State Integration 接收端点
    服务端安装 GSI 配置后，CS2 会自动 POST JSON 到该端点
    GSI 配置示例 (gamestate_integration_80gotv.cfg):
      "80GOTV" http://<host>/api/gsi/receive
    """
    data = request.get_json(force=True, silent=True)
    invalid = _invalid_gsi_payload(data)
    if invalid:
        return _receiver_error("gsi", invalid, 400)

    # CS2 GSI 回传 auth token 验证
    gsi_token = data.get("auth", {}).get("token", "")
    expected = Config.GSI_TOKEN
    if not expected:
        return _receiver_error("gsi", "服务器未配置 GSI_TOKEN", 503)
    if not hmac.compare_digest(str(gsi_token), str(expected)):
        return _receiver_error("gsi", "token 不匹配", 403)

    # 尝试匹配比赛
    map_name = data.get("map", {}).get("name", "")
    if not isinstance(map_name, str) or not map_name.strip():
        return _receiver_error("gsi", "缺少地图名", 400)

    conn = get_db()
    # 找正在打的比赛（匹配地图名）
    matches = conn.execute(
        f"""
        SELECT m.id FROM matches m
        WHERE ({get_sql_match_live()})
        AND (m.map1=? OR m.map2=? OR m.map3=? OR m.map4=? OR m.map5=?)
    """,
        (map_name, map_name, map_name, map_name, map_name),
    ).fetchall()

    if not matches:
        conn.close()
        return _receiver_error("gsi", "未找到匹配的比赛", 404, map_name=map_name)
    if len(matches) > 1:
        conn.close()
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
    previous_gsi = merged.get("gsi", {}) or {}
    # 只在阵亡瞬间记录位置，网页不会显示所有选手的实时坐标。
    _record_gsi_deaths(merged, data)
    _record_gsi_bomb_events(merged, data)

    # 计算回合历史（每回合结束时记录胜负方）
    round_num = data.get("map", {}).get("round", 0)
    if "round_history" not in merged:
        merged["round_history"] = []
    rh = merged["round_history"]
    # 检测新回合结束
    prev_round = data.get("previously", {}).get("round", {}) or {}
    prev_winner = prev_round.get("win_team", "")
    if prev_winner and (not rh or rh[-1].get("round") != round_num - 1):
        current_map = data.get("map", {}) or {}
        rh.append(
            {
                "round": round_num - 1,
                "winner": "t1" if prev_winner == "CT" else "t2",
                "side": prev_winner.lower(),
                "score_ct": (current_map.get("team_ct", {}) or {}).get("score", 0),
                "score_t": (current_map.get("team_t", {}) or {}).get("score", 0),
                "reason": _round_win_reason(data, previous_gsi, prev_winner),
            }
        )
        if len(rh) > 20:
            rh = rh[-20:]
        merged["round_history"] = rh

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
    conn.close()

    return jsonify({"ok": True, "match_id": match_id})


@app.route("/api/gotv/stats", methods=["POST"])
def gotv_stats_receiver():
    """
    GOTV 实时数据接收端点
    gotv_relay/relay.py 定时解析 demo 并 POST 选手统计数据到此端点
    请求头: X-GOTV-Secret: Config.GOTV_SECRET
    """
    if not Config.GOTV_SECRET:
        return _receiver_error("gotv", "服务器未配置 GOTV_SECRET", 503)
    if not hmac.compare_digest(request.headers.get("X-GOTV-Secret", ""), Config.GOTV_SECRET):
        return _receiver_error("gotv", "未授权", 403)

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

    conn = get_db()
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
        conn.close()
        return _receiver_error("gotv", "比赛不存在", 404, match_id, map_name)
    if match["status"] == "completed":
        conn.close()
        return _receiver_error("gotv", "比赛已结束，拒绝覆盖统计数据", 409, match_id, map_name)

    # 查找地图槽位
    map_names = [match["map1"], match["map2"], match["map3"], match["map4"], match["map5"]]
    configured_maps = [name for name in map_names if name]
    if configured_maps and not any(
        normalize_map_name(name) == normalize_map_name(map_name) for name in configured_maps
    ):
        conn.close()
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

        conn.execute(
            """
            INSERT INTO match_stats(match_id, player_id, team_id, kills, deaths, assists,
                                   adr, kpr, dpr, rating, impact, kast, headshot_percentage,
                                   t_rating, ct_rating, t_kills, ct_kills, t_deaths, ct_deaths, t_adr, ct_adr,
                                   map_name, side)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
            (
                match_id,
                db_player["id"],
                team_id,
                stat.get("kills", 0),
                stat.get("deaths", 0),
                stat.get("assists", 0),
                stat.get("adr", 0),
                stat.get("kpr", 0),
                stat.get("dpr", 0),
                stat.get("rating", 0),
                stat.get("impact", 0),
                stat.get("kast", 0),
                stat.get("headshot_percentage", 0),
                stat.get("t_rating", 0),
                stat.get("ct_rating", 0),
                stat.get("t_kills", 0),
                stat.get("ct_kills", 0),
                stat.get("t_deaths", 0),
                stat.get("ct_deaths", 0),
                stat.get("t_adr", 0),
                stat.get("ct_adr", 0),
                db_map_name,
                "",
            ),
        )
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
    conn.close()

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
