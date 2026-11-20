"""Weighted rankings and the public performance overview."""

from collections import Counter
from functools import partial

from src.website.domains.awards.champion_service import championship_teams_relation
from src.website.domains.events.arg_event_service import ordinary_event_condition
from src.website.domains.statistics.performance_service import stat_average_sql, summary_metric_sql
from src.website.domains.statistics.public_stat_evidence import weapon_counts
from src.website.domains.statistics.query_filters import _is_unfiltered, _side_expr, _stats_where
from src.website.domains.statistics.side_stats import side_metric_sql
from src.website.domains.statistics.stat_filters import TIME_FILTER_MAP
from src.website.domains.statistics.stats_storage import stat_map_count_sql, stats_relation


def _player_rankings(conn, filters, order="rating", limit=50):
    source = stats_relation(conn)
    if _is_unfiltered(filters):
        metric = partial(summary_metric_sql, stats_source=source)
        kills = metric("total_kills", "kills")
        deaths = metric("total_deaths", "deaths")
        first_kills = metric("first_kills", "first_kills")
        first_deaths = metric("first_deaths", "first_deaths")
        order_sql = {
            "rating": "rating IS NULL, rating DESC, s.maps DESC, p.nickname ASC",
            "kd": "kd IS NULL, kd DESC, rating DESC, p.nickname ASC",
            "adr": "adr IS NULL, adr DESC, rating DESC, p.nickname ASC",
            "maps": "s.maps DESC, rating DESC, p.nickname ASC",
            "pistol": "first_kills IS NULL, first_kills DESC, opening_success DESC, rating DESC",
        }.get(order, "rating IS NULL, rating DESC, s.maps DESC")
        return conn.execute(
            f"""
            SELECT p.nickname, p.id, p.avatar, t.short_name AS team,
                   {metric("avg_rating", "rating")} AS rating,
                   {kills} AS kills,
                   {deaths} AS deaths,
                   {metric("rounds_played", "rounds_played")} AS rounds,
                   ({kills}) - ({deaths}) AS kd_diff,
                   (({kills}) * 1.0 / NULLIF(({deaths}), 0)) AS kd,
                   {metric("avg_adr", "adr")} AS adr,
                   {metric("avg_kast", "kast")} AS kast,
                   {metric("avg_impact", "impact")} AS impact,
                   {metric("avg_hs", "headshot_percentage")} AS hs,
                   {metric("clutches_won", "clutches_won")} AS clutch,
                   {first_kills} AS first_kills,
                   {first_deaths} AS first_deaths,
                   (({first_kills}) * 1.0 /
                    NULLIF(({first_kills}) + ({first_deaths}), 0)) AS opening_success,
                   s.maps
            FROM player_performance_summary s
            JOIN players p ON s.player_id=p.id
            LEFT JOIN teams t ON p.team_id=t.id
            WHERE s.maps > 0
            ORDER BY {order_sql}
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    expr = _side_expr(filters["side"])
    where_sql, params = _stats_where(filters)
    order_sql = {
        "rating": "rating IS NULL, rating DESC, maps DESC, p.nickname ASC",
        "kd": "kd IS NULL, kd DESC, rating DESC, p.nickname ASC",
        "adr": "adr IS NULL, adr DESC, rating DESC, p.nickname ASC",
        "maps": "maps DESC, rating DESC, p.nickname ASC",
        "pistol": "first_kills DESC, opening_success DESC, rating DESC",
    }.get(order, "rating IS NULL, rating DESC")
    return conn.execute(
        f"""
        SELECT p.nickname, p.id, p.avatar, t.short_name AS team,
               {expr["rating"]} AS rating,
               {expr["kills"]} AS kills,
               {expr["deaths"]} AS deaths,
               {expr["rounds_played"]} AS rounds,
               {expr["kills"]} - {expr["deaths"]} AS kd_diff,
               ({expr["kills"]} * 1.0 / NULLIF({expr["deaths"]}, 0)) AS kd,
               {expr["adr"]} AS adr,
               {expr["kast"]} AS kast,
               {expr["impact"]} AS impact,
               {expr["hs"]} AS hs,
               {expr["clutches_won"]} AS clutch,
               {expr["first_kills"]} AS first_kills,
               {expr["first_deaths"]} AS first_deaths,
               ({expr["first_kills"]} * 1.0 /
                NULLIF({expr["first_kills"]} + {expr["first_deaths"]}, 0)) AS opening_success,
               {stat_map_count_sql()} AS maps
        FROM {source} ms
        JOIN players p ON ms.player_id=p.id
        LEFT JOIN teams t ON p.team_id=t.id
        JOIN matches m ON ms.match_id=m.id
        {where_sql}
        GROUP BY p.id
        ORDER BY {order_sql}
        LIMIT ?
    """,
        (*params, limit),
    ).fetchall()


_FLASH_RECORDED_SQL = "(ms.flash_count_recorded = 1 OR ms.flash_count > 0)"


def _flash_rankings(conn, filters, limit=50):
    """闪光弹榜：投掷和成功率只按有投掷记录的地图计算，全部缺失时返回 None（页面显示“暂无数据”）。"""
    where_sql, params = _stats_where(filters)
    side = filters["side"]
    thrown, blinded, opponent, assists, rounds = (
        side_metric_sql(field, side)
        for field in (
            "flash_count",
            "flash_blinded_seconds",
            "flash_enemy_seconds",
            "flash_assists",
            "rounds_played",
        )
    )
    recorded = _FLASH_RECORDED_SQL if side == "both" else f"{thrown} IS NOT NULL"
    return conn.execute(
        f"""
        SELECT p.nickname, p.id, p.avatar,
               {stat_map_count_sql()} AS maps,
               SUM({rounds}) AS rounds,
               AVG(CASE WHEN {recorded} THEN {thrown} END) AS thrown,
               AVG({blinded}) AS blinded,
               AVG({opponent}) AS opp_flashed,
               AVG(({opponent}) - ({blinded})) AS diff,
               AVG({assists}) AS fa,
               (SUM(CASE WHEN {recorded} AND {thrown} > 0
                         AND {opponent} > 0 THEN 1 ELSE 0 END) * 1.0 /
                NULLIF(SUM(CASE WHEN {recorded} AND {thrown} > 0
                                THEN 1 ELSE 0 END), 0)) AS success
        FROM {stats_relation(conn)} ms
        JOIN players p ON ms.player_id=p.id
        JOIN matches m ON ms.match_id=m.id
        {where_sql}
        GROUP BY p.id
        HAVING maps > 0
        ORDER BY success IS NULL, success DESC, diff DESC, maps DESC
        LIMIT ?
    """,
        (*params, limit),
    ).fetchall()


def _top_teams(conn, filters, limit=8):
    expr = _side_expr(filters["side"])
    # Temporary match-side teams use negative IDs and are not real team records.
    where_sql, params = _stats_where(filters, ["ms.team_id > 0"])
    return conn.execute(
        f"""
        SELECT
               MIN(CASE WHEN ms.team_id > 0 THEN t.id END) AS id,
               CASE
                 WHEN ms.team_id = -1 THEN COALESCE(t1.name, t1.short_name, 'TBD')
                 WHEN ms.team_id = -2 THEN COALESCE(t2.name, t2.short_name, 'TBD')
                 ELSE COALESCE(t.name, 'Team')
               END AS name,
               CASE
                 WHEN ms.team_id = -1 THEN COALESCE(t1.short_name, t1.name, 'T1')
                 WHEN ms.team_id = -2 THEN COALESCE(t2.short_name, t2.name, 'T2')
                 ELSE COALESCE(t.short_name, t.name, 'Team')
               END AS short_name,
               MIN(t.logo) AS logo,
               CASE WHEN ms.team_id > 0 THEN 0 ELSE 1 END AS is_temp,
               {expr["rating"]} AS rating,
               {stat_map_count_sql(per_player=False)} AS maps
        FROM {stats_relation(conn)} ms
        JOIN matches m ON ms.match_id=m.id
        LEFT JOIN teams t ON ms.team_id=t.id
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        {where_sql}
        GROUP BY CASE
                   WHEN ms.team_id > 0 THEN 'team:' || ms.team_id
                   ELSE 'match:' || ms.match_id || ':side:' || ms.team_id
                 END
        ORDER BY rating IS NULL, rating DESC, maps DESC, t.name ASC
        LIMIT ?
    """,
        (*params, limit),
    ).fetchall()


def _top_events(conn, filters, limit=20):
    """冠军赛事排名：按赛事维度展示冠军队伍/选手和比赛数。"""
    where_sql, params = _stats_where(filters)
    return conn.execute(
        f"""
        SELECT e.id, e.name, e.slug, e.status, e.start_date, e.end_date,
               COUNT(DISTINCT m.id) AS matches,
               {stat_map_count_sql(per_player=False)} AS maps,
               GROUP_CONCAT(DISTINCT COALESCE(c.team_short, c.team_name)) AS champion_teams,
               GROUP_CONCAT(DISTINCT c.team_id) AS champion_team_ids
        FROM events e
        JOIN matches m ON m.event_id=e.id
        JOIN {stats_relation(conn)} ms ON ms.match_id=m.id
        LEFT JOIN {championship_teams_relation(conn)} c ON c.event_id=e.id
        {where_sql}
        GROUP BY e.id
        ORDER BY matches DESC, e.start_date DESC, e.name ASC
        LIMIT ?
    """,
        (*params, limit),
    ).fetchall()


def _format_top_weapons(weapon_counter):
    weapon_names = {
        "ak47": "ak47",
        "m4a1_silencer": "m4a1_silencer",
        "m4a1": "m4a1",
        "awp": "awp",
        "usp_silencer": "usp_silencer",
        "hkp2000": "p2000",
        "glock": "glock",
        "galilar": "galilar",
        "famas": "famas",
        "deagle": "deagle",
        "mac10": "mac10",
        "mp9": "mp9",
        "mp7": "mp7",
        "ssg08": "ssg08",
        "aug": "aug",
        "sg556": "sg556",
    }
    weapon_colors = [
        "#2f76b7",
        "#338f98",
        "#2e9b73",
        "#9baa3f",
        "#b7a22f",
        "#c88324",
        "#d46a1f",
        "#bf4a2c",
        "#6f7d8c",
        "#9a7bc2",
    ]
    top_weapon_pairs = weapon_counter.most_common(9)
    other_weapon_count = sum(weapon_counter.values()) - sum(v for _, v in top_weapon_pairs)
    if other_weapon_count > 0:
        top_weapon_pairs.append(("other", other_weapon_count))
    total_weapon_kills = sum(v for _, v in top_weapon_pairs)
    cursor = 0
    weapons = []
    for idx, (weapon, count) in enumerate(top_weapon_pairs):
        pct = (count / total_weapon_kills * 100) if total_weapon_kills else 0
        start = cursor
        cursor += pct
        weapons.append(
            {
                "name": weapon_names.get(weapon, weapon),
                "count": count,
                "pct": pct,
                "start": start,
                "end": cursor,
                "color": weapon_colors[idx % len(weapon_colors)],
            }
        )
    return weapons


def _top_weapons(conn, filters):
    weapon_counter = Counter()
    rows = weapon_counts(conn, filters, TIME_FILTER_MAP[filters["time"]]["months"])
    for row in rows:
        weapon = str(row["weapon"] or "").strip().lower().removeprefix("weapon_")
        weapon = weapon.replace("-", "").replace(" ", "_")
        weapon = {
            "usps": "usp_silencer",
            "m4a1s": "m4a1_silencer",
        }.get(weapon, weapon)
        if weapon and weapon not in {"world", "worldent"}:
            weapon_counter[weapon] += int(row["kills"] or 0)
    return _format_top_weapons(weapon_counter)


def _overview_context(conn, filters):
    source = stats_relation(conn)
    totals = conn.execute(f"""
        SELECT COUNT(*) AS total_stats, {stat_average_sql("rating")} AS avg_rating,
               {stat_average_sql("adr")} AS avg_adr
        FROM {source} ms WHERE COALESCE(ms.data_status, 'final') <> 'superseded'
    """).fetchone()
    overview = {
        **dict(totals),
        "total_players": conn.execute("SELECT COUNT(*) AS cnt FROM players").fetchone()["cnt"],
        "total_teams": conn.execute("SELECT COUNT(*) AS cnt FROM teams").fetchone()["cnt"],
        "total_events": conn.execute(
            f"SELECT COUNT(*) AS cnt FROM events WHERE {ordinary_event_condition()}"
        ).fetchone()["cnt"],
        "total_matches": conn.execute(
            "SELECT COUNT(*) AS cnt FROM matches WHERE team1_score IS NOT NULL"
        ).fetchone()["cnt"],
    }
    overview["top_player"] = conn.execute(f"""
        SELECT p.nickname, p.id,
               {summary_metric_sql("avg_rating", "rating", stats_source=source)} AS r, s.maps AS m
        FROM player_performance_summary s
        JOIN players p ON s.player_id=p.id
        WHERE s.maps >= 5
        ORDER BY r IS NULL, r DESC, s.maps DESC
        LIMIT 1
    """).fetchone()
    overview["top_team"] = conn.execute("""
        SELECT t.name, t.short_name, t.id, COUNT(m.id) AS cnt,
               SUM(CASE WHEN (m.team1_id=t.id AND m.team1_score>m.team2_score)
                         OR (m.team2_id=t.id AND m.team2_score>m.team1_score) THEN 1 ELSE 0 END) AS wins
        FROM teams t
        JOIN matches m ON (m.team1_id=t.id OR m.team2_id=t.id)
        WHERE m.team1_score IS NOT NULL
        GROUP BY t.id HAVING cnt >= 3 ORDER BY (wins*1.0/cnt) DESC LIMIT 1
    """).fetchone()
    overview["recent_matches"] = conn.execute("""
        SELECT m.*, t1.short_name AS t1s, t2.short_name AS t2s,
               COALESCE(t1.name,'TBD') AS t1n, COALESCE(t2.name,'TBD') AS t2n,
               e.name AS event_name
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id
        WHERE m.team1_score IS NOT NULL
        ORDER BY m.match_time DESC LIMIT 8
    """).fetchall()
    overview["top_players"] = _player_rankings(conn, filters, "rating", 8)
    overview["top_teams"] = _top_teams(conn, filters, 8)
    overview["top_events"] = _top_events(conn, filters, 5)
    overview["top_weapons"] = _top_weapons(conn, filters)
    return overview
