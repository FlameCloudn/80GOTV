"""Read models shared by public JSON lists; no state changes on reads."""

from functools import partial

from src.website.domains.directory.player_directory import ACCOUNT_JOIN, IDENTITY_FIELDS
from src.website.domains.matches.match_utils import (
    get_sql_effective_status,
    get_sql_match_completed,
    get_sql_match_live,
    get_sql_match_upcoming,
)
from src.website.domains.matches.opponents import supplement_temp_teams
from src.website.domains.statistics.performance_service import stat_average_sql, summary_metric_sql
from src.website.domains.statistics.player_page_stats import player_coverage_sql
from src.website.domains.statistics.stats_storage import (
    stat_map_count_sql,
    stat_map_key_sql,
    stats_relation,
)


def load_match_page(conn, *, status, event, date, month, limit, offset):
    completed = status == "completed"
    status_sql = (
        get_sql_match_completed()
        if completed
        else (f"({get_sql_match_live()} OR {get_sql_match_upcoming()})")
    )
    clauses, params = [status_sql], []
    for value, clause in (
        (event, "m.event_id=?"),
        (date, "substr(COALESCE(m.match_time, ''), 1, 10)=?"),
        (month, "substr(COALESCE(m.match_time, ''), 1, 7)=?"),
    ):
        if value:
            clauses.append(clause)
            params.append(value)
    where = " AND ".join(clauses)
    total = conn.execute(f"SELECT COUNT(*) FROM matches m WHERE {where}", params).fetchone()[0]
    order = (
        "m.match_time DESC, m.id DESC"
        if completed
        else (
            "CASE WHEN effective_status='live' THEN 0 ELSE 1 END, "
            "CASE WHEN m.match_time IS NULL OR m.match_time='' THEN 1 ELSE 0 END, "
            "m.match_time, m.id"
        )
    )
    rows = conn.execute(
        f"""SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
                   t1.short_name AS t1s, t2.short_name AS t2s,
                   t1.logo AS team1_logo, t2.logo AS team2_logo,
                   e.name AS event_name, {get_sql_effective_status()}
            FROM matches m
            LEFT JOIN teams t1 ON m.team1_id=t1.id
            LEFT JOIN teams t2 ON m.team2_id=t2.id
            LEFT JOIN events e ON m.event_id=e.id
            WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?""",
        (*params, limit, offset),
    ).fetchall()
    return [supplement_temp_teams(row, conn) for row in rows], total


def load_player_page(conn, *, team, filter_key, initial, limit, offset):
    metric = partial(summary_metric_sql, stats_source=stats_relation(conn))
    clauses, params = [], []
    if team:
        clauses.append("p.team_id=?")
        params.append(team)
    if filter_key in {"mvps", "evps"}:
        clauses.append(
            "EXISTS (SELECT 1 FROM player_medals pm WHERE pm.player_id=p.id AND pm.type=?)"
        )
        params.append("MVP" if filter_key == "mvps" else "EVP")
    elif filter_key == "top10":
        clauses.append("s.maps>0")
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    order = "rating IS NULL, rating DESC, nickname, id"
    rank_limit = "LIMIT 10" if filter_key == "top10" else ""
    # The HTML list chooses its top ten before applying the alphabetical filter.
    query = f"""WITH ranked AS (
            SELECT p.*, t.name AS team_name, t.short_name AS team,
                   {IDENTITY_FIELDS},
                   COALESCE(s.maps, 0) AS maps,
                   {metric("avg_rating", "rating")} AS rating,
                   {metric("total_kills", "kills")} AS kills,
                   {metric("total_deaths", "deaths")} AS deaths,
                   {metric("total_assists", "assists")} AS assists,
                   {metric("avg_adr", "adr")} AS adr,
                   {metric("avg_hs", "headshot_percentage")} AS hs
            FROM players p {ACCOUNT_JOIN}
            LEFT JOIN teams t ON p.team_id=t.id
            LEFT JOIN player_performance_summary s ON s.player_id=p.id
            {where} ORDER BY {order} {rank_limit}
        )"""
    first = "substr(trim(nickname), 1, 1)"
    initial_where = ""
    if initial == "123":
        initial_where = f"WHERE {first} GLOB '[0-9]'"
    elif initial == "other":
        initial_where = f"WHERE {first} != '' AND {first} NOT GLOB '[A-Za-z0-9]'"
    elif len(initial) == 1 and "a" <= initial <= "z":
        initial_where = f"WHERE {first} = ? COLLATE NOCASE"
        params.append(initial)
    total = conn.execute(f"{query} SELECT COUNT(*) FROM ranked {initial_where}", params).fetchone()[
        0
    ]
    rows = conn.execute(
        f"{query} SELECT * FROM ranked {initial_where} ORDER BY {order} LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    return rows, total


def load_player_summary(conn, player_id):
    source = stats_relation(conn)
    metric = partial(summary_metric_sql, stats_source=source)
    row = conn.execute(
        f"""SELECT maps, {metric("rounds_played", "rounds_played")} AS rounds,
                   {metric("total_kills", "kills")} AS kills,
                   {metric("total_deaths", "deaths")} AS deaths,
                   {metric("total_assists", "assists")} AS assists,
                   {metric("avg_rating", "rating")} AS rating,
                   {metric("avg_adr", "adr")} AS adr,
                   {metric("avg_kast", "kast")} AS kast,
                   {metric("avg_hs", "headshot_percentage")} AS hs,
                   {metric("avg_kpr", "kills")} AS kpr,
                   {metric("avg_dpr", "deaths")} AS dpr,
                   {metric("avg_impact", "impact")} AS impact
            FROM player_performance_summary s WHERE player_id=?""",
        (player_id,),
    ).fetchone()
    summary = (
        dict(row)
        if row is not None
        else {
            "maps": 0,
            **dict.fromkeys(
                (
                    "rounds",
                    "kills",
                    "deaths",
                    "assists",
                    "rating",
                    "adr",
                    "kast",
                    "hs",
                    "kpr",
                    "dpr",
                    "impact",
                )
            ),
        }
    )
    evidence = conn.execute(
        f"""SELECT {player_coverage_sql()} FROM {source} ms
            WHERE player_id=? AND COALESCE(data_status, 'final') <> 'superseded'""",
        (player_id,),
    ).fetchone()
    summary["coverage"] = {
        "kills": {"maps": evidence["kills_maps"]},
        "adr": {
            "maps": evidence["adr_maps"] if summary["adr"] is not None else 0,
            "rounds": evidence["adr_rounds"],
        },
    }
    return summary


def load_team_statistics(conn, *, ranked=False):
    rating = stat_average_sql("rating")
    where = "WHERE totals.player_maps > 0" if ranked else ""
    order = "rating DESC, maps DESC, t.id LIMIT 10" if ranked else "t.name, t.id"
    # Aggregate rosters and player results separately, otherwise their join multiplies maps.
    return conn.execute(
        f"""WITH totals AS (
                SELECT team_id, COUNT(*) AS player_maps,
                       {stat_map_count_sql(per_player=False)} AS maps, {rating} AS rating
                FROM {stats_relation(conn)} ms
                WHERE COALESCE(data_status, 'final') <> 'superseded'
                GROUP BY team_id
            ), roster AS (
                SELECT team_id, COUNT(*) AS players FROM players GROUP BY team_id
            )
            SELECT t.*, COALESCE(roster.players, 0) AS players,
                   COALESCE(totals.maps, 0) AS maps,
                   COALESCE(totals.player_maps, 0) AS player_maps, totals.rating
            FROM teams t
            LEFT JOIN roster ON roster.team_id=t.id
            LEFT JOIN totals ON totals.team_id=t.id
            {where} ORDER BY {order}"""
    ).fetchall()


def load_map_statistics(conn):
    rating = stat_average_sql("rating")
    adr = stat_average_sql("adr")
    hs = stat_average_sql("headshot_percentage", weight="kills")
    return conn.execute(
        f"""SELECT MIN(map_name) AS map_name, {stat_map_count_sql(per_player=False)} AS maps,
                   COUNT(*) AS player_maps, {rating} AS rating, {adr} AS adr, {hs} AS hs
            FROM {stats_relation(conn)} ms
            WHERE map_name IS NOT NULL AND map_name != ''
              AND COALESCE(data_status, 'final') <> 'superseded'
            GROUP BY {stat_map_key_sql()} ORDER BY maps DESC, rating DESC, map_name LIMIT 10"""
    ).fetchall()


def load_statistics_totals(conn):
    rating = stat_average_sql("rating")
    return conn.execute(
        f"""SELECT COUNT(DISTINCT match_id) AS matches,
                   COUNT(DISTINCT player_id) AS players, COUNT(*) AS player_maps,
                   {rating} AS rating, SUM(kills) AS kills
            FROM {stats_relation(conn)} ms WHERE COALESCE(data_status, 'final') <> 'superseded'"""
    ).fetchone()
