"""Recorded per-side match details and round-weighted map aggregation."""

import json

from src.website.domains.statistics.stats_display import optional_number

SIDE_COUNTS = (
    "kills",
    "deaths",
    "assists",
    "first_kills",
    "first_deaths",
    "headshot_kills",
    "clutches_won",
    "clutch_1v1",
    "clutch_1v2",
    "clutch_1v3",
    "clutch_1v4",
    "clutch_1v5",
    "trade_deaths",
    "flash_assists",
    "enemies_flashed",
)
SIDE_AVERAGES = {"adr": 1, "kast": 1, "rws": 2, "impact": 2, "rating": 2}


def side_metric_sql(field, side, alias="ms"):
    """Read known side values, never treating a legacy default as measured zero."""
    if side == "both":
        return f"{alias}.{field}"
    payload = f"(CASE WHEN json_valid({alias}.side_stats_json) THEN {alias}.side_stats_json END)"
    path_field = {"rounds_played": "rounds", "rws_basic": "rws"}.get(field, field)
    value = f"json_extract({payload}, '$.{side}.{path_field}')"
    if field in ("kills", "deaths", "adr", "rating"):
        return (
            f"CASE WHEN json_type({payload}, '$.{side}')='object' THEN {value} "
            f"ELSE NULLIF({alias}.{side}_{field}, 0) END"
        )
    return value


def load_side_stats(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return {}
    if not isinstance(value, dict):
        return {}
    result = {}
    for side in ("t", "ct"):
        record = value.get(side)
        if not isinstance(record, dict):
            continue
        known = {
            key: optional_number(record.get(key))
            for key in (*SIDE_COUNTS, *SIDE_AVERAGES, "rounds", "maps", "headshot_percentage")
        }
        if any(item is not None for item in known.values()):
            result[side] = known
    return result


def aggregate_side_stats(records):
    result = {}
    for side in ("t", "ct"):
        entries = [record[side] for record in records if side in record]
        if not entries:
            continue
        played = [item for item in entries if item.get("rounds") != 0]
        known_rounds = [item["rounds"] for item in entries if item.get("rounds") is not None]
        combined: dict[str, float | int | None] = {
            "rounds": sum(known_rounds) if known_rounds else None,
            "maps": len(played),
        }
        for key in SIDE_COUNTS:
            values = [entry[key] for entry in entries if entry.get(key) is not None]
            combined[key] = sum(values) if values else None
        for key, digits in SIDE_AVERAGES.items():
            valid = [
                entry
                for entry in entries
                if entry.get(key) is not None and (entry.get("rounds") or 0) > 0
            ]
            rounds = sum(entry["rounds"] for entry in valid)
            combined[key] = (
                round(sum(entry[key] * entry["rounds"] for entry in valid) / rounds, digits)
                if rounds
                else None
            )
        valid_hs = [
            entry
            for entry in entries
            if (entry.get("kills") or 0) > 0
            and (
                entry.get("headshot_kills") is not None
                or entry.get("headshot_percentage") is not None
            )
        ]
        headshots = sum(
            entry["headshot_kills"]
            if entry.get("headshot_kills") is not None
            else entry["headshot_percentage"] * entry["kills"] / 100
            for entry in valid_hs
        )
        combined["headshot_percentage"] = (
            round(headshots / sum(entry["kills"] for entry in valid_hs) * 100, 1)
            if valid_hs
            else None
        )
        result[side] = combined
    return result
