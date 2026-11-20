"""比赛页和导播共用的展示名单；预先读取双方与候补后一次投影。"""

from src.website.domains.matches.match_roster_service import match_player_slots
from src.website.runtime.host import is_managed_event


def asset_path(folder, value):
    value = str(value or "").strip()
    if not value:
        return ""
    if value.startswith(("http://", "https://", "/")):
        return value
    return f"/static/{folder}/{value}"


def event_substitutes(conn, event_id):
    if not event_id:
        return []
    if is_managed_event(conn, event_id):
        rows = conn.execute(
            """SELECT player_id AS id,player_name AS nickname,group_username,steam_id,avatar,
                      is_bashizhong_student,preferred_registration_id,preferred_team_name
               FROM host_individual_entries_read WHERE event_id=? AND assignment_status='reserve'
               ORDER BY created_at,id""",
            (event_id,),
        ).fetchall()
    else:
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
            "avatar": asset_path("avatars", row["avatar"]),
            "is_bashizhong_student": row["is_bashizhong_student"],
            "role": "substitute",
            "preferred_registration_id": row["preferred_registration_id"],
            "preferred_team_name": row["preferred_team_name"] or "",
        }
        for row in rows
    ]


def display_rosters(players_by_side, substitutes):
    reserve_ids = {
        int(player["id"])
        for player in substitutes
        if str(player.get("id", "")).lstrip("-").isdigit() and int(player["id"]) > 0
    }
    return {
        side: [
            {
                # Keep the registration order stable. The desktop app and HUD use
                # this slot number to keep a player's name and avatar together.
                "id": row["id"],
                "slot": row["slot"],
                "nickname": row.get("nickname") or "",
                "group_username": row.get("group_username_override") or "",
                "steam_id": row.get("steam_id") or "",
                "avatar": asset_path("avatars", row.get("avatar")),
                "is_bashizhong_student": row.get("is_bashizhong_student"),
                **(
                    {"role": "substitute"}
                    if (
                        bool(row.get("is_substitute"))
                        if row.get("roster_frozen")
                        else row["id"] in reserve_ids
                    )
                    else {}
                ),
            }
            for row in ordered_rows
        ]
        for side, ordered_rows in players_by_side.items()
    }


def team_players(conn, match, side, slots=None):
    """兼容只取一侧的旧调用，正式比赛页和导播一次生成双方名单。"""
    slots = match_player_slots(conn, match, side) if slots is None else slots
    return display_rosters({side: slots}, event_substitutes(conn, match.get("event_id")))[side]
