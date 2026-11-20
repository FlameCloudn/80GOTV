"""Individual signup, reserves, and formation HTTP actions."""

import time

from flask import request, session

from src.website.domains.events import formation, legacy_registration, legacy_team_formation
from src.website.domains.events import registration as signup
from src.website.runtime.host import HostError
from src.website.web.access import csrf_required
from src.website.web.routes import event_registration
from src.website.web.routes.event_registration import registration_message
from src.website.web.routing import site_routes


def _enroll_managed(conn, event_id, account, origin):
    raw = request.form.get("preferred_registration_id", "").strip()
    preferred = None
    if raw:
        if raw.isascii() and raw.isdecimal() and len(raw) <= 19:
            preferred = int(raw)
        if preferred is None or preferred > 2**63 - 1:
            raise HostError("候补意向队伍编号无效", 400, code="bad_preferred_registration_id")
    signup.enroll(
        conn, event_id, account, origin, preferred_registration_id=preferred, now=int(time.time())
    )


@site_routes.route("/events/<int:event_id>/register-individual", methods=["POST"])
@csrf_required
def event_register_individual(event_id):
    if not event_registration._individual_registration_is_open():
        return event_registration._registration_failure(
            event_id,
            registration_message(
                "error.individual_opens_on",
                date=event_registration._individual_registration_open_label(),
            ),
            403,
        )
    if "user_id" not in session:
        return event_registration._registration_failure(
            event_id, registration_message("error.sign_in_to_individual"), 401
        )

    account = session["user_id"]

    def write(conn, managed):
        if managed:
            _enroll_managed(conn, event_id, account, "individual")
        else:
            legacy_registration.enroll_individual(conn, event_id, account)
        return registration_message("success.individual")

    return event_registration._write_registration(event_id, write)


@site_routes.route("/events/<int:event_id>/register-substitute", methods=["POST"])
@csrf_required
def event_register_substitute(event_id):
    if "user_id" not in session:
        return event_registration._registration_failure(
            event_id, registration_message("error.sign_in_to_reserve"), 401
        )
    if not event_registration.rate_limit("event_register_substitute", 10, 3600, by_ip=True):
        return event_registration._registration_failure(
            event_id, registration_message("error.too_many_actions"), 429
        )

    account = session["user_id"]

    def write(conn, managed):
        if managed:
            _enroll_managed(conn, event_id, account, "independent_reserve")
            return registration_message("success.reserve_saved")
        user = legacy_registration.substitute_entrant(conn, event_id, account)
        preferred = (request.form.get("preferred_registration_id") or "").strip()
        try:
            preferred_id = int(preferred) if preferred else None
        except ValueError as exc:
            raise HostError("请选择有效的替补队伍", 400, code="preferred_team_invalid") from exc
        team_name, updated = legacy_registration.enroll_substitute(
            conn, event_id, user, preferred_id
        )
        if updated:
            return registration_message(
                "success.reserve_preference_updated"
                if team_name
                else "success.reserve_pool_updated",
                team=team_name,
            )
        if team_name:
            return registration_message("success.reserve_specific", team=team_name)
        return registration_message("success.reserve_pool")

    return event_registration._write_registration(event_id, write)


@site_routes.route("/events/<int:event_id>/individual-registration/withdraw", methods=["POST"])
@csrf_required
def event_withdraw_individual(event_id):
    if "user_id" not in session:
        return event_registration._registration_failure(
            event_id, registration_message("error.sign_in"), 401
        )

    account = session["user_id"]

    def write(conn, managed):
        if managed:
            signup.withdraw_individual(conn, event_id, account, now=int(time.time()))
            return registration_message("success.registration_withdrawn")
        was_substitute = legacy_registration.withdraw_individual(conn, event_id, account)
        return registration_message(
            "success.reserve_withdrawn" if was_substitute else "success.individual_withdrawn"
        )

    return event_registration._write_registration(event_id, write)


@site_routes.route(
    "/events/<int:event_id>/individual-registration/<int:entry_id>/remove",
    methods=["POST"],
)
@csrf_required
def event_remove_individual_registration(event_id, entry_id):
    if "admin_id" not in session:
        return event_registration._registration_failure(
            event_id, registration_message("error.admin_remove_signup"), 403
        )

    account, admin = session.get("user_id"), session.get("admin_id")

    def write(conn, managed):
        if managed:
            signup.withdraw_individual(
                conn, event_id, account, entry_id=entry_id, admin_id=admin, now=int(time.time())
            )
            return registration_message("success.registration_withdrawn")
        player_name, reset = legacy_registration.remove_individual(conn, event_id, entry_id)
        return registration_message(
            "success.removed_individual_with_reset" if reset else "success.removed_individual",
            player=player_name,
        )

    return event_registration._write_registration(event_id, write)


@site_routes.route("/events/<int:event_id>/individual-registration/randomize", methods=["POST"])
@csrf_required
def event_randomize_individual_teams(event_id):
    if "admin_id" not in session:
        return event_registration._registration_failure(
            event_id, registration_message("error.admin_draw"), 403
        )

    def write(conn, managed):
        if managed:
            signup.require_admin(conn, session.get("admin_id"))
            raise HostError("本届在截止时正式分队，不重复抽签", code="managed_draw_disabled")
        conn.rollback()  # Do not hold the writer lock during the Steam refresh.
        summary = legacy_team_formation.randomize_individual_teams(conn, event_id)
        message = registration_message("success.teams_drawn", teams=summary.new_teams)
        if not summary.steam_configured:
            message += registration_message("success.draw_steam_not_configured")
        elif not summary.known_playtimes:
            message += registration_message("success.draw_no_public_playtime")
        elif summary.unknown_playtimes:
            message += registration_message(
                "success.draw_unknown_playtime", players=summary.unknown_playtimes
            )
        if summary.reserves:
            message += registration_message("success.draw_reserves", players=summary.reserves)
        return message

    return event_registration._write_registration(event_id, write)


@site_routes.route(
    "/events/<int:event_id>/individual-registration/finalize",
    methods=["POST"],
)
@csrf_required
def event_finalize_individual_teams(event_id):
    if "admin_id" not in session:
        return event_registration._registration_failure(
            event_id, registration_message("error.admin_confirm_teams"), 403
        )

    admin = session["admin_id"]

    def write(conn, managed):
        if managed:
            signup.require_admin(conn, admin)
        conn.rollback()  # Both formation paths refresh Steam before their roster writes.
        if managed:
            formation.process_due_event(conn, event_id, admin_id=admin)
            return registration_message("success.teams_confirmed")
        summary = legacy_team_formation.confirm_individual_teams(conn, event_id)
        parts = []
        if summary.completed_teams:
            parts.append(
                registration_message("success.confirm_filled_teams", teams=summary.completed_teams)
            )
        if summary.new_teams:
            parts.append(
                registration_message("success.confirm_created_teams", teams=summary.new_teams)
            )
        if summary.reserves:
            parts.append(registration_message("success.confirm_reserves", players=summary.reserves))
        separator = registration_message("success.confirm_summary_separator")
        message = registration_message("success.confirm_summary", summary=separator.join(parts))
        if not summary.steam_configured:
            message += registration_message("success.confirm_steam_not_configured")
        elif not summary.known_playtimes:
            message += registration_message("success.confirm_no_public_playtime")
        elif summary.unknown_playtimes:
            message += registration_message(
                "success.confirm_unknown_playtime", players=summary.unknown_playtimes
            )
        return message

    return event_registration._write_registration(event_id, write)
