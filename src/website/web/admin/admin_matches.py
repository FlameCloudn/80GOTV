"""Administrator routes for match scheduling and series controls."""

import logging

from flask import flash, redirect, render_template, request, session, url_for

from src.website.domains.matches import legacy_roster_edit, participants, setup
from src.website.domains.matches.admin_queries import _get_match_form_row, match_list
from src.website.runtime.database import get_db, write_transaction
from src.website.runtime.host import (
    PREMATCH_ONLY,
    HostError,
    is_managed_event,
    is_managed_match,
    write,
)
from src.website.web.access import admin_required as login_required
from src.website.web.access import csrf_required
from src.website.web.admin.admin import admin_bp
from src.website.web.admin.match_forms import form_state, parse_match_form
from src.website.web.admin.match_pages import show_match_form
from src.website.web.localization import t as ui_message
from src.website.workflows import legacy_match_admin, managed_prematch
from src.website.workflows.legacy_series import finish_legacy_series, reopen_legacy_series

logger = logging.getLogger("80gotv.admin.matches")

_SIDE_CONFLICT_MESSAGES = {
    "same_team": "flash.admin_matches.the_two_teams_must_be_different",
    "shared_player": "flash.admin_matches.the_same_player_cannot_play_on",
    "duplicate": "flash.admin_matches.a_match_with_the_same_event",
}


def _invalid_form(conn, message, match=None, values=None, sides=None, *, status=400):
    flash(message, "error")
    return show_match_form(conn, form_state(match, values, sides), status)


def _saved(conn, message):
    conn.close()
    flash(ui_message(message), "success")
    return redirect(url_for("admin.admin_matches"))


def _legacy_side_error(conn, values, sides, *, exclude_id=None):
    conflict = legacy_roster_edit.sides_conflict(conn, values, sides, exclude_id=exclude_id)
    return ui_message(_SIDE_CONFLICT_MESSAGES[conflict]) if conflict else None


@admin_bp.route("/matches")
@login_required
def admin_matches():
    conn = get_db()
    event_filter = request.args.get("event", "").strip()
    status_filter = request.args.get("status", "").strip()
    search_query = request.args.get("q", "").strip()
    matches, events, counts = match_list(conn, event_filter, status_filter, search_query)
    conn.close()
    return render_template(
        "admin/operations/matches.html",
        matches=matches,
        events=events,
        current_event=event_filter,
        current_status=status_filter or "all",
        search_query=search_query,
        counts=counts,
    )


@admin_bp.route("/matches/add", methods=["GET", "POST"])
@csrf_required
@login_required
def admin_matches_add():
    conn = get_db()
    if request.method != "POST":
        return show_match_form(conn)
    submission = parse_match_form(request.form)
    values = submission.values
    if error := setup.validation_error(conn, values):
        return _invalid_form(conn, error, values=values)
    if is_managed_event(conn, values["event_id"]):
        try:
            managed_prematch.create_match(conn, submission)
        except HostError as exc:
            return _invalid_form(conn, exc.message, values=values, status=exc.status)
        return _saved(conn, "flash.admin_matches.match_added_lock_the_match_roster")

    sides, error = legacy_roster_edit.sides_for_create(
        conn, submission.sides, is_test=bool(values["is_test_mode"])
    )
    if error := error or _legacy_side_error(conn, values, sides):
        return _invalid_form(conn, error, values=values, sides=sides)
    try:
        legacy_match_admin.create_match(conn, values, sides)
    except Exception as exc:
        logger.exception("创建比赛失败")
        return _invalid_form(
            conn,
            ui_message("flash.admin_matches.match_save_failed_exc", exc=exc),
            values=values,
            sides=sides,
        )
    return _saved(conn, "flash.admin_matches.match_added")


def _save_legacy_edit(conn, match, submission):
    match_id = match["id"]
    values = submission.values
    if is_managed_event(conn, values["event_id"]):
        return _invalid_form(
            conn,
            ui_message("flash.admin_matches.legacy_matches_cannot_be_moved_into"),
            match,
            status=409,
        )
    if setup.started_bp_setup_change(values, match, submission.provided):
        return _invalid_form(
            conn, ui_message("flash.admin_matches.map_veto_has_started_format_and"), match
        )
    setup.preserve_legacy_fields(values, match, submission.clear_bp_password)
    if error := setup.validation_error(conn, values):
        return _invalid_form(conn, error, match, values)
    # Whether test slots may be left empty comes from the saved match, not the form.
    values["is_test_mode"] = int(match["is_test_mode"] or 0)
    sides, error = legacy_roster_edit.sides_for_edit(conn, match, submission.sides)
    if error := error or _legacy_side_error(conn, values, sides, exclude_id=match_id):
        return _invalid_form(conn, error, match, values, sides)

    latest = match
    try:
        with write_transaction(conn):
            latest = legacy_match_admin.locked_edit_target(conn, match, submission)
            legacy_match_admin.edit_match(conn, match, latest, submission, sides)
    except ValueError as exc:
        if isinstance(exc, HostError) and exc.code == legacy_match_admin.BP_SETUP_CHANGED:
            return _invalid_form(conn, str(exc), latest)
        return _invalid_form(conn, str(exc), latest, values, sides)
    except Exception:
        logger.exception("更新比赛失败 match_id=%s", match_id)
        return _invalid_form(
            conn,
            ui_message("flash.admin_matches.the_match_could_not_be_saved"),
            latest,
            values,
            sides,
        )
    return _saved(conn, "flash.admin_matches.match_updated")


@admin_bp.route("/matches/edit/<int:match_id>", methods=["GET", "POST"])
@csrf_required
@login_required
def admin_matches_edit(match_id):
    conn = get_db()
    match = _get_match_form_row(conn, match_id)
    if not match:
        conn.close()
        return "比赛不存在", 404
    if request.method != "POST":
        return show_match_form(conn, match)
    submission = parse_match_form(request.form, include_results=True)
    if not is_managed_event(conn, match["event_id"]):
        return _save_legacy_edit(conn, match, submission)
    try:
        managed_prematch.edit_match(conn, match_id, submission, admin_id=session["admin_id"])
    except HostError as exc:
        return _invalid_form(conn, exc.message, match, status=exc.status)
    return _saved(conn, "flash.admin_matches.match_updated")


@admin_bp.route("/matches/delete/<int:match_id>", methods=["POST"])
@csrf_required
@login_required
def admin_matches_delete(match_id):
    conn = get_db()
    if is_managed_match(conn, match_id):
        conn.close()
        return PREMATCH_ONLY, 409
    try:
        if not legacy_match_admin.delete_match(conn, match_id):
            flash(ui_message("flash.admin_matches.match_not_found"), "error")
            return redirect(url_for("admin.admin_matches"))
        conn.commit()
        flash(ui_message("flash.admin_matches.match_deleted"), "success")
    except Exception as exc:
        conn.rollback()
        flash(ui_message("flash.admin_matches.deletion_failed_value1", value1=str(exc)), "error")
    finally:
        conn.close()
    return redirect(url_for("admin.admin_matches"))


@admin_bp.route("/matches/<int:match_id>/freeze-rosters", methods=["POST"])
@csrf_required
@login_required
def admin_match_freeze_rosters(match_id):
    conn = get_db()
    try:
        with write(conn):
            participants.freeze_rosters(conn, match_id, session["admin_id"])
    except HostError as exc:
        return exc.message, exc.status
    finally:
        conn.close()
    flash(ui_message("flash.admin_matches.match_rosters_locked"), "success")
    return redirect(url_for("admin.admin_matches_edit", match_id=match_id))


def _managed_series_form(conn, match_id, action):
    from src.website.workflows.admin_operations import dispatch_operation

    try:
        body: dict[str, object]
        if request.is_json:
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                raise HostError("请提交 JSON 对象", 400)
            body = payload
        else:
            body = {"reason": request.form.get("reason", "")}
            revision = request.form.get("expected_revision")
            if revision is not None:
                try:
                    body["expected_revision"] = int(revision)
                except ValueError:
                    raise HostError("裁定版本号无效", 400) from None
        if action == "reopen" and (not body.get("reason") or "expected_revision" not in body):
            raise HostError("请在比赛运营中核对结算版本，并填写重开原因")
        with write(conn):
            result = dispatch_operation(conn, match_id, action, body, session["admin_id"])
        if request.is_json:
            return {"ok": True, **result}
        flash("比赛已正式完赛" if action == "settle" else "已撤销本次结算", "success")
        return redirect(url_for("admin.admin_matches"))
    except HostError as exc:
        return ({"ok": False, "error": exc.message} if request.is_json else exc.message), exc.status
    finally:
        conn.close()


@admin_bp.route("/matches/<int:match_id>/complete", methods=["POST"])
@csrf_required
@login_required
def admin_match_complete(match_id):
    """Explicitly finish a match and optionally snapshot its Game Log."""
    conn = get_db()
    if is_managed_match(conn, match_id):
        return _managed_series_form(conn, match_id, "settle")
    try:
        saved = finish_legacy_series(
            conn, match_id, save_game_log=request.form.get("save_game_log") == "1"
        )
        conn.commit()
        flash(
            ui_message("flash.admin_matches.match_completed_saved_new_game_log", saved=saved),
            "success",
        )
    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "error")
    except Exception as exc:
        conn.rollback()
        logger.error("结束比赛失败 match_id=%s 错误类型=%s", match_id, type(exc).__name__)
        flash(ui_message("flash.admin_matches.the_match_could_not_be_completed"), "error")
    finally:
        conn.close()
    return redirect(url_for("admin.admin_matches"))


@admin_bp.route("/matches/<int:match_id>/reopen", methods=["POST"])
@csrf_required
@login_required
def admin_match_reopen(match_id):
    """Reopen a mistakenly completed match; time decides live/upcoming."""
    conn = get_db()
    if is_managed_match(conn, match_id):
        return _managed_series_form(conn, match_id, "reopen")
    try:
        changed = reopen_legacy_series(conn, match_id)
        conn.commit()
        flash("比赛已重新开启" if changed else "比赛未发生变化", "success")
    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "error")
    except Exception as exc:
        conn.rollback()
        logger.error("重新开启比赛失败 match_id=%s 错误类型=%s", match_id, type(exc).__name__)
        flash(ui_message("flash.admin_matches.the_match_could_not_be_reopened"), "error")
    finally:
        conn.close()
    return redirect(url_for("admin.admin_matches"))
