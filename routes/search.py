"""Site-wide search pages and API."""

from flask import jsonify, render_template, request

from models import get_db
from services.match_service import supplement_temp_teams
from utils.filters import date_display_filter
from utils.match_utils import get_sql_effective_status
from web_app import app

_SQL_EFFECTIVE_STATUS = get_sql_effective_status()


@app.route("/search")
def search():
    """全站搜索"""
    # 去除首尾空格，避免无意义的空白搜索
    q = request.args.get("q", "").strip()
    if not q:
        return render_template("search.html", query="", results={}, has_results=False)

    conn = get_db()
    # 模糊搜索：用 LIKE %关键词% 实现"包含即可"匹配，不要求精确相等
    like = f"%{q}%"

    # 新闻
    news_results = conn.execute(
        "SELECT id, title, summary, publish_time FROM news WHERE title LIKE ? OR content LIKE ? OR summary LIKE ? OR tags LIKE ? ORDER BY publish_time DESC LIMIT 10",
        (like, like, like, like),
    ).fetchall()

    # 选手
    player_results = conn.execute(
        """
        SELECT p.id, p.nickname, p.real_name, t.name AS team_name
        FROM players p
        LEFT JOIN teams t ON p.team_id=t.id
        WHERE p.nickname LIKE ? OR p.real_name LIKE ?
           OR EXISTS (
               SELECT 1 FROM player_nickname_history h
               WHERE h.player_id=p.id AND h.nickname LIKE ?
           )
        ORDER BY p.nickname
        LIMIT 10
    """,
        (like, like, like),
    ).fetchall()

    # 队伍
    team_results = conn.execute(
        "SELECT id, name, short_name FROM teams WHERE name LIKE ? OR short_name LIKE ? ORDER BY name LIMIT 10",
        (like, like),
    ).fetchall()

    # 赛事
    event_results = conn.execute(
        "SELECT id, name, description, start_date FROM events WHERE name LIKE ? OR description LIKE ? ORDER BY start_date DESC LIMIT 10",
        (like, like),
    ).fetchall()

    # 比赛
    match_results = conn.execute(
        f"""
        SELECT m.id, m.match_time, m.team1_score, m.team2_score, m.bo_format,
               t1.name AS team1_name, t2.name AS team2_name, e.name AS event_name,
               {_SQL_EFFECTIVE_STATUS}
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id
        WHERE t1.name LIKE ? OR t2.name LIKE ? OR e.name LIKE ?
        ORDER BY m.match_time DESC LIMIT 10
    """,
        (like, like, like),
    ).fetchall()

    # 为比赛补充临时队伍名称
    match_results = [supplement_temp_teams(m, conn) for m in match_results]
    conn.close()

    results = {
        "news": news_results,
        "players": player_results,
        "teams": team_results,
        "events": event_results,
        "matches": match_results,
    }
    # 判断是否有任何搜索结果，用于模板显示空状态提示
    has_results = any(len(v) > 0 for v in results.values())
    return render_template("search.html", query=q, results=results, has_results=has_results)


@app.route("/api/search")
def api_search():
    """即时搜索 API（返回 JSON）"""
    # 去除首尾空格
    q = request.args.get("q", "").strip()
    if not q or len(q) < 1:
        return jsonify({"results": []})

    conn = get_db()
    # 模糊搜索：用 LIKE %关键词% 实现"包含即可"匹配
    like = f"%{q}%"

    players = [
        dict(r)
        for r in conn.execute(
            """
        SELECT p.id, p.nickname, p.real_name, p.avatar
        FROM players p
        WHERE p.nickname LIKE ? OR p.real_name LIKE ?
           OR EXISTS (
               SELECT 1 FROM player_nickname_history h
               WHERE h.player_id=p.id AND h.nickname LIKE ?
           )
        ORDER BY p.nickname
        LIMIT 5
    """,
            (like, like, like),
        ).fetchall()
    ]

    teams = [
        dict(r)
        for r in conn.execute(
            "SELECT id, name, short_name FROM teams WHERE name LIKE ? OR short_name LIKE ? ORDER BY name LIMIT 5",
            (like, like),
        ).fetchall()
    ]

    events = [
        dict(r)
        for r in conn.execute(
            "SELECT id, name, start_date FROM events WHERE name LIKE ? ORDER BY start_date DESC LIMIT 5",
            (like,),
        ).fetchall()
    ]

    news = [
        dict(r)
        for r in conn.execute(
            "SELECT id, title, publish_time FROM news WHERE title LIKE ? OR tags LIKE ? ORDER BY publish_time DESC LIMIT 5",
            (like, like),
        ).fetchall()
    ]

    matches = [
        dict(r)
        for r in conn.execute(
            f"""
        SELECT m.id, m.slug, m.match_time, m.team1_score, m.team2_score,
               t1.name AS team1_name, t1.short_name AS t1s,
               t2.name AS team2_name, t2.short_name AS t2s,
               e.name AS event_name,
               {_SQL_EFFECTIVE_STATUS}
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id
        WHERE t1.name LIKE ? OR t2.name LIKE ? OR e.name LIKE ?
        ORDER BY m.match_time DESC LIMIT 5
    """,
            (like, like, like),
        ).fetchall()
    ]

    conn.close()

    results = []
    for p in players:
        results.append(
            {
                "type": "player",
                "label": p["nickname"],
                "sub": p.get("real_name") or "",
                "url": f"/players/{p['id']}",
            }
        )
    for t in teams:
        results.append(
            {
                "type": "team",
                "label": t["name"],
                "sub": t.get("short_name") or "",
                "url": f"/teams/{t['id']}",
            }
        )
    for e in events:
        results.append(
            {
                "type": "event",
                "label": e["name"],
                "sub": date_display_filter(e.get("start_date") or ""),
                "url": f"/events/{e['id']}",
            }
        )
    for n in news:
        results.append(
            {
                "type": "news",
                "label": n["title"],
                "sub": date_display_filter(n.get("publish_time") or ""),
                "url": f"/news/{n['id']}",
            }
        )
    for m in matches:
        m2 = supplement_temp_teams(m, None)
        results.append(
            {
                "type": "match",
                "label": f"{m2['t1s']} {m['team1_score']}:{m['team2_score']} {m2['t2s']}",
                "sub": m.get("event_name") or "",
                "url": f"/matches/{m.get('slug') or m['id']}",
            }
        )

    # 搜索结果为空时返回友好提示，方便前端展示空状态
    if not results:
        return jsonify({"results": [], "empty_message": f'没有找到与"{q}"相关的结果'})

    return jsonify({"results": results})
