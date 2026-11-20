"""Build the administrator's match setup page from read-only match and event data."""

from datetime import datetime, timedelta, timezone

from flask import render_template, request, url_for

from src.website.domains.events.entrant_options import match_entrant_options
from src.website.domains.matches import prematch_queries, setup
from src.website.domains.matches.admin_queries import (
    _get_form_dropdowns,
    _match_player_ids,
    _match_roster_options,
    _match_roster_selected,
)
from src.website.domains.matches.match_roster_service import managed_match_teams
from src.website.domains.matches.opponents import supplement_temp_teams
from src.website.runtime.host import is_managed_event
from src.website.web.localization import t as ui_message

_UTC8 = timezone(timedelta(hours=8))


def _utc_text_to_iso(raw):
    if not raw:
        return ""
    text = str(raw).strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_UTC8).isoformat()
    except ValueError:
        return text


def _epoch_to_iso(ts):
    if ts is None:
        return ""
    return datetime.fromtimestamp(int(ts), _UTC8).isoformat()


def _entrant_label(blocker, players):
    if blocker == "archived":
        return ui_message("roster.phase.archived")
    if blocker == "registration_invalid":
        return ui_message("roster.setup.registration_invalid")
    if blocker == "initial_pending":
        return ui_message("roster.setup.initial_pending")
    if blocker == "not_five_players":
        return ui_message("roster.setup.not_five_players", count=len(players))
    return ""


def _managed_events_for_match_add(conn):
    result = {}
    for event in match_entrant_options(conn):
        event_id = event["event_id"]
        entrants = []
        for choice in event["entrants"]:
            entrant_id = choice["event_entrant_id"]
            entrants.append(
                {
                    "event_entrant_id": entrant_id,
                    "name": choice["name"]
                    or ui_message("roster.entrant_fallback", entrant_id=entrant_id),
                    "club_name": choice["club_name"],
                    "origin_label": ui_message(
                        "roster.origin.formed"
                        if choice["origin"] == "formed"
                        else "roster.origin.registered"
                    ),
                    "ready": choice["blocker"] is None,
                    "not_ready_reason": _entrant_label(choice["blocker"], choice["players"]),
                    "players": choice["players"],
                }
            )
        result[str(event_id)] = {
            **event,
            "roster_url": url_for("admin.admin_event_roster", event_id=event_id),
            "entrants": entrants,
        }
    return result


def _managed_match_edit_info(conn, match):
    review = prematch_queries.review_rosters(conn, match)
    for side in review["sides"].values():
        if side:
            side["initial_confirmed_at_iso"] = _epoch_to_iso(side.pop("initial_confirmed_at"))
            side["frozen_at_iso"] = _utc_text_to_iso(side.pop("frozen_at"))
    review["roster_url"] = url_for("admin.admin_event_roster", event_id=match["event_id"])
    review["bp_url"] = f"/bp/{match['id']}"
    return review


def show_match_form(conn, match=None, status=200):
    events, teams, all_players = _get_form_dropdowns(conn)
    team1_player_ids = _match_player_ids(match, "team1_players")
    team2_player_ids = _match_player_ids(match, "team2_players")
    # Both database rows and the submitted-form dict support keys().
    is_new_match = not match or ("_is_new_form" in match.keys() and bool(match["_is_new_form"]))
    match_roster_options = {}
    match_roster_selected = {}
    if not is_new_match:
        match_roster_options = {side: _match_roster_options(conn, match, side) for side in (1, 2)}
        match_roster_selected = {side: _match_roster_selected(conn, match, side) for side in (1, 2)}
    managed_events_data = _managed_events_for_match_add(conn) if is_new_match else {}
    selected_sides = {}
    if is_new_match and request.method == "POST":
        selected_sides = {
            "1": {
                "type": request.form.get("side1_type", ""),
                "id": request.form.get("side1_id", ""),
            },
            "2": {
                "type": request.form.get("side2_type", ""),
                "id": request.form.get("side2_id", ""),
            },
        }
    managed_match_info = None
    if not is_new_match and match and is_managed_event(conn, match["event_id"]):
        managed_match_info = _managed_match_edit_info(conn, dict(match))
    if match and "_setup_editable" in match.keys():
        match_setup_editable = bool(match["_setup_editable"])
    elif match:
        match_setup_editable = setup.setup_editable(match)
    else:
        match_setup_editable = False
    custom_side_labels = {}
    if match:
        match = dict(match)
        managed = managed_match_teams(conn, match)
        team_names = {team["id"]: team["name"] for team in teams}
        for side in (1, 2):
            team_id = match.get(f"team{side}_id")
            match[f"team{side}_id"] = int(team_id) if team_id is not None else None
            match[f"team{side}_name"] = team_names.get(match[f"team{side}_id"])
        match = supplement_temp_teams(match, conn)
        for side in (1, 2):
            selected = match_roster_selected.get(side, [])
            if managed is not None:
                match[f"team{side}_id"] = managed.get(str(side), {}).get("team_id")
            if (managed is not None or not match_setup_editable) and not is_new_match:
                if side == 1:
                    team1_player_ids = selected
                else:
                    team2_player_ids = selected
            if (
                match[f"team{side}_name"] == "TBD"
                and not team_names.get(match[f"team{side}_id"])
                and any(selected)
            ):
                custom_side_labels[side] = "自选阵容 A" if side == 1 else "自选阵容 B"
    conn.close()
    return render_template(
        "admin/operations/matches_form.html",
        match=match,
        is_new_match=is_new_match,
        events=events,
        teams=teams,
        all_players=all_players,
        team1_player_ids=team1_player_ids,
        team2_player_ids=team2_player_ids,
        match_roster_options=match_roster_options,
        match_roster_selected=match_roster_selected,
        match_setup_editable=match_setup_editable,
        custom_side_labels=custom_side_labels,
        managed_events_data=managed_events_data,
        selected_sides=selected_sides,
        managed_match_info=managed_match_info,
    ), status
