"""Historical kill events and per-player matchups for the detailed match view."""

from collections import defaultdict

from .match_view import _safe_int


def _identity_key(value):
    return str(value or "").strip().casefold()


def _load_persisted_kill_events(conn, match_id):
    """Load compact kill rows saved during Demo import."""
    rows = conn.execute(
        """
        SELECT match_id, map_name, round_number, tick,
               killer_player_id, victim_player_id, assister_player_id,
               killer_steam_id, victim_steam_id, assister_steam_id,
               killer_name, victim_name, assister_name,
               killer_side, victim_side, assister_side,
               weapon, headshot
        FROM match_kill_events
        WHERE match_id=?
        ORDER BY map_name, round_number, tick, id
        """,
        (match_id,),
    ).fetchall()
    return [
        {
            "map_name": row["map_name"],
            "round_number": row["round_number"],
            "tick": row["tick"],
            "killer_player_id": row["killer_player_id"],
            "victim_player_id": row["victim_player_id"],
            "assister_player_id": row["assister_player_id"],
            "killer_steamid": row["killer_steam_id"],
            "victim_steamid": row["victim_steam_id"],
            "assister_steamid": row["assister_steam_id"],
            "killer": row["killer_name"],
            "victim": row["victim_name"],
            "assister": row["assister_name"],
            "killer_side": row["killer_side"],
            "victim_side": row["victim_side"],
            "assister_side": row["assister_side"],
            "weapon": row["weapon"],
            "headshot": bool(row["headshot"]),
        }
        for row in rows
    ]


def _build_player_alias_map(conn, player_ids):
    if not player_ids:
        return {}
    placeholders = ",".join("?" for _ in player_ids)
    rows = conn.execute(
        f"SELECT player_id, nickname FROM player_nickname_history WHERE player_id IN ({placeholders})",
        tuple(player_ids),
    ).fetchall()
    aliases = defaultdict(set)
    for row in rows:
        aliases[row["player_id"]].add(row["nickname"])
    return aliases


def _build_player_lookup(team1_rows, team2_rows, aliases):
    lookup = {}
    for row in team1_rows + team2_rows:
        pid = row["player_id"]
        if row.get("steam_id"):
            lookup[f"steam:{row['steam_id']}"] = pid
        names = {row.get("nickname") or ""}
        names.update(aliases.get(pid, set()))
        for name in names:
            key = _identity_key(name)
            if key:
                lookup[f"name:{key}"] = pid
    return lookup


def _event_player_id(lookup, steamid="", name=""):
    steam_key = f"steam:{steamid}" if steamid else ""
    if steam_key and steam_key in lookup:
        return lookup[steam_key]
    name_key = f"name:{_identity_key(name)}" if name else ""
    return lookup.get(name_key)


def _add_demo_stat_aliases(lookup, rows, kill_events):
    demo_stats = {}

    def key_for(steamid, name):
        steamid = str(steamid or "").strip()
        name = str(name or "").strip()
        if steamid:
            return f"steam:{steamid}", steamid, name
        name_key = _identity_key(name)
        return (f"name:{name_key}", "", name) if name_key else ("", "", "")

    for event in kill_events or []:
        killer_key, killer_steamid, killer_name = key_for(
            event.get("killer_steamid"), event.get("killer")
        )
        if killer_key:
            item = demo_stats.setdefault(
                killer_key,
                {
                    "steamid": killer_steamid,
                    "name": killer_name,
                    "kills": 0,
                    "deaths": 0,
                },
            )
            item["kills"] += 1
            if killer_name:
                item["name"] = killer_name
        victim_key, victim_steamid, victim_name = key_for(
            event.get("victim_steamid"), event.get("victim")
        )
        if victim_key:
            item = demo_stats.setdefault(
                victim_key,
                {
                    "steamid": victim_steamid,
                    "name": victim_name,
                    "kills": 0,
                    "deaths": 0,
                },
            )
            item["deaths"] += 1
            if victim_name:
                item["name"] = victim_name

    for item in demo_stats.values():
        if _event_player_id(lookup, item.get("steamid"), item.get("name")):
            continue
        scored = []
        for row in rows:
            if row.get("kills") is None or row.get("deaths") is None:
                continue
            score = abs(_safe_int(row.get("kills")) - item["kills"]) + abs(
                _safe_int(row.get("deaths")) - item["deaths"]
            )
            scored.append((score, row["player_id"]))
        scored.sort()
        if not scored:
            continue
        best_score, best_pid = scored[0]
        next_score = scored[1][0] if len(scored) > 1 else best_score + 99
        total_duels = item["kills"] + item["deaths"]
        limit = 4 if total_duels >= 40 else 2
        if best_score <= limit and best_score < next_score:
            if item.get("steamid"):
                lookup[f"steam:{item['steamid']}"] = best_pid
            name_key = _identity_key(item.get("name"))
            if name_key:
                lookup[f"name:{name_key}"] = best_pid


def _build_kill_matrix(team1_rows, team2_rows, aliases, kill_events):
    lookup = _build_player_lookup(team1_rows, team2_rows, aliases)
    _add_demo_stat_aliases(lookup, team1_rows + team2_rows, kill_events)
    team1_ids = {row["player_id"] for row in team1_rows}
    team2_ids = {row["player_id"] for row in team2_rows}

    def empty_matrix():
        return {
            t1["player_id"]: {t2["player_id"]: {"t1": 0, "t2": 0} for t2 in team2_rows}
            for t1 in team1_rows
        }

    def add_to_matrix(matrix, duel):
        matrix[duel["row_id"]][duel["col_id"]][duel["side"]] += 1

    def is_awp_kill(event):
        weapon = str(event.get("weapon") or "").strip().lower()
        weapon = weapon.removeprefix("weapon_")
        return weapon == "awp"

    matrices = {
        "all": empty_matrix(),
        "first": empty_matrix(),
        "awp": empty_matrix(),
    }
    total_events = 0
    matched_counts = {"all": 0, "first": 0, "awp": 0}
    duels_by_round = defaultdict(list)

    for event in kill_events:
        total_events += 1
        killer_id = event.get("killer_player_id") or _event_player_id(
            lookup, event.get("killer_steamid"), event.get("killer")
        )
        victim_id = event.get("victim_player_id") or _event_player_id(
            lookup, event.get("victim_steamid"), event.get("victim")
        )
        if not killer_id or not victim_id or killer_id == victim_id:
            continue
        if killer_id in team1_ids and victim_id in team2_ids:
            duel = {
                "row_id": killer_id,
                "col_id": victim_id,
                "side": "t1",
                "tick": _safe_int(event.get("tick")),
                "round_key": (
                    event.get("map_slot", 0),
                    _safe_int(event.get("round_number") or event.get("round")),
                ),
                "event": event,
            }
        elif killer_id in team2_ids and victim_id in team1_ids:
            duel = {
                "row_id": victim_id,
                "col_id": killer_id,
                "side": "t2",
                "tick": _safe_int(event.get("tick")),
                "round_key": (
                    event.get("map_slot", 0),
                    _safe_int(event.get("round_number") or event.get("round")),
                ),
                "event": event,
            }
        else:
            continue

        add_to_matrix(matrices["all"], duel)
        matched_counts["all"] += 1
        if is_awp_kill(event):
            add_to_matrix(matrices["awp"], duel)
            matched_counts["awp"] += 1
        if duel["round_key"][1] > 0:
            duels_by_round[duel["round_key"]].append(duel)

    for round_duels in duels_by_round.values():
        round_duels.sort(key=lambda item: item["tick"])
        if not round_duels:
            continue
        add_to_matrix(matrices["first"], round_duels[0])
        matched_counts["first"] += 1

    modes = [
        {
            "id": "all",
            "label": "全部",
            "cells": matrices["all"],
            "matched_events": matched_counts["all"],
        },
        {
            "id": "first",
            "label": "首杀",
            "cells": matrices["first"],
            "matched_events": matched_counts["first"],
        },
        {
            "id": "awp",
            "label": "AWP 击杀",
            "cells": matrices["awp"],
            "matched_events": matched_counts["awp"],
        },
    ]

    return {
        "rows": team1_rows,
        "cols": team2_rows,
        "cells": matrices["all"],
        "modes": modes,
        "total_events": total_events,
        "matched_events": matched_counts["all"],
    }
