"""Apply the same site-statistic filters to rows, sides, and matches."""

from src.website.domains.events.arg_event_service import ordinary_event_condition
from src.website.domains.matches.map_names import normalize_map_key
from src.website.domains.statistics.performance_service import stat_average_sql, weighted_rate_sql
from src.website.domains.statistics.side_stats import side_metric_sql
from src.website.domains.statistics.stat_filters import TIME_FILTER_MAP
from src.website.domains.statistics.stats_storage import stat_map_key_sql, stats_relation


def _is_unfiltered(filters):
    return (
        filters["time"] == "all"
        and filters["map"] == "all"
        and filters["side"] == "both"
        and filters.get("event") is None
    )


def _stats_where(filters, extra=None):
    clauses = ["COALESCE(ms.data_status, 'final') <> 'superseded'"]
    clauses.extend(extra or [])
    params = []
    months = TIME_FILTER_MAP[filters["time"]]["months"]
    if months:
        clauses.append("m.match_time >= datetime('now', ?)")
        params.append(f"-{months} months")
    if filters["map"] != "all":
        clauses.append(f"{stat_map_key_sql()} = ?")
        params.append(normalize_map_key(filters["map"]))
    if filters.get("event") is not None:
        clauses.append("m.event_id = ?")
        params.append(filters["event"])
    if not clauses:
        return "", params
    return " WHERE " + " AND ".join(clauses), params


def _match_where(filters, extra=None):
    clauses = list(extra or [])
    params = []
    months = TIME_FILTER_MAP[filters["time"]]["months"]
    if months:
        clauses.append("m.match_time >= datetime('now', ?)")
        params.append(f"-{months} months")
    if filters.get("event") is not None:
        clauses.append("m.event_id = ?")
        params.append(filters["event"])
    if not clauses:
        return "", params
    return " WHERE " + " AND ".join(clauses), params


def _side_expr(side):
    return {
        **{
            key: f"SUM({side_metric_sql(key, side)})"
            for key in (
                "kills",
                "deaths",
                "rounds_played",
                "clutches_won",
                "first_kills",
                "first_deaths",
            )
        },
        **{key: stat_average_sql(key, side) for key in ("rating", "adr", "kast", "impact")},
        "hs": stat_average_sql("headshot_percentage", side, weight="kills"),
        "kpr": weighted_rate_sql(
            side_metric_sql("kills", side), side_metric_sql("rounds_played", side)
        ),
    }


def _available_maps(conn):
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
        name = row["map_name"]
        key = normalize_map_key(name)
        if not key or key in seen:
            continue
        seen.add(key)
        maps.append({"value": name, "label": name})
    return maps


def _available_events(conn):
    return conn.execute(
        f"""
        SELECT DISTINCT e.id, e.name, e.start_date
        FROM events e
        JOIN matches m ON m.event_id=e.id
        JOIN {stats_relation(conn)} ms ON ms.match_id=m.id
        WHERE COALESCE(ms.data_status, 'final') <> 'superseded'
          AND {ordinary_event_condition("e")}
        ORDER BY COALESCE(e.start_date, '') DESC, e.name ASC
        """
    ).fetchall()
