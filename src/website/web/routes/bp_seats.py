"""续租或释放本场比赛的操作席。"""

from flask import request, session

from src.website.domains.matches import bp_commands as veto
from src.website.runtime.host import HostError
from src.website.web.access import csrf_required, is_admin
from src.website.web.bp_access import bp_json, locked_match, participant_seat
from src.website.web.routing import site_routes


@site_routes.route("/api/bp/<int:match_id>/heartbeat", methods=["POST"])
@csrf_required
@bp_json
def bp_api_heartbeat(match_id):
    admin = is_admin()
    if "user_id" not in session and not admin:
        raise HostError("请先登录", 401)
    with locked_match(match_id) as (conn, match):
        veto.require_action_window(conn, match, check_score=False)
        seat = participant_seat(conn, match, admin=admin)
        user_id = int(session.get("admin_id" if admin else "user_id") or 0)
        revision = veto.heartbeat(conn, match, seat, user_id)
    return {"ok": True, "seat" if admin else "team": seat, "bp_revision": revision}


@site_routes.route("/api/bp/<int:match_id>/seat/release", methods=["POST"])
@csrf_required
@bp_json
def bp_api_release_seat(match_id):
    if not is_admin():
        raise HostError("仅管理员可释放席位", 403)
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        raise HostError("请求格式无效", 400)
    team = str(data.get("team") or "")
    if team not in ("t1", "t2"):
        raise HostError("队伍无效", 400)
    with locked_match(match_id) as (conn, match):
        revision = veto.release_seat(conn, match, team, session.get("admin_id"))
    return {"ok": True, "team": team, "bp_revision": revision}
