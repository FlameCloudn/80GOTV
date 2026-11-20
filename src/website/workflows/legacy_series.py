"""Finish or reopen a historical match in the caller's write transaction."""

import json

from src.website.domains.matches.bracket_service import refresh_bracket_for_match
from src.website.domains.matches.match_roster_service import freeze_match_roster
from src.website.domains.matches.series import completed_match_result_error
from src.website.domains.operations.live_log import persist_live_match_events
from src.website.domains.predictions.scoring import revoke_legacy_points, score_predictions


def finish_legacy_series(conn, match_id, *, save_game_log):
    conn.execute("UPDATE matches SET status=status WHERE id=?", (match_id,))
    match = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
    if not match:
        raise ValueError("比赛不存在")
    error = completed_match_result_error(match)
    if error:
        raise ValueError(error)
    saved = 0
    if save_game_log:
        row = conn.execute(
            "SELECT live_state FROM live_match_data WHERE match_id=?", (match_id,)
        ).fetchone()
        if row and row["live_state"]:
            try:
                live_state = json.loads(row["live_state"])
            except (TypeError, ValueError):
                live_state = None
            if isinstance(live_state, dict):
                saved = persist_live_match_events(conn, match_id, live_state)
    freeze_match_roster(conn, match, confirmed=True)
    conn.execute("UPDATE matches SET status='completed' WHERE id=?", (match_id,))
    refresh_bracket_for_match(conn, match_id)
    score_predictions(conn, match_id)
    return saved


def reopen_legacy_series(conn, match_id):
    changed = conn.execute(
        "UPDATE matches SET status='live' WHERE id=? AND status='completed'", (match_id,)
    ).rowcount
    if changed:
        revoke_legacy_points(conn, match_id)
        refresh_bracket_for_match(conn, match_id)
    return changed
