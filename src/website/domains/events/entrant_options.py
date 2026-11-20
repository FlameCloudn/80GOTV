"""List event entrants and the facts needed to select one while scheduling."""

from src.website.runtime.host import has_event_schema


def match_entrant_options(conn):
    if not has_event_schema(conn):
        return []
    events = conn.execute(
        """SELECT c.event_id, c.archived_at, b.formed_at
           FROM event_registration_control c
           LEFT JOIN event_formation_batches b USING(event_id)"""
    ).fetchall()
    if not events:
        return []
    entrants = conn.execute(
        """SELECT e.event_id, e.event_entrant_id, e.registration_id,
                  g.club_id, g.group_origin, g.archived_at AS team_archived_at,
                  r.team_name, r.status AS reg_status,
                  t.name AS club_name,
                  i.confirmed_at
           FROM event_entrants e
           JOIN event_registration_groups g ON g.event_id=e.event_id AND g.registration_id=e.registration_id
           JOIN event_registrations r ON r.id=e.registration_id AND r.event_id=e.event_id
           LEFT JOIN teams t ON t.id=g.club_id
           LEFT JOIN event_initial_rosters i ON i.event_entrant_id=e.event_entrant_id
           ORDER BY e.event_id, e.event_entrant_id"""
    ).fetchall()
    initial_by_entrant = {}
    for row in conn.execute("SELECT event_entrant_id, player_id FROM event_initial_members"):
        initial_by_entrant.setdefault(row["event_entrant_id"], set()).add(row["player_id"])
    current_by_entrant = {}
    for row in conn.execute(
        """SELECT cm.event_entrant_id, cm.player_id, p.nickname
           FROM event_current_members cm
           JOIN players p ON p.id=cm.player_id
           ORDER BY cm.event_entrant_id, cm.roster_slot"""
    ):
        current_by_entrant.setdefault(row["event_entrant_id"], []).append(
            {"id": row["player_id"], "nickname": row["nickname"] or f"#{row['player_id']}"}
        )

    entrants_by_event = {}
    for entrant in entrants:
        entrant_id = entrant["event_entrant_id"]
        confirmed = entrant["confirmed_at"] is not None
        initial = initial_by_entrant.get(entrant_id, set())
        players = [
            {**player, "is_added_sub": bool(confirmed and player["id"] not in initial)}
            for player in current_by_entrant.get(entrant_id, [])
        ]
        if entrant["team_archived_at"] is not None:
            blocker = "archived"
        elif entrant["reg_status"] != "pending":
            blocker = "registration_invalid"
        elif not confirmed:
            blocker = "initial_pending"
        elif len(players) != 5:
            blocker = "not_five_players"
        else:
            blocker = None
        entrants_by_event.setdefault(entrant["event_id"], []).append(
            {
                "event_entrant_id": entrant_id,
                "name": entrant["team_name"],
                "club_name": entrant["club_name"] or "",
                "origin": entrant["group_origin"],
                "blocker": blocker,
                "players": players,
            }
        )
    return [
        {
            "event_id": event["event_id"],
            "archived": event["archived_at"] is not None,
            "formed": event["formed_at"] is not None,
            "entrants": entrants_by_event.get(event["event_id"], []),
        }
        for event in events
    ]
