"""Public news list and article pages."""

from flask import render_template, request, session

from models import get_db
from utils.helpers import build_comment_tree
from web_app import app


@app.route("/news")
def news_list():
    """新闻列表"""
    tag_filter = request.args.get("tag", "")
    page = request.args.get("page", 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page

    conn = get_db()
    if tag_filter:
        news = conn.execute(
            "SELECT * FROM news WHERE tags LIKE ? ORDER BY publish_time DESC LIMIT ? OFFSET ?",
            (f"%{tag_filter}%", per_page, offset),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) as cnt FROM news WHERE tags LIKE ?", (f"%{tag_filter}%",)
        ).fetchone()["cnt"]
    else:
        news = conn.execute(
            "SELECT * FROM news ORDER BY publish_time DESC LIMIT ? OFFSET ?", (per_page, offset)
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) as cnt FROM news").fetchone()["cnt"]

    # 收集所有标签用于热门标签展示
    all_news_for_tags = conn.execute("SELECT tags FROM news WHERE tags != ''").fetchall()
    conn.close()

    tag_counts = {}
    for row in all_news_for_tags:
        for t in row["tags"].split(","):
            t = t.strip()
            if t:
                tag_counts[t] = tag_counts.get(t, 0) + 1
    hot_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    total_pages = (total + per_page - 1) // per_page
    return render_template(
        "news.html",
        news=news,
        page=page,
        total_pages=total_pages,
        tag_filter=tag_filter,
        hot_tags=hot_tags,
    )


@app.route("/news/<int:news_id>")
def news_detail(news_id):
    """新闻详情"""
    conn = get_db()
    news = conn.execute("SELECT * FROM news WHERE id=?", (news_id,)).fetchone()

    if not news:
        conn.close()
        return "新闻不存在", 404

    # 关联比赛
    related_match = None
    if news["related_match_id"]:
        related_match = conn.execute(
            """
            SELECT m.*, t1.short_name as t1s, t2.short_name as t2s,
                   COALESCE(t1.name, 'Team 1') as t1n, COALESCE(t2.name, 'Team 2') as t2n,
                   e.name as event_name
            FROM matches m
            LEFT JOIN teams t1 ON m.team1_id = t1.id
            LEFT JOIN teams t2 ON m.team2_id = t2.id
            LEFT JOIN events e ON m.event_id = e.id
            WHERE m.id=?
        """,
            (news["related_match_id"],),
        ).fetchone()

    raw_comments = conn.execute(
        """
        SELECT c.*, u.username, u.avatar,
               (SELECT COUNT(*) FROM comment_likes WHERE comment_id=c.id) as like_count,
               (SELECT 1 FROM comment_likes WHERE comment_id=c.id AND user_id=?) as user_liked
        FROM comments c
        JOIN users u ON c.user_id = u.id
        WHERE c.target_type='news' AND c.target_id=?
        ORDER BY c.created_at ASC
    """,
        (session.get("user_id"), news_id),
    ).fetchall()

    # 热门标签
    all_news_for_tags = conn.execute("SELECT tags FROM news WHERE tags != ''").fetchall()
    conn.close()

    comments = build_comment_tree(raw_comments)

    tag_counts = {}
    for row in all_news_for_tags:
        for t in row["tags"].split(","):
            t = t.strip()
            if t:
                tag_counts[t] = tag_counts.get(t, 0) + 1
    hot_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    return render_template(
        "news_detail.html",
        news=news,
        comments=comments,
        hot_tags=hot_tags,
        related_match=related_match,
    )
