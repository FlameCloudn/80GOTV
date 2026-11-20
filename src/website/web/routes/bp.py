"""BP 房间、浏览器共享口令与当前状态。"""

from flask import current_app, flash, redirect, render_template, request, session, url_for

from src.website.domains.matches import bp_manager as rules
from src.website.domains.matches import bp_match_state as store
from src.website.domains.matches.maps import bp_lock_reason
from src.website.domains.matches.opponents import read_opponents
from src.website.runtime.database import db
from src.website.runtime.host import HostError
from src.website.web.access import check_bp_password, csrf_required, is_admin
from src.website.web.bp_access import bp_json, password_verified, verification_marker
from src.website.web.localization import t as ui_message
from src.website.web.routing import site_routes


@site_routes.route("/bp/<int:match_id>")
def bp_room(match_id):
    admin = is_admin()
    if "user_id" not in session and not admin:
        flash(ui_message("flash.bp.please_log_in_first"), "error")
        return redirect(url_for("user_login"))
    with db() as conn:
        match = read_opponents(conn, match_id)
        if not match:
            flash(ui_message("flash.bp.match_not_found"), "error")
            return redirect(url_for("user_profile"))
        team = store.player_team_for_account(conn, match, session.get("user_id"))
        if not team and not admin:
            flash(ui_message("flash.bp.you_are_not_a_participant_in"), "error")
            return redirect(url_for("user_profile"))
        can_start = store.window_is_open(match) and not bp_lock_reason(conn, match)
        state, _ = store.ensure_bp_started(conn, match)
    response = current_app.make_response(
        render_template(
            "public/matches/bp_room.html",
            match=match,
            bp_state=state,
            my_team=team,
            is_admin=admin,
            bp_verified=admin or password_verified(match),
            bp_can_start=can_start,
            configured_map_pool=store.map_pool(match["map_pool"]) or list(rules.ALL_MAPS),
        )
    )
    response.headers.update(
        {
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        }
    )
    return response


@site_routes.route("/bp/<int:match_id>/verify", methods=["POST"])
@csrf_required
@bp_json
def bp_verify(match_id):
    admin = is_admin()
    if "user_id" not in session and not admin:
        raise HostError("请先登录", 200)
    with db() as conn:
        match = store.find_match(conn, match_id)
        if match is None:
            raise HostError("比赛不存在", 404)
        if not admin and not store.window_is_open(match):
            raise HostError("比赛已结束或取消，BP 已锁定", 403)
        team = store.player_team_for_account(conn, match, session.get("user_id"))
        if not admin and not team:
            raise HostError("你未参加该比赛", 403)
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            raise HostError("请求格式无效", 400)
        stored = match["bp_password"]
        if not admin and stored and not check_bp_password(stored, str(data.get("password") or "")):
            raise HostError("BP 共享口令错误", 403)
    session[f"bp_verified_{match_id}"] = verification_marker(stored)
    return {"ok": True, "team": team, "bp_state": store.parse_bp_state(match["bp_state"])[0]}


@site_routes.route("/api/bp/<int:match_id>/state")
@bp_json
def bp_api_state(match_id):
    admin = is_admin()
    if "user_id" not in session and not admin:
        raise HostError("请先登录", 200)
    with db() as conn:
        match = store.find_match(conn, match_id)
        if match is None:
            raise HostError("比赛不存在", 404)
        if not admin and not store.player_team_for_account(conn, match, session.get("user_id")):
            raise HostError("你未参加该比赛", 403)
        state, _ = store.ensure_bp_started(conn, match)
        can_start = store.window_is_open(match) and not bp_lock_reason(conn, match)
    if state is None:
        return {"ok": True, "state": None, "status": "waiting", "bp_can_start": can_start}
    return {
        "ok": True,
        "state": state,
        "info": rules.get_current_step_info(state),
        "bp_can_start": can_start,
    }
