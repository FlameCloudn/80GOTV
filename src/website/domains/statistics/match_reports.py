"""战报和海报读取已采纳的统计；旧赛不拿缺失值凑总数。"""

from src.website.domains.statistics.performance_service import stat_average_sql
from src.website.domains.statistics.stats_storage import stats_relation


def poster_ratings(conn, match_id):
    valid_side = (
        "CASE WHEN LOWER(TRIM(ms.match_team_side)) IN ('t1','t2') "
        "THEN LOWER(TRIM(ms.match_team_side)) END"
    )
    return [
        dict(row)
        for row in conn.execute(
            f"""
        SELECT ms.team_id, p.nickname,
               CASE WHEN COUNT(DISTINCT {valid_side})=1 THEN MIN({valid_side}) END AS match_team_side,
               {stat_average_sql("rating")} AS rating
        FROM {stats_relation(conn)} ms
        JOIN players p ON p.id=ms.player_id
        WHERE ms.match_id=?
          AND COALESCE(ms.data_status, 'final') <> 'superseded'
        GROUP BY ms.team_id, p.id
        ORDER BY ms.team_id, rating DESC
    """,
            (match_id,),
        )
    ]


def report_players(conn, match, managed):
    match_id = match["id"]
    source = stats_relation(conn)

    def report_metric(field, aggregate):
        # 往届战报要求每张图都有该项；托管场按已采纳该项的样本计算。
        if managed:
            return aggregate
        return f"CASE WHEN COUNT(ms.{field})=COUNT(*) THEN {aggregate} END"

    overall_rows = [
        dict(row)
        for row in conn.execute(
            f"""
        WITH sided_stats AS (
            SELECT ms.*,
                   CASE WHEN LOWER(TRIM(COALESCE(ms.match_team_side, ''))) IN ('t1', 't2')
                        THEN LOWER(TRIM(ms.match_team_side))
                        WHEN ms.team_id=? THEN 't1'
                        WHEN ms.team_id=? THEN 't2' END AS report_side
            FROM {source} ms
            WHERE ms.match_id=?
              AND COALESCE(ms.data_status, 'final') <> 'superseded'
        )
        SELECT ms.player_id, ms.report_side AS match_team_side, p.nickname, p.avatar,
               {report_metric("kills", "SUM(ms.kills)")} AS kills,
               {report_metric("deaths", "SUM(ms.deaths)")} AS deaths,
               {report_metric("adr", stat_average_sql("adr"))} AS adr,
               {report_metric("kast", stat_average_sql("kast"))} AS kast,
               {report_metric("rating", stat_average_sql("rating"))} AS rating
        FROM sided_stats ms
        JOIN players p ON p.id=ms.player_id
        WHERE ms.report_side IS NOT NULL
        GROUP BY ms.report_side, ms.player_id
        ORDER BY rating DESC
    """,
            (match.get("team1_id"), match.get("team2_id"), match_id),
        ).fetchall()
    ]
    map_rows = [
        dict(row)
        for row in conn.execute(
            f"""
        SELECT ms.player_id, ms.team_id, ms.match_team_side, ms.map_name,
               ms.scheduled_map_id, ms.legacy_slot, p.nickname,
               ms.kills, ms.deaths, ms.adr, ms.kast, ms.rating
        FROM {source} ms
        JOIN players p ON p.id=ms.player_id
        WHERE ms.match_id=?
          AND COALESCE(ms.data_status, 'final') <> 'superseded'
        ORDER BY ms.map_name, ms.rating DESC
    """,
            (match_id,),
        ).fetchall()
    ]
    return overall_rows, map_rows
