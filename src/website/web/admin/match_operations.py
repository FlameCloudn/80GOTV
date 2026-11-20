"""HTTP endpoints for managing actual play, technical replays, and results."""

from contextlib import closing

from flask import flash, jsonify, redirect, render_template, request, session, url_for

from src.website.domains.operations.audit import read_player_stats, read_result_history
from src.website.domains.operations.inspection import read_overview
from src.website.runtime.database import get_db
from src.website.runtime.host import HostError, is_managed_match, write
from src.website.web.access import admin_required, csrf_required
from src.website.web.admin.admin import admin_bp
from src.website.web.localization import t as ui_message
from src.website.web.read_models.operations_panel import read_panel_bundle
from src.website.workflows.admin_operations import command_note, dispatch_operation


@admin_bp.get("/matches/<int:match_id>/operations")
@admin_required
def managed_operations(match_id):
    with closing(get_db()) as conn:
        try:
            if not is_managed_match(conn, match_id):
                raise HostError("本场不属于新赛事流程", 404)
            conn.execute("BEGIN")
            return jsonify(ok=True, **read_overview(conn, match_id))
        except HostError as exc:
            return jsonify(ok=False, error=exc.message), exc.status


@admin_bp.get("/matches/<int:match_id>/operations/runs/<int:run_id>/players/<int:player_id>/stats")
@admin_required
def managed_stat_fields(match_id, run_id, player_id):
    with closing(get_db()) as conn:
        try:
            if not is_managed_match(conn, match_id):
                raise HostError("本场不属于新赛事流程", 404)
            conn.execute("BEGIN")
            result = read_player_stats(
                conn,
                match_id,
                run_id,
                player_id,
                request.args.get("scope", "all"),
                include_history=request.args.get("history") == "1",
            )
            return jsonify(ok=True, **result)
        except HostError as exc:
            return jsonify(ok=False, error=exc.message), exc.status


@admin_bp.get("/matches/<int:match_id>/operations/history")
@admin_required
def managed_result_history(match_id):
    with closing(get_db()) as conn:
        if not is_managed_match(conn, match_id):
            return jsonify(ok=False, error="本场不属于新赛事流程"), 404
        conn.execute("BEGIN")
        return jsonify(ok=True, **read_result_history(conn, match_id))


@admin_bp.get("/matches/<int:match_id>/operations/panel-context")
@admin_required
def managed_operations_panel_context(match_id):
    with closing(get_db()) as conn:
        try:
            if not is_managed_match(conn, match_id):
                raise HostError("本场不属于新赛事流程", 404)
            conn.execute("BEGIN")
            return jsonify(ok=True, **read_panel_bundle(conn, match_id))
        except HostError as exc:
            return jsonify(ok=False, error=exc.message), exc.status


@admin_bp.get("/matches/<int:match_id>/operate")
@admin_required
def managed_match_operate(match_id):
    with closing(get_db()) as conn:
        if not is_managed_match(conn, match_id):
            flash(ui_message("flash.match_operations.this_match_uses_the_legacy_process"), "info")
            return redirect(url_for("admin.admin_matches_edit", match_id=match_id))
        conn.execute("BEGIN")
        bundle = read_panel_bundle(conn, match_id)
    return render_template(
        "admin/operations/match_operations.html",
        match_id=match_id,
        match=bundle["context"]["match"],
        participants=bundle["context"]["participants"],
        panel_bundle=bundle,
    )


@admin_bp.post("/matches/<int:match_id>/operations/<action>")
@csrf_required
@admin_required
def managed_operation(match_id, action):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(ok=False, error="请提交 JSON 对象"), 400
    with closing(get_db()) as conn:
        try:
            if not is_managed_match(conn, match_id):
                raise HostError("本场不属于新赛事流程", 404)
            with write(conn):
                result = dispatch_operation(conn, match_id, action, body, session["admin_id"])
            return jsonify({"ok": True, **result}), 409 if result.get("ok") is False else 200
        except HostError as exc:
            return jsonify(ok=False, error=exc.message), exc.status


@admin_bp.route("/events/<int:event_id>/operations/bracket", methods=["GET", "POST"])
@csrf_required
@admin_required
def managed_bracket(event_id):
    from src.website.domains.matches.managed_bracket import create_bracket_match, get_bracket_links
    from src.website.runtime.host import is_managed_event

    with closing(get_db()) as conn:
        try:
            if not is_managed_event(conn, event_id):
                raise HostError("本届仍使用原签表", 404)
            if request.method == "GET":
                from src.website.web.admin.event_brackets import _event_bracket_matches

                conn.execute("BEGIN")
                return jsonify(
                    ok=True,
                    links=get_bracket_links(conn, event_id),
                    matches=_event_bracket_matches(conn, event_id),
                )
            body = request.get_json(silent=True)
            if not isinstance(body, dict):
                raise HostError("请提交赛制、轮次及可选的开赛时间", 400)
            at = command_note(body, "match_time", required=False) or None
            if at and conn.execute("SELECT datetime(?)", (at,)).fetchone()[0] is None:
                raise HostError("开赛时间无效", 400)
            with write(conn):
                result = create_bracket_match(
                    conn,
                    event_id,
                    bo_format=body.get("bo_format"),
                    stage=command_note(body, "stage"),
                    actor=session["admin_id"],
                    match_time=at,
                )
            return jsonify(ok=True, **result), 201
        except HostError as exc:
            return jsonify(ok=False, error=exc.message), exc.status
