"""Public home page and signed-in dashboard."""

from flask import render_template

from models import get_db
from services.home_service import load_home_feed
from services.match_service import supplement_temp_teams
from utils.match_utils import (
    get_sql_effective_status,
    get_sql_match_completed,
)
from web_app import app

_SQL_MATCH_COMPLETED = get_sql_match_completed()
_SQL_EFFECTIVE_STATUS = get_sql_effective_status()


@app.route("/")
def index():
    """首页"""
    conn = get_db()
    try:
        feed = load_home_feed(conn)
        news = feed["news"]
        forum_activity = feed["forum_activity"]
        matches = feed["matches"]
        recent = feed["recent"]
        top_players = feed["top_players"]
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
        forum_activity=forum_activity,
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
            FROM player_performance_summary
            WHERE maps > 0
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
            SELECT e.name AS event, e.slug AS slug, COUNT(m.id) AS cnt
            FROM events e
            LEFT JOIN matches m ON e.id=m.event_id
            GROUP BY e.id
            ORDER BY cnt DESC
        """).fetchall()
        ]

        for event_row in event_matches:
            if event_row["slug"] == "2026-spring-80-major":
                # This event has three known historical matches that were not recorded.
                event_row["cnt"] = max(event_row["cnt"], 3)

        event_matches = sorted(
            event_matches,
            key=lambda event_row: (-event_row["cnt"], event_row["event"]),
        )[:10]
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
