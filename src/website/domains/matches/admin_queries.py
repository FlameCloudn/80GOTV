"""Read roster choices, managed matches, and schedule constraints."""

import json

from src.website.domains.matches.match_roster_service import (
    managed_match_teams,
    match_player_slots,
    registration_player_slots,
)
from src.website.domains.matches.match_utils import get_sql_effective_status
from src.website.domains.matches.opponents import supplement_temp_teams
from src.website.runtime.database import row_get
from src.website.runtime.host import has_event_schema, is_managed_event


def _get_form_dropdowns(conn):
    return (
        conn.execute("SELECT * FROM events ORDER BY start_date DESC").fetchall(),
        conn.execute("SELECT * FROM teams ORDER BY name").fetchall(),
        conn.execute(
            "SELECT p.*, t.name AS team_name FROM players p LEFT JOIN teams t ON p.team_id=t.id ORDER BY p.nickname"
        ).fetchall(),
    )


def _get_match_form_row(conn, match_id):
    match = conn.execute(
        """SELECT m.*, t1.name AS team1_name, t2.name AS team2_name FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id LEFT JOIN teams t2 ON m.team2_id=t2.id
        WHERE m.id=?""",
        (match_id,),
    ).fetchone()
    if match and is_managed_event(conn, match["event_id"]):
        from src.website.domains.matches.maps import project_legacy_map_fields

        return project_legacy_map_fields(conn, match)
    return match


def _match_player_ids(match, key):
    if not match or not match[key]:
        return []
    try:
        return json.loads(match[key])
    except (TypeError, json.JSONDecodeError):
        return []


def _event_reserve_player_ids(conn, event_id):
    """Return database player ids for registered substitutes in an event."""
    if not event_id:
        return []
    rows = conn.execute(
        """
        SELECT DISTINCT p.id
        FROM event_individual_registrations ir
        JOIN players p ON p.steam_id=ir.steam_id
        WHERE ir.event_id=? AND ir.assignment_status='reserve'
        ORDER BY p.nickname COLLATE NOCASE
        """,
        (event_id,),
    ).fetchall()
    return [row["id"] for row in rows]


def _match_roster_options(conn, match, side):
    """Build the small player list an admin can use for a match substitution."""
    current_ids = [
        player["id"] for player in match_player_slots(conn, match, side) if player.get("id")
    ]
    registered_ids = [
        player["id"] for player in registration_player_slots(conn, match, side) if player.get("id")
    ]
    managed = managed_match_teams(conn, match)
    reserve_ids = (
        [
            player["id"]
            for player in managed.get(str(side), {}).get("players", [])
            if player["is_substitute"]
        ]
        if managed is not None
        else _event_reserve_player_ids(conn, row_get(match, "event_id"))
    )
    candidate_ids = list(dict.fromkeys(current_ids + registered_ids + reserve_ids))
    if not candidate_ids:
        return []
    placeholders = ",".join("?" for _ in candidate_ids)
    rows = conn.execute(
        f"""
        SELECT p.id, p.nickname, p.team_id, p.steam_id, t.name AS team_name
        FROM players p
        LEFT JOIN teams t ON t.id=p.team_id
        WHERE p.id IN ({placeholders})
        ORDER BY p.nickname COLLATE NOCASE
        """,
        candidate_ids,
    ).fetchall()
    reserve_set = set(reserve_ids)
    by_id = {row["id"]: row for row in rows}
    ordered = [by_id[player_id] for player_id in candidate_ids if player_id in by_id]
    return [
        {
            "id": row["id"],
            "nickname": row["nickname"] or "",
            "team_name": row["team_name"] or "",
            "has_steam_id": bool(str(row["steam_id"] or "").strip()),
            "is_substitute": row["id"] in reserve_set,
        }
        for row in ordered
    ]


def _match_roster_selected(conn, match, side):
    """Keep the exact slots supplied by the administrator or registration."""
    slots = {player["slot"]: player.get("id") for player in match_player_slots(conn, match, side)}
    if not slots:
        return []
    return [slots.get(slot) for slot in range(1, max(slots) + 1)]


def annotate_managed_matches(conn, matches):
    """Attach read-only is_managed / rosters_frozen flags to match dicts."""
    if not matches:
        return matches
    if not has_event_schema(conn):
        for m in matches:
            m["is_managed"] = False
            m["rosters_frozen"] = False
        return matches
    managed_events = {
        r[0] for r in conn.execute("SELECT event_id FROM event_registration_control").fetchall()
    }
    managed_ids = [m["id"] for m in matches if m.get("event_id") in managed_events]
    frozen_counts = {}
    if managed_ids:
        placeholders = ",".join("?" for _ in managed_ids)
        for row in conn.execute(
            f"""SELECT p.match_id, COUNT(*) AS cnt
                FROM match_participants p
                JOIN match_roster_members r ON r.match_participant_id=p.match_participant_id
                WHERE p.match_id IN ({placeholders})
                GROUP BY p.match_id""",
            managed_ids,
        ):
            frozen_counts[row["match_id"]] = row["cnt"]
    for m in matches:
        managed = m.get("event_id") in managed_events
        m["is_managed"] = managed
        m["rosters_frozen"] = bool(managed and frozen_counts.get(m["id"], 0) == 10)
    return matches


def _duplicate_match(
    conn,
    values,
    team1_id,
    team2_id,
    team1_players,
    team2_players,
    exclude_id=None,
):
    sql = (
        "SELECT id, team1_id, team2_id, team1_players, team2_players, is_test_mode "
        "FROM matches WHERE event_id=? AND match_time=?"
    )
    params = [values["event_id"], values["match_time"]]
    if exclude_id is not None:
        sql += " AND id<>?"
        params.append(exclude_id)
    for row in conn.execute(sql, params).fetchall():
        if values["is_test_mode"] and row["is_test_mode"]:
            return True
        if team1_id and team2_id:
            if {str(row["team1_id"]), str(row["team2_id"])} == {
                str(team1_id),
                str(team2_id),
            }:
                return True
        elif team1_players and team2_players:
            current_sides = {
                frozenset(
                    str(value)
                    for value in _match_player_ids(row, "team1_players")
                    if value is not None
                ),
                frozenset(
                    str(value)
                    for value in _match_player_ids(row, "team2_players")
                    if value is not None
                ),
            }
            submitted_sides = {
                frozenset(value for value in json.loads(team1_players) if value is not None),
                frozenset(value for value in json.loads(team2_players) if value is not None),
            }
            if current_sides == submitted_sides:
                return True
    return False


def match_list(conn, event_filter, status_filter, search_query):
    events = conn.execute(
        "SELECT id, name, short_name FROM events ORDER BY start_date DESC, id DESC"
    ).fetchall()
    sql_effective_status = get_sql_effective_status()
    query = f"""SELECT m.*, t1.name AS team1_name, t2.name AS team2_name, e.name AS event_name,
        {sql_effective_status} FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id"""
    params = [event_filter] if event_filter else []
    if event_filter:
        query += " WHERE m.event_id=?"
    query += " ORDER BY m.match_time DESC, m.id DESC"
    rows = conn.execute(query, params).fetchall()
    matches = annotate_managed_matches(conn, [supplement_temp_teams(row, conn) for row in rows])

    if search_query:
        lowered = search_query.lower()
        matches = [
            m
            for m in matches
            if lowered in (m.get("team1_name") or "").lower()
            or lowered in (m.get("team2_name") or "").lower()
            or lowered in (m.get("event_name") or "").lower()
            or str(m.get("id")) == search_query
        ]
    counts = {"all": len(matches), "live": 0, "upcoming": 0, "completed": 0, "cancelled": 0}
    for match in matches:
        status = match.get("effective_status")
        if status in counts:
            counts[status] += 1
    if status_filter and status_filter != "all":
        matches = [m for m in matches if m.get("effective_status") == status_filter]
    return matches, events, counts
