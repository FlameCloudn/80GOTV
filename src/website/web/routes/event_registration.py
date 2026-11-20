"""Registration form policy, transaction selection, and team signup HTTP."""

import time
from contextlib import closing, contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import flash, jsonify, redirect, render_template, request, session, url_for

from src.website.domains.events import legacy_team_registration
from src.website.domains.events import registration as signup
from src.website.domains.events.registration_reads import registration_panel
from src.website.runtime.database import get_db
from src.website.runtime.host import HostError, is_managed_event
from src.website.runtime.rate_limiter import rate_limit
from src.website.runtime.storage import site_paths
from src.website.runtime.uploads import remove_uploaded_team_logo, save_uploaded_team_logo
from src.website.web.access import csrf_required
from src.website.web.localization import MESSAGES, current_language
from src.website.web.localization import t as ui_message
from src.website.web.presentation.filters import date_display_filter
from src.website.web.routing import site_routes

_INDIVIDUAL_REGISTRATION_OPENS_AT = datetime(2026, 7, 20, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def _individual_registration_is_open():
    return datetime.now(ZoneInfo("Asia/Shanghai")) >= _INDIVIDUAL_REGISTRATION_OPENS_AT


def _individual_registration_open_label():
    month = _INDIVIDUAL_REGISTRATION_OPENS_AT.month
    day = _INDIVIDUAL_REGISTRATION_OPENS_AT.day
    if _registration_language() == "en":
        return date_display_filter(_INDIVIDUAL_REGISTRATION_OPENS_AT)
    return f"{month} 月 {day} 日"


def _registration_wants_json():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _registration_language():
    # The site's own enhanced forms opt in; old AJAX integrations keep their exact text.
    if _registration_wants_json() and request.headers.get("X-80GOTV-UI") != "1":
        return "zh"
    return current_language()


def registration_message(key, **values):
    return MESSAGES[f"registration.{key}"][_registration_language()].format_map(values)


def _registration_error_message(error):
    language = _registration_language()
    text = MESSAGES.get(f"registration.error.{error.code}")
    if language != "zh" and text is not None:
        return text[language].format_map(error.params)
    return str(error)


def _registration_failure(event_id, message, status=400):
    if _registration_wants_json():
        return jsonify({"success": False, "error": message}), status
    flash(message, "error")
    return redirect(url_for("event_detail", event_id=event_id))


def _registration_success(event_id, message):
    if not _registration_wants_json():
        flash(message, "success")
        return redirect(url_for("event_detail", event_id=event_id))

    with closing(get_db()) as conn:
        panel = registration_panel(conn, event_id, session.get("user_id"))
    html = render_template(
        "public/events/_event_registration_list.html",
        individual_registration_open=_individual_registration_is_open(),
        **panel,
    )
    return jsonify({"success": True, "message": message, "html": html})


def _begin_registration_write(conn):
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")


@contextmanager
def _registration_write(event_id):
    with closing(get_db()) as conn:
        _begin_registration_write(conn)
        try:
            # Decide which tables own this event only after acquiring the write lock.
            yield conn, is_managed_event(conn, event_id)
            if conn.in_transaction:
                conn.commit()
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            raise


def _write_registration(event_id, action):
    try:
        with _registration_write(event_id) as (conn, managed):
            message = action(conn, managed)
    except HostError as exc:
        return _registration_failure(event_id, _registration_error_message(exc), exc.status)
    return _registration_success(event_id, message)


def _store_registration_logo(file):
    logo = save_uploaded_team_logo(file, site_paths().root)
    if not logo:
        raise HostError(
            "队标无效，请上传不超过 10MB 的 PNG、JPG 或 GIF 图片", 400, code="invalid_logo"
        )
    return logo


def _remove_registration_logo(logo):
    if logo:
        remove_uploaded_team_logo(site_paths().root, logo)


_LEGACY_CREATE_FLASH = {
    "signup_not_open": "registration_is_not_open_for_this",
    "steam_required": "link_your_steam_account_before_registering",
    "team_name_required": "enter_a_team_name",
    "select_slot": "choose_a_valid_slot",
    "already_on_team": "you_are_already_on_a_registered",
    "cancel_individual_before_joining": "you_are_registered_individually_cancel_that",
    "team_name_taken": "a_team_with_this_name_is",
    "invalid_signup_slot_steam": "invalid_steam_id_in_slot_value1",
    "invalid_logo": "invalid_logo_upload_a_png_jpg",
}


@site_routes.route("/events/<int:event_id>/register", methods=["POST"])
@csrf_required
def event_register(event_id):
    if "user_id" not in session:
        flash(ui_message("flash.event_registration.log_in_before_registering"), "error")
        return redirect(url_for("user_login", next=url_for("event_detail", event_id=event_id)))
    event_url = url_for("event_detail", event_id=event_id)
    if not rate_limit("event_register", 10, 3600, by_ip=True):
        flash(
            ui_message("flash.event_registration.too_many_registration_actions_please_try"), "error"
        )
        return redirect(event_url)

    account = session["user_id"]
    name = request.form.get("team_name", "").strip()
    own_slot = request.form.get("my_slot", -1, type=int)
    slots = [
        (request.form.get(f"pname_{i}", "").strip(), request.form.get(f"psteam_{i}", "").strip())
        for i in range(5)
    ]
    file = request.files.get("team_logo")
    new_logo = None
    managed = False
    try:
        with _registration_write(event_id) as (conn, managed):
            if managed:
                now = int(time.time())
                reg_id = signup.create_group(
                    conn,
                    event_id,
                    account,
                    name,
                    roster_slot=own_slot,
                    reservations={
                        i: seat for i, seat in enumerate(slots) if i != own_slot and any(seat)
                    },
                    now=now,
                )
                if file:
                    new_logo = _store_registration_logo(file)
                    group = signup.authorize_group_edit(conn, event_id, reg_id, account, now=now)
                    signup.replace_group_logo(conn, group, new_logo)
            else:
                occupants = legacy_team_registration.signup_slots(
                    conn, event_id, account, name, own_slot, slots
                )
                if file:
                    new_logo = _store_registration_logo(file)
                legacy_team_registration.register_team(
                    conn, event_id, name, account, occupants, logo=new_logo
                )
    except HostError as exc:
        _remove_registration_logo(new_logo)
        legacy_key = _LEGACY_CREATE_FLASH.get(exc.code) if not managed and exc.code else None
        message = (
            ui_message(f"flash.event_registration.{legacy_key}", **exc.params)
            if legacy_key
            else _registration_error_message(exc)
        )
        flash(message, "error")
        if not managed and exc.code == "steam_required":
            return redirect(url_for("user_profile"))
        return redirect(event_url)
    except Exception:
        _remove_registration_logo(new_logo)
        raise

    message = (
        registration_message("success.team_created")
        if managed
        else ui_message("flash.event_registration.team_team_name_created_you_are", team_name=name)
    )
    flash(message, "success")
    return redirect(event_url)
