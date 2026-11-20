"""Project public registered teams for event preload in the desktop director."""

import re

from src.website.domains.directory.team_logo_service import team_logo_static_path
from src.website.domains.operations.broadcast_rosters import asset_path, event_substitutes


def _registration_short_name(name):
    words = re.findall(r"[A-Za-z0-9]+", str(name or ""))
    if len(words) >= 2 and words[0].lower() == "team":
        return ("T" + words[1][0]).upper()
    if len(words) >= 2:
        return "".join(word[0] for word in words[:3]).upper()
    compact = re.sub(r"[^A-Za-z0-9]", "", str(name or ""))
    return (compact[:3] or "TM").upper()


def _registration_players(conn, registration_id, creator_user_id):
    rows = conn.execute(
        """
        SELECT s.slot_index, s.user_id, s.filled_by_creator,
               COALESCE(p.id, -1000000-s.id) AS id,
               COALESCE(NULLIF(s.player_name, ''), NULLIF(p.nickname, ''),
                        NULLIF(u.username, '')) AS nickname,
               COALESCE(NULLIF(p.steam_id, ''), NULLIF(s.steam_id, ''),
                        NULLIF(u.steam_id64, ''), '') AS steam_id,
               COALESCE(NULLIF(p.avatar, ''), NULLIF(u.avatar, ''), '') AS avatar
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
                "steam_id": row["steam_id"] or "",
                "avatar": asset_path("avatars", row["avatar"]),
                "role": role,
                "slot": row["slot_index"] + 1,
            }
        )
    return players


def _registration_team(registration, players):
    registration_id = registration["id"]
    return {
        "id": None,
        "source_id": f"registration-{registration_id}",
        "registration_id": registration_id,
        "name": registration["team_name"] or "TEAM",
        "short_name": _registration_short_name(registration["team_name"]),
        "logo": team_logo_static_path(registration["team_logo"]),
        "series_score": 0,
        "players": players,
    }


def _managed_registration_teams(conn, event_id):
    teams = {}
    # The view supplies all five slots, including seats not yet filled by a player.
    for row in conn.execute(
        """SELECT r.id,r.team_name,r.team_logo,r.creator_user_id,
                  s.slot_index,s.player_id,s.player_name,s.steam_id,s.avatar,
                  s.user_id,s.filled_by_creator
           FROM host_registration_slots_read s
           JOIN event_registrations r ON r.id=s.registration_id
           WHERE s.event_id=? ORDER BY r.created_at,r.id,s.slot_index""",
        (event_id,),
    ):
        registration_id, slot = row["id"], row["slot_index"]
        if registration_id not in teams:
            teams[registration_id] = _registration_team(row, [])
        role = "captain" if row["user_id"] == row["creator_user_id"] else "member"
        if row["filled_by_creator"]:
            role = "reserved"
        teams[registration_id]["players"].append(
            {
                # Keep the desktop client's existing placeholder ID for empty/reserved seats.
                "id": row["player_id"] or -(1000000 + registration_id * 5 + slot),
                "nickname": row["player_name"],
                "steam_id": row["steam_id"],
                "avatar": asset_path("avatars", row["avatar"]),
                "role": role,
                "slot": slot + 1,
            }
        )
    return list(teams.values())


def _legacy_registrations(conn, event_id):
    return conn.execute(
        """
        SELECT id, team_name, team_logo, creator_user_id
        FROM event_registrations
        WHERE event_id=? AND status='pending'
        ORDER BY created_at, id
        """,
        (event_id,),
    ).fetchall()


def read_event_payload(conn, event, *, hosted):
    event_id = event["id"]
    substitutes = event_substitutes(conn, event_id)
    if hosted:
        teams = _managed_registration_teams(conn, event_id)
    else:
        teams = [
            _registration_team(
                registration,
                _registration_players(conn, registration["id"], registration["creator_user_id"]),
            )
            for registration in _legacy_registrations(conn, event_id)
        ]
    return {
        "source_type": "event",
        "id": event_id,
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
