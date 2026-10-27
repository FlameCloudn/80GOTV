"""Online match Ban/Pick room and APIs."""

import hashlib
import hmac
import json
import time
from copy import deepcopy

from flask import flash, g, jsonify, redirect, render_template, request, session, url_for

from models import get_db
from services.match_roster_service import resolve_match_roster
from services.match_service import supplement_temp_teams
from utils.bp_manager import (
    ensure_bp_started,
    normalize_bp_state,
)
from utils.helpers import is_admin as _helper_is_admin
from utils.web_helpers import check_bp_password, csrf_required
from web_app import app

BP_SEAT_TIMEOUT_SECONDS = 30


def _get_bp_write_connection(match_id):
    conn = get_db()
    g.bp_write_connection = conn
    # Acquire the database write lock before reading the shared JSON state.
    conn.execute("UPDATE matches SET bp_state=bp_state WHERE id=?", (match_id,))
    return conn


@app.teardown_request
def _close_bp_write_connection(_error):
    conn = g.pop("bp_write_connection", None)
    if conn is not None:
        conn.close()


def _bp_window_is_open(match):
    return bool(match and str(match["status"] or "").lower() not in {"completed", "cancelled"})


def _bp_verification_marker(stored_password):
    return hashlib.sha256(str(stored_password or "").encode("utf-8")).hexdigest()


def _bp_password_is_verified(match):
    if not match["bp_password"]:
        return True
    marker = session.get(f"bp_verified_{match['id']}")
    return isinstance(marker, str) and hmac.compare_digest(
        marker, _bp_verification_marker(match["bp_password"])
    )


def _bp_change_lock_error(match):
    if not _bp_window_is_open(match):
        return "比赛已结束或取消，不能重置或撤回 BP"
    fields = ["team1_score", "team2_score"]
    fields.extend(f"map{slot}_t{side}" for slot in range(1, 6) for side in (1, 2))
    if any(match[field] not in (None, 0, "0", "") for field in fields):
        return "比赛已产生比分，不能重置或撤回 BP"
    return None


def _clear_bp_generated_maps(conn, match_id, bo_format):
    updates: dict[str, int | None] = {f"map{slot}": None for slot in range(1, 6)}
    updates.update({f"map{slot}_picked_by": None for slot in range(1, 6)})
    updates.update(
        {
            "bp_process": None,
            "decider_knife_winner": None,
            "decider_start_side": None,
            "has_map3": int(bo_format in ("BO3", "BO5")),
            "has_map4": int(bo_format == "BO5"),
            "has_map5": int(bo_format == "BO5"),
        }
    )
    conn.execute(
        "UPDATE matches SET " + ", ".join(f"{field}=?" for field in updates) + " WHERE id=?",
        (*updates.values(), match_id),
    )


def _load_player_ids(raw_value):
    try:
        values = json.loads(raw_value) if raw_value else []
        return (
            [int(value) for value in values if not isinstance(value, bool) and str(value).isdigit()]
            if isinstance(values, list)
            else []
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def _get_player_team(player, match, conn):
    """确定选手属于 t1 还是 t2，无法确定返回 None。"""
    if not player:
        return None
    steam_id = str(player["steam_id"] or "").strip()
    return resolve_match_roster(conn, match)["side_by_steam_id"].get(steam_id)


def _get_current_player_team(conn, match):
    if "user_id" not in session:
        return None
    user = conn.execute(
        "SELECT steam_id64 AS steam_id FROM users WHERE id=?", (session["user_id"],)
    ).fetchone()
    if not user or not user["steam_id"]:
        return None
    return _get_player_team(user, match, conn)


def _match_team_captain_user_id(conn, match, team):
    """Return the registered captain for a match side.

    Event registrations are authoritative. For older matches without a direct
    registration link, the first player in the stored roster is used only as a
    compatibility fallback when that player's Steam account is linked.
    """
    if team not in {"t1", "t2"}:
        return None
    prefix = "team1" if team == "t1" else "team2"
    team_name = str(match[f"{prefix}_name"] or "").strip()
    event_id = match["event_id"]
    player_ids = _load_player_ids(match[f"{prefix}_players"])
    if event_id and player_ids:
        placeholders = ",".join("?" for _ in player_ids)
        steam_rows = conn.execute(
            f"SELECT steam_id FROM players WHERE id IN ({placeholders})",
            player_ids,
        ).fetchall()
        match_steam_ids = {
            str(row["steam_id"] or "").strip()
            for row in steam_rows
            if str(row["steam_id"] or "").strip()
        }
        if match_steam_ids:
            registration_rows = conn.execute(
                """SELECT r.creator_user_id, s.steam_id
                   FROM event_registrations r
                   JOIN event_registration_slots s ON s.registration_id=r.id
                   WHERE r.event_id=? AND r.status='pending'""",
                (event_id,),
            ).fetchall()
            overlap = {}
            for row in registration_rows:
                steam_id = str(row["steam_id"] or "").strip()
                if steam_id in match_steam_ids and row["creator_user_id"]:
                    overlap[int(row["creator_user_id"])] = (
                        overlap.get(int(row["creator_user_id"]), 0) + 1
                    )
            if overlap:
                return max(overlap, key=lambda creator_id: overlap[creator_id])
    if event_id and team_name:
        row = conn.execute(
            """SELECT creator_user_id
               FROM event_registrations
               WHERE event_id=? AND status='pending'
                 AND lower(trim(team_name))=lower(trim(?))
               ORDER BY id LIMIT 1""",
            (event_id, team_name),
        ).fetchone()
        if row and row["creator_user_id"]:
            return int(row["creator_user_id"])

    if not player_ids:
        return None
    row = conn.execute(
        """SELECT u.id
           FROM players p
           JOIN users u ON u.steam_id64=p.steam_id
           WHERE p.id=?
           ORDER BY u.id LIMIT 1""",
        (player_ids[0],),
    ).fetchone()
    return int(row["id"]) if row else None


def _current_user_is_captain(conn, match, team):
    user_id = session.get("user_id")
    captain_id = _match_team_captain_user_id(conn, match, team)
    return bool(user_id and captain_id and int(user_id) == captain_id)


def _load_bp_state(raw_state):
    """读取 BP 状态，并把旧版状态接到修复后的规则。"""
    if not raw_state:
        return None, False
    try:
        state = json.loads(raw_state)
        changed = normalize_bp_state(state)
        return state, changed
    except (json.JSONDecodeError, TypeError, ValueError):
        return None, False


@app.route("/bp/<int:match_id>")
def bp_room(match_id):
    """BP 房间 - 需要登录；只有参赛队长可以操作。"""
    is_admin = _helper_is_admin()
    if "user_id" not in session and not is_admin:
        flash("请先登录", "error")
        return redirect(url_for("user_login"))

    conn = get_db()
    match = conn.execute(
        """
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s,
               t1.logo AS t1_logo, t2.logo AS t2_logo,
               e.name AS event_name, e.status AS event_status
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id = t1.id
        LEFT JOIN teams t2 ON m.team2_id = t2.id
        LEFT JOIN events e ON m.event_id = e.id
        WHERE m.id=?
    """,
        (match_id,),
    ).fetchone()

    if not match:
        conn.close()
        flash("比赛不存在", "error")
        return redirect(url_for("user_profile"))
    match = supplement_temp_teams(match, conn)

    team1_name = match["team1_name"]
    team2_name = match["team2_name"]

    # 查找选手身份
    player = None
    my_team = None

    if "user_id" in session:
        user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
        if user and user["steam_id64"]:
            player = conn.execute(
                "SELECT * FROM players WHERE steam_id=?", (user["steam_id64"],)
            ).fetchone()

    my_team = _get_current_player_team(conn, match)
    if not my_team and not is_admin:
        conn.close()
        flash("你未参加该比赛", "error")
        return redirect(url_for("user_profile"))

    # A match may have a shared BP password. It is stored as a hash; the
    # password itself is never sent to the page or written to logs.
    bp_verified = bool(is_admin or _bp_password_is_verified(match))
    bp_can_start = _bp_window_is_open(match)
    bp_state, state_changed = ensure_bp_started(conn, match)
    if state_changed:
        conn.commit()
    # Every locked-roster player can request their team's one operation seat.
    # Keep the old template names as compatibility aliases for the UI.
    captain_team = my_team
    is_captain = bool(my_team)
    configured_map_pool = None
    try:
        configured_map_pool = json.loads(match["map_pool"]) if match["map_pool"] else None
    except (TypeError, ValueError, json.JSONDecodeError):
        configured_map_pool = None
    if not isinstance(configured_map_pool, list) or not configured_map_pool:
        from utils.bp_manager import ALL_MAPS

        configured_map_pool = list(ALL_MAPS)

    conn.close()
    resp = app.make_response(
        render_template(
            "bp_room.html",
            match=match,
            player=player,
            bp_state=bp_state,
            bp_verified=bp_verified,
            my_team=my_team,
            team1_name=team1_name,
            team2_name=team2_name,
            is_admin=is_admin,
            is_captain=is_captain,
            captain_team=captain_team,
            bp_can_start=bp_can_start,
            configured_map_pool=configured_map_pool,
        )
    )
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/bp/<int:match_id>/verify", methods=["POST"])
@csrf_required
def bp_verify(match_id):
    """验证共享 BP 口令，并建立当前浏览器的操作会话。"""
    is_admin = _helper_is_admin()
    if "user_id" not in session and not is_admin:
        return jsonify({"ok": False, "msg": "请先登录"})
    conn = get_db()
    match = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()

    if not match:
        conn.close()
        return jsonify({"ok": False, "msg": "比赛不存在"}), 404
    if not is_admin and not _bp_window_is_open(match):
        conn.close()
        return jsonify({"ok": False, "msg": "比赛已结束或取消，BP 已锁定"}), 403

    player_team = _get_current_player_team(conn, match)
    if not is_admin and not player_team:
        conn.close()
        return jsonify({"ok": False, "msg": "你未参加该比赛"}), 403

    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        conn.close()
        return jsonify({"ok": False, "msg": "请求格式无效"}), 400
    stored_password = match["bp_password"]
    provided_password = str(data.get("password") or "")
    # Existing matches without a configured password remain usable. Once a
    # password exists, do not let a participant skip the check.
    if (
        not is_admin
        and stored_password
        and not check_bp_password(stored_password, provided_password)
    ):
        conn.close()
        return jsonify({"ok": False, "msg": "BP 共享口令错误"}), 403

    conn.close()
    session[f"bp_verified_{match_id}"] = _bp_verification_marker(stored_password)
    return jsonify(
        {"ok": True, "team": player_team, "bp_state": _load_bp_state(match["bp_state"])[0]}
    )


@app.route("/api/bp/<int:match_id>/state")
def bp_api_state(match_id):
    """获取当前 BP 状态"""
    is_admin = _helper_is_admin()
    if "user_id" not in session and not is_admin:
        return jsonify({"ok": False, "msg": "请先登录"})

    conn = get_db()
    match = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()

    if not match:
        conn.close()
        return jsonify({"ok": False, "msg": "比赛不存在"}), 404
    if not is_admin:
        if not _get_current_player_team(conn, match):
            conn.close()
            return jsonify({"ok": False, "msg": "你未参加该比赛"}), 403
    state, state_changed = ensure_bp_started(conn, match)
    if state_changed:
        conn.commit()
    if state is None:
        conn.close()
        return jsonify(
            {
                "ok": True,
                "state": None,
                "status": "waiting",
                "bp_can_start": _bp_window_is_open(match),
            }
        )
    conn.close()

    from utils.bp_manager import get_current_step_info

    info = get_current_step_info(state)
    return jsonify(
        {
            "ok": True,
            "state": state,
            "info": info,
            "bp_can_start": _bp_window_is_open(match),
        }
    )


@app.route("/api/bp/<int:match_id>/action", methods=["POST"])
@csrf_required
def bp_api_action(match_id):
    """执行 BP 操作 (roll/ban/pick/choose-side)"""
    is_admin = _helper_is_admin()
    if "user_id" not in session and not is_admin:
        return jsonify({"ok": False, "msg": "请先登录"})

    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"ok": False, "msg": "请求格式无效"}), 400
    action = data.get("action", "")
    team = data.get("team", "")  # 't1' 或 't2'
    allowed_actions = {"start", "roll", "choose_order", "ban", "pick", "choose_side"}
    if action not in allowed_actions:
        return jsonify({"ok": False, "msg": "无效操作"}), 400

    conn = _get_bp_write_connection(match_id)
    match = conn.execute(
        """
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id = t1.id
        LEFT JOIN teams t2 ON m.team2_id = t2.id
        WHERE m.id=?
    """,
        (match_id,),
    ).fetchone()

    if not match:
        conn.close()
        return jsonify({"ok": False, "msg": "比赛不存在"})
    if not _bp_window_is_open(match):
        conn.close()
        return jsonify({"ok": False, "msg": "比赛已结束或取消，BP 已锁定"}), 403
    if _bp_change_lock_error(match):
        conn.close()
        return jsonify({"ok": False, "msg": "比赛已产生比分，不能继续更改 BP"}), 409
    # 校验队伍归属（管理员除外）。锁定名单中的任何选手都可以操作，
    # 不再把权限错误地绑在“队长”这个长期身份上。
    player_team = None
    if not is_admin:
        if not _bp_password_is_verified(match):
            conn.close()
            return jsonify({"ok": False, "msg": "请先输入 BP 共享口令"}), 403
        player_team = _get_current_player_team(conn, match)
        if player_team is None:
            conn.close()
            return jsonify({"ok": False, "msg": "你未参加该比赛"})
        if action == "start":
            team = player_team
        elif team != player_team:
            conn.close()
            return jsonify({"ok": False, "msg": "不能操作对方队伍"})

    # 加载或初始化 BP 状态
    from utils.bp_manager import (
        ban_map,
        choose_side,
        get_current_step_info,
        init_bp_state,
        pick_map,
        process_roll,
        roll,
        set_first_choice,
    )

    bp_state, state_changed = ensure_bp_started(conn, match)

    if bp_state is None and action == "start":
        try:
            raw_pool = match["map_pool"]
            configured_pool = None
            if raw_pool:
                try:
                    parsed_pool = json.loads(raw_pool) if isinstance(raw_pool, str) else raw_pool
                    if isinstance(parsed_pool, list):
                        configured_pool = parsed_pool
                except (TypeError, ValueError, json.JSONDecodeError):
                    configured_pool = None
            bp_state = init_bp_state(match["bo_format"] or "BO3", configured_pool)
        except ValueError as exc:
            conn.close()
            return jsonify({"ok": False, "msg": str(exc)}), 400
        if is_admin:
            bp_state["controller_seats"]["admin"] = {
                "user_id": int(session.get("admin_id") or 0),
                "last_seen": time.time(),
            }
        elif player_team:
            bp_state["controller_seats"][player_team] = {
                "user_id": int(session["user_id"]),
                "last_seen": time.time(),
            }
        conn.execute(
            "UPDATE matches SET bp_state=? WHERE id=?",
            (json.dumps(bp_state, ensure_ascii=False), match_id),
        )
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "state": bp_state, "info": get_current_step_info(bp_state)})

    if bp_state is None:
        conn.close()
        return jsonify({"ok": False, "msg": "BP 未初始化"})

    if action == "start":
        conn.close()
        return jsonify({"ok": False, "msg": "BP 已经开始，请勿重复启动"})

    expected_revision = data.get("bp_revision")
    if expected_revision is not None:
        try:
            expected_revision = int(expected_revision)
        except (TypeError, ValueError):
            conn.close()
            return jsonify({"ok": False, "msg": "BP 版本号无效"}), 400
        if expected_revision != int(bp_state.get("revision", 0)):
            current_info = get_current_step_info(bp_state)
            conn.close()
            return jsonify(
                {
                    "ok": False,
                    "msg": "BP 已被另一名操作员更新，请刷新后再操作",
                    "state": bp_state,
                    "info": current_info,
                    "bp_revision": bp_state.get("revision", 0),
                }
            ), 409

    # 每队一个操作席，管理员另占一个管理席；超过超时时间的席位可接管。
    seat_key = "admin" if is_admin else player_team
    if seat_key:
        seats = bp_state.setdefault("controller_seats", {})
        current_seat = seats.get(seat_key)
        current_user_id = int(session.get("admin_id") or session.get("user_id") or 0)
        seat_alive = (
            current_seat
            and time.time() - float(current_seat.get("last_seen", 0) or 0)
            <= BP_SEAT_TIMEOUT_SECONDS
        )
        if seat_alive and int(current_seat.get("user_id", -1)) != current_user_id:
            conn.close()
            return jsonify(
                {"ok": False, "msg": "该操作席已有另一名操作员，请等待掉线或联系管理员释放席位"}
            ), 409
        seats[seat_key] = {"user_id": current_user_id, "last_seen": time.time()}

    ok, result = False, "未知操作"
    before_state = deepcopy(bp_state)
    before_state.pop("state_history", None)
    before_state.pop("audit_log", None)

    if action == "roll":
        value = roll()
        ok, winner = process_roll(bp_state, team, value)
        if not ok:
            result = winner
        elif winner == "tie":
            result = "双方点数相同，请重新 Roll"
        elif winner:
            result = f"{team} roll 得 {value}, 先手: {winner}"
        else:
            result = f"{team} roll 得 {value}, 等待对方 roll"

    elif action == "choose_order":
        choice = data.get("choice", "")
        if choice not in ("first", "second"):
            conn.close()
            return jsonify({"ok": False, "msg": "无效选择"})
        ok, result = set_first_choice(bp_state, team, choice)
        if ok:
            result = f"选择{'先手' if choice == 'first' else '后手'}"

    elif action == "ban":
        map_name = data.get("map", "")
        ok, result = ban_map(bp_state, team, map_name)

    elif action == "pick":
        map_name = data.get("map", "")
        ok, result = pick_map(bp_state, team, map_name)

    elif action == "choose_side":
        map_name = data.get("map", "")
        side = data.get("side", "")
        if side not in ("CT", "T"):
            conn.close()
            return jsonify({"ok": False, "msg": "无效选边"})
        ok, result = choose_side(bp_state, team, map_name, side)

    if ok:
        history = bp_state.setdefault("state_history", [])
        history.append(before_state)
        if len(history) > 30:
            del history[:-30]
        bp_state.setdefault("audit_log", []).append(
            {
                "revision": int(bp_state.get("revision", 0)) + 1,
                "user_id": session.get("user_id") if not is_admin else session.get("admin_id"),
                "team": team,
                "action": action,
                "map": data.get("map"),
                "at": time.time(),
            }
        )
        bp_state["revision"] = int(bp_state.get("revision", 0)) + 1

    if not ok:
        conn.rollback()
        conn.close()
        return jsonify(
            {
                "ok": False,
                "msg": result,
                "state": bp_state,
                "info": get_current_step_info(bp_state),
                "bp_revision": bp_state.get("revision", 0),
            }
        )

    # 保存状态
    conn.execute(
        "UPDATE matches SET bp_state=? WHERE id=?",
        (json.dumps(bp_state, ensure_ascii=False), match_id),
    )

    # BP 完成后写入地图数据
    if bp_state["status"] == "completed":
        from utils.bp_manager import save_bp_to_match

        if not save_bp_to_match(conn, match_id, bp_state):
            conn.rollback()
            conn.close()
            return jsonify({"ok": False, "msg": "BP 地图保存失败，本次操作未保存"}), 400

    conn.commit()
    conn.close()

    info = get_current_step_info(bp_state)
    return jsonify(
        {
            "ok": ok,
            "msg": result,
            "state": bp_state,
            "info": info,
            "bp_revision": bp_state.get("revision", 0),
        }
    )


@app.route("/api/bp/<int:match_id>/reset", methods=["POST"])
@csrf_required
def bp_api_reset(match_id):
    """管理员重置 BP"""
    is_admin = _helper_is_admin()
    if not is_admin:
        return jsonify({"ok": False, "msg": "仅管理员可重置 BP"}), 403

    conn = _get_bp_write_connection(match_id)
    match = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
    if not match:
        conn.close()
        return jsonify({"ok": False, "msg": "比赛不存在"}), 404
    lock_error = _bp_change_lock_error(match)
    if lock_error:
        conn.close()
        return jsonify({"ok": False, "msg": lock_error}), 409
    state, _ = ensure_bp_started(conn, match)
    if state and state.get("status") == "completed":
        _clear_bp_generated_maps(conn, match_id, state["bo"])
    conn.execute("UPDATE matches SET bp_state=NULL WHERE id=?", (match_id,))
    conn.commit()
    conn.close()

    session.pop(f"bp_verified_{match_id}", None)
    return jsonify({"ok": True, "msg": "BP 已重置"})


@app.route("/api/bp/<int:match_id>/heartbeat", methods=["POST"])
@csrf_required
def bp_api_heartbeat(match_id):
    """Keep a team's BP operation seat alive without changing BP state."""
    if "user_id" not in session and not _helper_is_admin():
        return jsonify({"ok": False, "msg": "请先登录"}), 401
    conn = _get_bp_write_connection(match_id)
    match = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
    if not match:
        conn.close()
        return jsonify({"ok": False, "msg": "比赛不存在"}), 404
    if not _bp_window_is_open(match):
        conn.close()
        return jsonify({"ok": False, "msg": "比赛已结束或取消，BP 已锁定"}), 403
    if _helper_is_admin():
        state, changed = ensure_bp_started(conn, match)
        if state is None:
            conn.close()
            return jsonify({"ok": False, "msg": "BP 尚未开始"}), 409
        user_id = int(session.get("admin_id") or 0)
        state.setdefault("controller_seats", {})["admin"] = {
            "user_id": user_id,
            "last_seen": time.time(),
        }
        conn.execute(
            "UPDATE matches SET bp_state=? WHERE id=?",
            (json.dumps(state, ensure_ascii=False), match_id),
        )
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "seat": "admin", "bp_revision": state.get("revision", 0)})
    if not _bp_password_is_verified(match):
        conn.close()
        return jsonify({"ok": False, "msg": "请先输入 BP 共享口令"}), 403
    team = _get_current_player_team(conn, match)
    if not team:
        conn.close()
        return jsonify({"ok": False, "msg": "你未参加该比赛"}), 403
    state, changed = ensure_bp_started(conn, match)
    if state is None:
        conn.close()
        return jsonify({"ok": False, "msg": "BP 尚未开始"}), 409
    seat = state.setdefault("controller_seats", {}).get(team)
    user_id = int(session["user_id"])
    if (
        seat
        and time.time() - float(seat.get("last_seen", 0) or 0) <= BP_SEAT_TIMEOUT_SECONDS
        and int(seat.get("user_id", -1)) != user_id
    ):
        conn.close()
        return jsonify({"ok": False, "msg": "本队席位已被占用"}), 409
    state.setdefault("controller_seats", {})[team] = {"user_id": user_id, "last_seen": time.time()}
    conn.execute(
        "UPDATE matches SET bp_state=? WHERE id=?",
        (json.dumps(state, ensure_ascii=False), match_id),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "team": team, "bp_revision": state.get("revision", 0)})


@app.route("/api/bp/<int:match_id>/seat/release", methods=["POST"])
@csrf_required
def bp_api_release_seat(match_id):
    """管理员释放队伍操作席，便于掉线后的接管。"""
    if not _helper_is_admin():
        return jsonify({"ok": False, "msg": "仅管理员可释放席位"}), 403
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"ok": False, "msg": "请求格式无效"}), 400
    team = str(data.get("team") or "")
    if team not in {"t1", "t2"}:
        return jsonify({"ok": False, "msg": "队伍无效"}), 400
    conn = _get_bp_write_connection(match_id)
    match = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
    if not match:
        conn.close()
        return jsonify({"ok": False, "msg": "比赛不存在"}), 404
    if str(match["status"] or "") in ("completed", "cancelled"):
        conn.close()
        return jsonify({"ok": False, "msg": "比赛已结束，不能撤销 BP"}), 409
    played = any(
        int(match[f"map{slot}_t1"] or 0) > 0 or int(match[f"map{slot}_t2"] or 0) > 0
        for slot in range(1, 6)
    )
    if played:
        conn.close()
        return jsonify({"ok": False, "msg": "比赛已产生比分，不能撤销 BP"}), 409
    state, _ = ensure_bp_started(conn, match)
    if state is None:
        conn.close()
        return jsonify({"ok": False, "msg": "BP 尚未开始"}), 409
    state.setdefault("controller_seats", {}).pop(team, None)
    state["revision"] = int(state.get("revision", 0) or 0) + 1
    state.setdefault("audit_log", []).append(
        {
            "action": "release_seat",
            "team": team,
            "revision": state["revision"],
            "at": time.time(),
            "admin_id": session.get("admin_id"),
        }
    )
    conn.execute(
        "UPDATE matches SET bp_state=? WHERE id=?",
        (json.dumps(state, ensure_ascii=False), match_id),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "team": team, "bp_revision": state.get("revision", 0)})


@app.route("/api/bp/<int:match_id>/undo", methods=["POST"])
@csrf_required
def bp_api_undo(match_id):
    """管理员撤回一步 BP；后续步骤随快照一起回退，审计记录保留。"""
    if not _helper_is_admin():
        return jsonify({"ok": False, "msg": "仅管理员可撤回 BP"}), 403
    conn = _get_bp_write_connection(match_id)
    match = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
    if not match:
        conn.close()
        return jsonify({"ok": False, "msg": "比赛不存在"}), 404
    lock_error = _bp_change_lock_error(match)
    if lock_error:
        conn.close()
        return jsonify({"ok": False, "msg": lock_error}), 409
    state, _ = ensure_bp_started(conn, match)
    if state is None:
        conn.close()
        return jsonify({"ok": False, "msg": "BP 尚未开始"}), 409
    history = state.get("state_history") or []
    if not history:
        conn.close()
        return jsonify({"ok": False, "msg": "没有可撤回的 BP 操作"}), 409
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        conn.close()
        return jsonify({"ok": False, "msg": "请求格式无效"}), 400
    target = data.get("steps_back", 1)
    try:
        steps_back = max(1, min(int(target), len(history)))
    except (TypeError, ValueError):
        steps_back = 1
    restored = deepcopy(history[-steps_back])
    audit = list(state.get("audit_log") or [])
    audit.append(
        {
            "action": "undo",
            "steps_back": steps_back,
            "at": time.time(),
            "admin_id": session.get("admin_id"),
        }
    )
    restored["state_history"] = history[:-steps_back]
    restored["audit_log"] = audit
    restored["revision"] = int(state.get("revision", 0)) + 1
    was_completed = str(state.get("status") or "") == "completed"
    if was_completed and str(restored.get("status") or "") != "completed":
        bo = str(restored.get("bo") or "BO3").upper()
        _clear_bp_generated_maps(conn, match_id, bo)
    conn.execute(
        "UPDATE matches SET bp_state=? WHERE id=?",
        (json.dumps(restored, ensure_ascii=False), match_id),
    )
    if restored.get("status") == "completed":
        from utils.bp_manager import save_bp_to_match

        if not save_bp_to_match(conn, match_id, restored):
            conn.rollback()
            conn.close()
            return jsonify({"ok": False, "msg": "BP 地图保存失败，本次撤回未保存"}), 400
    conn.commit()
    conn.close()
    from utils.bp_manager import get_current_step_info

    return jsonify(
        {
            "ok": True,
            "state": restored,
            "info": get_current_step_info(restored),
            "bp_revision": restored["revision"],
        }
    )
