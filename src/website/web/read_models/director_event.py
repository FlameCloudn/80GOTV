"""Project public registered teams for event preload in the desktop director."""

import re

from src.website.domains.directory.team_logo_service import team_logo_static_path
from src.website.domains.events.reads import registration_groups
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
                "avatar": asset_path("avatars", row["avatar"]),
                "is_bashizhong_student": row["is_bashizhong_student"],
                "role": role,
                "slot": row["slot_index"] + 1,
            }
        )
    return players


def _managed_registration_players(slots, creator_user_id):
    return [
        {
            "id": slot["player_id"] or slot["id"],
            "nickname": slot["player_name"],
            "group_username": slot["group_username"] or "",
            "steam_id": slot["steam_id"],
            "avatar": asset_path("avatars", slot["avatar"]),
            "is_bashizhong_student": slot["is_bashizhong_student"],
            "role": (
                "reserved"
                if slot["filled_by_creator"]
                else "captain"
                if slot["user_id"] == creator_user_id
                else "member"
            ),
            "slot": slot["slot_index"] + 1,
        }
        for slot in slots
    ]


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
    groups = registration_groups(conn, event_id) if hosted else []
    registrations = [] if hosted else _legacy_registrations(conn, event_id)
    substitutes = event_substitutes(conn, event_id)
    if hosted:
        teams = [
            _registration_team(
                group["info"],
                _managed_registration_players(group["slots"], group["info"]["creator_user_id"]),
            )
            for group in reversed(groups)
        ]
    else:
        teams = [
            _registration_team(
                registration,
                _registration_players(conn, registration["id"], registration["creator_user_id"]),
            )
            for registration in registrations
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
