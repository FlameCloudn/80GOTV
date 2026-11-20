"""Project one selected match into the desktop director's existing contract."""

import hashlib
import json

from src.website.domains.directory.team_logo_service import team_logo_static_path
from src.website.domains.matches.bp_match_state import ensure_bp_started
from src.website.domains.matches.maps import bp_lock_reason, broadcast_maps
from src.website.domains.matches.match_roster_service import resolve_match_roster
from src.website.domains.matches.match_utils import get_bo_max_maps
from src.website.domains.matches.opponents import supplement_temp_teams
from src.website.domains.matches.participants import rosters_frozen
from src.website.domains.operations.broadcast_rosters import display_rosters, event_substitutes
from src.website.domains.operations.projection import (
    live_schema_ready,
    project_director_match,
    start_projection,
)


def _stored_bp(raw_state):
    try:
        state = json.loads(raw_state) if raw_state else None
    except (TypeError, ValueError):
        return None
    return state if isinstance(state, dict) else None


def _live_snapshot(conn, match_id):
    row = conn.execute(
        "SELECT live_state FROM live_match_data WHERE match_id=?", (match_id,)
    ).fetchone()
    try:
        return json.loads(row["live_state"] or "{}") if row else {}
    except (TypeError, ValueError):
        return {}


def _legacy_maps(match, bp_state, live_state):
    raw_unconfirmed = (
        live_state.get("unconfirmed_map_slots", []) if isinstance(live_state, dict) else []
    )
    unconfirmed = (
        {
            value
            for value in raw_unconfirmed
            if isinstance(value, int) and not isinstance(value, bool)
        }
        if isinstance(raw_unconfirmed, list)
        else set()
    )
    maps = []
    for slot in range(1, get_bo_max_maps(match.get("bo_format")) + 1):
        if slot >= 3 and not match.get(f"has_map{slot}", 1):
            continue
        name = match.get(f"map{slot}") or ""
        bp_pick = next(
            (
                pick
                for pick in (bp_state or {}).get("picks", [])
                if pick.get("map") == name
                or str(pick.get("map", "")).lower() == str(name).replace("de_", "").lower()
            ),
            {},
        )
        picked_by = match.get(f"map{slot}_picked_by") or bp_pick.get("picked_by") or ""
        side = bp_pick.get("side")
        chooser = bp_pick.get("side_team")
        if not chooser and picked_by in {"t1", "t2"}:
            chooser = "t2" if picked_by == "t1" else "t1"
        opening_ct_team = ""
        if side in {"CT", "T"} and chooser in {"t1", "t2"}:
            opening_ct_team = chooser if side == "CT" else ("t2" if chooser == "t1" else "t1")
        score1 = match.get(f"map{slot}_t1") or 0
        score2 = match.get(f"map{slot}_t2") or 0
        maps.append(
            {
                "slot": slot,
                "name": name,
                "team1_score": score1,
                "team2_score": score2,
                "map_finished": slot - 1 not in unconfirmed and score1 != score2,
                "picked_by": picked_by,
                "opening_ct_team": opening_ct_team,
                "opening_side_source": "website_bp" if opening_ct_team else "pending",
            }
        )
    return maps


def _managed_maps(conn, match_id, roster, live_state):
    operations_enabled = live_schema_ready(conn)
    maps = [
        dict(item, team1_score=0, team2_score=0, map_finished=False)
        for item in broadcast_maps(conn, match_id)
    ]
    if operations_enabled:
        project_director_match(
            conn, match_id, maps, roster, live_state if isinstance(live_state, dict) else {}
        )
    return maps


def _decider(match, bp_state):
    result = {
        "knife_winner": match.get("decider_knife_winner") or "",
        "start_side": match.get("decider_start_side") or "",
        "side_team": "",
    }
    if bp_state:
        pick = next(
            (pick for pick in bp_state.get("picks", []) if pick.get("picked_by") == "remaining"),
            None,
        )
        if pick and pick.get("side") in {"CT", "T"}:
            result["start_side"] = pick["side"]
            result["side_team"] = pick.get("side_team") or ""
    return result


def _team(match, side, players, *, hosted):
    key = f"team{side}"
    result = {
        "id": match.get(f"{key}_id"),
        "name": match.get(f"{key}_name") or "TBD",
        "short_name": match.get(f"t{side}s") or "TBD",
        "logo": team_logo_static_path(match.get(f"{key}_logo")),
        "series_score": match.get(f"{key}_score") or 0,
        "players": players,
    }
    registration_id = match.get(f"{key}_registration_id")
    if hosted and registration_id:
        result["source_id"] = f"registration-{registration_id}"
    return result


def read_match_payload(conn, row, *, hosted):
    match = supplement_temp_teams(row, conn)
    match_id = match["id"]
    # Preserve the historical BP upgrade on read. For hosted matches this only
    # normalizes the response and never changes the saved state.
    bp_state, bp_changed = ensure_bp_started(conn, match)
    if bp_changed:
        conn.commit()
    substitutes = event_substitutes(conn, match.get("event_id"))
    roster = resolve_match_roster(conn, match)
    roster_issues = roster["issues"]
    live_state = _live_snapshot(conn, match_id)
    maps = (
        _managed_maps(conn, match_id, roster, live_state)
        if hosted
        else _legacy_maps(match, bp_state, live_state)
    )
    players = display_rosters(roster["players"], substitutes)
    roster_revision = hashlib.sha256(
        json.dumps(roster["steam_ids"], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    closed = str(match.get("status") or "").lower() in {"completed", "cancelled"}
    start = (
        start_projection(conn, match_id)
        if hosted
        else {
            "ready_for_start": not roster_issues
            and bool(bp_state and bp_state.get("status") == "completed")
            and not closed
        }
    )
    status = (
        match.get("status") if hosted else match.get("effective_status") or match.get("status")
    ) or "upcoming"
    return {
        "id": match_id,
        "status": status,
        "event": {
            "id": match.get("event_id"),
            "name": match.get("event_name") or "80GOTV",
            "short_name": match.get("event_short_name") or "",
        },
        "stage": match.get("stage") or "",
        "bo": match.get("bo_format") or "BO3",
        "match_time": match.get("match_time") or "",
        "team1": _team(match, 1, players[1], hosted=hosted),
        "team2": _team(match, 2, players[2], hosted=hosted),
        "substitutes": substitutes,
        "substitute_count": len(substitutes),
        "maps": maps,
        "bp": bp_state if bp_state is not None else _stored_bp(match.get("bp_state")),
        "bp_revision": int((bp_state or {}).get("revision", 0) or 0),
        "roster_revision": roster_revision,
        "roster_locked": rosters_frozen(conn, match_id) if hosted else not roster_issues,
        "roster_issues": roster_issues,
        **start,
        "bp_can_start": (not hosted or bp_lock_reason(conn, match) is None) and not closed,
        "decider": _decider(match, bp_state),
        "live_api": f"/api/live/{match_id}",
        "live_ingest_api": f"/api/broadcast/matches/{match_id}/live",
    }
