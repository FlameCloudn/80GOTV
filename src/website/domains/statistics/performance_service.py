"""Weighted statistic queries and the player performance summary."""

from src.website.domains.statistics.side_stats import side_metric_sql
from src.website.domains.statistics.stats_storage import stat_map_count_sql, stats_relation

SUMMARY_COLUMNS = (
    "player_id",
    "matches",
    "maps",
    "total_kills",
    "total_deaths",
    "total_assists",
    "avg_kills",
    "avg_deaths",
    "avg_assists",
    "avg_rating",
    "avg_adr",
    "avg_kast",
    "avg_hs",
    "avg_kpr",
    "avg_dpr",
    "avg_impact",
    "avg_t_rating",
    "avg_ct_rating",
    "avg_t_adr",
    "avg_ct_adr",
    "rounds_played",
    "multi1k",
    "multi2k",
    "multi3k",
    "multi4k",
    "multi5k",
    "first_kills",
    "first_deaths",
    "mvp_count",
    "clutches_won",
    "clutch_1v1",
    "clutch_1v2",
    "clutch_1v3",
    "clutch_1v4",
    "clutch_1v5",
    "utility_damage",
    "enemies_flashed",
    "flash_count",
    "he_count",
    "smoke_count",
    "molotov_count",
    "flash_blinded_seconds",
    "flash_enemy_seconds",
    "flash_assists",
    "flash_maps",
    "opponent_flash_maps",
    "trade_kills",
    "trade_deaths",
    "bomb_plants",
    "bomb_defuses",
    "avg_utility_damage_per_round",
    "avg_damage_delta_per_round",
    "avg_rws_basic",
    "updated_at",
)


def weighted_average_sql(value_sql, weight_sql, *, unweighted_where="1"):
    """Return a SQL expression for a value weighted by recorded rounds.

    Rating-like fields are emitted per map.  Averaging those map averages
    gives a short map the same influence as a full map, which makes career and
    filtered views disagree.  Keeping the expression here makes every reader
    use the same rule.
    """
    valid = f"COALESCE({weight_sql}, 0) > 0 AND {value_sql} IS NOT NULL"
    weighted = (
        f"SUM(CASE WHEN {valid} THEN {value_sql} * {weight_sql} END) * 1.0 / "
        f"NULLIF(SUM(CASE WHEN {valid} THEN {weight_sql} END), 0)"
    )
    return f"COALESCE({weighted}, AVG(CASE WHEN {unweighted_where} THEN {value_sql} END))"


def stat_average_sql(field, side="both", *, weight="rounds_played", alias="ms"):
    """Average current samples using the metric's own scope and recorded weight."""
    return weighted_average_sql(
        side_metric_sql(field, side, alias),
        side_metric_sql(weight, side, alias),
        unweighted_where=f"{alias}.scheduled_map_id IS NULL",
    )


def weighted_rate_sql(numerator_sql, denominator_sql):
    """Return a SQL expression for totals divided by recorded rounds."""
    valid = f"COALESCE({denominator_sql}, 0) > 0 AND {numerator_sql} IS NOT NULL"
    return (
        f"(SUM(CASE WHEN {valid} THEN {numerator_sql} END) * 1.0 / "
        f"NULLIF(SUM(CASE WHEN {valid} THEN {denominator_sql} END), 0))"
    )


def summary_metric_sql(
    summary_column, raw_column, summary_alias="s", *, stats_source="match_stats"
):
    """旧汇总表不允许 NULL，读取时用原始记录区分未知和真实零值。"""
    coverage = ""
    if summary_column in {"avg_kpr", "avg_dpr"}:
        coverage = "AND available.rounds_played > 0 "
    elif stats_source != "match_stats" and summary_column in {
        "avg_rating",
        "avg_adr",
        "avg_kast",
        "avg_impact",
        "avg_hs",
    }:
        weight = "kills" if summary_column == "avg_hs" else "rounds_played"
        coverage = f"AND (available.scheduled_map_id IS NULL OR available.{weight} > 0) "
    return (
        f"CASE WHEN EXISTS (SELECT 1 FROM {stats_source} available "
        f"WHERE available.player_id={summary_alias}.player_id "
        "AND COALESCE(available.data_status, 'final') <> 'superseded' "
        f"AND available.{raw_column} IS NOT NULL {coverage}) "
        f"THEN {summary_alias}.{summary_column} END"
    )


def refresh_player_performance(conn, player_ids=None):
    """Refresh compact career rows from all current per-map samples."""
    ids = sorted({int(player_id) for player_id in (player_ids or []) if player_id})
    if player_ids is not None and not ids:
        return
    source = stats_relation(conn)
    params = ()
    where_sql = ""
    if ids:
        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            f"DELETE FROM player_performance_summary WHERE player_id IN ({placeholders})",
            tuple(ids),
        )
        where_sql = f"WHERE player_id IN ({placeholders})"
        params = tuple(ids)
    else:
        conn.execute(
            f"""DELETE FROM player_performance_summary
               WHERE player_id NOT IN (
                   SELECT DISTINCT player_id
                   FROM {source}
                   WHERE player_id IS NOT NULL
                     AND COALESCE(data_status, 'final') <> 'superseded'
               )"""
        )
    filter_sql = (
        f"{where_sql} AND player_id IS NOT NULL AND COALESCE(data_status, 'final') <> 'superseded'"
        if where_sql
        else "WHERE player_id IS NOT NULL AND COALESCE(data_status, 'final') <> 'superseded'"
    )

    columns_sql = ",".join(SUMMARY_COLUMNS)
    avg_rating = stat_average_sql("rating")
    avg_adr = stat_average_sql("adr")
    avg_kast = stat_average_sql("kast")
    avg_hs = stat_average_sql("headshot_percentage", weight="kills")
    avg_kpr = weighted_rate_sql("kills", "rounds_played")
    avg_dpr = weighted_rate_sql("deaths", "rounds_played")
    avg_impact = stat_average_sql("impact")
    avg_utility_damage_per_round = weighted_rate_sql("utility_damage", "rounds_played")
    avg_damage_delta_per_round = stat_average_sql("damage_delta_per_round")
    avg_rws_basic = stat_average_sql("rws_basic")
    conn.execute(
        f"""
        INSERT OR REPLACE INTO player_performance_summary({columns_sql})
        SELECT
            player_id,
            COUNT(DISTINCT match_id),
            {stat_map_count_sql()},
            COALESCE(SUM(kills), 0),
            COALESCE(SUM(deaths), 0),
            COALESCE(SUM(assists), 0),
            COALESCE(AVG(kills), 0),
            COALESCE(AVG(deaths), 0),
            COALESCE(AVG(assists), 0),
            COALESCE({avg_rating}, 0),
            COALESCE({avg_adr}, 0),
            COALESCE({avg_kast}, 0),
            COALESCE({avg_hs}, 0),
            COALESCE({avg_kpr}, 0),
            COALESCE({avg_dpr}, 0),
            COALESCE({avg_impact}, 0),
            COALESCE({stat_average_sql("rating", "t")}, 0),
            COALESCE({stat_average_sql("rating", "ct")}, 0),
            COALESCE({stat_average_sql("adr", "t")}, 0),
            COALESCE({stat_average_sql("adr", "ct")}, 0),
            COALESCE(SUM(rounds_played), 0),
            COALESCE(SUM(multi1k), 0),
            COALESCE(SUM(multi2k), 0),
            COALESCE(SUM(multi3k), 0),
            COALESCE(SUM(multi4k), 0),
            COALESCE(SUM(multi5k), 0),
            COALESCE(SUM(first_kills), 0),
            COALESCE(SUM(first_deaths), 0),
            COALESCE(SUM(mvp_count), 0),
            COALESCE(SUM(clutches_won), 0),
            COALESCE(SUM(clutch_1v1), 0),
            COALESCE(SUM(clutch_1v2), 0),
            COALESCE(SUM(clutch_1v3), 0),
            COALESCE(SUM(clutch_1v4), 0),
            COALESCE(SUM(clutch_1v5), 0),
            COALESCE(SUM(utility_damage), 0),
            COALESCE(SUM(enemies_flashed), 0),
            COALESCE(SUM(flash_count), 0),
            COALESCE(SUM(he_count), 0),
            COALESCE(SUM(smoke_count), 0),
            COALESCE(SUM(molotov_count), 0),
            COALESCE(SUM(flash_blinded_seconds), 0),
            COALESCE(SUM(flash_enemy_seconds), 0),
            COALESCE(SUM(flash_assists), 0),
            COALESCE(SUM(CASE WHEN flash_count > 0 THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN flash_enemy_seconds > 0 THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(trade_kills), 0),
            COALESCE(SUM(trade_deaths), 0),
            COALESCE(SUM(bomb_plants), 0),
            COALESCE(SUM(bomb_defuses), 0),
            COALESCE({avg_utility_damage_per_round}, 0),
            COALESCE({avg_damage_delta_per_round}, 0),
            COALESCE({avg_rws_basic}, 0),
            CURRENT_TIMESTAMP
        FROM {source} ms
        {filter_sql}
        GROUP BY player_id
        """,
        params,
    )
