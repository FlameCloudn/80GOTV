"""Project current GSI or GOTV observations onto the two fixed scoreboard slots."""

import math

from src.website.domains.operations.live_rosters import gsi_team_mapping
from src.website.domains.operations.live_service import _load_live_player_profiles


def format_live_timer(value):
    try:
        seconds = max(0, int(math.ceil(float(value))))
    except (TypeError, ValueError, OverflowError):
        return "-"
    return f"{seconds // 60}:{seconds % 60:02d}"


def _last_completed_round(result):
    history = result["round_history"] + result["overtime_history"]
    if not history:
        return 0
    try:
        return int(history[-1].get("round_number", history[-1].get("round", 0)) or 0)
    except (TypeError, ValueError, AttributeError):
        return 0


def _set_gsi_clock(result, gsi, game_map):
    phase = gsi.get("phase_countdowns", {}) or {}
    round_phase = (gsi.get("round", {}) or {}).get("phase", "")
    raw_round = int(game_map.get("round", 0) or 0)
    last_completed = _last_completed_round(result)
    round_over = game_map.get("phase") == "gameover" or str(round_phase or "") == "over"
    result["round"] = max(1, last_completed if round_over and last_completed else raw_round + 1)
    result["timer"] = format_live_timer(
        phase.get("phase_ends_in_seconds", phase.get("phase_ends_in"))
    )
    countdown_phase = str(phase.get("phase", "") or "")
    tactical = countdown_phase.startswith("timeout")
    result["phase_countdown"] = countdown_phase
    result["paused"] = tactical or countdown_phase in {"paused", "pause"}
    result["pause_type"] = "tactical" if tactical else "technical" if result["paused"] else ""
    result["phase"] = round_phase or countdown_phase
    return raw_round


def _gsi_player(steamid, data, roster_profile, public_profile, raw_round, *, managed):
    state = data.get("state", {}) or {}
    weapons = data.get("weapons", {}) or {}
    match_stats = data.get("match_stats", {}) or {}
    # Managed observations may be unknown; old feeds used zero for absent stats.
    default = None if managed else 0
    damage = match_stats.get("damage", default)
    primary = secondary = ""
    for weapon, info in sorted(weapons.items(), key=lambda item: item[0]):
        kind = info.get("type", "")
        if kind in ("Rifle", "SniperRifle", "Machine Gun", "Shotgun", "Submachine Gun"):
            primary = info.get("name") or weapon
        elif kind == "Pistol":
            secondary = info.get("name") or weapon
    return {
        "steamid": steamid,
        "player_id": roster_profile.get("player_id"),
        "roster_slot": roster_profile.get("slot"),
        "is_substitute": bool(roster_profile.get("is_substitute")),
        "name": roster_profile.get("name") or public_profile.get("name") or data.get("name", ""),
        "avatar": roster_profile.get("avatar") or public_profile.get("avatar", ""),
        "hp": state.get("health", 0),
        "armor": state.get("armor", 0),
        "helmet": state.get("helmet", False),
        "money": state.get("money", 0),
        "kills": match_stats.get("kills", default),
        "assists": match_stats.get("assists", default),
        "deaths": match_stats.get("deaths", default),
        "adr": None if managed and damage is None else round(damage / max(raw_round + 1, 1), 1),
        "observer_slot": data.get("observer_slot"),
        "primary": primary,
        "secondary": secondary,
        "alive": state.get("health", 0) > 0,
    }


def _missing_player(steamid, profile, default):
    return {
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
        "kills": default,
        "assists": default,
        "deaths": default,
        "adr": default,
        "observer_slot": None,
        "primary": "",
        "secondary": "",
        "alive": False,
        "missing": True,
    }


def _player_order(item):
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


def _gsi_lineups(gsi, current_sides, roster_profiles, public_profiles, raw_round, *, managed):
    teams: dict[str, list] = {"team1": [], "team2": []}
    seen = set()
    for steamid, data in (gsi.get("allplayers", {}) or {}).items():
        roster_profile = roster_profiles.get(steamid, {})
        # A live frame can still contain observers or a player from a previous session.
        if (managed or roster_profiles) and not roster_profile:
            continue
        side = str(data.get("team") or "")
        if managed and side.upper() not in ("CT", "T"):
            continue
        seen.add(str(steamid))
        entry = _gsi_player(
            steamid,
            data,
            roster_profile,
            public_profiles.get(str(steamid), {}),
            raw_round,
            managed=managed,
        )
        # The lineup fixes the team slot; the current CT/T side can change at half.
        identity = roster_profile.get("team") or current_sides.get(side)
        if identity in teams:
            teams[identity].append(entry)
    for steamid, profile in roster_profiles.items():
        if steamid in seen or not profile.get("name") or (managed and not profile["has_appeared"]):
            continue
        # A planned slot alone does not show that the player appeared in this run.
        teams[profile["team"]].append(_missing_player(steamid, profile, None if managed else 0))
    return [sorted(teams[key], key=_player_order)[:5] for key in ("team1", "team2")]


def apply_gsi_frame(result, row, state, gsi, roster_profiles, public_profiles, *, managed):
    result["updated_at"] = state.get("gsi_received_at") or row["updated_at"]
    game_map = gsi.get("map", {}) or {}
    result["map_name"] = game_map.get("name", "")
    result["mode"] = game_map.get("mode", "")
    result["bomb"] = gsi.get("bomb", {}) or {}
    raw_round = _set_gsi_clock(result, gsi, game_map)

    roster_sides = {steam_id: profile["team"] for steam_id, profile in roster_profiles.items()}
    side_mapping = gsi_team_mapping(gsi, row, roster_sides)
    result["side_uncertain"] = not bool(side_mapping)
    result["side_mapping"] = side_mapping
    result["players_t1"], result["players_t2"] = _gsi_lineups(
        gsi, side_mapping or {}, roster_profiles, public_profiles, raw_round, managed=managed
    )
    identity_side = {identity: side for side, identity in (side_mapping or {}).items()}
    side_data = {"CT": game_map.get("team_ct", {}) or {}, "T": game_map.get("team_t", {}) or {}}
    for slot in (1, 2):
        key = f"team{slot}"
        side = identity_side.get(key)
        stats = side_data[side] if side else {}
        result[key] = {
            "name": row[f"scheduled_team{slot}_name"] or (stats.get("name") if side else "TBD"),
            "score": stats.get("score") if side else None,
            "side": side,
            "timeouts_remaining": stats.get("timeouts_remaining", 0) if side else None,
        }
    if not managed and result["round_history"]:
        result["latest_round_result"] = result["round_history"][-1]


def apply_gotv_frame(conn, result, row, gotv, roster_profiles, *, managed):
    result["updated_at"] = gotv.get("last_push", "") or row["updated_at"]
    result["map_name"] = gotv.get("map_name", "")
    result["round"] = gotv.get("rounds_count", 0)
    profiles = (
        roster_profiles
        if managed
        else _load_live_player_profiles(
            conn,
            [
                player.get("steamid") or player.get("steam_id")
                for player in gotv.get("t1_players", []) + gotv.get("t2_players", [])
            ],
        )
    )
    default = None if managed else 0
    for side in (1, 2):
        key = f"team{side}"
        result[key] = {
            "name": gotv.get(f"{key}_name", "TBD"),
            "score": gotv.get(f"{key}_score", 0),
        }
        entries = result[f"players_t{side}"]
        for player in gotv.get(f"t{side}_players", []):
            steamid = player.get("steamid") or player.get("steam_id", "")
            profile = profiles.get(str(steamid), {})
            if managed and profile.get("team") != key:
                continue
            entry = {
                "steamid": steamid,
                "name": profile.get("name") or player.get("name", ""),
                "hp": "-",
                "armor": "-",
                "money": "-",
                "kills": player.get("kills", default),
                "deaths": player.get("deaths", default),
                "assists": player.get("assists", default),
                "adr": player.get("adr", default),
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
            entries.append(entry)
            if len(entries) == 5:
                break
