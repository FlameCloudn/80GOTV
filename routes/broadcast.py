"""Public match metadata for the local broadcast HUD and desktop manager."""

import json
import re
from datetime import datetime

from flask import jsonify

from models import get_db
from services.match_service import supplement_temp_teams
from utils.match_utils import (
    get_bo_max_maps,
    get_sql_effective_status,
    get_sql_match_live,
    get_sql_match_upcoming,
)
from web_app import app

_SQL_MATCH_LIVE = get_sql_match_live()
_SQL_MATCH_UPCOMING = get_sql_match_upcoming()
_SQL_EFFECTIVE_STATUS = get_sql_effective_status()


def _broadcast_response(payload, status=200):
    response = jsonify(payload)
    response.status_code = status
    # The HUD runs locally in LHM/OBS. These endpoints contain public match data only.
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, HEAD, OPTIONS"
    return response


def _match_query(where_sql):
    return f"""
        SELECT m.*, t1.name AS team1_name, t1.short_name AS t1s,
               t1.logo AS team1_logo,
               t2.name AS team2_name, t2.short_name AS t2s,
               t2.logo AS team2_logo,
               e.name AS event_name, e.short_name AS event_short_name,
               {_SQL_EFFECTIVE_STATUS}
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id
        WHERE {where_sql}
    """


def _asset_path(folder, value):
    value = str(value or "").strip()
    if not value:
        return ""
    if value.startswith(("http://", "https://", "/")):
        return value
    return f"/static/{folder}/{value}"


def _player_ids(raw_value):
    try:
        values = json.loads(raw_value) if raw_value else []
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [int(value) for value in values if str(value).isdigit()]


def _team_players(conn, match, side):
    ids = _player_ids(match.get(f"team{side}_players"))
    if ids:
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"""SELECT id, nickname, group_username_override, steam_id, avatar,
                       is_bashizhong_student
                FROM players WHERE id IN ({placeholders}) ORDER BY nickname COLLATE NOCASE""",
            ids,
        ).fetchall()
    else:
        team_id = match.get(f"team{side}_id")
        if not team_id or team_id < 1:
            return []
        rows = conn.execute(
            """SELECT id, nickname, group_username_override, steam_id, avatar,
                      is_bashizhong_student
               FROM players WHERE team_id=? ORDER BY nickname COLLATE NOCASE""",
            (team_id,),
        ).fetchall()

    return [
        {
            "id": row["id"],
            "nickname": row["nickname"] or "",
            "group_username": row["group_username_override"] or "",
            "steam_id": row["steam_id"] or "",
            "avatar": _asset_path("avatars", row["avatar"]),
            "is_bashizhong_student": row["is_bashizhong_student"],
        }
        for row in rows
    ]


def _event_substitutes(conn, event_id):
    if not event_id:
        return []
    rows = conn.execute(
        """
        SELECT COALESCE(p.id, -ir.id) AS id,
               COALESCE(NULLIF(ir.player_name, ''), NULLIF(p.nickname, ''),
                        NULLIF(u.username, '')) AS nickname,
               COALESCE(NULLIF(p.group_username_override, ''),
                        NULLIF(u.group_username, ''), '') AS group_username,
               COALESCE(NULLIF(p.steam_id, ''), NULLIF(u.steam_id64, ''), ir.steam_id) AS steam_id,
               COALESCE(NULLIF(p.avatar, ''), NULLIF(u.avatar, ''), '') AS avatar,
               COALESCE(p.is_bashizhong_student, u.is_bashizhong_student) AS is_bashizhong_student,
               ir.preferred_registration_id,
               preferred.team_name AS preferred_team_name
        FROM event_individual_registrations ir
        LEFT JOIN users u ON u.id=ir.user_id
        LEFT JOIN event_registrations preferred
          ON preferred.id=ir.preferred_registration_id
         AND preferred.event_id=ir.event_id
         AND preferred.status='pending'
        LEFT JOIN players p ON p.id=(
            SELECT p2.id FROM players p2
            WHERE p2.steam_id=ir.steam_id
            ORDER BY p2.id LIMIT 1
        )
        WHERE ir.event_id=? AND ir.assignment_status='reserve'
        ORDER BY ir.created_at, ir.id
        """,
        (event_id,),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "nickname": row["nickname"] or "",
            "group_username": row["group_username"] or "",
            "steam_id": row["steam_id"] or "",
            "avatar": _asset_path("avatars", row["avatar"]),
            "is_bashizhong_student": row["is_bashizhong_student"],
            "role": "substitute",
            "preferred_registration_id": row["preferred_registration_id"],
            "preferred_team_name": row["preferred_team_name"] or "",
        }
        for row in rows
    ]


def _registration_short_name(name):
    words = re.findall(r"[A-Za-z0-9]+", str(name or ""))
    if len(words) >= 2 and words[0].lower() == "team":
        return ("T" + words[1][0]).upper()
    if len(words) >= 2:
        return "".join(word[0] for word in words[:3]).upper()
    compact = re.sub(r"[^A-Za-z0-9]", "", str(name or ""))
    return (compact[:3] or "TM").upper()


def _registration_logo_path(value):
    value = str(value or "").strip().replace("\\", "/")
    if not value or value.startswith(("http://", "https://", "/")):
        return value
    if "/" in value:
        return _asset_path("uploads", value)
    return _asset_path("uploads/team_logos", value)


def _registration_players(conn, registration_id, creator_user_id):
    rows = conn.execute(
        """
        SELECT s.id AS slot_id, s.slot_index, s.user_id, s.player_name,
               s.steam_id AS slot_steam_id, s.filled_by_creator,
               COALESCE(p.id, -1000000-s.id) AS id,
               COALESCE(NULLIF(s.player_name, ''), NULLIF(p.nickname, ''),
                        NULLIF(u.username, '')) AS nickname,
               COALESCE(NULLIF(p.group_username_override, ''),
                        NULLIF(u.group_username, ''), '') AS group_username,
               COALESCE(NULLIF(p.steam_id, ''), NULLIF(s.steam_id, ''),
                        NULLIF(u.steam_id64, ''), '') AS steam_id,
               COALESCE(NULLIF(p.avatar, ''), NULLIF(u.avatar, ''), '') AS avatar,
               COALESCE(p.is_bashizhong_student, u.is_bashizhong_student) AS is_bashizhong_student
        FROM event_registration_slots s
        LEFT JOIN users u ON u.id=s.user_id
        LEFT JOIN players p ON p.id=(
            SELECT p2.id FROM players p2
            WHERE p2.steam_id=COALESCE(NULLIF(s.steam_id, ''), NULLIF(u.steam_id64, ''))
            ORDER BY p2.id LIMIT 1
        )
        WHERE s.registration_id=?
        ORDER BY s.slot_index, s.id
        """,
        (registration_id,),
    ).fetchall()
    players = []
    for row in rows:
        role = "captain" if row["user_id"] == creator_user_id else "member"
        if row["filled_by_creator"] and not row["user_id"]:
            role = "reserved"
        players.append(
            {
                "id": row["id"],
                "nickname": row["nickname"] or "",
                "group_username": row["group_username"] or "",
                "steam_id": row["steam_id"] or "",
                "avatar": _asset_path("avatars", row["avatar"]),
                "is_bashizhong_student": row["is_bashizhong_student"],
                "role": role,
                "slot": row["slot_index"] + 1,
            }
        )
    return players


def _event_roster_payload(conn, event):
    registrations = conn.execute(
        """
        SELECT id, team_name, team_logo, creator_user_id
        FROM event_registrations
        WHERE event_id=? AND status='pending'
        ORDER BY created_at, id
        """,
        (event["id"],),
    ).fetchall()
    substitutes = _event_substitutes(conn, event["id"])
    teams = []
    for registration in registrations:
        teams.append(
            {
                "id": None,
                "source_id": f"registration-{registration['id']}",
                "registration_id": registration["id"],
                "name": registration["team_name"] or "TEAM",
                "short_name": _registration_short_name(registration["team_name"]),
                "logo": _registration_logo_path(registration["team_logo"]),
                "series_score": 0,
                "players": _registration_players(
                    conn, registration["id"], registration["creator_user_id"]
                ),
            }
        )
    return {
        "source_type": "event",
        "id": event["id"],
        "name": event["name"] or "80GOTV",
        "short_name": event["short_name"] or "",
        "status": event["status"] or "upcoming",
        "start_date": event["start_date"] or "",
        "end_date": event["end_date"] or "",
        "teams": teams,
        "team_count": len(teams),
        "substitutes": substitutes,
        "substitute_count": len(substitutes),
    }


def _bp_payload(raw_state):
    try:
        state = json.loads(raw_state) if raw_state else None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return state if isinstance(state, dict) else None


def _match_payload(row, conn):
    match = supplement_temp_teams(row, conn)
    substitutes = _event_substitutes(conn, match.get("event_id"))
    map_count = get_bo_max_maps(match.get("bo_format"))
    maps = []
    for slot in range(1, map_count + 1):
        if slot >= 3 and not match.get(f"has_map{slot}", 1):
            continue
        maps.append(
            {
                "slot": slot,
                "name": match.get(f"map{slot}") or "",
                "team1_score": match.get(f"map{slot}_t1") or 0,
                "team2_score": match.get(f"map{slot}_t2") or 0,
                "picked_by": match.get(f"map{slot}_picked_by") or "",
            }
        )

    return {
        "id": match["id"],
        "status": match.get("effective_status") or match.get("status") or "upcoming",
        "event": {
            "id": match.get("event_id"),
            "name": match.get("event_name") or "80GOTV",
            "short_name": match.get("event_short_name") or "",
        },
        "stage": match.get("stage") or "",
        "bo": match.get("bo_format") or "BO3",
        "match_time": match.get("match_time") or "",
        "team1": {
            "id": match.get("team1_id"),
            "name": match.get("team1_name") or "TBD",
            "short_name": match.get("t1s") or "TBD",
            "logo": _asset_path("uploads", match.get("team1_logo")),
            "series_score": match.get("team1_score") or 0,
            "players": _team_players(conn, match, 1),
        },
        "team2": {
            "id": match.get("team2_id"),
            "name": match.get("team2_name") or "TBD",
            "short_name": match.get("t2s") or "TBD",
            "logo": _asset_path("uploads", match.get("team2_logo")),
            "series_score": match.get("team2_score") or 0,
            "players": _team_players(conn, match, 2),
        },
        "substitutes": substitutes,
        "substitute_count": len(substitutes),
        "maps": maps,
        "bp": _bp_payload(match.get("bp_state")),
        "decider": {
            "knife_winner": match.get("decider_knife_winner") or "",
            "start_side": match.get("decider_start_side") or "",
        },
        "live_api": f"/api/live/{match['id']}",
        "live_ingest_api": f"/api/broadcast/matches/{match['id']}/live",
    }


@app.route("/api/broadcast/matches")
def api_broadcast_matches():
    """Return matches available to the local desktop manager."""
    conn = get_db()
    rows = conn.execute(
        _match_query("1=1")
        + f"""
        ORDER BY CASE WHEN {_SQL_MATCH_LIVE} THEN 0
                      WHEN {_SQL_MATCH_UPCOMING} THEN 1 ELSE 2 END,
                 datetime(m.match_time) DESC, m.id DESC
        LIMIT 100
        """
    ).fetchall()
    matches = [_match_payload(row, conn) for row in rows]
    conn.close()
    return _broadcast_response(
        {
            "ok": True,
            "matches": matches,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }
    )


@app.route("/api/broadcast/events")
def api_broadcast_events():
    """Return events that already have registered teams or public substitutes."""
    conn = get_db()
    rows = conn.execute(
        """
        SELECT e.*
        FROM events e
        WHERE EXISTS(
            SELECT 1 FROM event_registrations r
            WHERE r.event_id=e.id AND r.status='pending'
        ) OR EXISTS(
            SELECT 1 FROM event_individual_registrations ir
            WHERE ir.event_id=e.id AND ir.assignment_status='reserve'
        )
        ORDER BY date(e.start_date) DESC, e.id DESC
        LIMIT 100
        """
    ).fetchall()
    events = [_event_roster_payload(conn, row) for row in rows]
    conn.close()
    return _broadcast_response(
        {
            "ok": True,
            "events": events,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }
    )


@app.route("/api/broadcast/events/<int:event_id>")
def api_broadcast_event(event_id):
    """Return all registered teams, players and public substitutes for an event."""
    conn = get_db()
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not event:
        conn.close()
        return _broadcast_response({"ok": False, "event": None, "error": "赛事不存在"}, 404)
    payload = _event_roster_payload(conn, event)
    conn.close()
    return _broadcast_response(
        {
            "ok": True,
            "event": payload,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }
    )


@app.route("/api/broadcast/current")
def api_broadcast_current():
    """Return the live match, or the next upcoming match when the stream is idle."""
    conn = get_db()
    row = conn.execute(
        _match_query(f"({_SQL_MATCH_LIVE} OR {_SQL_MATCH_UPCOMING})")
        + f"""
        ORDER BY CASE WHEN {_SQL_MATCH_LIVE} THEN 0 ELSE 1 END,
                 datetime(m.match_time) ASC, m.id ASC
        LIMIT 1
        """
    ).fetchone()
    if not row:
        conn.close()
        return _broadcast_response(
            {
                "ok": False,
                "match": None,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
    payload = _match_payload(row, conn)
    conn.close()
    return _broadcast_response(
        {
            "ok": True,
            "match": payload,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }
    )


@app.route("/api/broadcast/matches/<int:match_id>")
def api_broadcast_match(match_id):
    """Return one match selected in the HUD settings."""
    conn = get_db()
    row = conn.execute(_match_query("m.id=?"), (match_id,)).fetchone()
    if not row:
        conn.close()
        return _broadcast_response({"ok": False, "error": "比赛不存在"}, 404)
    payload = _match_payload(row, conn)
    conn.close()
    return _broadcast_response(
        {
            "ok": True,
            "match": payload,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
