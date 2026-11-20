"""Recorded player totals, recent matches and chart samples for public pages."""

from src.website.domains.matches.match_utils import get_sql_match_completed
from src.website.domains.statistics.performance_service import stat_average_sql, weighted_rate_sql
from src.website.domains.statistics.player_history import (
    _player_available_maps,
    _player_side_expr,
    _player_stat_where,
    _recent_matches_with_teams,
)
from src.website.domains.statistics.side_stats import side_metric_sql
from src.website.domains.statistics.stats_storage import stat_map_count_sql, stats_relation


def player_coverage_sql(side="both"):
    kills = side_metric_sql("kills", side)
    adr = side_metric_sql("adr", side)
    rounds = side_metric_sql("rounds_played", side)
    weighted = f"{adr} IS NOT NULL AND {rounds} > 0"
    return f"""COUNT({kills}) AS kills_maps,
               COALESCE(NULLIF(COUNT(CASE WHEN {weighted} THEN 1 END), 0),
                        COUNT(CASE WHEN ms.scheduled_map_id IS NULL THEN {adr} END)) AS adr_maps,
               SUM(CASE WHEN {weighted} THEN {rounds} END) AS adr_rounds"""


def _completed_match_record(conn, source, where, params):
    rows = conn.execute(
        f"""
        SELECT m.id, m.team1_score, m.team2_score,
               MAX(CASE WHEN LOWER(TRIM(ms.match_team_side)) IN ('t1', 't2')
                        THEN LOWER(TRIM(ms.match_team_side))='t1'
                        ELSE ms.team_id=COALESCE(m.team1_id, -1) END) AS on_team1,
               MAX(CASE WHEN LOWER(TRIM(ms.match_team_side)) IN ('t1', 't2')
                        THEN LOWER(TRIM(ms.match_team_side))='t2'
                        ELSE ms.team_id=COALESCE(m.team2_id, -2) END) AS on_team2
        FROM {source} ms
        JOIN matches m ON ms.match_id=m.id
        {where} AND {get_sql_match_completed()}
        GROUP BY m.id
        """,
        params,
    ).fetchall()
    record = {"wins": 0, "losses": 0, "finished": 0}
    for row in rows:
        team1_score = row["team1_score"]
        team2_score = row["team2_score"]
        if team1_score is None or team2_score is None or team1_score == team2_score:
            continue
        on_team1 = bool(row["on_team1"])
        on_team2 = bool(row["on_team2"])
        if on_team1 == on_team2:
            continue
        won = (on_team1 and team1_score > team2_score) or (on_team2 and team2_score > team1_score)
        record["finished"] += 1
        record["wins" if won else "losses"] += 1
    return record


def load_player_page_stats(conn, player_id, filters, *, profile=False, event_filter=""):
    source = stats_relation(conn)
    side = filters["side"]
    expr = _player_side_expr(side)
    where, params = _player_stat_where(player_id, filters)
    if event_filter:
        where += " AND m.event_id=?"
        params.append(event_filter)

    avg_rating = stat_average_sql("rating", side)
    avg_adr = stat_average_sql("adr", side)
    totals = ", ".join(
        f"SUM({value}) AS {f'total_{key}' if key in ('kills', 'deaths', 'assists') else key}"
        for key, value in expr.items()
        if key not in ("rating", "adr")
    )
    overall = conn.execute(
        f"""
        SELECT COUNT(DISTINCT ms.match_id) AS matches, {stat_map_count_sql()} AS maps,
               {player_coverage_sql(side)}, {totals},
               {avg_rating} AS avg_rating, {avg_adr} AS avg_adr,
               {stat_average_sql("kast", side)} AS avg_kast,
               {stat_average_sql("headshot_percentage", side, weight="kills")} AS avg_hs,
               {weighted_rate_sql(expr["kills"], expr["rounds_played"])} AS avg_kpr,
               {weighted_rate_sql(expr["deaths"], expr["rounds_played"])} AS avg_dpr,
               {stat_average_sql("impact", side)} AS avg_impact,
               {stat_average_sql("rating", "t")} AS avg_t_rating,
               {stat_average_sql("rating", "ct")} AS avg_ct_rating,
               {weighted_rate_sql(expr["utility_damage"], expr["rounds_played"])} AS utility_damage_per_round,
               {stat_average_sql("damage_delta_per_round", side)} AS damage_delta_per_round,
               {stat_average_sql("rws_basic", side)} AS rws_basic
        FROM {source} ms
        JOIN matches m ON ms.match_id=m.id
        {where}
        """,
        params,
    ).fetchone()
    recent_rows = conn.execute(
        f"""
        SELECT m.*,
               SUM({expr["kills"]}) AS kills, SUM({expr["deaths"]}) AS deaths,
               SUM({expr["assists"]}) AS assists, {avg_rating} AS rating, {avg_adr} AS adr,
               t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s, e.name AS event_name
        FROM {source} ms
        JOIN matches m ON ms.match_id=m.id
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id
        {where}
        GROUP BY m.id ORDER BY m.match_time DESC LIMIT 10
        """,
        params,
    ).fetchall()

    # The profile charts series averages, while the detailed page charts each map.
    if profile:
        chart_rating, chart_adr = avg_rating, avg_adr
        chart_order = "GROUP BY m.id ORDER BY m.match_time ASC"
    else:
        chart_rating, chart_adr = expr["rating"], expr["adr"]
        chart_order = "ORDER BY m.match_time ASC, ms.legacy_slot ASC"
    chart_rows = conn.execute(
        f"""SELECT m.match_time, {chart_rating} AS rating, {chart_adr} AS adr
            FROM {source} ms JOIN matches m ON ms.match_id=m.id
            {where} {chart_order} LIMIT 30""",
        params,
    ).fetchall()
    result = {
        "overall": overall,
        "recent_matches": _recent_matches_with_teams(recent_rows, conn, player_id),
        "chart_rows": chart_rows,
    }
    if profile:
        alltime = conn.execute(
            """SELECT matches, total_kills, total_deaths, avg_rating, avg_adr, avg_kast, avg_impact
               FROM player_performance_summary WHERE player_id=?""",
            (player_id,),
        ).fetchone()
        result["overall_alltime"] = (
            alltime
            if alltime is not None
            else {
                "matches": 0,
                "total_kills": 0,
                "total_deaths": 0,
                "avg_rating": 0,
                "avg_adr": 0,
                "avg_kast": 0,
                "avg_impact": 0,
            }
        )
        result["match_record"] = _completed_match_record(conn, source, where, params)
    else:
        result["map_options"] = _player_available_maps(conn)
    return result
