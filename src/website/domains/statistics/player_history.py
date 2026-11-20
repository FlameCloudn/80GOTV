"""Select a player's recorded maps, side data and opponents."""

from src.website.domains.matches.map_names import normalize_map_key
from src.website.domains.matches.opponents import supplement_temp_teams
from src.website.domains.statistics.side_stats import side_metric_sql
from src.website.domains.statistics.stat_filters import TIME_FILTER_MAP
from src.website.domains.statistics.stats_display import resolve_match_team_side
from src.website.domains.statistics.stats_storage import stat_map_key_sql, stats_relation


def _player_available_maps(conn):
    rows = conn.execute(f"""
        SELECT DISTINCT map_name
        FROM {stats_relation(conn)}
        WHERE map_name IS NOT NULL AND map_name != ''
          AND COALESCE(data_status, 'final') <> 'superseded'
        ORDER BY map_name
    """).fetchall()
    seen = set()
    maps = []
    for row in rows:
        key = normalize_map_key(row["map_name"])
        if not key or key in seen:
            continue
        seen.add(key)
        maps.append({"value": row["map_name"], "label": row["map_name"]})
    return maps


def _player_stat_where(player_id, filters):
    clauses = ["ms.player_id=?", "COALESCE(ms.data_status, 'final') <> 'superseded'"]
    params = [player_id]
    months = TIME_FILTER_MAP[filters["time"]]["months"]
    if months:
        clauses.append("m.match_time >= datetime('now', ?)")
        params.append(f"-{months} months")
    if filters["map"] != "all":
        clauses.append(f"{stat_map_key_sql()}=?")
        params.append(normalize_map_key(filters["map"]))
    return " WHERE " + " AND ".join(clauses), params


def _player_side_expr(side):
    return {
        key: side_metric_sql(key, side)
        for key in (
            "kills",
            "deaths",
            "assists",
            "rounds_played",
            "rating",
            "adr",
            "multi1k",
            "multi2k",
            "multi3k",
            "multi4k",
            "multi5k",
            "first_kills",
            "first_deaths",
            "trade_kills",
            "trade_deaths",
            "clutches_won",
            "utility_damage",
            "enemies_flashed",
            "bomb_plants",
            "bomb_defuses",
            "flash_count",
        )
    }


def _recent_matches_with_teams(rows, conn, player_id):
    matches = [supplement_temp_teams(row, conn) for row in rows]
    if not matches:
        return matches
    by_id = {match["id"]: match for match in matches}
    placeholders = ",".join("?" for _ in by_id)
    records = conn.execute(
        f"""SELECT match_id, team_id, match_team_side FROM {stats_relation(conn)}
            WHERE player_id=? AND match_id IN ({placeholders})
              AND COALESCE(data_status, 'final') <> 'superseded'""",
        (player_id, *by_id),
    ).fetchall()
    sides = {match_id: set() for match_id in by_id}
    for record in records:
        side = resolve_match_team_side(dict(record), by_id[record["match_id"]])
        if side is not None:
            sides[record["match_id"]].add(side)
    for match in matches:
        known_sides = sides[match["id"]]
        side = next(iter(known_sides)) if len(known_sides) == 1 else None
        match["stat_team_side"] = side
        match["stat_team_id"] = (
            match.get("team1_id")
            if side == "t1"
            else match.get("team2_id")
            if side == "t2"
            else None
        )
    return matches
