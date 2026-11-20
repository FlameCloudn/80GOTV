"""Review fixed teams, allowed substitutes and players in actual map attempts."""

from src.website.domains.events import roster_management as event_rosters
from src.website.domains.matches import participants
from src.website.domains.operations.inspection import attempt_player_ids


def _event_entrants(conn, event_id):
    entrants = {}
    for er in conn.execute(
        """SELECT ee.event_entrant_id, r.team_name, g.club_id, t.name AS club_name
           FROM event_entrants ee
           JOIN event_registration_groups g ON g.registration_id=ee.registration_id
           JOIN event_registrations r ON r.id=ee.registration_id
           LEFT JOIN teams t ON t.id=g.club_id
           WHERE ee.event_id=?
           ORDER BY ee.event_entrant_id""",
        (event_id,),
    ).fetchall():
        entrants[str(er["event_entrant_id"])] = {
            "id": er["event_entrant_id"],
            "name": er["team_name"] or f"参赛队 #{er['event_entrant_id']}",
            "club_id": er["club_id"],
            "club_name": er["club_name"] or "",
        }
    return entrants


def review_lineups(conn, match_id, event_id):
    entrants = _event_entrants(conn, event_id)
    fixed_sides = participants.sides(conn, match_id)
    rosters_frozen = participants.rosters_frozen(conn, match_id)
    participants_list = []
    player_ids = set()

    for side_num in (1, 2):
        side = fixed_sides.get(side_num)
        if not side:
            continue
        eid = side["event_entrant_id"]
        approved = event_rosters.roster(conn, event_id, eid)
        reserves = [
            dict(r)
            for r in conn.execute(
                """SELECT c.player_id, p.nickname, p.steam_id, e.registration_origin
                   FROM event_reserve_candidates c
                   JOIN event_signup_entries e USING(event_id, player_id)
                   JOIN players p ON p.id=c.player_id
                   WHERE c.event_id=? AND c.assigned_entrant_id=? AND c.withdrawn_at IS NULL
                     AND NOT EXISTS (
                       SELECT 1 FROM event_current_members cm
                       WHERE cm.event_id=c.event_id AND cm.player_id=c.player_id
                     )
                   ORDER BY c.player_id""",
                (event_id, eid),
            ).fetchall()
        ]
        for p in side["players"]:
            player_ids.add(p["id"])
        for r in reserves:
            player_ids.add(r["player_id"])
        player_ids.update(approved["initial_player_ids"])
        player_ids.update(approved["current_player_ids"])
        participants_list.append(
            {
                "side_num": side_num,
                "side_key": side["side_key"],
                "match_participant_id": side["match_participant_id"],
                "event_entrant_id": eid,
                "name": side["name"],
                "short_name": side["short_name"] or "",
                "club_name": (entrants.get(str(eid)) or {}).get("club_name", ""),
                "frozen": bool(side["frozen_at"]),
                "frozen_at": side["frozen_at"],
                "initial_player_ids": list(approved["initial_player_ids"]),
                "current_player_ids": list(approved["current_player_ids"]),
                "players": [
                    {
                        "id": p["id"],
                        "nickname": p["nickname"],
                        "steam_id": p["steam_id"] or "",
                        "slot": p["slot"],
                        "is_substitute": bool(p["is_substitute"]),
                    }
                    for p in side["players"]
                ],
                "assigned_reserves": reserves,
            }
        )

    player_ids.update(attempt_player_ids(conn, match_id))

    players = {}
    if player_ids:
        placeholders = ",".join("?" for _ in player_ids)
        for p in conn.execute(
            f"SELECT id, nickname, steam_id FROM players WHERE id IN ({placeholders})",
            tuple(player_ids),
        ).fetchall():
            players[str(p["id"])] = {
                "id": p["id"],
                "nickname": p["nickname"],
                "steam_id": p["steam_id"] or "",
            }
    return {
        "rosters_frozen": rosters_frozen,
        "entrants": entrants,
        "participants": participants_list,
        "players": players,
    }
