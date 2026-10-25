"""Read models shared by public JSON lists; no state changes on reads."""

from services.match_service import supplement_temp_teams
from services.performance_service import summary_metric_sql, weighted_average_sql
from utils.match_utils import (
    get_sql_effective_status,
    get_sql_match_completed,
    get_sql_match_live,
    get_sql_match_upcoming,
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
                   COALESCE((
                       SELECT NULLIF(TRIM(u.group_username), '') FROM users u
                       WHERE u.steam_id64=p.steam_id
                       ORDER BY COALESCE(u.is_placeholder, 0), u.id DESC LIMIT 1
                   ), NULLIF(TRIM(p.group_username_override), ''), '') AS group_username,
                   COALESCE((
                       SELECT u.is_bashizhong_student FROM users u
                       WHERE u.steam_id64=p.steam_id
                       ORDER BY COALESCE(u.is_placeholder, 0), u.id DESC LIMIT 1
                   ), p.is_bashizhong_student) AS managed_is_bashizhong_student,
                   COALESCE(s.maps, 0) AS maps,
                   {summary_metric_sql("avg_rating", "rating")} AS rating,
                   {summary_metric_sql("total_kills", "kills")} AS kills,
                   {summary_metric_sql("total_deaths", "deaths")} AS deaths,
                   {summary_metric_sql("total_assists", "assists")} AS assists,
                   {summary_metric_sql("avg_adr", "adr")} AS adr,
                   {summary_metric_sql("avg_hs", "headshot_percentage")} AS hs
            FROM players p
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
    row = conn.execute(
        f"""SELECT maps, rounds_played AS rounds,
                   {summary_metric_sql("total_kills", "kills")} AS kills,
                   {summary_metric_sql("total_deaths", "deaths")} AS deaths,
                   {summary_metric_sql("total_assists", "assists")} AS assists,
                   {summary_metric_sql("avg_rating", "rating")} AS rating,
                   {summary_metric_sql("avg_adr", "adr")} AS adr,
                   {summary_metric_sql("avg_kast", "kast")} AS kast,
                   {summary_metric_sql("avg_hs", "headshot_percentage")} AS hs,
                   CASE WHEN rounds_played>0 THEN
                       {summary_metric_sql("avg_kpr", "kills")} END AS kpr,
                   CASE WHEN rounds_played>0 THEN
                       {summary_metric_sql("avg_dpr", "deaths")} END AS dpr,
                   {summary_metric_sql("avg_impact", "impact")} AS impact
            FROM player_performance_summary s WHERE player_id=?""",
        (player_id,),
    ).fetchone()
    if row is not None:
        return row
    return {
        **dict.fromkeys(("maps", "rounds", "kills", "deaths", "assists"), 0),
        **dict.fromkeys(("rating", "adr", "kast", "hs", "kpr", "dpr", "impact")),
    }


def load_team_statistics(conn, *, ranked=False):
    rating = weighted_average_sql("rating", "rounds_played")
    where = "WHERE totals.player_maps > 0" if ranked else ""
    order = "rating DESC, maps DESC, t.id LIMIT 10" if ranked else "t.name, t.id"
    # Aggregate rosters and player results separately, otherwise their join multiplies maps.
    return conn.execute(
        f"""WITH active AS (
                SELECT * FROM match_stats
                WHERE COALESCE(data_status, 'final') <> 'superseded'
            ), totals AS (
                SELECT team_id, COUNT(*) AS player_maps, {rating} AS rating
                FROM active GROUP BY team_id
            ), map_totals AS (
                SELECT team_id, COUNT(*) AS maps FROM (
                    SELECT DISTINCT team_id, match_id, map_name FROM active
                ) GROUP BY team_id
            ), roster AS (
                SELECT team_id, COUNT(*) AS players FROM players GROUP BY team_id
            )
            SELECT t.*, COALESCE(roster.players, 0) AS players,
                   COALESCE(map_totals.maps, 0) AS maps,
                   COALESCE(totals.player_maps, 0) AS player_maps, totals.rating
            FROM teams t
            LEFT JOIN roster ON roster.team_id=t.id
            LEFT JOIN totals ON totals.team_id=t.id
            LEFT JOIN map_totals ON map_totals.team_id=t.id
            {where} ORDER BY {order}"""
    ).fetchall()


def load_map_statistics(conn):
    rating = weighted_average_sql("rating", "rounds_played")
    adr = weighted_average_sql("adr", "rounds_played")
    hs = weighted_average_sql("headshot_percentage", "kills")
    return conn.execute(
        f"""SELECT map_name, COUNT(DISTINCT match_id) AS maps,
                   COUNT(*) AS player_maps, {rating} AS rating, {adr} AS adr, {hs} AS hs
            FROM match_stats
            WHERE map_name IS NOT NULL AND map_name != ''
              AND COALESCE(data_status, 'final') <> 'superseded'
            GROUP BY map_name ORDER BY maps DESC, rating DESC, map_name LIMIT 10"""
    ).fetchall()


def load_statistics_totals(conn):
    rating = weighted_average_sql("rating", "rounds_played")
    return conn.execute(
        f"""SELECT COUNT(DISTINCT match_id) AS matches,
                   COUNT(DISTINCT player_id) AS players, COUNT(*) AS player_maps,
                   {rating} AS rating, SUM(kills) AS kills
            FROM match_stats WHERE COALESCE(data_status, 'final') <> 'superseded'"""
    ).fetchone()
