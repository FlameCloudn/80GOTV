"""Read-only live-match API used by match pages."""

import json

from flask import jsonify

from models import get_db
from services.live_service import _is_recent_iso_timestamp, _load_live_player_profiles
from web_app import app


@app.route("/api/live/<int:match_id>")
def api_live_match(match_id):
    """实时比赛数据 API — 合并 GSI（本地旁观者）和 GOTV relay 数据"""
    conn = get_db()
    row = conn.execute(
        """
        SELECT l.live_state, l.updated_at,
               t1.name AS scheduled_team1_name, t2.name AS scheduled_team2_name
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
        "kill_markers": [],
        "kill_events": [],
        "bomb_events": [],
        "timer": "-",
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
    markers = state.get("kill_markers", [])
    result["kill_markers"] = markers[-10:] if isinstance(markers, list) else []
    events = state.get("kill_events", [])
    result["kill_events"] = events[-24:] if isinstance(events, list) else []
    bomb_events = state.get("bomb_events", [])
    result["bomb_events"] = bomb_events[-24:] if isinstance(bomb_events, list) else []
    profile_ids = set()
    for steamid in gsi.get("allplayers", {}) or {}:
        profile_ids.add(str(steamid))
    for marker in result["kill_markers"]:
        profile_ids.add(str(marker.get("steamid", "")))
    for event in result["kill_events"]:
        profile_ids.update(
            {
                str(event.get("killer_steamid", "")),
                str(event.get("assister_steamid", "")),
                str(event.get("victim_steamid", "")),
            }
        )
    for event in result["bomb_events"]:
        profile_ids.add(str(event.get("player_steamid", "")))
    profiles = _load_live_player_profiles(conn, profile_ids)
    for marker in result["kill_markers"]:
        marker["name"] = profiles.get(str(marker.get("steamid", "")), {}).get("name") or marker.get(
            "name", ""
        )
    for event in result["kill_events"]:
        event["killer"] = profiles.get(str(event.get("killer_steamid", "")), {}).get(
            "name"
        ) or event.get("killer", "")
        event["assister"] = profiles.get(str(event.get("assister_steamid", "")), {}).get(
            "name"
        ) or event.get("assister", "")
        event["victim"] = profiles.get(str(event.get("victim_steamid", "")), {}).get(
            "name"
        ) or event.get("victim", "")
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
        result["map_name"] = gmap.get("name", "")
        result["mode"] = gmap.get("mode", "")
        result["round"] = gmap.get("round", 0)
        result["timer"] = str(gphase.get("phase_ends_in_seconds", "") or "-")
        result["bomb"] = gsi.get("bomb", {}) or {}

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
                "adr": round(pmatch.get("damage", 0) / max(gmap.get("round", 1), 1), 1),
                "primary": primary,
                "secondary": secondary,
                "alive": pstate.get("health", 0) > 0,
            }
            if pdata.get("team") == "CT" or pdata.get("team") == "team1":
                t1_players.append(entry)
            else:
                t2_players.append(entry)

        result["players_t1"] = sorted(t1_players, key=lambda x: x["kills"], reverse=True)[:5]
        result["players_t2"] = sorted(t2_players, key=lambda x: x["kills"], reverse=True)[:5]

        # GSI 的地图数据中直接包含 CT 和 T 当前比分。
        ct = gmap.get("team_ct", {}) or {}
        terrorists = gmap.get("team_t", {}) or {}
        gr = gsi.get("round", {}) or {}
        result["team1"] = {
            "name": ct.get("name") or "CT",
            "score": ct.get("score", gr.get("ct_score", 0)),
            "side": "CT",
        }
        result["team2"] = {
            "name": terrorists.get("name") or "T",
            "score": terrorists.get("score", gr.get("t_score", 0)),
            "side": "T",
        }
        result["phase"] = gr.get("phase", "")
        result["round_history"] = state.get("round_history", [])

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
