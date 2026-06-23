"""Public home page and signed-in dashboard."""

from datetime import datetime

from flask import render_template

from models import get_db
from services.match_service import supplement_temp_teams
from utils.match_utils import (
    get_sql_effective_status,
    get_sql_match_completed,
    get_sql_match_live,
    get_sql_match_upcoming,
)
from web_app import app

_SQL_MATCH_COMPLETED = get_sql_match_completed()
_SQL_MATCH_UPCOMING = get_sql_match_upcoming()
_SQL_MATCH_LIVE = get_sql_match_live()
_SQL_EFFECTIVE_STATUS = get_sql_effective_status()


@app.route("/")
def index():
    """首页"""
    conn = get_db()
    try:
        today_str = datetime.now().strftime("%Y-%m-%d")
        news = conn.execute("SELECT * FROM news ORDER BY publish_time DESC LIMIT 12").fetchall()

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
        matches = [supplement_temp_teams(m, conn) for m in matches]

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
        recent = [supplement_temp_teams(m, conn) for m in recent]

        top_players = conn.execute("""
            SELECT p.nickname, p.id, t.short_name AS team, AVG(ms.rating) AS avg_rating
            FROM match_stats ms
            JOIN players p ON ms.player_id=p.id
            LEFT JOIN teams t ON p.team_id=t.id
            GROUP BY p.id
            ORDER BY avg_rating DESC LIMIT 5
        """).fetchall()
        top_player = top_players[0] if top_players else None

        team_ranking = conn.execute(f"""
            SELECT t.id, t.name, t.short_name,
                   COUNT(m.id) AS match_count,
                   SUM(CASE
                       WHEN (m.team1_id=t.id AND m.team1_score>m.team2_score)
                         OR (m.team2_id=t.id AND m.team2_score>m.team1_score)
                       THEN 1 ELSE 0 END) AS wins
            FROM teams t
            JOIN matches m ON m.team1_id=t.id OR m.team2_id=t.id
            WHERE {_SQL_MATCH_COMPLETED}
            GROUP BY t.id
            ORDER BY wins DESC, match_count DESC, t.name ASC
            LIMIT 5
        """).fetchall()

        active_events = conn.execute("""
            SELECT id, name, start_date, end_date
            FROM events
            ORDER BY start_date DESC
            LIMIT 5
        """).fetchall()

        # 比分条：最近结束的 10 场比赛
        ticker_matches = conn.execute(f"""
            SELECT m.*, t1.short_name AS t1s, t2.short_name AS t2s,
                   {_SQL_EFFECTIVE_STATUS}
            FROM matches m
            LEFT JOIN teams t1 ON m.team1_id=t1.id
            LEFT JOIN teams t2 ON m.team2_id=t2.id
            WHERE {_SQL_MATCH_COMPLETED}
            ORDER BY m.match_time DESC LIMIT 10
        """).fetchall()
        ticker_matches = [supplement_temp_teams(m, conn) for m in ticker_matches]
    finally:
        conn.close()

    return render_template(
        "index.html",
        news=news,
        matches=matches,
        recent=recent,
        top_player=top_player,
        top_players=top_players,
        team_ranking=team_ranking,
        active_events=active_events,
        ticker_matches=ticker_matches,
    )


@app.route("/dashboard")
def dashboard():
    """数据仪表盘"""
    conn = get_db()
    try:
        # 1. 选手生涯 Rating 分布（按选手平均 rating 分桶）
        rating_buckets = [
            dict(r)
            for r in conn.execute("""
            SELECT
                CASE WHEN avg_rating < 0.5 THEN '0-0.5'
                     WHEN avg_rating < 0.7 THEN '0.5-0.7'
                     WHEN avg_rating < 0.9 THEN '0.7-0.9'
                     WHEN avg_rating < 1.1 THEN '0.9-1.1'
                     WHEN avg_rating < 1.3 THEN '1.1-1.3'
                     WHEN avg_rating < 1.5 THEN '1.3-1.5'
                     ELSE '1.5+'
                END AS bucket,
                COUNT(*) AS cnt
            FROM (
                SELECT player_id, AVG(rating) AS avg_rating
                FROM match_stats
                GROUP BY player_id
            )
            GROUP BY bucket
            ORDER BY MIN(avg_rating)
        """).fetchall()
        ]

        # 2. MVP 与 EVP 分开排行
        top_mvps = [
            dict(r)
            for r in conn.execute("""
            SELECT p.nickname, p.id, COUNT(pm.id) AS mvp_count
            FROM player_medals pm
            JOIN players p ON pm.player_id = p.id
            WHERE pm.type='MVP'
            GROUP BY p.id
            ORDER BY mvp_count DESC, p.nickname ASC
            LIMIT 5
        """).fetchall()
        ]
        top_evps = [
            dict(r)
            for r in conn.execute("""
            SELECT p.nickname, p.id, COUNT(pm.id) AS evp_count
            FROM player_medals pm
            JOIN players p ON pm.player_id = p.id
            WHERE pm.type='EVP'
            GROUP BY p.id
            ORDER BY evp_count DESC, p.nickname ASC
            LIMIT 5
        """).fetchall()
        ]
        medal_totals = dict(
            conn.execute("""
            SELECT SUM(CASE WHEN type='MVP' THEN 1 ELSE 0 END) AS mvp_count,
                   SUM(CASE WHEN type='EVP' THEN 1 ELSE 0 END) AS evp_count
            FROM player_medals
        """).fetchone()
        )

        # 3. 赛事比赛数量分布
        event_matches = [
            dict(r)
            for r in conn.execute("""
            SELECT e.name AS event, COUNT(m.id) AS cnt
            FROM events e
            LEFT JOIN matches m ON e.id=m.event_id
            GROUP BY e.id
            ORDER BY cnt DESC
            LIMIT 10
        """).fetchall()
        ]
    finally:
        conn.close()

    return render_template(
        "dashboard.html",
        rating_buckets=rating_buckets,
        top_mvps=top_mvps,
        top_evps=top_evps,
        medal_totals=medal_totals,
        event_matches=event_matches,
    )
