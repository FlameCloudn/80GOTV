"""Forum list, thread and reply pages."""

from datetime import datetime, timedelta, timezone

from flask import flash, jsonify, redirect, render_template, request, session, url_for

from models import get_db
from services.notification_service import create_notification
from utils.helpers import row_get
from utils.rate_limiter import rate_limit
from utils.web_helpers import csrf_required, user_required
from web_app import app


@app.route("/forum")
def forum_index():
    """论坛首页 - 贴吧风格扁平帖子列表"""
    tag_filter = request.args.get("tag", "").strip()
    tag_mode = request.args.get("tag_mode", "intersection").strip()
    search_query = request.args.get("q", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = 25
    offset = (page - 1) * per_page

    conn = get_db()

    where_clauses = []
    params = []

    if search_query:
        where_clauses.append("(t.title LIKE ? OR t.content LIKE ?)")
        params.extend([f"%{search_query}%", f"%{search_query}%"])

    if tag_filter:
        tags_list = [t.strip() for t in tag_filter.split(",") if t.strip()]
        if tags_list:
            tag_parts = []
            for tag in tags_list:
                tag_parts.append("t.tags LIKE ?")
                params.append(f"%{tag}%")
            if tag_mode == "union":
                where_clauses.append("(" + " OR ".join(tag_parts) + ")")
            else:
                where_clauses.append("(" + " AND ".join(tag_parts) + ")")

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    threads = conn.execute(
        f"""
        SELECT t.*, u.username, u.avatar,
               (SELECT username FROM users WHERE id=t.last_reply_user_id) AS last_reply_username
        FROM forum_threads t
        JOIN users u ON t.user_id=u.id
        WHERE {where_sql}
        ORDER BY t.is_pinned DESC, t.last_reply_at DESC, t.created_at DESC
        LIMIT ? OFFSET ?
    """,
        params + [per_page, offset],
    ).fetchall()

    total = conn.execute(
        f"SELECT COUNT(*) FROM forum_threads t WHERE {where_sql}", params
    ).fetchone()[0]

    total_pages = (total + per_page - 1) // per_page

    # All-time hot tags
    all_tags_rows = conn.execute(
        "SELECT tags FROM forum_threads WHERE tags != '' AND tags IS NOT NULL"
    ).fetchall()
    tag_counter = {}
    for row in all_tags_rows:
        raw = row["tags"] if isinstance(row, dict) else row[0]
        for t in raw.split(","):
            t = t.strip()
            if t:
                tag_counter[t] = tag_counter.get(t, 0) + 1
    hot_tags = sorted(tag_counter.items(), key=lambda x: -x[1])[:15]

    def _tag_fs(count, min_c, max_c):
        if max_c > min_c:
            return round(11 + (count - min_c) / (max_c - min_c) * 7, 1)
        return 14.0

    if hot_tags:
        counts = [c for _, c in hot_tags]
        min_c, max_c = min(counts), max(counts)
    else:
        min_c, max_c = 0, 1
    hot_tags_with_size = [(tag, count, _tag_fs(count, min_c, max_c)) for tag, count in hot_tags]

    # Trending tags (last 7 days)
    seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    trending_rows = conn.execute(
        "SELECT tags FROM forum_threads WHERE tags != '' AND tags IS NOT NULL "
        "AND (created_at >= ? OR last_reply_at >= ?)",
        (seven_days_ago, seven_days_ago),
    ).fetchall()
    trending_counter = {}
    for row in trending_rows:
        raw = row["tags"] if isinstance(row, dict) else row[0]
        for t in raw.split(","):
            t = t.strip()
            if t:
                trending_counter[t] = trending_counter.get(t, 0) + 1
    trending_tags = sorted(trending_counter.items(), key=lambda x: -x[1])[:10]
    if trending_tags:
        t_counts = [c for _, c in trending_tags]
        t_min_c, t_max_c = min(t_counts), max(t_counts)
    else:
        t_min_c, t_max_c = 0, 1
    trending_tags_with_size = [
        (tag, count, _tag_fs(count, t_min_c, t_max_c)) for tag, count in trending_tags
    ]

    conn.close()
    return render_template(
        "forum/index.html",
        threads=threads,
        page=page,
        total_pages=total_pages,
        hot_tags_with_size=hot_tags_with_size,
        trending_tags_with_size=trending_tags_with_size,
        tag_filter=tag_filter,
        tag_mode=tag_mode,
        search_query=search_query,
    )


@app.route("/forum/t/<int:thread_id>")
def forum_thread(thread_id):
    """帖子详情"""
    conn = get_db()
    thread = conn.execute(
        """
        SELECT t.*, u.username, u.avatar
        FROM forum_threads t
        JOIN users u ON t.user_id=u.id
        WHERE t.id=?
    """,
        (thread_id,),
    ).fetchone()

    if not thread:
        conn.close()
        return "帖子不存在", 404

    # 增加浏览量
    conn.execute("UPDATE forum_threads SET view_count=view_count+1 WHERE id=?", (thread_id,))
    conn.commit()

    # 获取回复（使用 comments 表，target_type='forum_thread'，按时间正序，不分页）
    page = request.args.get("page", 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page

    posts = conn.execute(
        """
        SELECT co.*, u.username, u.avatar,
               (SELECT COUNT(*) FROM comment_likes WHERE comment_id=co.id) AS like_count,
               (SELECT 1 FROM comment_likes WHERE comment_id=co.id AND user_id=?) AS user_liked
        FROM comments co
        JOIN users u ON co.user_id=u.id
        WHERE co.target_type='forum_thread' AND co.target_id=?
        ORDER BY co.created_at ASC
        LIMIT ? OFFSET ?
    """,
        (session.get("user_id"), thread_id, per_page, offset),
    ).fetchall()

    total_posts = conn.execute(
        "SELECT COUNT(*) FROM comments WHERE target_type='forum_thread' AND target_id=?",
        (thread_id,),
    ).fetchone()[0]
    total_pages = (total_posts + per_page - 1) // per_page

    conn.close()
    return render_template(
        "forum/thread.html",
        thread=thread,
        posts=posts,
        page=page,
        total_pages=total_pages,
        total_posts=total_posts,
    )


@app.route("/forum/thread/new", methods=["GET", "POST"])
@csrf_required
@user_required
def forum_new_thread():
    """发表新帖"""
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        raw_tags = request.form.get("tags", "").strip()
        # 规范化 tag：逗号分隔，去空格，去重，最多 5 个
        tag_list = []
        seen = set()
        for t in raw_tags.split(","):
            t = t.strip()
            if t and t not in seen:
                tag_list.append(t)
                seen.add(t)
                if len(tag_list) >= 5:
                    break
        tags = ", ".join(tag_list)

        if not rate_limit("forum_thread", 3, 300):
            flash("发帖过于频繁，请 5 分钟后再试", "error")
            return render_template("forum/new_thread.html")

        if not title or not content:
            flash("请填写标题和内容", "error")
            return render_template("forum/new_thread.html")

        if len(title) > 120:
            flash("标题最多 120 字", "error")
            return render_template("forum/new_thread.html")

        if len(content) > 10000:
            flash("内容最多 10000 字", "error")
            return render_template("forum/new_thread.html")

        conn = get_db()
        default_category = conn.execute(
            "SELECT id FROM forum_categories ORDER BY sort_order, id LIMIT 1"
        ).fetchone()
        if not default_category:
            conn.close()
            flash("论坛版块尚未初始化，请联系管理员", "error")
            return render_template("forum/new_thread.html")
        conn.execute(
            """
            INSERT INTO forum_threads(category_id, user_id, title, content, tags, last_reply_at)
            VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)
        """,
            (default_category["id"], session["user_id"], title, content, tags),
        )
        conn.commit()
        thread_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()

        flash("帖子发布成功", "success")
        return redirect(url_for("forum_thread", thread_id=thread_id))

    return render_template("forum/new_thread.html")


@app.route("/forum/t/<int:thread_id>/reply", methods=["POST"])
@csrf_required
@user_required
def forum_thread_reply(thread_id):
    """回复帖子（复用评论系统）"""
    conn = get_db()
    thread = conn.execute(
        "SELECT id, user_id, title, is_locked FROM forum_threads WHERE id=?", (thread_id,)
    ).fetchone()
    if not thread:
        conn.close()
        return "帖子不存在", 404
    if thread["is_locked"]:
        conn.close()
        flash("该帖子已锁定，无法回复", "error")
        return redirect(url_for("forum_thread", thread_id=thread_id))

    content = request.form.get("content", "").strip()
    if not content:
        flash("回复内容不能为空", "error")
        conn.close()
        return redirect(url_for("forum_thread", thread_id=thread_id))

    if len(content) > 5000:
        flash("回复最多 5000 字", "error")
        conn.close()
        return redirect(url_for("forum_thread", thread_id=thread_id))

    if not rate_limit("forum_reply", 10, 60):
        flash("回复过于频繁，请稍后再试", "error")
        conn.close()
        return redirect(url_for("forum_thread", thread_id=thread_id))

    conn.execute(
        """
        INSERT INTO comments(user_id, target_type, target_id, content)
        VALUES(?, 'forum_thread', ?, ?)
    """,
        (session["user_id"], thread_id, content),
    )

    conn.execute(
        """
        UPDATE forum_threads SET reply_count=reply_count+1, last_reply_at=CURRENT_TIMESTAMP,
        last_reply_user_id=? WHERE id=?
    """,
        (session["user_id"], thread_id),
    )

    # 通知楼主
    if thread["user_id"] != session["user_id"]:
        preview = content[:50] + ("..." if len(content) > 50 else "")
        create_notification(
            conn,
            thread["user_id"],
            "forum_reply",
            f"{session.get('user_username', '')} 回复了你的帖子《{row_get(thread, 'title', '')}》：{preview}",
            f"/forum/t/{thread_id}",
        )

    conn.commit()
    conn.close()

    flash("回复成功", "success")
    return redirect(url_for("forum_thread", thread_id=thread_id))


@app.route("/api/forum/tags")
def api_forum_tags():
    """标签自动补全"""
    q = request.args.get("q", "").strip()
    conn = get_db()
    rows = conn.execute(
        "SELECT tags FROM forum_threads WHERE tags != '' AND tags IS NOT NULL"
    ).fetchall()
    conn.close()
    seen = set()
    matched = []
    for row in rows:
        raw = row["tags"] if isinstance(row, dict) else row[0]
        for tag in raw.split(","):
            tag = tag.strip()
            if tag and tag not in seen:
                seen.add(tag)
                if not q or q.lower() in tag.lower():
                    matched.append(tag)
    matched.sort(key=lambda t: (not t.lower().startswith(q.lower()) if q else False, t.lower()))
    return jsonify(tags=matched[:10])
