"""操作员的 BP 步骤与管理员的撤销、重置入口。"""

from flask import request, session

from src.website.domains.matches import bp_commands as veto
from src.website.runtime.host import HostError
from src.website.web.access import csrf_required, is_admin
from src.website.web.bp_access import bp_json, locked_match, participant_seat, state_fields
from src.website.web.routing import site_routes


@site_routes.route("/api/bp/<int:match_id>/action", methods=["POST"])
@csrf_required
@bp_json
def bp_api_action(match_id):
    admin = is_admin()
    if "user_id" not in session and not admin:
        raise HostError("请先登录", 200)
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        raise HostError("请求格式无效", 400)
    action = data.get("action", "")
    if action not in veto.TURN_ACTIONS:
        raise HostError("无效操作", 400)
    with locked_match(match_id, missing_status=200) as (conn, match):
        veto.require_action_window(conn, match, check_score=True)
        seat = participant_seat(conn, match, admin=admin, denied_status=200)
        team = data.get("team", "")
        if not admin:
            if action == "start":
                team = seat
            elif team != seat:
                raise HostError("不能操作对方队伍", 200)
        state, message = veto.play_turn(
            conn,
            match,
            action,
            team,
            data,
            seat=seat,
            actor_id=session.get("admin_id" if admin else "user_id"),
            seat_user_id=int(session.get("admin_id") or session.get("user_id") or 0),
        )
    fields = state_fields(state)
    if action == "start":
        del fields["bp_revision"]
        return {"ok": True, **fields}
    return {"ok": True, "msg": message, **fields}


@site_routes.route("/api/bp/<int:match_id>/reset", methods=["POST"])
@csrf_required
@bp_json
def bp_api_reset(match_id):
    if not is_admin():
        raise HostError("仅管理员可重置 BP", 403)
    with locked_match(match_id) as (conn, match):
        veto.reset(conn, match)
    session.pop(f"bp_verified_{match_id}", None)
    return {"ok": True, "msg": "BP 已重置"}


@site_routes.route("/api/bp/<int:match_id>/undo", methods=["POST"])
@csrf_required
@bp_json
def bp_api_undo(match_id):
    if not is_admin():
        raise HostError("仅管理员可撤回 BP", 403)
    with locked_match(match_id) as (conn, match):
        state = veto.undo(conn, match, request.get_json(silent=True) or {}, session.get("admin_id"))
    return {"ok": True, **state_fields(state)}
