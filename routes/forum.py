"""Forum list, thread and reply pages."""

from flask import flash, redirect, render_template, request, session, url_for

from models import get_db
from services.notification_service import create_notification
from utils.helpers import is_admin, row_get
from utils.rate_limiter import rate_limit
from utils.web_helpers import csrf_required, user_required
from web_app import app

FORUM_SORT_ORDERS = {
    "latest": "t.is_pinned DESC, COALESCE(t.last_reply_at, t.created_at) DESC, t.id DESC",
    "newest": "t.is_pinned DESC, t.created_at DESC, t.id DESC",
    "popular": "t.is_pinned DESC, (t.reply_count * 8 + t.view_count) DESC, COALESCE(t.last_reply_at, t.created_at) DESC",
}


def _forum_categories(conn):
    return conn.execute(
        """
        SELECT c.*, COUNT(t.id) AS thread_count
        FROM forum_categories c
        LEFT JOIN forum_threads t ON t.category_id=c.id
        GROUP BY c.id
        ORDER BY c.sort_order, c.id
        """
    ).fetchall()


def _can_manage_thread(thread):
    return is_admin() or (
        session.get("user_id") and int(session["user_id"]) == int(thread["user_id"])
    )


def _render_thread_form(template_name, conn, thread=None, status=200):
    categories = _forum_categories(conn)
    conn.close()
    return (
        render_template(template_name, categories=categories, thread=thread),
        status,
    )


@app.route("/forum")
def forum_index():
    """论坛首页 - 贴吧风格扁平帖子列表"""
    search_query = request.args.get("q", "").strip()
    category_slug = request.args.get("category", "").strip()
    sort_by = request.args.get("sort", "latest").strip()
    if sort_by not in FORUM_SORT_ORDERS:
        sort_by = "latest"
    mine_only = request.args.get("mine") == "1" and bool(session.get("user_id"))
    page = max(1, request.args.get("page", 1, type=int))
    per_page = 25
    offset = (page - 1) * per_page

    conn = get_db()
    categories = _forum_categories(conn)
    valid_category_slugs = {row["slug"] for row in categories}
    if category_slug not in valid_category_slugs:
        category_slug = ""

    where_clauses = []
    params = []

    if search_query:
        where_clauses.append("(t.title LIKE ? OR t.content LIKE ?)")
        params.extend([f"%{search_query}%", f"%{search_query}%"])
    if category_slug:
        where_clauses.append("c.slug=?")
        params.append(category_slug)
    if mine_only:
        where_clauses.append("t.user_id=?")
        params.append(session["user_id"])

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
    order_sql = FORUM_SORT_ORDERS[sort_by]

    threads = conn.execute(
        f"""
        SELECT t.*, c.name AS category_name, c.slug AS category_slug,
               u.username,
               CASE WHEN COALESCE(u.is_bashizhong_student, 1)<>0
                    THEN u.group_username END AS group_username,
               u.avatar, u.is_cheater,
               lr.username AS last_reply_username,
               CASE WHEN COALESCE(lr.is_bashizhong_student, 1)<>0
                    THEN lr.group_username END
                   AS last_reply_group_username,
               lr.is_cheater AS last_reply_is_cheater
        FROM forum_threads t
        JOIN forum_categories c ON t.category_id=c.id
        JOIN users u ON t.user_id=u.id
        LEFT JOIN users lr ON lr.id=t.last_reply_user_id
        WHERE {where_sql}
        ORDER BY {order_sql}
        LIMIT ? OFFSET ?
    """,
        params + [per_page, offset],
    ).fetchall()

    total = conn.execute(
        f"""SELECT COUNT(*) FROM forum_threads t
            JOIN forum_categories c ON t.category_id=c.id
            WHERE {where_sql}""",
        params,
    ).fetchone()[0]

    total_pages = (total + per_page - 1) // per_page

    conn.close()
    return render_template(
        "forum/index.html",
        threads=threads,
        page=page,
        total_pages=total_pages,
        search_query=search_query,
        categories=categories,
        category_filter=category_slug,
        sort_by=sort_by,
        mine_only=mine_only,
    )


@app.route("/forum/t/<int:thread_id>")
def forum_thread(thread_id):
    """帖子详情"""
    conn = get_db()
    thread = conn.execute(
        """
        SELECT t.*, c.name AS category_name, c.slug AS category_slug,
               u.username,
               CASE WHEN COALESCE(u.is_bashizhong_student, 1)<>0
                    THEN u.group_username END AS group_username,
               u.avatar, u.is_cheater
        FROM forum_threads t
        JOIN forum_categories c ON t.category_id=c.id
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
        SELECT co.*, u.username,
               CASE WHEN COALESCE(u.is_bashizhong_student, 1)<>0
                    THEN u.group_username END AS group_username,
               u.avatar, u.is_cheater,
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
        can_manage_thread=_can_manage_thread(thread),
        is_forum_admin=is_admin(),
        current_user_id=session.get("user_id"),
    )


@app.route("/forum/thread/new", methods=["GET", "POST"])
@csrf_required
@user_required
def forum_new_thread():
    """发表新帖"""
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        category_id = request.form.get("category_id", "").strip()

        if not rate_limit("forum_thread", 3, 300):
            flash("发帖过于频繁，请 5 分钟后再试", "error")
            conn = get_db()
            return _render_thread_form("forum/new_thread.html", conn, status=429)

        if not title or not content:
            flash("请填写标题和内容", "error")
            conn = get_db()
            return _render_thread_form("forum/new_thread.html", conn, status=400)

        if len(title) > 120:
            flash("标题最多 120 字", "error")
            conn = get_db()
            return _render_thread_form("forum/new_thread.html", conn, status=400)

        if len(content) > 10000:
            flash("内容最多 10000 字", "error")
            conn = get_db()
            return _render_thread_form("forum/new_thread.html", conn, status=400)

        conn = get_db()
        category = None
        if category_id.isdigit():
            category = conn.execute(
                "SELECT id FROM forum_categories WHERE id=?", (int(category_id),)
            ).fetchone()
        elif not category_id:
            category = conn.execute(
                "SELECT id FROM forum_categories ORDER BY sort_order, id LIMIT 1"
            ).fetchone()
        if not category:
            flash("请选择有效的论坛版块", "error")
            return _render_thread_form("forum/new_thread.html", conn, status=400)
        conn.execute(
            """
            INSERT INTO forum_threads(category_id, user_id, title, content, last_reply_at)
            VALUES(?,?,?,?,CURRENT_TIMESTAMP)
        """,
            (category["id"], session["user_id"], title, content),
        )
        conn.commit()
        thread_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()

        flash("帖子发布成功", "success")
        return redirect(url_for("forum_thread", thread_id=thread_id))

    conn = get_db()
    return _render_thread_form("forum/new_thread.html", conn)


@app.route("/forum/t/<int:thread_id>/edit", methods=["GET", "POST"])
@csrf_required
def forum_edit_thread(thread_id):
    """楼主或管理员编辑帖子。"""
    conn = get_db()
    thread = conn.execute("SELECT * FROM forum_threads WHERE id=?", (thread_id,)).fetchone()
    if not thread:
        conn.close()
        return "帖子不存在", 404
    if not session.get("user_id") and not is_admin():
        conn.close()
        flash("请先登录", "error")
        return redirect(url_for("user_login", next=request.path))
    if not _can_manage_thread(thread):
        conn.close()
        return "无权编辑此帖子", 403

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        category_id = request.form.get("category_id", "").strip()
        if not title or not content:
            flash("请填写标题和内容", "error")
            return _render_thread_form("forum/edit_thread.html", conn, thread, 400)
        if len(title) > 120 or len(content) > 10000:
            flash("标题最多 120 字，内容最多 10000 字", "error")
            return _render_thread_form("forum/edit_thread.html", conn, thread, 400)
        category = None
        if category_id.isdigit():
            category = conn.execute(
                "SELECT id FROM forum_categories WHERE id=?", (int(category_id),)
            ).fetchone()
        if not category:
            flash("请选择有效的论坛版块", "error")
            return _render_thread_form("forum/edit_thread.html", conn, thread, 400)
        conn.execute(
            "UPDATE forum_threads SET title=?, content=?, category_id=? WHERE id=?",
            (title, content, category["id"], thread_id),
        )
        conn.commit()
        conn.close()
        flash("帖子已更新", "success")
        return redirect(url_for("forum_thread", thread_id=thread_id))

    return _render_thread_form("forum/edit_thread.html", conn, thread)


@app.route("/forum/t/<int:thread_id>/manage", methods=["POST"])
@csrf_required
def forum_manage_thread(thread_id):
    """楼主删除空帖，管理员置顶、锁定或删除帖子。"""
    action = request.form.get("action", "").strip()
    conn = get_db()
    thread = conn.execute("SELECT * FROM forum_threads WHERE id=?", (thread_id,)).fetchone()
    if not thread:
        conn.close()
        return "帖子不存在", 404

    admin = is_admin()
    owner = session.get("user_id") and int(session["user_id"]) == int(thread["user_id"])
    if action in {"pin", "unpin", "lock", "unlock"}:
        if not admin:
            conn.close()
            return "仅管理员可执行此操作", 403
        if action in {"pin", "unpin"}:
            conn.execute(
                "UPDATE forum_threads SET is_pinned=? WHERE id=?",
                (1 if action == "pin" else 0, thread_id),
            )
            message = "帖子已置顶" if action == "pin" else "已取消置顶"
        else:
            conn.execute(
                "UPDATE forum_threads SET is_locked=? WHERE id=?",
                (1 if action == "lock" else 0, thread_id),
            )
            message = "帖子已锁定" if action == "lock" else "帖子已解锁"
        conn.commit()
        conn.close()
        flash(message, "success")
        return redirect(url_for("forum_thread", thread_id=thread_id))

    if action == "delete":
        if not admin and not (owner and int(thread["reply_count"] or 0) == 0):
            conn.close()
            return "有回复的帖子只能由管理员删除", 403
        comment_ids = [
            row["id"]
            for row in conn.execute(
                "SELECT id FROM comments WHERE target_type='forum_thread' AND target_id=?",
                (thread_id,),
            ).fetchall()
        ]
        for comment_id in comment_ids:
            conn.execute("DELETE FROM comment_likes WHERE comment_id=?", (comment_id,))
        conn.execute(
            "DELETE FROM comments WHERE target_type='forum_thread' AND target_id=?",
            (thread_id,),
        )
        conn.execute("DELETE FROM forum_threads WHERE id=?", (thread_id,))
        conn.execute(
            "DELETE FROM notifications WHERE link=? OR link LIKE ?",
            (f"/forum/t/{thread_id}", f"/forum/t/{thread_id}#%"),
        )
        conn.commit()
        conn.close()
        flash("帖子已删除", "success")
        return redirect(url_for("forum_index"))

    conn.close()
    return "无效操作", 400


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
