"""Public news list and article pages."""

from flask import redirect, render_template, request, session

from models import get_db
from utils.helpers import build_comment_tree
from web_app import app


@app.route("/news")
def news_list():
    """新闻列表"""
    page = request.args.get("page", 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page

    conn = get_db()
    news = conn.execute(
        "SELECT * FROM news ORDER BY publish_time DESC LIMIT ? OFFSET ?", (per_page, offset)
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) as cnt FROM news").fetchone()["cnt"]
    conn.close()

    total_pages = (total + per_page - 1) // per_page
    return render_template(
        "news.html",
        news=news,
        page=page,
        total_pages=total_pages,
    )


@app.route("/news/<int:news_id>")
def news_detail(news_id):
    """新闻详情"""
    conn = get_db()
    news = conn.execute("SELECT * FROM news WHERE id=?", (news_id,)).fetchone()

    if not news:
        conn.close()
        return "新闻不存在", 404
    if news["redirect_url"]:
        target = news["redirect_url"]
        conn.close()
        return redirect(target)

    # 关联比赛
    related_match = None
    if news["related_match_id"]:
        related_match = conn.execute(
            """
            SELECT m.*, t1.short_name as t1s, t2.short_name as t2s,
                   COALESCE(t1.name, 'TBD') as t1n, COALESCE(t2.name, 'TBD') as t2n,
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
        SELECT c.*, u.username,
               CASE WHEN COALESCE(u.is_bashizhong_student, 1)<>0
                    THEN u.group_username END AS group_username,
               u.avatar, u.is_cheater,
               (SELECT COUNT(*) FROM comment_likes WHERE comment_id=c.id) as like_count,
               (SELECT 1 FROM comment_likes WHERE comment_id=c.id AND user_id=?) as user_liked
        FROM comments c
        JOIN users u ON c.user_id = u.id
        WHERE c.target_type='news' AND c.target_id=?
        ORDER BY c.created_at ASC, c.id ASC
    """,
        (session.get("user_id"), news_id),
    ).fetchall()

    conn.close()

    comments = build_comment_tree(raw_comments)

    return render_template(
        "news_detail.html",
        news=news,
        comments=comments,
        related_match=related_match,
    )
