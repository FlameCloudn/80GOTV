"""Read a public live scoreboard, tied to the real map run for managed matches."""

import json

from src.website.domains.demos.demo_parser import normalize_map_name
from src.website.domains.matches.participants import sides as participant_sides
from src.website.domains.operations.live_log import (
    load_legacy_timeline,
    load_run_timeline,
    uses_run_timeline,
)
from src.website.domains.operations.live_rosters import roster_profiles_by_steamid
from src.website.domains.operations.live_service import (
    _is_recent_iso_timestamp,
    _load_live_player_profiles,
    _position_to_radar,
)
from src.website.web.read_models.live_frames import apply_gotv_frame, apply_gsi_frame


def _empty_scoreboard(match_id):
    return {
        "ok": False,
        "match_id": match_id,
        "team1": None,
        "team2": None,
        "players_t1": [],
        "players_t2": [],
        "round_history": [],
        "overtime_history": [],
        "latest_round_result": None,
        "death_markers": [],
        "kill_markers": [],
        "kill_events": [],
        "bomb_events": [],
        "timer": "-",
        "phase": "",
        "phase_countdown": "",
        "paused": False,
        "pause_type": "",
        "has_gsi": False,
        "bomb": {},
        "server": {},
        "updated_at": None,
        "side_uncertain": True,
        "side_mapping": None,
    }


def _stored_match(conn, match_id):
    return conn.execute(
        """SELECT l.live_state, l.updated_at,
                  t1.name AS scheduled_team1_name, t2.name AS scheduled_team2_name,
                  t1.short_name AS scheduled_team1_short, t2.short_name AS scheduled_team2_short,
                  m.id, m.event_id, m.team1_id, m.team2_id, m.team1_players, m.team2_players,
                  m.roster_snapshot, m.team1_registration_id, m.team2_registration_id
           FROM matches m
           LEFT JOIN live_match_data l ON l.match_id=m.id
           LEFT JOIN teams t1 ON m.team1_id=t1.id
           LEFT JOIN teams t2 ON m.team2_id=t2.id
           WHERE m.id=?""",
        (match_id,),
    ).fetchone()


def _latest_attempt(conn, match_id):
    # A void map waiting for replay must not expose the previous completed map as live.
    return conn.execute(
        """SELECT r.map_run_id,r.status,s.map_name,o.score1,o.score2
           FROM scheduled_maps s JOIN map_runs r USING(scheduled_map_id)
           LEFT JOIN official_map_results o ON o.scheduled_map_id=s.scheduled_map_id
                AND o.map_run_id=r.map_run_id AND o.is_current=1
           WHERE s.match_id=? AND s.is_enabled=1
           ORDER BY s.map_order DESC,r.attempt_no DESC LIMIT 1""",
        (match_id,),
    ).fetchone()


def _live_state(row):
    try:
        return json.loads(row["live_state"]) if row and row["live_state"] else None
    except (json.JSONDecodeError, TypeError):
        return None


def _managed_timeline(conn, result, match_id, run):
    timeline = load_run_timeline(conn, match_id, run["map_run_id"]) if run else []
    rounds = [event for event in timeline if event["type"] == "round"]
    result["round_history"] = [event for event in rounds if event["round"] <= 24]
    result["overtime_history"] = [event for event in rounds if event["round"] > 24][-24:]
    result["latest_round_result"] = rounds[-1] if rounds else None
    markers = [event for event in timeline if event["type"] == "death"][-10:]
    result["kill_markers"] = result["death_markers"] = markers
    result["bomb_events"] = [event for event in timeline if event["type"] == "plant"][-24:]
    if timeline:
        result["round"] = timeline[-1]["round"]


def _legacy_timeline(conn, result, match_id, state, gsi, gotv):
    for field in ("round_history", "overtime_history"):
        if isinstance(state.get(field), list):
            result[field] = state[field]
    markers = state.get("death_markers", state.get("kill_markers", []))
    result["kill_markers"] = result["death_markers"] = (
        markers[-10:] if isinstance(markers, list) else []
    )
    current_map = normalize_map_name(
        (gsi.get("map", {}) or {}).get("name", "") or gotv.get("map_name", "")
    )
    timeline = [
        event
        for event in load_legacy_timeline(conn, match_id)
        if normalize_map_name(event.get("map_name", "")) == current_map
    ]
    result["kill_events"] = [event for event in timeline if event.get("type") == "kill"][-40:]
    result["bomb_events"] = [event for event in timeline if event.get("type") == "plant"][-24:]
    bomb_events = state.get("bomb_events", [])
    if isinstance(bomb_events, list) and bomb_events:
        result["bomb_events"] = bomb_events[-24:]


def _legacy_public_profiles(conn, result, gsi):
    profile_ids = {str(steamid) for steamid in gsi.get("allplayers", {}) or {}}
    profile_ids.update(str(marker.get("steamid", "")) for marker in result["death_markers"])
    profile_ids.update(str(event.get("player_steamid", "")) for event in result["bomb_events"])
    return _load_live_player_profiles(conn, profile_ids)


def _decorate_markers(result, gsi, profiles):
    for marker in result["death_markers"]:
        profile = profiles.get(str(marker.get("steamid", "")), {})
        marker["name"] = profile.get("name") or marker.get("name", "")
        try:
            point = _position_to_radar(
                gsi.get("map", {}).get("name") or result.get("map_name", ""),
                (float(marker.get("x")), float(marker.get("y")), float(marker.get("z") or 0)),
            )
            if point:
                marker["radar_x"] = round(point[0] / 708 * 100, 2)
                marker["radar_y"] = round(point[1] / 708 * 100, 2)
        except (TypeError, ValueError):
            pass
    for event in result["bomb_events"]:
        profile = profiles.get(str(event.get("player_steamid", "")), {})
        event["player"] = profile.get("name") or event.get("player", "")


def _feed(state, source):
    value = state.get(source)
    return value if isinstance(value, dict) else {}


def _sources(result, state, gsi, gotv):
    has_gsi = bool(gsi)
    gsi_is_fresh = has_gsi and _is_recent_iso_timestamp(state.get("gsi_received_at"))
    gotv_is_fresh = bool(gotv) and _is_recent_iso_timestamp(gotv.get("last_push"))
    result["has_gsi"] = gsi_is_fresh
    if gsi_is_fresh:
        result["source"] = "gsi"
    elif gotv_is_fresh:
        result["source"] = "gotv"
    elif gotv:
        result["source"] = "stale_gotv"
    else:
        result["source"] = "stale_gsi" if has_gsi else ""
    return has_gsi and (gsi_is_fresh or not gotv)


def _apply_fixed_teams(result, fixed_teams):
    for side, team in fixed_teams.items():
        key = f"team{side}"
        result[key] = {
            **(result[key] or {}),
            "name": team["name"],
            "short_name": team["short_name"],
        }


def _apply_official_scores(result, run, row):
    if run and run["status"] == "closed":
        for side in (1, 2):
            key = f"team{side}"
            if result[key] is None:
                result[key] = {"name": row[f"scheduled_team{side}_name"]}
            result[key]["score"] = run[f"score{side}"]


def read_scoreboard(conn, match_id):
    if not conn.in_transaction:
        conn.execute("BEGIN")
    result = _empty_scoreboard(match_id)
    row = _stored_match(conn, match_id)
    if not row:
        return result
    state = _live_state(row)
    managed = uses_run_timeline(conn, match_id)
    run = _latest_attempt(conn, match_id) if managed else None
    if run:
        if run["status"] == "void":
            result["reason"] = "map_run_void"
            return result
        if run["status"] == "closed" and run["score1"] is None:
            return result
        if not isinstance(state, dict) or state.get("map_run_id") != run["map_run_id"]:
            state = {}
        result.update(map_run_id=run["map_run_id"], map_name=run["map_name"])
    elif managed and isinstance(state, dict):
        state = {"a2s": state["a2s"]} if state.get("a2s") else None
    if not isinstance(state, dict):
        return result

    fixed_teams = participant_sides(conn, match_id) if managed else {}
    if fixed_teams:
        row = dict(row)
        for side, team in fixed_teams.items():
            row[f"scheduled_team{side}_name"] = team["name"]
            row[f"scheduled_team{side}_short"] = team["short_name"]
    roster_profiles = roster_profiles_by_steamid(conn, row, run_id=run["map_run_id"]) if run else {}
    gsi, gotv = _feed(state, "gsi"), _feed(state, "gotv")
    result["ok"] = True
    result["server"] = _feed(state, "a2s").get("server", {}) or {}
    if managed:
        _managed_timeline(conn, result, match_id, run)
        profiles = roster_profiles
    else:
        _legacy_timeline(conn, result, match_id, state, gsi, gotv)
        profiles = _legacy_public_profiles(conn, result, gsi)
    _decorate_markers(result, gsi, profiles)

    if _sources(result, state, gsi, gotv):
        if not managed:
            roster_profiles = roster_profiles_by_steamid(conn, row)
        apply_gsi_frame(result, row, state, gsi, roster_profiles, profiles, managed=managed)
    elif gotv:
        apply_gotv_frame(conn, result, row, gotv, roster_profiles, managed=managed)
    elif result["server"].get("online"):
        result["source"] = "a2s"
        result["updated_at"] = row["updated_at"]
        result["map_name"] = result["server"].get("map_name", "")

    _apply_fixed_teams(result, fixed_teams)
    _apply_official_scores(result, run, row)
    return result
