"""Read-only live-match API used by match pages."""

import json
import math

from flask import jsonify

from models import get_db
from services.live_log_service import load_legacy_timeline, load_run_timeline, uses_run_timeline
from services.live_roster_service import gsi_team_mapping as _gsi_team_mapping
from services.live_roster_service import roster_profiles_by_steamid as _roster_profiles_by_steamid
from services.live_roster_service import (
    roster_side_by_steamid as _roster_side_by_steamid,  # noqa: F401
)
from services.live_service import (
    _is_recent_iso_timestamp,
    _load_live_player_profiles,
    _position_to_radar,
)
from site_core.matches.participants import sides as participant_sides
from utils.demo_parser import normalize_map_name
from web_app import app


def _player_ids(value):
    """Return numeric player ids stored on a match roster."""
    if isinstance(value, list):
        values = value
    else:
        try:
            values = json.loads(value or "[]")
        except (TypeError, ValueError):
            values = []
    result = []
    for value in values if isinstance(values, list) else []:
        try:
            result.append(int(value))
        except (TypeError, ValueError):
            continue
    return result


def _format_live_timer(value):
    try:
        seconds = max(0, int(math.ceil(float(value))))
    except (TypeError, ValueError, OverflowError):
        return "-"
    return f"{seconds // 60}:{seconds % 60:02d}"


@app.route("/api/live/<int:match_id>")
def api_live_match(match_id):
    """实时比赛数据 API — 合并 GSI（本地旁观者）和 GOTV relay 数据"""
    conn = get_db()
    if not conn.in_transaction:
        conn.execute("BEGIN")
    row = conn.execute(
        """
        SELECT l.live_state, l.updated_at,
               t1.name AS scheduled_team1_name, t2.name AS scheduled_team2_name,
               t1.short_name AS scheduled_team1_short,
               t2.short_name AS scheduled_team2_short,
               m.id, m.event_id, m.team1_id, m.team2_id, m.team1_players, m.team2_players,
               m.roster_snapshot, m.team1_registration_id, m.team2_registration_id
        FROM matches m
        LEFT JOIN live_match_data l ON l.match_id=m.id
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        WHERE m.id=?
    """,
        (match_id,),
    ).fetchone()

    result = {
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
    try:
        state = json.loads(row["live_state"]) if row and row["live_state"] else None
    except (json.JSONDecodeError, TypeError):
        state = None
    managed = bool(row and uses_run_timeline(conn, match_id))
    run = None
    if managed:
        # Look at the last attempted slot even when void. In the gap before a
        # replay starts, the previous completed map is not the live map.
        run = conn.execute(
            """SELECT r.map_run_id,r.status,s.map_name,o.score1,o.score2
               FROM scheduled_maps s JOIN map_runs r USING(scheduled_map_id)
               LEFT JOIN official_map_results o ON o.scheduled_map_id=s.scheduled_map_id
                    AND o.map_run_id=r.map_run_id AND o.is_current=1
               WHERE s.match_id=? AND s.is_enabled=1
               ORDER BY s.map_order DESC,r.attempt_no DESC LIMIT 1""",
            (match_id,),
        ).fetchone()
        if run and (
            run["status"] == "void" or (run["status"] == "closed" and run["score1"] is None)
        ):
            if run["status"] == "void":
                result["reason"] = "map_run_void"
            conn.close()
            return jsonify(result)
        if run:
            if not isinstance(state, dict) or state.get("map_run_id") != run["map_run_id"]:
                state = {}
            result.update(map_run_id=run["map_run_id"], map_name=run["map_name"])
        elif isinstance(state, dict):
            state = {"a2s": state["a2s"]} if state.get("a2s") else None
    if not isinstance(state, dict):
        conn.close()
        return jsonify(result)

    fixed_teams = participant_sides(conn, match_id) if managed else {}
    if fixed_teams:
        row = dict(row)
        for side, team in fixed_teams.items():
            row[f"scheduled_team{side}_name"] = team["name"]
            row[f"scheduled_team{side}_short"] = team["short_name"]
    roster_profiles = (
        _roster_profiles_by_steamid(conn, row, run_id=run["map_run_id"]) if run else {}
    )
    # This endpoint shows live observations, not the approved post-match statistics.
    stat_default = None if managed else 0
    result["ok"] = True
    gsi = state.get("gsi")
    if not isinstance(gsi, dict):
        gsi = {}
    gotv = state.get("gotv")
    if not isinstance(gotv, dict):
        gotv = {}
    a2s = state.get("a2s")
    if not isinstance(a2s, dict):
        a2s = {}
    result["server"] = a2s.get("server", {}) or {}
    if managed:
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
    else:
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
    profile_ids = set()
    for steamid in gsi.get("allplayers", {}) or {}:
        profile_ids.add(str(steamid))
    for marker in result["death_markers"]:
        profile_ids.add(str(marker.get("steamid", "")))
    for event in result["bomb_events"]:
        profile_ids.add(str(event.get("player_steamid", "")))
    profiles = roster_profiles if managed else _load_live_player_profiles(conn, profile_ids)
    for marker in result["death_markers"]:
        marker["name"] = profiles.get(str(marker.get("steamid", "")), {}).get("name") or marker.get(
            "name", ""
        )
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
        event["player"] = profiles.get(str(event.get("player_steamid", "")), {}).get(
            "name"
        ) or event.get("player", "")

    # --- GSI 数据（逐帧实时） ---
    has_gsi = bool(gsi)
    gsi_is_fresh = has_gsi and _is_recent_iso_timestamp(state.get("gsi_received_at"))
    gotv_is_fresh = bool(gotv) and _is_recent_iso_timestamp(gotv.get("last_push"))
    use_gsi = has_gsi and (gsi_is_fresh or not gotv)
    result["has_gsi"] = gsi_is_fresh
    result["source"] = (
        "gsi"
        if gsi_is_fresh
        else (
            "gotv"
            if gotv_is_fresh
            else ("stale_gotv" if gotv else ("stale_gsi" if has_gsi else ""))
        )
    )

    if use_gsi:
        result["updated_at"] = state.get("gsi_received_at") or row["updated_at"]
        gmap = gsi.get("map", {}) or {}
        gphase = gsi.get("phase_countdowns", {}) or {}
        if not managed:
            roster_profiles = _roster_profiles_by_steamid(conn, row)
        roster_side_by_steamid = {
            steam_id: profile["team"] for steam_id, profile in roster_profiles.items()
        }
        side_mapping = _gsi_team_mapping(gsi, row, roster_side_by_steamid)
        identity_side = {identity: side for side, identity in (side_mapping or {}).items()}
        result["side_uncertain"] = not bool(side_mapping)
        result["side_mapping"] = side_mapping
        result["map_name"] = gmap.get("name", "")
        result["mode"] = gmap.get("mode", "")
        raw_round = int(gmap.get("round", 0) or 0)
        round_phase = str((gsi.get("round", {}) or {}).get("phase", "") or "")
        stored_history = result["round_history"]
        overtime_history = result["overtime_history"]
        if isinstance(stored_history, list) and isinstance(overtime_history, list):
            stored_history = stored_history + overtime_history
        last_completed_round = 0
        if isinstance(stored_history, list) and stored_history:
            try:
                last_completed_round = int(
                    stored_history[-1].get("round_number", stored_history[-1].get("round", 0)) or 0
                )
            except (TypeError, ValueError, AttributeError):
                last_completed_round = 0
        result["round"] = max(
            1,
            last_completed_round
            if (gmap.get("phase") == "gameover" or round_phase == "over") and last_completed_round
            else raw_round + 1,
        )
        result["timer"] = _format_live_timer(
            gphase.get("phase_ends_in_seconds", gphase.get("phase_ends_in"))
        )
        result["bomb"] = gsi.get("bomb", {}) or {}
        countdown_phase = str(gphase.get("phase", "") or "")
        result["phase_countdown"] = countdown_phase
        result["paused"] = countdown_phase.startswith("timeout") or countdown_phase in {
            "paused",
            "pause",
        }
        result["pause_type"] = (
            "tactical"
            if countdown_phase.startswith("timeout")
            else "technical"
            if result["paused"]
            else ""
        )

        # allplayers 数据（HP/武器/护甲/金钱）。坐标仅用于服务端记录阵亡点。
        allplayers = gsi.get("allplayers", {}) or {}
        steamids = [str(steamid) for steamid in allplayers]
        live_profiles = roster_profiles if managed else _load_live_player_profiles(conn, steamids)

        t1_players = []
        t2_players = []
        seen_roster_ids = set()
        for steamid, pdata in allplayers.items():
            # A GSI frame can briefly retain a player from a previous server
            # session. When this match has an explicit roster, never expose
            # observers or stale players outside that roster.
            if (managed or roster_side_by_steamid) and steamid not in roster_side_by_steamid:
                continue
            player_side = str(pdata.get("team") or "")
            if managed and player_side.upper() not in ("CT", "T"):
                continue
            seen_roster_ids.add(str(steamid))
            pstate = pdata.get("state", {}) or {}
            pweapons = pdata.get("weapons", {}) or {}
            pmatch = pdata.get("match_stats", {}) or {}
            damage = pmatch.get("damage", stat_default)
            primary = ""
            secondary = ""
            for wname, wdata in sorted(pweapons.items(), key=lambda x: x[0]):
                wtype = wdata.get("type", "")
                if wtype in ("Rifle", "SniperRifle", "Machine Gun", "Shotgun", "Submachine Gun"):
                    primary = wdata.get("name") or wname
                elif wtype == "Pistol":
                    secondary = wdata.get("name") or wname

            roster_profile = roster_profiles.get(str(steamid), {})
            live_profile = live_profiles.get(str(steamid), {})
            entry = {
                "steamid": steamid,
                "player_id": roster_profile.get("player_id"),
                "roster_slot": roster_profile.get("slot"),
                "is_substitute": bool(roster_profile.get("is_substitute")),
                "name": roster_profile.get("name")
                or live_profile.get("name")
                or pdata.get("name", ""),
                "avatar": roster_profile.get("avatar") or live_profile.get("avatar", ""),
                "hp": pstate.get("health", 0),
                "armor": pstate.get("armor", 0),
                "helmet": pstate.get("helmet", False),
                "money": pstate.get("money", 0),
                "kills": pmatch.get("kills", stat_default),
                "assists": pmatch.get("assists", stat_default),
                "deaths": pmatch.get("deaths", stat_default),
                "adr": None
                if managed and damage is None
                else round(damage / max(raw_round + 1, 1), 1),
                "observer_slot": pdata.get("observer_slot"),
                "primary": primary,
                "secondary": secondary,
                "alive": pstate.get("health", 0) > 0,
            }
            # The lineup is authoritative for the fixed team slot.
            # GSI's CT/T value only describes the current side and changes at half.
            player_identity = roster_side_by_steamid.get(steamid)
            if not player_identity and side_mapping:
                player_identity = side_mapping.get(player_side)
            if player_identity == "team1":
                t1_players.append(entry)
            elif player_identity == "team2":
                t2_players.append(entry)

        # A lineup slot alone does not prove that somebody ever connected to this run.
        for steamid, player_identity in roster_side_by_steamid.items():
            if steamid in seen_roster_ids:
                continue
            profile = roster_profiles.get(steamid, {})
            if not profile.get("name") or (managed and not profile["has_appeared"]):
                continue
            missing_entry = {
                "steamid": steamid,
                "player_id": profile.get("player_id"),
                "roster_slot": profile.get("slot"),
                "is_substitute": bool(profile.get("is_substitute")),
                "name": profile["name"],
                "avatar": profile.get("avatar", ""),
                "hp": "-",
                "armor": "-",
                "helmet": False,
                "money": "-",
                "kills": stat_default,
                "assists": stat_default,
                "deaths": stat_default,
                "adr": stat_default,
                "observer_slot": None,
                "primary": "",
                "secondary": "",
                "alive": False,
                "missing": True,
            }
            if player_identity == "team1":
                t1_players.append(missing_entry)
            elif player_identity == "team2":
                t2_players.append(missing_entry)

        def player_order(item):
            kills = int(item.get("kills", 0) or 0)
            deaths = int(item.get("deaths", 0) or 0)
            return (
                1 if item.get("missing") else 0,
                -(kills - deaths),
                -kills,
                deaths,
                int(item.get("observer_slot", 99) or 99),
                str(item.get("steamid", "")),
            )

        result["players_t1"] = sorted(t1_players, key=player_order)[:5]
        result["players_t2"] = sorted(t2_players, key=player_order)[:5]

        # GSI 的地图数据中直接包含 CT 和 T 当前比分。
        ct = gmap.get("team_ct", {}) or {}
        terrorists = gmap.get("team_t", {}) or {}
        gr = gsi.get("round", {}) or {}
        side_data = {"CT": ct, "T": terrorists}
        team1_side = identity_side.get("team1")
        team2_side = identity_side.get("team2")
        result["team1"] = {
            "name": row["scheduled_team1_name"]
            or (side_data[team1_side].get("name") if team1_side else "TBD"),
            "score": side_data[team1_side].get("score") if team1_side else None,
            "side": team1_side,
            "timeouts_remaining": side_data[team1_side].get("timeouts_remaining", 0)
            if team1_side
            else None,
        }
        result["team2"] = {
            "name": row["scheduled_team2_name"]
            or (side_data[team2_side].get("name") if team2_side else "TBD"),
            "score": side_data[team2_side].get("score") if team2_side else None,
            "side": team2_side,
            "timeouts_remaining": side_data[team2_side].get("timeouts_remaining", 0)
            if team2_side
            else None,
        }
        result["phase"] = gr.get("phase", "") or countdown_phase
        if not managed and result["round_history"]:
            result["latest_round_result"] = result["round_history"][-1]

    # --- GOTV 数据（回退/补充） ---
    if not use_gsi and gotv:
        result["updated_at"] = gotv.get("last_push", "") or row["updated_at"]
        result["map_name"] = gotv.get("map_name", "")
        result["round"] = gotv.get("rounds_count", 0)
        result["team1"] = {
            "name": gotv.get("team1_name", "TBD"),
            "score": gotv.get("team1_score", 0),
        }
        result["team2"] = {
            "name": gotv.get("team2_name", "TBD"),
            "score": gotv.get("team2_score", 0),
        }
        gotv_profiles = (
            roster_profiles
            if managed
            else _load_live_player_profiles(
                conn,
                [
                    p.get("steamid") or p.get("steam_id")
                    for p in gotv.get("t1_players", []) + gotv.get("t2_players", [])
                ],
            )
        )
        for side in (1, 2):
            players = result[f"players_t{side}"]
            for p in gotv.get(f"t{side}_players", []):
                steamid = p.get("steamid") or p.get("steam_id", "")
                profile = gotv_profiles.get(str(steamid), {})
                if managed and profile.get("team") != f"team{side}":
                    continue
                entry = {
                    "steamid": steamid,
                    "name": profile.get("name") or p.get("name", ""),
                    "hp": "-",
                    "armor": "-",
                    "money": "-",
                    "kills": p.get("kills", stat_default),
                    "deaths": p.get("deaths", stat_default),
                    "assists": p.get("assists", stat_default),
                    "adr": p.get("adr", stat_default),
                    "primary": "-",
                    "secondary": "-",
                    "alive": True,
                }
                if managed:
                    entry.update(
                        player_id=profile["player_id"],
                        roster_slot=profile["slot"],
                        avatar=profile["avatar"],
                        is_substitute=profile["is_substitute"],
                    )
                players.append(entry)
                if len(players) == 5:
                    break
    elif not use_gsi and result["server"].get("online"):
        result["source"] = "a2s"
        result["updated_at"] = row["updated_at"]
        result["map_name"] = result["server"].get("map_name", "")

    for side, team in fixed_teams.items():
        key = f"team{side}"
        result[key] = {
            **(result[key] or {}),
            "name": team["name"],
            "short_name": team["short_name"],
        }

    if run and run["status"] == "closed":
        for side in (1, 2):
            key = f"team{side}"
            if result[key] is None:
                result[key] = {"name": row[f"scheduled_team{side}_name"]}
            result[key]["score"] = run[f"score{side}"]

    conn.close()
    return jsonify(result)
