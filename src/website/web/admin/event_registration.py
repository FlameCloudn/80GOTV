"""Manage signup control and the event roster workbench."""

import json
import time
from contextlib import closing, nullcontext

from flask import flash, jsonify, redirect, render_template, request, session, url_for

from src.website.domains.events import formation
from src.website.domains.events import registration as signup
from src.website.domains.events import roster_management as event_rosters
from src.website.runtime.database import get_db
from src.website.runtime.host import HostError, has_event_schema, write
from src.website.web.access import admin_required as login_required
from src.website.web.access import csrf_required
from src.website.web.admin.admin import admin_bp
from src.website.web.admin.event_forms import _form_number
from src.website.web.localization import t as ui_message
from src.website.web.read_models.event_admin import (
    _event_registration_control,
    _event_roster_context,
)


@admin_bp.get("/events/<int:event_id>/registration-control")
@login_required
def admin_registration_control(event_id):
    with closing(get_db()) as conn:
        if not has_event_schema(conn):
            return jsonify(success=False, error="此数据库未开放赛前托管"), 409
        conn.execute("BEGIN")
        try:
            signup.require_admin(conn, session.get("admin_id"))
        except HostError as exc:
            return jsonify(success=False, error=str(exc)), exc.status
        state = conn.execute(
            """SELECT c.*,b.formation_revision,b.formed_at FROM event_registration_control c
            LEFT JOIN event_formation_batches b USING(event_id) WHERE c.event_id=?""",
            (event_id,),
        ).fetchone()
        if state is None:
            return jsonify(success=False, error="本届尚未启用"), 404
        entrants = [
            event_rosters.roster(conn, event_id, r[0])
            for r in conn.execute(
                "SELECT event_entrant_id FROM event_entrants WHERE event_id=? ORDER BY event_entrant_id",
                (event_id,),
            )
        ]
        candidates = [
            dict(r)
            for r in conn.execute(
                """SELECT c.player_id,c.assigned_entrant_id,
            e.registration_origin,e.preferred_registration_id FROM event_reserve_candidates c JOIN event_signup_entries e
            USING(event_id,player_id) WHERE event_id=? AND withdrawn_at IS NULL ORDER BY c.player_id""",
                (event_id,),
            )
        ]
        unverified = [
            dict(r)
            for r in conn.execute(
                """SELECT s.registration_id,s.roster_slot,
            s.display_label,s.steam_id FROM event_signup_reservations s JOIN event_registration_groups g
            USING(registration_id) WHERE g.event_id=? ORDER BY s.registration_id,s.roster_slot""",
                (event_id,),
            )
        ]
        return jsonify(
            **dict(state),
            entrants=entrants,
            reserve_candidates=candidates,
            unverified_reservations=unverified,
        )


@admin_bp.post("/events/<int:event_id>/registration-control/<action>")
@csrf_required
@login_required
def admin_registration_action(event_id, action):
    return _registration_action(event_id, action)


def _registration_action(event_id, action):
    body = request.get_json(silent=True) if request.is_json else request.form.to_dict()
    if not isinstance(body, dict):
        return jsonify(success=False, error="请求需要有效的表单或 JSON 对象"), 400
    try:
        with closing(get_db()) as conn, nullcontext() if action == "form-due" else write(conn):
            admin = session.get("admin_id")
            signup.require_admin(conn, admin)
            now = int(time.time())
            common = dict(admin_id=admin, now=now)
            reason = body.get("reason", "")
            if not isinstance(reason, str):
                raise HostError("理由必须是文字", 400)

            def number(key):
                return _form_number(body.get(key))

            def structured(key, kind):
                value = body.get(key, {} if kind is dict else None)
                if not request.is_json and isinstance(value, str):
                    try:
                        value = json.loads(value)
                    except ValueError:
                        raise HostError("名单或协商资料格式不正确", 400) from None
                if not isinstance(value, kind):
                    raise HostError("名单或协商资料格式不正确", 400)
                return value

            def ids(value):
                if not isinstance(value, list) or not value:
                    raise HostError("请选择非空名单", 400)
                return [_form_number(x) for x in value]

            result = {"event_id": event_id}
            if action == "enable":
                signup.enable_event(conn, event_id, number("registration_deadline"), **common)
            elif action == "disable":
                signup.disable_unused_event(conn, event_id, **common)
            elif action == "archive-team":
                if "registration_id" in body and "event_entrant_id" not in body:
                    reg = number("registration_id")
                elif "event_entrant_id" in body and "registration_id" not in body:
                    reg = event_rosters.roster(conn, event_id, number("event_entrant_id"))[
                        "registration_id"
                    ]
                else:
                    raise HostError("请提供本届的一个报名号或参赛身份", 400)
                result = event_rosters.archive_team(conn, event_id, reg, reason=reason, **common)
            elif action == "form-due":
                result = formation.process_due_event(conn, event_id, admin_id=admin)
            elif action == "archive":
                signup.archive_event(conn, event_id, admin_id=admin, now=now)
            elif action == "link-club":
                signup.link_club(
                    conn,
                    event_id,
                    number("registration_id"),
                    number("club_id"),
                    admin_id=admin,
                    now=now,
                )
            elif action == "review-reservation":
                slot = _form_number(body.get("roster_slot"), minimum=0)
                if slot > 4:
                    raise HostError("位置须为 0 至 4", 400)
                account = body.get("verified_account_id")
                signup.review_reservation(
                    conn,
                    event_id,
                    number("registration_id"),
                    slot,
                    _form_number(account) if account not in (None, "") else None,
                    reason=reason,
                    **common,
                )
            elif action == "confirm-initial":
                if set(body) - {
                    "registration_action",
                    "csrf_token",
                    "event_entrant_ids",
                    "expected_revision",
                }:
                    raise HostError("只能确认该版本当前的五人，不能同时更改名单", 400)
                result = event_rosters.confirm_initial_rosters(
                    conn,
                    event_id,
                    ids(structured("event_entrant_ids", list)),
                    expected_revision=number("expected_revision"),
                    **common,
                )
            elif action == "adjust-formation":
                assignments = {
                    _form_number(k): ids(v) for k, v in structured("assignments", dict).items()
                }
                result = event_rosters.adjust_formation(
                    conn,
                    event_id,
                    assignments,
                    expected_revision=number("expected_revision"),
                    reason=reason,
                    **common,
                )
            elif action == "assign-reserve":
                excluded = {
                    _form_number(k): v for k, v in structured("excluded_candidates", dict).items()
                }
                result = event_rosters.assign_reserve(
                    conn,
                    event_id,
                    number("event_entrant_id"),
                    number("player_id"),
                    excluded_candidates=excluded,
                    expected_revision=number("expected_revision"),
                    reason=reason,
                    **common,
                )
            elif action == "replace-before-series":
                result = event_rosters.replace_before_series(
                    conn,
                    event_id,
                    number("event_entrant_id"),
                    number("outgoing_player_id"),
                    number("incoming_player_id"),
                    expected_revision=number("expected_revision"),
                    reason=reason,
                    **common,
                )
            else:
                raise HostError("未识别的赛事操作", 404)
    except HostError as exc:
        response = jsonify(success=False, error=str(exc))
        if exc.code:
            response.headers["X-80GOTV-Error"] = exc.code
        return response, exc.status
    return jsonify(result)


@admin_bp.get("/events/<int:event_id>/roster")
@login_required
def admin_event_roster(event_id):
    with closing(get_db()) as conn:
        event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        if not event:
            return "赛事不存在", 404
        if not has_event_schema(conn):
            flash(ui_message("flash.admin_events.prematch_management_is_not_enabled_on"), "error")
            return redirect(url_for("admin.admin_events_edit", event_id=event_id))
        try:
            signup.require_admin(conn, session.get("admin_id"))
        except HostError as exc:
            flash(str(exc), "error")
            return redirect(url_for("admin.admin_events"))
        control = _event_registration_control(conn, event)
        if not control["enabled"]:
            flash(ui_message("flash.admin_events.managed_registration_is_not_enabled_for"), "error")
            return redirect(url_for("admin.admin_events_edit", event_id=event_id))
        ctx = _event_roster_context(conn, event, control)
        return render_template(
            "admin/events/event_roster.html",
            event=event,
            control=control,
            **ctx,
        )
