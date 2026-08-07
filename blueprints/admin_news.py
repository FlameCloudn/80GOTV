"""Admin news management pages."""

import re
from datetime import datetime

from flask import flash, redirect, render_template, request, url_for

from blueprints.admin import admin_bp
from models import get_db
from utils.helpers import normalize_internal_path, sanitize_html
from utils.web_helpers import admin_required as login_required
from utils.web_helpers import csrf_required

RECENT_MATCHES_SQL = """SELECT m.id, m.match_time, t1.short_name as t1s, t2.short_name as t2s,
    COALESCE(t1.name,'TBD') as t1n, COALESCE(t2.name,'TBD') as t2n, m.team1_score, m.team2_score, e.name as event_name
    FROM matches m LEFT JOIN teams t1 ON m.team1_id=t1.id LEFT JOIN teams t2 ON m.team2_id=t2.id
    LEFT JOIN events e ON m.event_id=e.id ORDER BY m.match_time DESC LIMIT 100"""


def _recent_matches(conn):
    return conn.execute(RECENT_MATCHES_SQL).fetchall()


def _news_form_values():
    return {
        "title": request.form.get("title", "").strip(),
        "content": sanitize_html(request.form.get("content", "")).strip(),
        "summary": request.form.get("summary", "").strip(),
        "author": request.form.get("author", "admin").strip() or "admin",
        "publish_time": request.form.get("publish_time", "").strip()
        or datetime.now().isoformat(timespec="minutes"),
        "related_match_id": request.form.get("related_match_id", "").strip() or None,
        "redirect_url": request.form.get("redirect_url", "").strip() or None,
    }


def _news_validation_error(conn, values, exclude_id=None):
    if not values["title"]:
        return "新闻标题不能为空"
    plain_content = re.sub(r"<[^>]+>", "", values["content"]).replace("&nbsp;", "").strip()
    if not plain_content:
        return "新闻正文不能为空"
    sql = "SELECT id FROM news WHERE LOWER(TRIM(title))=LOWER(TRIM(?))"
    params = [values["title"]]
    if exclude_id is not None:
        sql += " AND id<>?"
        params.append(exclude_id)
    if conn.execute(sql, params).fetchone():
        return "已存在同标题新闻"
    if values["related_match_id"]:
        if (
            not values["related_match_id"].isdigit()
            or not conn.execute(
                "SELECT id FROM matches WHERE id=?", (values["related_match_id"],)
            ).fetchone()
        ):
            return "关联比赛不存在"
    redirect_url = normalize_internal_path(values["redirect_url"])
    if values["redirect_url"] and not redirect_url:
        return "跳转地址只能填写本站路径或 80gotv.cn 地址"
    if exclude_id is not None and redirect_url == f"/news/{exclude_id}":
        return "跳转地址不能指向当前新闻自身"
    values["redirect_url"] = redirect_url
    return None


def _render_news_form(conn, news, status=200):
    recent_matches = _recent_matches(conn)
    conn.close()
    return render_template("admin/news_form.html", news=news, recent_matches=recent_matches), status


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
        conn = get_db()
        values = _news_form_values()
        error = _news_validation_error(conn, values)
        if error:
            values["id"] = None
            flash(error, "error")
            return _render_news_form(conn, values, 400)
        conn.execute(
            """INSERT INTO news(title, content, summary, author, publish_time, related_match_id, redirect_url)
            VALUES(?,?,?,?,?,?,?)""",
            (
                values["title"],
                values["content"],
                values["summary"],
                values["author"],
                values["publish_time"],
                values["related_match_id"],
                values["redirect_url"],
            ),
        )
        conn.commit()
        conn.close()
        flash("新闻添加成功", "success")
        return redirect(url_for("admin.admin_news"))
    conn = get_db()
    return _render_news_form(conn, None)


@admin_bp.route("/news/edit/<int:news_id>", methods=["GET", "POST"])
@csrf_required
@login_required
def admin_news_edit(news_id):
    conn = get_db()
    news = conn.execute("SELECT * FROM news WHERE id=?", (news_id,)).fetchone()
    if not news:
        conn.close()
        return "新闻不存在", 404
    if request.method == "POST":
        values = _news_form_values()
        error = _news_validation_error(conn, values, news_id)
        if error:
            values["id"] = news_id
            flash(error, "error")
            return _render_news_form(conn, values, 400)
        conn.execute(
            """UPDATE news SET title=?, content=?, summary=?, author=?, publish_time=?, tags='', related_match_id=?, redirect_url=?
            WHERE id=?""",
            (
                values["title"],
                values["content"],
                values["summary"],
                values["author"],
                values["publish_time"],
                values["related_match_id"],
                values["redirect_url"],
                news_id,
            ),
        )
        conn.commit()
        conn.close()
        flash("新闻更新成功", "success")
        return redirect(url_for("admin.admin_news"))
    return _render_news_form(conn, news)


@admin_bp.route("/news/delete/<int:news_id>", methods=["POST"])
@csrf_required
@login_required
def admin_news_delete(news_id):
    conn = get_db()
    try:
        news = conn.execute("SELECT id FROM news WHERE id=?", (news_id,)).fetchone()
        if not news:
            flash("新闻不存在", "error")
            return redirect(url_for("admin.admin_news"))
        conn.execute(
            "DELETE FROM comment_likes WHERE comment_id IN "
            "(SELECT id FROM comments WHERE target_type='news' AND target_id=?)",
            (news_id,),
        )
        conn.execute("DELETE FROM comments WHERE target_type='news' AND target_id=?", (news_id,))
        conn.execute("DELETE FROM news WHERE id=?", (news_id,))
        conn.commit()
        flash("新闻删除成功", "success")
    except Exception as e:
        conn.rollback()
        flash(f"删除失败：{str(e)}", "error")
    finally:
        conn.close()
    return redirect(url_for("admin.admin_news"))
