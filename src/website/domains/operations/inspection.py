"""Read actual map attempts, their evidence, and receiver health for administrators."""

import json

from src.website.domains.matches.match_utils import get_sql_effective_status
from src.website.domains.matches.results import read_results
from src.website.domains.operations import run_control


def _attempt(conn, run):
    run_id = run["map_run_id"]
    replay = conn.execute(
        "SELECT * FROM technical_replays WHERE map_run_id=?", (run_id,)
    ).fetchone()
    return {
        **dict(run),
        "replay": dict(replay) if replay else None,
        "lineup": [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM map_run_lineups WHERE map_run_id=? ORDER BY match_participant_id,roster_slot",
                (run_id,),
            )
        ],
        "participations": [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM run_participations WHERE map_run_id=? ORDER BY participation_id",
                (run_id,),
            )
        ],
        "rounds": [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM map_run_rounds WHERE map_run_id=? ORDER BY round_number",
                (run_id,),
            )
        ],
    }


def read_overview(conn, match_id):
    maps = []
    for row in conn.execute(
        "SELECT * FROM scheduled_maps WHERE match_id=? AND is_enabled=1 ORDER BY map_order",
        (match_id,),
    ):
        map_id = row["scheduled_map_id"]
        item = dict(row)
        item["effective_roster"] = run_control.effective_roster(conn, match_id, map_id)
        item["runs"] = [
            _attempt(conn, run)
            for run in conn.execute(
                "SELECT * FROM map_runs WHERE scheduled_map_id=? ORDER BY attempt_no", (map_id,)
            )
        ]
        maps.append(item)
    return {
        "match_id": match_id,
        **run_control.start_state(conn, match_id),
        "maps": maps,
        "results": read_results(conn, match_id),
    }


def attempt_player_ids(conn, match_id):
    """Include historical and void attempts, even if a scheduled map is no longer enabled."""
    return {
        row[0]
        for row in conn.execute(
            """SELECT l.player_id FROM map_run_lineups l
               JOIN map_runs r USING(map_run_id) JOIN scheduled_maps s USING(scheduled_map_id)
               WHERE s.match_id=?
               UNION
               SELECT rp.player_id FROM run_participations rp
               JOIN map_runs r USING(map_run_id) JOIN scheduled_maps s USING(scheduled_map_id)
               WHERE s.match_id=?
               UNION
               SELECT tr.outgoing_player_id FROM technical_replays tr
               JOIN map_runs r USING(map_run_id) JOIN scheduled_maps s USING(scheduled_map_id)
               WHERE s.match_id=? AND tr.outgoing_player_id IS NOT NULL
               UNION
               SELECT tr.incoming_player_id FROM technical_replays tr
               JOIN map_runs r USING(map_run_id) JOIN scheduled_maps s USING(scheduled_map_id)
               WHERE s.match_id=? AND tr.incoming_player_id IS NOT NULL""",
            (match_id, match_id, match_id, match_id),
        ).fetchall()
        if row[0] is not None
    }


def director_sessions(conn, match_id):
    sessions = {}
    for row in conn.execute(
        """SELECT ds.scheduled_map_id, ds.map_run_id, ds.session_id, ds.actor, ds.reason, ds.bound_at
           FROM live_director_sessions ds
           JOIN scheduled_maps s USING(scheduled_map_id)
           WHERE s.match_id=? ORDER BY ds.bound_at, ds.session_id""",
        (match_id,),
    ).fetchall():
        sessions.setdefault(str(row["map_run_id"]), []).append(dict(row))
    return sessions


def read_live_diagnostics(conn):
    receivers = conn.execute("""
        SELECT s.*, m.match_time, t1.name AS team1_name, t2.name AS team2_name
        FROM live_ingest_status s
        LEFT JOIN matches m ON s.match_id=m.id
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        ORDER BY s.source
    """).fetchall()
    rows = conn.execute(f"""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               l.live_state, l.updated_at, {get_sql_effective_status()}
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN live_match_data l ON l.match_id=m.id
        WHERE COALESCE(m.status, '') NOT IN ('completed', 'cancelled')
        ORDER BY CASE WHEN m.match_time IS NULL THEN 1 ELSE 0 END, m.match_time
    """).fetchall()
    matches = []
    for row in rows:
        match = dict(row)
        try:
            state = json.loads(match.get("live_state") or "{}")
        except (TypeError, ValueError):
            state = {}
        gsi = state.get("gsi", {}) or {}
        gotv = state.get("gotv", {}) or {}
        a2s = state.get("a2s", {}) or {}
        match["current_map"] = (
            (gsi.get("map", {}) or {}).get("name")
            or gotv.get("map_name")
            or (a2s.get("server", {}) or {}).get("map_name")
            or "-"
        )
        match["live_source"] = "GSI" if gsi else ("GOTV" if gotv else ("A2S" if a2s else "-"))
        matches.append(match)
    return receivers, matches
