"""Team signup, slots, and captain HTTP actions."""

import time

from flask import current_app, request, session

from src.website.domains.events import legacy_team_registration as legacy
from src.website.domains.events import registration as signup
from src.website.runtime.host import HostError
from src.website.web.access import csrf_required
from src.website.web.routes.event_registration import (
    _registration_error_message,
    _registration_failure,
    _registration_success,
    _registration_write,
    _remove_registration_logo,
    _store_registration_logo,
    _write_registration,
    registration_message,
)
from src.website.web.routing import site_routes


@site_routes.route("/events/<int:event_id>/join/<int:reg_id>/<int:slot>", methods=["POST"])
@csrf_required
def event_join_slot(event_id, reg_id, slot):
    if "user_id" not in session:
        return _registration_failure(event_id, registration_message("error.sign_in_to_join"), 401)
    if slot not in range(5):
        return _registration_failure(event_id, registration_message("error.slot_not_found"), 404)
    account = session["user_id"]

    def write(conn, managed):
        if managed:
            signup.join_group(conn, event_id, reg_id, account, slot, now=int(time.time()))
        else:
            legacy.join_team(conn, event_id, reg_id, slot, account)
        return registration_message("success.joined")

    return _write_registration(event_id, write)


@site_routes.route("/events/<int:event_id>/leave/<int:reg_id>/<int:slot>", methods=["POST"])
@csrf_required
def event_leave_slot(event_id, reg_id, slot):
    if "user_id" not in session:
        return _registration_failure(event_id, registration_message("error.sign_in_to_leave"), 401)
    if slot not in range(5):
        return _registration_failure(event_id, registration_message("error.slot_not_found"), 404)
    account = session["user_id"]

    def write(conn, managed):
        if managed:
            signup.leave_slot(conn, event_id, reg_id, slot, account, now=int(time.time()))
            return registration_message("success.left_own_slot")
        team, position = legacy.leave_team(conn, event_id, reg_id, slot, account)
        return registration_message("success.left_named_slot", team=team, position=position)

    return _write_registration(event_id, write)


@site_routes.route("/events/<int:event_id>/registrations/<int:reg_id>/rename", methods=["POST"])
@csrf_required
def event_registration_rename(event_id, reg_id):
    account, admin = session.get("user_id"), session.get("admin_id")
    name = request.form.get("team_name", "").strip()

    def write(conn, managed):
        if managed:
            signup.rename_group(
                conn, event_id, reg_id, account, name, admin_id=admin, now=int(time.time())
            )
            return registration_message("success.renamed")
        legacy.rename_team(conn, event_id, reg_id, account, admin, name)
        return registration_message("success.renamed_to", team=name)

    return _write_registration(event_id, write)


@site_routes.route("/events/<int:event_id>/registrations/<int:reg_id>/logo", methods=["POST"])
@csrf_required
def event_registration_upload_logo(event_id, reg_id):
    return _change_logo(event_id, reg_id, upload=True)


@site_routes.route(
    "/events/<int:event_id>/registrations/<int:reg_id>/logo/remove", methods=["POST"]
)
@csrf_required
def event_registration_remove_logo(event_id, reg_id):
    return _change_logo(event_id, reg_id, upload=False)


def _change_logo(event_id, reg_id, *, upload):
    account, admin = session.get("user_id"), session.get("admin_id")
    file = request.files.get("team_logo") if upload else None
    new_logo = None
    saving_legacy_logo = False
    try:
        with _registration_write(event_id) as (conn, managed):
            if managed:
                team = signup.authorize_group_edit(
                    conn, event_id, reg_id, account, admin_id=admin, now=int(time.time())
                )
            else:
                operation = "upload_logo" if upload else "remove_logo"
                team = legacy.authorize_team_edit(conn, event_id, reg_id, account, admin, operation)
            if upload:
                new_logo = _store_registration_logo(file)
                saving_legacy_logo = not managed
            replace = signup.replace_group_logo if managed else legacy.replace_team_logo
            old_logo = replace(conn, team, new_logo)
    except HostError as exc:
        _remove_registration_logo(new_logo)
        return _registration_failure(event_id, _registration_error_message(exc), exc.status)
    except Exception:
        _remove_registration_logo(new_logo)
        if saving_legacy_logo:
            return _registration_failure(
                event_id, registration_message("error.logo_save_failed"), 500
            )
        raise

    _remove_registration_logo(old_logo)
    message = registration_message("success.logo_updated" if upload else "success.logo_removed")
    return _registration_success(event_id, message)


@site_routes.route("/events/<int:event_id>/registrations/<int:reg_id>/dissolve", methods=["POST"])
@csrf_required
def event_registration_dissolve(event_id, reg_id):
    account, admin = session.get("user_id"), session.get("admin_id")
    dissolving_legacy_team = False
    try:
        with _registration_write(event_id) as (conn, managed):
            if managed:
                logo = signup.dissolve_group(
                    conn, event_id, reg_id, account, admin_id=admin, now=int(time.time())
                )
                message = registration_message("success.disbanded")
            else:
                team = legacy.authorize_team_edit(
                    conn, event_id, reg_id, account, admin, "dissolve"
                )
                dissolving_legacy_team = True
                team_name, logo = legacy.dissolve_team(conn, team)
                message = registration_message("success.named_team_disbanded", team=team_name)
    except HostError as exc:
        return _registration_failure(event_id, _registration_error_message(exc), exc.status)
    except Exception:
        if not dissolving_legacy_team:
            raise
        current_app.logger.exception(
            "解散报名队伍失败 event_id=%s registration_id=%s", event_id, reg_id
        )
        return _registration_failure(event_id, registration_message("error.dissolve_failed"), 500)

    _remove_registration_logo(logo)
    return _registration_success(event_id, message)


@site_routes.route(
    "/events/<int:event_id>/registrations/<int:reg_id>/slots/<int:slot>/remove", methods=["POST"]
)
@csrf_required
def event_registration_remove_member(event_id, reg_id, slot):
    if slot not in range(5):
        return _registration_failure(event_id, registration_message("error.slot_not_found"), 404)
    account, admin = session.get("user_id"), session.get("admin_id")

    def write(conn, managed):
        if managed:
            signup.remove_group_member(
                conn, event_id, reg_id, account, slot, admin_id=admin, now=int(time.time())
            )
            return registration_message("success.slot_cleared")
        player = legacy.remove_member(conn, event_id, reg_id, slot, account, admin)
        return registration_message("success.member_removed", player=player)

    return _write_registration(event_id, write)


@site_routes.route(
    "/events/<int:event_id>/registrations/<int:reg_id>/slots/<int:slot>/update", methods=["POST"]
)
@csrf_required
def event_registration_update_member(event_id, reg_id, slot):
    if slot not in range(5):
        return _registration_failure(event_id, registration_message("error.slot_not_found"), 404)
    account, admin = session.get("user_id"), session.get("admin_id")
    name = request.form.get("player_name", "").strip()
    steam = request.form.get("steam_id", "").strip()

    def write(conn, managed):
        if managed:
            signup.set_reservation(
                conn,
                event_id,
                reg_id,
                account,
                slot,
                name,
                steam,
                admin_id=admin,
                now=int(time.time()),
            )
            return registration_message("success.slot_updated")
        legacy.update_member(conn, event_id, reg_id, slot, account, admin, name, steam)
        return registration_message("success.numbered_slot_updated", position=slot + 1)

    return _write_registration(event_id, write)


@site_routes.route(
    "/events/<int:event_id>/registrations/<int:reg_id>/slots/<int:slot>/captain", methods=["POST"]
)
@csrf_required
def event_registration_transfer_captain(event_id, reg_id, slot):
    admin = session.get("admin_id")
    if not admin:
        return _registration_failure(
            event_id, registration_message("error.admin_transfer_captain"), 403
        )
    if slot not in range(5):
        return _registration_failure(event_id, registration_message("error.slot_not_found"), 404)

    def write(conn, managed):
        if managed:
            signup.transfer_group_captain(
                conn, event_id, reg_id, slot, admin_id=admin, now=int(time.time())
            )
            return registration_message("success.captain_transferred")
        player = legacy.transfer_captain(conn, event_id, reg_id, slot, admin)
        return registration_message("success.named_captain_appointed", player=player)

    return _write_registration(event_id, write)
