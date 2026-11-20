"""Build the authenticated operations panel from match facts and audit history."""

import json

from flask import url_for

from src.website.domains.demos.demo_storage import list_originals
from src.website.domains.matches.results import map_change_options
from src.website.domains.matches.series import get_series_result
from src.website.domains.operations.audit import read_result_history
from src.website.domains.operations.inspection import director_sessions, read_overview
from src.website.domains.operations.lineup_review import review_lineups
from src.website.domains.predictions.votes import managed_vote_open
from src.website.domains.statistics import statistics
from src.website.runtime.host import HostError
from src.website.web.read_models.operations_panel_bracket import bracket_context


def _load_match(conn, match_id):
    match_row = conn.execute(
        """SELECT m.id, m.event_id, m.bo_format, m.stage, m.status, m.match_time, m.slug,
                  m.bp_state, m.team1_score, m.team2_score,
                  e.name AS event_name, e.slug AS event_slug, e.status AS event_status,
                  c.archived_at AS event_archived_at,
                  a.authorized_at, a.admin_id AS authorized_by
           FROM matches m
           JOIN events e ON e.id=m.event_id
           JOIN event_registration_control c ON c.event_id=m.event_id
           LEFT JOIN match_start_authorizations a ON a.match_id=m.id
           WHERE m.id=?""",
        (match_id,),
    ).fetchone()
    if not match_row:
        raise HostError("比赛不存在或仍使用往届流程", 404)
    return match_row


def _match_header(match_row, admins, rosters_frozen):
    event_id = match_row["event_id"]
    bp_state = None
    if match_row["bp_state"]:
        try:
            bp_state = json.loads(match_row["bp_state"])
        except ValueError:
            bp_state = None
    return {
        "id": match_row["id"],
        "event_id": event_id,
        "event_name": match_row["event_name"],
        "event_status": match_row["event_status"],
        "event_archived": match_row["event_archived_at"] is not None,
        "bo_format": match_row["bo_format"] or "BO3",
        "stage": match_row["stage"] or "",
        "status": match_row["status"],
        "match_time": match_row["match_time"] or "",
        "slug": match_row["slug"] or "",
        "bp_status": (bp_state or {}).get("status") if isinstance(bp_state, dict) else None,
        "rosters_frozen": rosters_frozen,
        "authorized_at": match_row["authorized_at"],
        "authorized_by_name": admins.get(str(match_row["authorized_by"]), "")
        if match_row["authorized_by"]
        else "",
        "bp_url": f"/bp/{match_row['id']}",
        "public_url": f"/matches/{match_row['slug'] or match_row['id']}",
        "edit_url": url_for("admin.admin_matches_edit", match_id=match_row["id"]),
        "event_roster_url": url_for("admin.admin_event_roster", event_id=event_id),
        "event_bracket_url": url_for("admin.admin_event_bracket", event_id=event_id),
    }


def _vote_summary(conn, match_id):
    vote_rows = [
        dict(r)
        for r in conn.execute(
            """SELECT v.id, v.user_id, u.username, v.voted_for, v.score1_guess, v.score2_guess,
                      v.points_earned, v.scored, v.created_at
               FROM match_votes v
               LEFT JOIN users u ON u.id=v.user_id
               WHERE v.match_id=? ORDER BY v.id""",
            (match_id,),
        ).fetchall()
    ]
    t1_votes = sum(1 for v in vote_rows if v["voted_for"] == "t1")
    t2_votes = sum(1 for v in vote_rows if v["voted_for"] == "t2")
    settled_votes = sum(1 for v in vote_rows if v["scored"])
    return {
        "vote_open": bool(managed_vote_open(conn, match_id)),
        "total_votes": len(vote_rows),
        "t1_votes": t1_votes,
        "t2_votes": t2_votes,
        "settled_count": settled_votes,
        "votes": vote_rows,
    }


def _panel_context(conn, match_id):
    match_row = _load_match(conn, match_id)
    event_id = match_row["event_id"]
    admins = {
        str(row["id"]): row["username"]
        for row in conn.execute("SELECT id, username FROM admins").fetchall()
    }
    lineups = review_lineups(conn, match_id, event_id)
    sessions = director_sessions(conn, match_id)
    event_matches, downstream_links = bracket_context(conn, event_id, match_id, lineups["entrants"])
    return {
        "match": _match_header(match_row, admins, lineups["rosters_frozen"]),
        "participants": lineups["participants"],
        "players": lineups["players"],
        "admins": admins,
        "entrants": lineups["entrants"],
        "event_matches": event_matches,
        "downstream_links": downstream_links,
        "director_sessions": sessions,
        "predictions": _vote_summary(conn, match_id),
        "stat_field_names": list(statistics.FIELD_NAMES),
        "count_fields": sorted(statistics._COUNTS),
    }


def read_panel_bundle(conn, match_id):
    overview = read_overview(conn, match_id)
    result = overview["results"]
    context = _panel_context(conn, match_id)
    context["map_change_options"] = map_change_options(result)
    context["series_decided"] = bool(
        get_series_result(result["bo_format"], result["score1"], result["score2"])[0]
    )
    return {
        "context": context,
        "overview": overview,
        "history": read_result_history(conn, match_id),
        "originals": list_originals(conn, match_id),
    }
