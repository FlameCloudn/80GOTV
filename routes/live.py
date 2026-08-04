"""Read-only live-match API used by match pages."""

import json
import math

from flask import jsonify

from models import get_db
from services.live_service import (
    _is_recent_iso_timestamp,
    _load_live_player_profiles,
    _position_to_radar,
)
from web_app import app


def _normalize_team_label(value):
    return "".join(character for character in str(value or "").casefold() if character.isalnum())


def _gsi_team_mapping(gsi, row):
    identity = gsi.get("_80gotv", {}) if isinstance(gsi, dict) else {}
    ct_identity = identity.get("team_ct")
    t_identity = identity.get("team_t")
    if {ct_identity, t_identity} == {"team1", "team2"}:
        return {"CT": ct_identity, "T": t_identity}

    gmap = gsi.get("map", {}) or {}
    ct_name = _normalize_team_label((gmap.get("team_ct", {}) or {}).get("name"))
    t_name = _normalize_team_label((gmap.get("team_t", {}) or {}).get("name"))
    team1_labels = {
        _normalize_team_label(row["scheduled_team1_name"]),
        _normalize_team_label(row["scheduled_team1_short"]),
    }
    team2_labels = {
        _normalize_team_label(row["scheduled_team2_name"]),
        _normalize_team_label(row["scheduled_team2_short"]),
    }
    team1_labels.discard("")
    team2_labels.discard("")
    if ct_name in team1_labels or t_name in team2_labels:
        return {"CT": "team1", "T": "team2"}
    if ct_name in team2_labels or t_name in team1_labels:
        return {"CT": "team2", "T": "team1"}
    return {"CT": "team1", "T": "team2"}


def _format_live_timer(value):
    try:
        seconds = max(0, int(math.ceil(float(value))))
    except (TypeError, ValueError):
        return "-"
    return f"{seconds // 60}:{seconds % 60:02d}"


@app.route("/api/live/<int:match_id>")
def api_live_match(match_id):
    """实时比赛数据 API — 合并 GSI（本地旁观者）和 GOTV relay 数据"""
    conn = get_db()
    row = conn.execute(
        """
        SELECT l.live_state, l.updated_at,
               t1.name AS scheduled_team1_name, t2.name AS scheduled_team2_name,
               t1.short_name AS scheduled_team1_short,
               t2.short_name AS scheduled_team2_short
        FROM live_match_data l
        LEFT JOIN matches m ON l.match_id=m.id
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        WHERE l.match_id=?
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
    }
    if not row or not row["live_state"]:
        conn.close()
        return jsonify(result)

    try:
        state = json.loads(row["live_state"])
    except (json.JSONDecodeError, TypeError):
        conn.close()
        return jsonify(result)

    result["ok"] = True
    gsi = state.get("gsi", {}) or {}
    gotv = state.get("gotv", {}) or {}
    a2s = state.get("a2s", {}) or {}
    result["server"] = a2s.get("server", {}) or {}
    markers = state.get("death_markers", state.get("kill_markers", []))
    result["death_markers"] = markers[-10:] if isinstance(markers, list) else []
    # Keep the legacy field for older clients, but do not expose inferred kill events.
    result["kill_markers"] = result["death_markers"]
    result["kill_events"] = []
    bomb_events = state.get("bomb_events", [])
    result["bomb_events"] = bomb_events[-24:] if isinstance(bomb_events, list) else []
    profile_ids = set()
    for steamid in gsi.get("allplayers", {}) or {}:
        profile_ids.add(str(steamid))
    for marker in result["death_markers"]:
        profile_ids.add(str(marker.get("steamid", "")))
    for event in result["bomb_events"]:
        profile_ids.add(str(event.get("player_steamid", "")))
    profiles = _load_live_player_profiles(conn, profile_ids)
    for marker in result["death_markers"]:
        marker["name"] = profiles.get(str(marker.get("steamid", "")), {}).get("name") or marker.get(
            "name", ""
        )
        try:
            point = _position_to_radar(
                gsi.get("map", {}).get("name", ""),
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
    use_gsi = has_gsi and (gsi_is_fresh or not gotv)
    result["has_gsi"] = gsi_is_fresh
    result["source"] = (
        "gsi" if gsi_is_fresh else ("gotv" if gotv else ("stale_gsi" if has_gsi else ""))
    )

    if use_gsi:
        result["updated_at"] = state.get("gsi_received_at") or row["updated_at"]
        gmap = gsi.get("map", {}) or {}
        gphase = gsi.get("phase_countdowns", {}) or {}
        side_mapping = _gsi_team_mapping(gsi, row)
        identity_side = {identity: side for side, identity in side_mapping.items()}
        result["map_name"] = gmap.get("name", "")
        result["mode"] = gmap.get("mode", "")
        raw_round = int(gmap.get("round", 0) or 0)
        round_phase = str((gsi.get("round", {}) or {}).get("phase", "") or "")
        stored_history = state.get("round_history", [])
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
        live_profiles = _load_live_player_profiles(conn, steamids)

        t1_players = []
        t2_players = []
        for steamid, pdata in allplayers.items():
            pstate = pdata.get("state", {}) or {}
            pweapons = pdata.get("weapons", {}) or {}
            pmatch = pdata.get("match_stats", {}) or {}
            primary = ""
            secondary = ""
            for wname, wdata in sorted(pweapons.items(), key=lambda x: x[0]):
                wtype = wdata.get("type", "")
                if wtype in ("Rifle", "SniperRifle", "Machine Gun", "Shotgun", "Submachine Gun"):
                    primary = wdata.get("name") or wname
                elif wtype == "Pistol":
                    secondary = wdata.get("name") or wname

            entry = {
                "steamid": steamid,
                "name": live_profiles.get(str(steamid), {}).get("name") or pdata.get("name", ""),
                "avatar": live_profiles.get(str(steamid), {}).get("avatar", ""),
                "hp": pstate.get("health", 0),
                "armor": pstate.get("armor", 0),
                "helmet": pstate.get("helmet", False),
                "money": pstate.get("money", 0),
                "kills": pmatch.get("kills", 0),
                "assists": pmatch.get("assists", 0),
                "deaths": pmatch.get("deaths", 0),
                "adr": round(
                    pmatch.get("damage", 0) / max(int(gmap.get("round", 0) or 0) + 1, 1), 1
                ),
                "observer_slot": pdata.get("observer_slot", 99),
                "primary": primary,
                "secondary": secondary,
                "alive": pstate.get("health", 0) > 0,
            }
            player_side = str(pdata.get("team") or "")
            player_identity = side_mapping.get(player_side, player_side)
            if player_identity == "team1":
                t1_players.append(entry)
            else:
                t2_players.append(entry)

        player_order = lambda item: (
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
        team1_side = identity_side.get("team1", "CT")
        team2_side = identity_side.get("team2", "T")
        result["team1"] = {
            "name": row["scheduled_team1_name"] or side_data[team1_side].get("name") or "Team 1",
            "score": side_data[team1_side].get("score", 0),
            "side": team1_side,
            "timeouts_remaining": side_data[team1_side].get("timeouts_remaining", 0),
        }
        result["team2"] = {
            "name": row["scheduled_team2_name"] or side_data[team2_side].get("name") or "Team 2",
            "score": side_data[team2_side].get("score", 0),
            "side": team2_side,
            "timeouts_remaining": side_data[team2_side].get("timeouts_remaining", 0),
        }
        result["phase"] = gr.get("phase", "") or countdown_phase
        result["round_history"] = state.get("round_history", [])
        if result["round_history"]:
            result["latest_round_result"] = result["round_history"][-1]

    # --- GOTV 数据（回退/补充） ---
    if not use_gsi and gotv:
        result["updated_at"] = gotv.get("last_push", "") or row["updated_at"]
        result["map_name"] = gotv.get("map_name", "")
        result["round"] = gotv.get("rounds_count", 0)
        result["team1"] = {
            "name": gotv.get("team1_name", "Team 1"),
            "score": gotv.get("team1_score", 0),
        }
        result["team2"] = {
            "name": gotv.get("team2_name", "Team 2"),
            "score": gotv.get("team2_score", 0),
        }
        gotv_profiles = _load_live_player_profiles(
            conn,
            [
                p.get("steamid") or p.get("steam_id")
                for p in gotv.get("t1_players", []) + gotv.get("t2_players", [])
            ],
        )
        result["players_t1"] = [
            {
                "steamid": p.get("steamid") or p.get("steam_id", ""),
                "name": gotv_profiles.get(str(p.get("steamid") or p.get("steam_id", "")), {}).get(
                    "name"
                )
                or p.get("name", ""),
                "hp": "-",
                "armor": "-",
                "money": "-",
                "kills": p.get("kills", 0),
                "deaths": p.get("deaths", 0),
                "assists": p.get("assists", 0),
                "adr": p.get("adr", 0),
                "primary": "-",
                "secondary": "-",
                "alive": True,
            }
            for p in gotv.get("t1_players", [])[:5]
        ]
        result["players_t2"] = [
            {
                "steamid": p.get("steamid") or p.get("steam_id", ""),
                "name": gotv_profiles.get(str(p.get("steamid") or p.get("steam_id", "")), {}).get(
                    "name"
                )
                or p.get("name", ""),
                "hp": "-",
                "armor": "-",
                "money": "-",
                "kills": p.get("kills", 0),
                "deaths": p.get("deaths", 0),
                "assists": p.get("assists", 0),
                "adr": p.get("adr", 0),
                "primary": "-",
                "secondary": "-",
                "alive": True,
            }
            for p in gotv.get("t2_players", [])[:5]
        ]
    elif not use_gsi and result["server"].get("online"):
        result["source"] = "a2s"
        result["updated_at"] = row["updated_at"]
        result["map_name"] = result["server"].get("map_name", "")

    conn.close()
    return jsonify(result)
