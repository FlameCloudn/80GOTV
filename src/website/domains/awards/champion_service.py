"""Persist championship membership from match evidence, not current teams."""

import json
from collections import defaultdict

from src.website.domains.awards.championship import has_championship_schema
from src.website.domains.matches.match_roster_service import resolve_match_roster


def _historical_members(conn, event_id, team_id):
    members = set()
    matches = conn.execute(
        """SELECT * FROM matches WHERE event_id=? AND status='completed'
           AND (team1_id=? OR team2_id=?)""",
        (event_id, team_id, team_id),
    ).fetchall()
    for match in matches:
        sides = {1 if match["team1_id"] == team_id else 2}
        if match["team1_id"] == match["team2_id"]:
            continue
        evidence = defaultdict(set)
        # Registration can change after a match, so it is not historical evidence.
        try:
            snapshot = json.loads(match["roster_snapshot"] or "null")
            teams = (
                snapshot.get("teams")
                if isinstance(snapshot, dict) and snapshot.get("version") == 1
                else None
            )
            frozen = isinstance(teams, dict) and all(
                isinstance(teams.get(str(side)), dict)
                and isinstance(teams[str(side)].get("players"), list)
                for side in (1, 2)
            )
        except (TypeError, ValueError):
            frozen = False
        if frozen and isinstance(teams, dict):
            if any(
                "team_id" in teams[str(side)]
                and teams[str(side)]["team_id"] != match[f"team{side}_id"]
                for side in (1, 2)
            ):
                continue
            for side in (1, 2):
                for slot in teams[str(side)]["players"]:
                    player_id = slot.get("id") if isinstance(slot, dict) else None
                    player_id_text = str(player_id)
                    if (
                        not isinstance(player_id, bool)
                        and player_id_text.isdigit()
                        and int(player_id_text) > 0
                        and (
                            snapshot.get("evidence") == "confirmed_match"
                            or slot.get("roster_source") in {"admin", "history"}
                        )
                    ):
                        evidence[int(player_id_text)].add(side)
        else:
            roster = resolve_match_roster(conn, match)
            for side in (1, 2):
                for slot in roster["players"][side]:
                    if slot.get("id") and slot.get("roster_source") == "admin":
                        evidence[slot["id"]].add(side)
        for stat in conn.execute(
            """SELECT player_id, LOWER(TRIM(match_team_side)) AS side FROM match_stats
               WHERE match_id=? AND player_id IS NOT NULL
                 AND COALESCE(data_status,'final')='final'
                 AND LOWER(TRIM(match_team_side)) IN ('t1','t2')""",
            (match["id"],),
        ):
            evidence[stat["player_id"]].add(1 if stat["side"] == "t1" else 2)
        members.update(
            player_id
            for player_id, player_sides in evidence.items()
            if player_sides == sides
            and conn.execute("SELECT 1 FROM players WHERE id=?", (player_id,)).fetchone()
        )
    return members


def _freeze_champion(conn, champion):
    if champion["players_snapshot_at"] is not None:
        return
    for player_id in _historical_members(conn, champion["event_id"], champion["team_id"]):
        conn.execute(
            "INSERT OR IGNORE INTO event_champion_players(champion_id,player_id) VALUES(?,?)",
            (champion["id"], player_id),
        )
    conn.execute(
        "UPDATE event_champions SET players_snapshot_at=CURRENT_TIMESTAMP WHERE id=?",
        (champion["id"],),
    )


def backfill_champion_members(conn):
    """Freeze old awards once, even when no reliable membership evidence exists."""
    for champion in conn.execute(
        "SELECT * FROM event_champions WHERE players_snapshot_at IS NULL"
    ).fetchall():
        _freeze_champion(conn, champion)


def save_champion(conn, event_id, team_id):
    champions = conn.execute(
        "SELECT * FROM event_champions WHERE event_id=?", (event_id,)
    ).fetchall()
    retained = next((champion for champion in champions if champion["team_id"] == team_id), None)
    for champion in champions:
        if not retained or champion["id"] != retained["id"]:
            conn.execute("DELETE FROM event_champions WHERE id=?", (champion["id"],))
    if team_id is None:
        return
    if retained is None:
        champion_id = conn.execute(
            "INSERT INTO event_champions(event_id,team_id) VALUES(?,?)", (event_id, team_id)
        ).lastrowid
        retained = conn.execute(
            "SELECT * FROM event_champions WHERE id=?", (champion_id,)
        ).fetchone()
    _freeze_champion(conn, retained)


def championship_teams_relation(conn):
    legacy = """SELECT ec.id, ec.event_id, ec.team_id, t.name AS team_name, t.short_name AS team_short,
                       t.logo, t.description, 0 AS players
                FROM event_champions ec JOIN teams t ON t.id=ec.team_id"""
    if not has_championship_schema(conn):
        return f"({legacy})"
    return f"""({legacy} UNION ALL
        SELECT c.event_id, c.event_id, c.club_id, c.team_name, c.team_short_name,
               c.team_logo, t.description, 5
        FROM managed_event_champions c LEFT JOIN teams t ON t.id=c.club_id)"""


def list_championship_teams(conn, event_id: int | None = None):
    return conn.execute(
        f"""SELECT c.*, e.name AS event_name, e.slug AS event_slug, e.start_date AS event_date
           FROM {championship_teams_relation(conn)} c JOIN events e ON e.id=c.event_id
           WHERE (? IS NULL OR c.event_id=?) ORDER BY e.start_date DESC""",
        (event_id, event_id),
    ).fetchall()


def player_championships(conn, player_id):
    query = """SELECT ec.id, ec.event_id, ec.team_id, ec.players_snapshot_at, ec.created_at,
                  e.name AS event_name, e.id AS event_id, e.slug AS event_slug, e.start_date AS event_date
           FROM event_champions ec JOIN events e ON ec.event_id=e.id
           JOIN event_champion_players ecp ON ecp.champion_id=ec.id
           WHERE ecp.player_id=?"""
    params = (player_id,)
    if has_championship_schema(conn):
        query += """ UNION ALL
            SELECT c.event_id, c.event_id, c.club_id, c.created_at, c.created_at,
                   e.name, e.id, e.slug, e.start_date
            FROM managed_event_champions c JOIN events e ON e.id=c.event_id
            JOIN managed_event_champion_players cp ON cp.event_id=c.event_id
            WHERE cp.player_id=?"""
        params += (player_id,)
    return conn.execute(f"{query} ORDER BY event_date DESC", params).fetchall()
