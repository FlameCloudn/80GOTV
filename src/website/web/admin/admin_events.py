"""Administrative event settings, listing, updates and deletion."""

import time

from flask import flash, redirect, render_template, request, session, url_for

from src.website.domains.awards.player_awards_service import delete_event_awards
from src.website.domains.events import registration as signup
from src.website.domains.events.status import add_effective_event_status
from src.website.domains.matches.match_references import update_match_slug
from src.website.runtime.database import get_db
from src.website.runtime.host import HostError, has_event_schema, is_managed_event
from src.website.web.access import admin_required as login_required
from src.website.web.access import csrf_required
from src.website.web.admin.admin import admin_bp
from src.website.web.admin.event_awards import _event_award_options, _submit_event_awards
from src.website.web.admin.event_forms import (
    _event_dict,
    _event_form_values,
    _event_validation_error,
    _form_number,
)
from src.website.web.admin.event_registration import _registration_action
from src.website.web.localization import t as ui_message
from src.website.web.read_models.event_admin import (
    _admin_events_control_map,
    _event_registration_control,
)


@admin_bp.route("/events")
@login_required
def admin_events():
    conn = get_db()
    events = conn.execute("SELECT * FROM events ORDER BY start_date DESC").fetchall()
    control_map = _admin_events_control_map(conn)
    events = [
        {**add_effective_event_status(e), "registration_control": control_map.get(e["id"])}
        for e in events
    ]
    conn.close()
    return render_template("admin/events/events.html", events=events)


@admin_bp.route("/events/add", methods=["GET", "POST"])
@csrf_required
@login_required
def admin_events_add():
    if request.method == "POST":
        conn = get_db()
        schema_ready = has_event_schema(conn)
        values = _event_form_values()
        error = _event_validation_error(conn, values)
        if error:
            conn.close()
            flash(error, "error")
            return render_template(
                "admin/events/events_form.html",
                event=_event_dict(values),
                registration_control={
                    "schema_ready": schema_ready,
                    "enabled": False,
                    "can_enable": True,
                    "blockers": [],
                },
            ), 400
        deadline = request.form.get("registration_deadline")
        cursor = conn.execute(
            """INSERT INTO events(name, short_name, slug, description, start_date, end_date, format, status, stream_url, registration_open)
                        VALUES(?,?,?,?,?,?,?,?,?,?)""",
            values if deadline is None else (*values[:-1], 0),
        )
        if deadline is not None:
            try:
                signup.enable_event(
                    conn,
                    cursor.lastrowid,
                    _form_number(deadline),
                    admin_id=session.get("admin_id"),
                    now=int(time.time()),
                )
            except HostError as exc:
                conn.rollback()
                conn.close()
                flash(str(exc), "error")
                return render_template(
                    "admin/events/events_form.html",
                    event=_event_dict(values),
                    registration_control={
                        "schema_ready": schema_ready,
                        "enabled": False,
                        "can_enable": True,
                        "blockers": [],
                    },
                ), exc.status
        conn.commit()
        conn.close()
        flash(ui_message("flash.admin_events.event_added"), "success")
        return redirect(url_for("admin.admin_events"))
    conn = get_db()
    schema_ready = has_event_schema(conn)
    conn.close()
    return render_template(
        "admin/events/events_form.html",
        event=None,
        registration_control={
            "schema_ready": schema_ready,
            "enabled": False,
            "can_enable": True,
            "blockers": [],
        },
    )


@admin_bp.route("/events/edit/<int:event_id>", methods=["GET", "POST"])
@csrf_required
@login_required
def admin_events_edit(event_id):
    if request.method == "POST" and request.form.get("registration_action"):
        return _registration_action(event_id, request.form["registration_action"])
    conn = get_db()
    if request.method == "POST":
        conn.execute("BEGIN IMMEDIATE")
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not event:
        conn.close()
        return "赛事不存在", 404
    reg_control = _event_registration_control(conn, event)
    if request.method == "POST":
        values = _event_form_values(event)
        managed = is_managed_event(conn, event_id)
        award_fields = ("champion_team_id", "mvp_player_id", "evp_player_ids")
        submit_awards = any(field in request.form for field in award_fields)
        if managed:
            submit_awards = any(any(request.form.getlist(field)) for field in award_fields)
            if values[7] == "ongoing" or (
                event["status"] == "completed" and values[7] != "completed"
            ):
                conn.close()
                return "本届只办理赛前管理和归档，不能开赛或重新开放已归档赛事", 409
            values = (*values[:-1], event["registration_open"] if values[7] != "completed" else 0)
        error = _event_validation_error(conn, values, event_id)
        if not error and submit_awards:
            try:
                _submit_event_awards(conn, event_id)
            except HostError as exc:
                if exc.status != 400:
                    conn.close()
                    return exc.message, exc.status
                error = exc.message
        if error:
            teams, players, champion_team, mvp_player, evp_players = _event_award_options(
                conn, event_id
            )
            conn.close()
            flash(error, "error")
            return render_template(
                "admin/events/events_form.html",
                event=_event_dict(values, event_id),
                teams=teams,
                champion_team=champion_team,
                mvp_player=mvp_player,
                evp_players=evp_players,
                all_players=players,
                registration_control=reg_control,
            ), 400
        if event["slug"] and event["slug"] != values[2]:
            conn.execute(
                "INSERT OR IGNORE INTO event_slug_aliases(slug,event_id) VALUES(?,?)",
                (event["slug"], event_id),
            )
        conn.execute(
            """UPDATE events SET name=?, short_name=?, slug=?, description=?, start_date=?, end_date=?, format=?, status=?, stream_url=?, registration_open=?
                        WHERE id=?""",
            values + (event_id,),
        )
        if event["short_name"] != values[1]:
            for match in conn.execute(
                "SELECT id FROM matches WHERE event_id=? ORDER BY id", (event_id,)
            ).fetchall():
                update_match_slug(conn, match["id"])
        if managed and values[7] == "completed":
            signup.archive_event(
                conn, event_id, admin_id=session.get("admin_id"), now=int(time.time())
            )
        conn.commit()
        conn.close()
        flash(ui_message("flash.admin_events.event_updated"), "success")
        return redirect(url_for("admin.admin_events"))
    teams, players, champion_team, mvp_player, evp_players = _event_award_options(conn, event_id)
    conn.close()
    return render_template(
        "admin/events/events_form.html",
        event=event,
        teams=teams,
        champion_team=champion_team,
        mvp_player=mvp_player,
        evp_players=evp_players,
        all_players=players,
        registration_control=reg_control,
    )


@admin_bp.route("/events/delete/<int:event_id>", methods=["POST"])
@csrf_required
@login_required
def admin_events_delete(event_id):
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if is_managed_event(conn, event_id):
            flash(ui_message("flash.admin_events.event_registrations_and_rosters_must_be"), "error")
            return redirect(url_for("admin.admin_events"))
        event = conn.execute("SELECT id FROM events WHERE id=?", (event_id,)).fetchone()
        if not event:
            flash(ui_message("flash.admin_events.event_not_found"), "error")
            return redirect(url_for("admin.admin_events"))
        references = conn.execute(
            """SELECT
                 (SELECT COUNT(*) FROM matches WHERE event_id=?) +
                 (SELECT COUNT(*) FROM event_registrations WHERE event_id=?) +
                 (SELECT COUNT(*) FROM event_individual_registrations WHERE event_id=?)""",
            (event_id, event_id, event_id),
        ).fetchone()[0]
        if references:
            flash(ui_message("flash.admin_events.this_event_still_has_matches_or"), "error")
            return redirect(url_for("admin.admin_events"))
        delete_event_awards(conn, event_id)
        conn.execute("DELETE FROM event_slug_aliases WHERE event_id=?", (event_id,))
        conn.execute("DELETE FROM events WHERE id=?", (event_id,))
        conn.commit()
        flash(ui_message("flash.admin_events.event_deleted"), "success")
    except Exception as e:
        conn.rollback()
        flash(ui_message("flash.admin_events.deletion_failed_value1", value1=str(e)), "error")
    finally:
        conn.close()
    return redirect(url_for("admin.admin_events"))
