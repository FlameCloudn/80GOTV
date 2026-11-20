"""Read comparable players and filtered metrics."""

from src.website.domains.statistics.query_filters import _side_expr, _stats_where
from src.website.domains.statistics.stats_storage import stat_map_count_sql, stats_relation


def _comparison_players(conn):
    return conn.execute(
        """
        SELECT p.id, p.nickname, p.avatar, t.short_name AS team
        FROM player_performance_summary s
        JOIN players p ON s.player_id=p.id
        LEFT JOIN teams t ON p.team_id=t.id
        WHERE s.maps > 0
        ORDER BY p.nickname COLLATE NOCASE
        """
    ).fetchall()


def _comparison_profile(conn, player_id, filters):
    expr = _side_expr(filters["side"])
    where_sql, filter_params = _stats_where(filters, ["ms.player_id = ?"])
    row = conn.execute(
        f"""
        SELECT p.id, p.nickname, p.avatar, t.short_name AS team,
               COUNT(DISTINCT ms.match_id) AS matches,
               {stat_map_count_sql()} AS maps,
               {expr["rounds_played"]} AS rounds,
               {expr["kills"]} AS kills,
               {expr["deaths"]} AS deaths,
               ({expr["kills"]} * 1.0 / NULLIF({expr["deaths"]}, 0)) AS kd,
               {expr["kpr"]} AS kpr,
               {expr["rating"]} AS rating,
               {expr["adr"]} AS adr,
               {expr["kast"]} AS kast,
               {expr["impact"]} AS impact,
               {expr["hs"]} AS hs
        FROM {stats_relation(conn)} ms
        JOIN matches m ON ms.match_id=m.id
        JOIN players p ON ms.player_id=p.id
        LEFT JOIN teams t ON p.team_id=t.id
        {where_sql}
        GROUP BY p.id
        HAVING maps > 0
        """,
        (player_id, *filter_params),
    ).fetchone()
    return dict(row) if row else None
