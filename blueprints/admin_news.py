"""Admin news management pages."""

from datetime import datetime

from flask import flash, redirect, render_template, request, url_for

from blueprints.admin import admin_bp
from models import get_db
from utils.helpers import sanitize_html
from utils.web_helpers import admin_required as login_required
from utils.web_helpers import csrf_required


@admin_bp.route("/news")
@login_required
def admin_news():
    conn = get_db()
    news = conn.execute("SELECT * FROM news ORDER BY publish_time DESC").fetchall()
    conn.close()
    return render_template("admin/news.html", news=news)


@admin_bp.route("/news/add", methods=["GET", "POST"])
@csrf_required
@login_required
def admin_news_add():
    if request.method == "POST":
        title = request.form.get("title")
        content = sanitize_html(request.form.get("content", ""))
        summary = request.form.get("summary")
        author = request.form.get("author", "admin")
        publish_time = request.form.get("publish_time", datetime.now().isoformat())
        tags = request.form.get("tags", "").strip()
        related_match_id = request.form.get("related_match_id", "") or None
        conn = get_db()
        conn.execute(
            """INSERT INTO news(title, content, summary, author, publish_time, tags, related_match_id)
            VALUES(?,?,?,?,?,?,?)""",
            (title, content, summary, author, publish_time, tags, related_match_id),
        )
        conn.commit()
        conn.close()
        flash("新闻添加成功", "success")
        return redirect(url_for("admin.admin_news"))
    conn = get_db()
    recent_matches = conn.execute("""SELECT m.id, m.match_time, t1.short_name as t1s, t2.short_name as t2s,
        COALESCE(t1.name,'Team 1') as t1n, COALESCE(t2.name,'Team 2') as t2n, m.team1_score, m.team2_score, e.name as event_name
        FROM matches m LEFT JOIN teams t1 ON m.team1_id=t1.id LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id ORDER BY m.match_time DESC LIMIT 100""").fetchall()
    conn.close()
    return render_template("admin/news_form.html", news=None, recent_matches=recent_matches)


@admin_bp.route("/news/edit/<int:news_id>", methods=["GET", "POST"])
@csrf_required
@login_required
def admin_news_edit(news_id):
    conn = get_db()
    if request.method == "POST":
        title = request.form.get("title")
        content = sanitize_html(request.form.get("content", ""))
        summary = request.form.get("summary")
        author = request.form.get("author")
        publish_time = request.form.get("publish_time")
        tags = request.form.get("tags", "").strip()
        related_match_id = request.form.get("related_match_id", "") or None
        conn.execute(
            """UPDATE news SET title=?, content=?, summary=?, author=?, publish_time=?, tags=?, related_match_id=?
            WHERE id=?""",
            (title, content, summary, author, publish_time, tags, related_match_id, news_id),
        )
        conn.commit()
        conn.close()
        flash("新闻更新成功", "success")
        return redirect(url_for("admin.admin_news"))
    news = conn.execute("SELECT * FROM news WHERE id=?", (news_id,)).fetchone()
    recent_matches = conn.execute("""SELECT m.id, m.match_time, t1.short_name as t1s, t2.short_name as t2s,
        COALESCE(t1.name,'Team 1') as t1n, COALESCE(t2.name,'Team 2') as t2n, m.team1_score, m.team2_score, e.name as event_name
        FROM matches m LEFT JOIN teams t1 ON m.team1_id=t1.id LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id ORDER BY m.match_time DESC LIMIT 100""").fetchall()
    conn.close()
    return render_template("admin/news_form.html", news=news, recent_matches=recent_matches)


@admin_bp.route("/news/delete/<int:news_id>", methods=["POST"])
@csrf_required
@login_required
def admin_news_delete(news_id):
    try:
        conn = get_db()
        conn.execute("DELETE FROM news WHERE id=?", (news_id,))
        conn.commit()
        conn.close()
        flash("新闻删除成功", "success")
    except Exception as e:
        flash(f"删除失败：{str(e)}", "error")
    return redirect(url_for("admin.admin_news"))
