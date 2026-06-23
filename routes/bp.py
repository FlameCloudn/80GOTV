"""Online match Ban/Pick room and APIs."""

import json

from flask import flash, jsonify, redirect, render_template, request, session, url_for

from models import get_db
from utils.bp_manager import normalize_bp_state
from utils.helpers import is_admin as _helper_is_admin
from utils.rate_limiter import rate_limit
from utils.web_helpers import (
    check_bp_password,
    csrf_required,
    hash_bp_password,
    is_hashed_bp_password,
)
from web_app import app


def _load_player_ids(raw_value):
    try:
        values = json.loads(raw_value) if raw_value else []
        return [int(value) for value in values] if isinstance(values, list) else []
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def _get_player_team(player, match):
    """确定选手属于 t1 还是 t2，无法确定返回 None。"""
    if match["team1_id"] and match["team1_id"] > 0 and player["team_id"] == match["team1_id"]:
        return "t1"
    if match["team2_id"] and match["team2_id"] > 0 and player["team_id"] == match["team2_id"]:
        return "t2"
    if player["id"] in _load_player_ids(match["team1_players"]):
        return "t1"
    if player["id"] in _load_player_ids(match["team2_players"]):
        return "t2"
    return None


def _get_current_player_team(conn, match):
    if "user_id" not in session:
        return None
    user = conn.execute("SELECT steam_id64 FROM users WHERE id=?", (session["user_id"],)).fetchone()
    if not user or not user["steam_id64"]:
        return None
    player = conn.execute(
        "SELECT id, team_id FROM players WHERE steam_id=?", (user["steam_id64"],)
    ).fetchone()
    return _get_player_team(player, match) if player else None


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
    """BP 房间 - 需要登录和密码验证"""
    is_admin = _helper_is_admin()
    if "user_id" not in session and not is_admin:
        flash("请先登录", "error")
        return redirect(url_for("user_login"))

    conn = get_db()
    match = conn.execute(
        """
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
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

    # 默认队伍名
    team1_name = match["team1_name"] or "TEAM 1"
    team2_name = match["team2_name"] or "TEAM 2"

    # 查找选手身份
    player = None
    my_team = None

    if "user_id" in session:
        user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
        if user and user["steam_id64"]:
            player = conn.execute(
                "SELECT * FROM players WHERE steam_id=?", (user["steam_id64"],)
            ).fetchone()

    if player:
        # 判断选手属于哪一队
        if match["team1_id"] and match["team1_id"] > 0 and player["team_id"] == match["team1_id"]:
            my_team = "t1"
        elif match["team2_id"] and match["team2_id"] > 0 and player["team_id"] == match["team2_id"]:
            my_team = "t2"
        else:
            import json as _json

            t1p = (
                [int(x) for x in _json.loads(match["team1_players"])]
                if match["team1_players"]
                else []
            )
            t2p = (
                [int(x) for x in _json.loads(match["team2_players"])]
                if match["team2_players"]
                else []
            )
            if player["id"] in t1p:
                my_team = "t1"
            elif player["id"] in t2p:
                my_team = "t2"

        # 检查是否参赛（match_stats 或队伍名单）
        if not my_team:
            in_match = conn.execute(
                "SELECT 1 FROM match_stats WHERE match_id=? AND player_id=?",
                (match_id, player["id"]),
            ).fetchone()
            if not in_match:
                import json as _json2

                t1p = (
                    [int(x) for x in _json2.loads(match["team1_players"])]
                    if match["team1_players"]
                    else []
                )
                t2p = (
                    [int(x) for x in _json2.loads(match["team2_players"])]
                    if match["team2_players"]
                    else []
                )
                if player["id"] not in t1p and player["id"] not in t2p:
                    if not is_admin:
                        conn.close()
                        flash("你未参加该比赛", "error")
                        return redirect(url_for("user_profile"))

    if not player and not is_admin:
        conn.close()
        flash("请先在个人主页绑定 Steam ID", "error")
        return redirect(url_for("user_profile"))

    bp_verified = session.get(f"bp_verified_{match_id}") or is_admin

    # 未验证密码时不把 BP 过程发到浏览器。
    bp_state = None
    if (bp_verified or not match["bp_password"]) and match["bp_state"]:
        bp_state, state_changed = _load_bp_state(match["bp_state"])
        if state_changed:
            conn.execute(
                "UPDATE matches SET bp_state=? WHERE id=?",
                (json.dumps(bp_state, ensure_ascii=False), match_id),
            )
            conn.commit()

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
        )
    )
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/bp/<int:match_id>/verify", methods=["POST"])
@csrf_required
def bp_verify(match_id):
    """验证 BP 密码"""
    is_admin = _helper_is_admin()
    if "user_id" not in session and not is_admin:
        return jsonify({"ok": False, "msg": "请先登录"})
    if not rate_limit(f"bp_verify:{match_id}", 5, 300, by_ip=True):
        return jsonify({"ok": False, "msg": "尝试次数过多，请 5 分钟后再试"}), 429

    password = request.form.get("password", "")
    conn = get_db()
    match = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()

    if not match or not match["bp_password"]:
        conn.close()
        return jsonify({"ok": False, "msg": "该比赛未设置 BP 密码"})

    if not is_admin and not _get_current_player_team(conn, match):
        conn.close()
        return jsonify({"ok": False, "msg": "你未参加该比赛"}), 403

    if check_bp_password(match["bp_password"], password):
        if not is_hashed_bp_password(match["bp_password"]):
            conn.execute(
                "UPDATE matches SET bp_password=? WHERE id=?",
                (hash_bp_password(password), match_id),
            )
            conn.commit()
        conn.close()
        session[f"bp_verified_{match_id}"] = True
        bp_state, state_changed = _load_bp_state(match["bp_state"])
        if state_changed:
            conn = get_db()
            conn.execute(
                "UPDATE matches SET bp_state=? WHERE id=?",
                (json.dumps(bp_state, ensure_ascii=False), match_id),
            )
            conn.commit()
            conn.close()
        return jsonify({"ok": True, "bp_state": bp_state})
    else:
        conn.close()
        return jsonify({"ok": False, "msg": "密码错误"})


@app.route("/api/bp/<int:match_id>/state")
def bp_api_state(match_id):
    """获取当前 BP 状态"""
    is_admin = _helper_is_admin()
    if "user_id" not in session and not is_admin:
        return jsonify({"ok": False, "msg": "请先登录"})

    conn = get_db()
    match = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()

    if not match or not match["bp_state"]:
        conn.close()
        return jsonify({"ok": False, "msg": "BP 未开始"})
    if not is_admin:
        if not _get_current_player_team(conn, match):
            conn.close()
            return jsonify({"ok": False, "msg": "你未参加该比赛"}), 403
        if match["bp_password"] and not session.get(f"bp_verified_{match_id}"):
            conn.close()
            return jsonify({"ok": False, "msg": "请先验证 BP 密码"}), 403
    conn.close()

    state, state_changed = _load_bp_state(match["bp_state"])
    if state is None:
        return jsonify({"ok": False, "msg": "BP 状态数据异常"})

    if state_changed:
        conn = get_db()
        conn.execute(
            "UPDATE matches SET bp_state=? WHERE id=?",
            (json.dumps(state, ensure_ascii=False), match_id),
        )
        conn.commit()
        conn.close()

    from utils.bp_manager import get_current_step_info

    info = get_current_step_info(state)
    return jsonify({"ok": True, "state": state, "info": info})


@app.route("/api/bp/<int:match_id>/action", methods=["POST"])
@csrf_required
def bp_api_action(match_id):
    """执行 BP 操作 (roll/ban/pick/choose-side)"""
    is_admin = _helper_is_admin()
    if "user_id" not in session and not is_admin:
        return jsonify({"ok": False, "msg": "请先登录"})

    data = request.get_json(silent=True) or {}
    action = data.get("action", "")
    team = data.get("team", "")  # 't1' 或 't2'
    allowed_actions = {"start", "roll", "choose_order", "ban", "pick", "choose_side"}
    if action not in allowed_actions:
        return jsonify({"ok": False, "msg": "无效操作"}), 400

    conn = get_db()
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
    if match["bp_password"] and not session.get(f"bp_verified_{match_id}") and not is_admin:
        conn.close()
        return jsonify({"ok": False, "msg": "请先验证 BP 密码"}), 403

    # 校验队伍归属（管理员除外）
    if not is_admin:
        player_team = _get_current_player_team(conn, match)
        if player_team is None:
            conn.close()
            return jsonify({"ok": False, "msg": "你未参加该比赛"})
        if action != "start" and team != player_team:
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

    bp_state = None
    if match["bp_state"]:
        bp_state, _ = _load_bp_state(match["bp_state"])

    if bp_state is None and action == "start":
        try:
            bp_state = init_bp_state(match["bo_format"] or "BO3")
        except ValueError as exc:
            conn.close()
            return jsonify({"ok": False, "msg": str(exc)}), 400
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

    ok, result = False, "未知操作"

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

    # 保存状态
    conn.execute(
        "UPDATE matches SET bp_state=? WHERE id=?",
        (json.dumps(bp_state, ensure_ascii=False), match_id),
    )

    # BP 完成后写入地图数据
    if bp_state["status"] == "completed":
        from utils.bp_manager import save_bp_to_match

        save_bp_to_match(conn, match_id, bp_state)

    conn.commit()
    conn.close()

    info = get_current_step_info(bp_state)
    return jsonify({"ok": ok, "msg": result, "state": bp_state, "info": info})


@app.route("/api/bp/<int:match_id>/reset", methods=["POST"])
@csrf_required
def bp_api_reset(match_id):
    """管理员重置 BP"""
    is_admin = _helper_is_admin()
    if not is_admin:
        return jsonify({"ok": False, "msg": "仅管理员可重置 BP"}), 403

    conn = get_db()
    conn.execute("UPDATE matches SET bp_state=NULL WHERE id=?", (match_id,))
    conn.commit()
    conn.close()

    session.pop(f"bp_verified_{match_id}", None)
    return jsonify({"ok": True, "msg": "BP 已重置"})
