"""Shared queries for the server-rendered home page and its JSON APIs."""

from datetime import date, datetime

from services.match_service import supplement_temp_teams
from utils.match_utils import (
    get_sql_effective_status,
    get_sql_match_completed,
    get_sql_match_live,
    get_sql_match_upcoming,
)

_SQL_MATCH_COMPLETED = get_sql_match_completed()
_SQL_MATCH_UPCOMING = get_sql_match_upcoming()
_SQL_MATCH_LIVE = get_sql_match_live()
_SQL_EFFECTIVE_STATUS = get_sql_effective_status()


def load_home_feed(conn, today=None):
    """Return the common news, match and player lists for the home surfaces."""
    if today is None:
        today_str = datetime.now().strftime("%Y-%m-%d")
    elif isinstance(today, (date, datetime)):
        today_str = today.strftime("%Y-%m-%d")
    else:
        today_str = str(today)[:10]

    news = conn.execute("SELECT * FROM news ORDER BY publish_time DESC LIMIT 12").fetchall()
    forum_activity = conn.execute(
        """
        SELECT id, title, reply_count
        FROM forum_threads
        ORDER BY COALESCE(last_reply_at, created_at) DESC, id DESC
        LIMIT 8
        """
    ).fetchall()
    matches = conn.execute(
        f"""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s, e.name AS event_name,
               {_SQL_EFFECTIVE_STATUS}
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id
        WHERE ({_SQL_MATCH_LIVE} OR {_SQL_MATCH_UPCOMING})
          AND substr(COALESCE(m.match_time, ''), 1, 10)=?
        ORDER BY CASE WHEN effective_status='live' THEN 0 ELSE 1 END,
                 CASE WHEN m.match_time IS NULL OR m.match_time='' THEN 1 ELSE 0 END,
                 m.match_time
        LIMIT 10
        """,
        (today_str,),
    ).fetchall()
    matches = [supplement_temp_teams(match, conn) for match in matches]

    recent = conn.execute(f"""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s,
               {_SQL_EFFECTIVE_STATUS}
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        WHERE {_SQL_MATCH_COMPLETED}
        ORDER BY m.match_time DESC LIMIT 8
    """).fetchall()
    recent = [supplement_temp_teams(match, conn) for match in recent]

    top_players = conn.execute("""
        SELECT p.nickname, p.id, t.short_name AS team, s.avg_rating
        FROM player_performance_summary s
        JOIN players p ON s.player_id=p.id
        LEFT JOIN teams t ON p.team_id=t.id
        WHERE s.maps > 0
        ORDER BY s.avg_rating DESC, s.maps DESC
        LIMIT 5
    """).fetchall()

    return {
        "news": news,
        "forum_activity": forum_activity,
        "matches": matches,
        "recent": recent,
        "top_players": top_players,
    }
