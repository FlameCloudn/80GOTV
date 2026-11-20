"""Player statistics and comparison views for a match."""

import math
from collections import defaultdict

from src.website.domains.statistics.side_stats import aggregate_side_stats, load_side_stats
from src.website.domains.statistics.stats_display import optional_number
from src.website.runtime.database import row_get


def _safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default=0):
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _avg_values(values, digits=2):
    values = [number for value in values if (number := optional_number(value)) is not None]
    if not values:
        return None
    return round(sum(values) / len(values), digits)


def _optional_int(value):
    number = optional_number(value)
    return int(number) if number is not None else None


def _optional_round(value, digits):
    number = optional_number(value)
    return round(number, digits) if number is not None else None


def _sum_known(values):
    known = [value for value in values if value is not None]
    return sum(known) if known else None


def _match_rating_sort_key(row):
    rating = row["rating"]
    return rating is not None, rating if rating is not None else 0


def _rating_bar_width(value, maximum=1.6):
    rating = _safe_float(value)
    if rating <= 0:
        return 0
    return min(100, round((rating / maximum) * 100, 1))


def _apply_rating_scale(rows, minimum=1.6):
    highest = max((optional_number(row.get("rating")) or 0 for row in rows), default=0)
    maximum = max(minimum, math.ceil(highest * 5) / 5)
    for row in rows:
        row["rating_bar"] = _rating_bar_width(row.get("rating"), maximum)
    return {
        "maximum": maximum,
        "average_pct": round(100 / maximum, 4),
        "half_pct": round(50 / maximum, 4),
        "excellent_pct": round(160 / maximum, 4),
    }


def _recorded_side_metrics(row):
    values = {
        f"{side}_{key}": optional_number(row_get(row, f"{side}_{key}"))
        for side in ("t", "ct")
        for key in ("kills", "deaths", "adr", "rating")
    }
    sides = load_side_stats(row_get(row, "side_stats_json"))
    for side, recorded in sides.items():
        for key in ("kills", "deaths", "adr", "rating"):
            values[f"{side}_{key}"] = recorded.get(key)
    # Old imports defaulted every side column to zero even when only totals were recorded.
    if (
        not sides
        and not any(values.values())
        and any(optional_number(row_get(row, key)) for key in ("kills", "deaths", "adr", "rating"))
    ):
        return dict.fromkeys(values)
    return values


def _build_match_player_row(data, team_side, team_short, team_name):
    kills = _optional_int(data.get("kills"))
    deaths = _optional_int(data.get("deaths"))
    assists = _optional_int(data.get("assists"))
    hs_pct = optional_number(data.get("headshot_percentage"))
    first_kills = _optional_int(data.get("first_kills"))
    first_deaths = _optional_int(data.get("first_deaths"))
    rating = optional_number(data.get("rating"))
    multi = [_optional_int(data.get(f"multi{size}k")) for size in range(2, 6)]
    multi_kills = (
        sum(value for value in multi if value is not None)
        if all(value is not None for value in multi)
        else None
    )
    mk_rating = optional_number(data.get("impact"))
    rws = optional_number(data.get("rws", data.get("rws_basic")))
    side_metrics = _recorded_side_metrics(data)
    result = {
        "player_id": data.get("player_id"),
        "nickname": data.get("nickname") or "Unknown",
        "avatar": data.get("avatar"),
        "steam_id": str(data.get("steam_id") or data.get("steamid") or ""),
        "team_side": team_side,
        "team_short": team_short,
        "team_name": team_name,
        "maps": _safe_int(data.get("maps"), 1),
        "kills": kills,
        "deaths": deaths,
        "assists": assists,
        "adr": _optional_round(data.get("adr"), 1),
        "kast": _optional_round(data.get("kast"), 1),
        "rating": _optional_round(rating, 2),
        "impact": _optional_round(data.get("impact"), 2),
        "kpr": _optional_round(data.get("kpr"), 2),
        "dpr": _optional_round(data.get("dpr"), 2),
        "mk_rating": _optional_round(mk_rating, 2),
        "multi_kills": multi_kills,
        "headshot_percentage": _optional_round(hs_pct, 1),
        "headshot_kills": int(round(kills * hs_pct / 100))
        if kills is not None and hs_pct is not None
        else None,
        "first_kills": first_kills,
        "first_deaths": first_deaths,
        "opening_diff": first_kills - first_deaths
        if first_kills is not None and first_deaths is not None
        else None,
        "clutches_won": _optional_int(data.get("clutches_won")),
        "clutch_1v1": _optional_int(data.get("clutch_1v1")),
        "clutch_1v2": _optional_int(data.get("clutch_1v2")),
        "clutch_1v3": _optional_int(data.get("clutch_1v3")),
        "clutch_1v4": _optional_int(data.get("clutch_1v4")),
        "clutch_1v5": _optional_int(data.get("clutch_1v5")),
        "trade_kills": _optional_int(data.get("trade_kills")),
        "trade_deaths": _optional_int(data.get("trade_deaths")),
        "enemies_flashed": _optional_int(data.get("enemies_flashed")),
        "flash_assists": _optional_int(data.get("flash_assists")),
        "utility_damage": _optional_round(data.get("utility_damage"), 1),
        "rounds_played": _optional_int(data.get("rounds_played")),
        "damage_delta_per_round": _optional_round(data.get("damage_delta_per_round"), 2),
        "rws": _optional_round(rws, 2),
        "t_kills": _optional_int(side_metrics["t_kills"]),
        "t_deaths": _optional_int(side_metrics["t_deaths"]),
        "t_adr": _optional_round(side_metrics["t_adr"], 1),
        "t_rating": _optional_round(side_metrics["t_rating"], 2),
        "ct_kills": _optional_int(side_metrics["ct_kills"]),
        "ct_deaths": _optional_int(side_metrics["ct_deaths"]),
        "ct_adr": _optional_round(side_metrics["ct_adr"], 1),
        "ct_rating": _optional_round(side_metrics["ct_rating"], 2),
        "rating_bar": _rating_bar_width(rating),
    }
    view_keys = (
        "kills",
        "deaths",
        "assists",
        "first_kills",
        "first_deaths",
        "opening_diff",
        "maps",
        "kast",
        "clutches_won",
        "headshot_kills",
        "enemies_flashed",
        "flash_assists",
        "trade_deaths",
        "rws",
        "impact",
        "headshot_percentage",
    )
    result["side_views"] = {"overall": {key: result.get(key) for key in view_keys}}
    recorded_sides = load_side_stats(data.get("side_stats_json"))
    for side in ("t", "ct"):
        known = any(
            result[f"{side}_{key}"] is not None for key in ("kills", "deaths", "adr", "rating")
        )
        result["side_views"][side] = {
            "kills": result[f"{side}_kills"],
            "deaths": result[f"{side}_deaths"],
            "maps": data.get(f"{side}_maps", result["maps"] if known else None),
        }
        if side in recorded_sides:
            result["side_views"][side].update(recorded_sides[side])
            values = result["side_views"][side]
            if values.get("maps") is None:
                values["maps"] = int(values.get("rounds") != 0)
            side_first_kills, side_first_deaths = (
                values.get("first_kills"),
                values.get("first_deaths"),
            )
            values["opening_diff"] = (
                side_first_kills - side_first_deaths
                if side_first_kills is not None and side_first_deaths is not None
                else None
            )
    return result


def _display_rows_from_raw(rows, team_side, team_short, team_name):
    result = []
    for row in rows:
        data = dict(row)
        data["maps"] = 1
        result.append(_build_match_player_row(data, team_side, team_short, team_name))
    result.sort(key=_match_rating_sort_key, reverse=True)
    return result


_MATCH_AVERAGES = {
    "adr": 1,
    "kast": 1,
    "rating": 2,
    "impact": 2,
    "kpr": 2,
    "dpr": 2,
    "rws_basic": 2,
    "headshot_percentage": 1,
    "damage_delta_per_round": 2,
}


def _weighted_map_average(entries, digits):
    total_weight = sum(weight for _, weight in entries)
    if total_weight:
        return round(sum(value * weight for value, weight in entries) / total_weight, digits)
    return _avg_values([value for value, _ in entries], digits)


def _aggregate_match_rows(rows, team_side, team_short, team_name):
    grouped = defaultdict(
        lambda: {
            "kills": None,
            "deaths": None,
            "assists": None,
            "first_kills": None,
            "first_deaths": None,
            "clutches_won": None,
            "clutch_1v1": None,
            "clutch_1v2": None,
            "clutch_1v3": None,
            "clutch_1v4": None,
            "clutch_1v5": None,
            "trade_kills": None,
            "trade_deaths": None,
            "enemies_flashed": None,
            "flash_assists": None,
            "side_entries": [],
            "utility_damage": None,
            "rounds_played": None,
            "t_kills": None,
            "t_deaths": None,
            "ct_kills": None,
            "ct_deaths": None,
            "multi2k": None,
            "multi3k": None,
            "multi4k": None,
            "multi5k": None,
            "scheduled_maps": set(),
            "legacy_maps": 0,
            "legacy_side_values": defaultdict(list),
            "averages": defaultdict(list),
            "t_maps": 0,
            "ct_maps": 0,
        }
    )
    for row in rows:
        side_metrics = _recorded_side_metrics(row)
        pid = row["player_id"]
        item = grouped[pid]
        item["player_id"] = pid
        item["nickname"] = row["nickname"]
        item["avatar"] = row_get(row, "avatar")
        item["steam_id"] = row_get(row, "steam_id")
        scheduled_map_id = row_get(row, "scheduled_map_id")
        if scheduled_map_id is None:
            item["legacy_maps"] += 1
            for side in ("t", "ct"):
                for key in ("adr", "rating"):
                    column = f"{side}_{key}"
                    item["legacy_side_values"][column].append(side_metrics[column])
        else:
            item["scheduled_maps"].add(scheduled_map_id)
        item["side_entries"].append(load_side_stats(row_get(row, "side_stats_json")))
        for key in (
            "kills",
            "deaths",
            "assists",
            "first_kills",
            "first_deaths",
            "clutches_won",
            "clutch_1v1",
            "clutch_1v2",
            "clutch_1v3",
            "clutch_1v4",
            "clutch_1v5",
            "trade_kills",
            "trade_deaths",
            "enemies_flashed",
            "flash_assists",
            "rounds_played",
            "t_kills",
            "t_deaths",
            "ct_kills",
            "ct_deaths",
            "multi2k",
            "multi3k",
            "multi4k",
            "multi5k",
        ):
            value = _optional_int(side_metrics[key] if key in side_metrics else row_get(row, key))
            if value is not None:
                item[key] = (item[key] or 0) + value
        utility_damage = optional_number(row_get(row, "utility_damage"))
        if utility_damage is not None:
            item["utility_damage"] = (item["utility_damage"] or 0) + utility_damage
        for key in _MATCH_AVERAGES:
            value = optional_number(row_get(row, key))
            weight_key = "kills" if key == "headshot_percentage" else "rounds_played"
            weight = max(0, _safe_int(row_get(row, weight_key)))
            if value is not None and (weight or scheduled_map_id is None):
                item["averages"][key].append((value, weight))
        for side in ("t", "ct"):
            if any(
                side_metrics[f"{side}_{key}"] is not None
                for key in ("kills", "deaths", "adr", "rating")
            ):
                item[f"{side}_maps"] += 1

    result = []
    for item in grouped.values():
        sides = aggregate_side_stats(item["side_entries"])
        data = {
            "player_id": item.get("player_id"),
            "nickname": item.get("nickname"),
            "avatar": item.get("avatar"),
            "steam_id": item.get("steam_id"),
            "maps": len(item["scheduled_maps"]) + item["legacy_maps"],
            "kills": item["kills"],
            "deaths": item["deaths"],
            "assists": item["assists"],
            "first_kills": item["first_kills"],
            "first_deaths": item["first_deaths"],
            "clutches_won": item["clutches_won"],
            "clutch_1v1": item["clutch_1v1"],
            "clutch_1v2": item["clutch_1v2"],
            "clutch_1v3": item["clutch_1v3"],
            "clutch_1v4": item["clutch_1v4"],
            "clutch_1v5": item["clutch_1v5"],
            "trade_kills": item["trade_kills"],
            "trade_deaths": item["trade_deaths"],
            "enemies_flashed": item["enemies_flashed"],
            "flash_assists": item["flash_assists"],
            "side_stats_json": sides,
            "utility_damage": item["utility_damage"],
            "rounds_played": item["rounds_played"],
            "multi2k": item["multi2k"],
            "multi3k": item["multi3k"],
            "multi4k": item["multi4k"],
            "multi5k": item["multi5k"],
            "t_kills": item["t_kills"],
            "t_deaths": item["t_deaths"],
            "ct_kills": item["ct_kills"],
            "ct_deaths": item["ct_deaths"],
            **{
                key: _weighted_map_average(item["averages"][key], digits)
                for key, digits in _MATCH_AVERAGES.items()
            },
            "t_maps": item["t_maps"] or None,
            "ct_maps": item["ct_maps"] or None,
        }
        # When historical rows have no side round counts, keep their recorded display values.
        for side in ("t", "ct"):
            for key, digits in (("adr", 1), ("rating", 2)):
                if sides.get(side, {}).get(key) is None:
                    column = f"{side}_{key}"
                    value = _avg_values(item["legacy_side_values"][column], digits)
                    if side in sides:
                        sides[side][key] = value
                    else:
                        data[column] = value
        result.append(_build_match_player_row(data, team_side, team_short, team_name))
    result.sort(key=_match_rating_sort_key, reverse=True)
    return result


def _team_summary(rows):
    return {
        "rating": _avg_values([row["rating"] for row in rows], 2),
        "adr": _avg_values([row["adr"] for row in rows], 1),
        "kills": _sum_known(row["kills"] for row in rows),
        "deaths": _sum_known(row["deaths"] for row in rows),
        "assists": _sum_known(row["assists"] for row in rows),
        "first_kills": _sum_known(row["first_kills"] for row in rows),
        "clutches": _sum_known(row["clutches_won"] for row in rows),
    }


def _highlight_rows(players):
    def top_by(key):
        usable = [player for player in players if _safe_float(player.get(key, 0)) > 0]
        return max(usable, key=lambda player: _safe_float(player.get(key, 0))) if usable else None

    highlights = [
        {"label": "最高 Rating", "player": top_by("rating"), "key": "rating", "digits": 2},
        {"label": "最高 ADR", "player": top_by("adr"), "key": "adr", "digits": 1},
        {"label": "最多击杀", "player": top_by("kills"), "key": "kills", "digits": 0},
        {"label": "最多首杀", "player": top_by("first_kills"), "key": "first_kills", "digits": 0},
        {"label": "最多助攻", "player": top_by("assists"), "key": "assists", "digits": 0},
        {"label": "最多残局", "player": top_by("clutches_won"), "key": "clutches_won", "digits": 0},
    ]
    for item in highlights:
        player = item.get("player")
        if not player:
            item["value"] = "-"
            continue
        value = player.get(item["key"], 0)
        item["value"] = (
            f"{_safe_float(value):.{item['digits']}f}" if item["digits"] else str(_safe_int(value))
        )
    return highlights
