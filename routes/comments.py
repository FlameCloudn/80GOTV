"""Comment create, delete and like endpoints."""

from flask import flash, jsonify, redirect, request, session, url_for

from models import get_db
from services.notification_service import create_notification
from utils.helpers import is_admin as _helper_is_admin
from utils.rate_limiter import rate_limit
from utils.web_helpers import csrf_required, safe_redirect_target, user_required
from web_app import app


@app.route("/comment/<target_type>/<int:target_id>", methods=["POST"])
@csrf_required
@user_required
def add_comment(target_type, target_id):
    """发表评论"""
    if target_type not in ("news", "match"):
        return "无效目标", 400

    if not rate_limit("comment", 10, 60):
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
        if is_ajax:
            return {"success": False, "error": "评论过于频繁，请稍后再试"}, 429
        flash("评论过于频繁，请稍后再试", "error")
        return redirect(safe_redirect_target(url_for("index")))

    content = request.form.get("content", "").strip()
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if not content:
        if is_ajax:
            return {"success": False, "error": "评论内容不能为空"}, 400
        flash("评论内容不能为空", "error")
        if target_type == "news":
            return redirect(url_for("news_detail", news_id=target_id))
        else:
            return redirect(url_for("match_detail", slug=target_id))

    if len(content) > 2000:
        if is_ajax:
            return {"success": False, "error": "评论最多 2000 字"}, 400
        flash("评论最多 2000 字", "error")
        if target_type == "news":
            return redirect(url_for("news_detail", news_id=target_id))
        else:
            return redirect(url_for("match_detail", slug=target_id))

    parent_id = request.form.get("parent_id")
    if parent_id and parent_id.isdigit():
        parent_id = int(parent_id)
    else:
        parent_id = None

    conn = get_db()
    target_table = "news" if target_type == "news" else "matches"
    target_exists = conn.execute(
        f"SELECT id FROM {target_table} WHERE id=?", (target_id,)
    ).fetchone()
    if not target_exists:
        conn.close()
        if is_ajax:
            return {"success": False, "error": "评论目标不存在"}, 404
        return "评论目标不存在", 404

    # 验证父评论存在且属于同一 target
    if parent_id:
        parent_exists = conn.execute(
            "SELECT id FROM comments WHERE id=? AND target_type=? AND target_id=?",
            (parent_id, target_type, target_id),
        ).fetchone()
        if not parent_exists:
            parent_id = None  # 父评论不存在，降级为顶级评论
    conn.execute(
        "INSERT INTO comments(user_id, target_type, target_id, content, parent_id) VALUES(?,?,?,?,?)",
        (session["user_id"], target_type, target_id, content, parent_id),
    )
    new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    if target_type == "news":
        conn.execute("UPDATE news SET comment_count = comment_count + 1 WHERE id=?", (target_id,))

    # 回复通知：通知父评论作者
    if parent_id:
        parent = conn.execute("SELECT user_id FROM comments WHERE id=?", (parent_id,)).fetchone()
        if parent and parent["user_id"] != session["user_id"]:
            reply_username = session.get("user_username", "")
            preview = content[:50] + ("..." if len(content) > 50 else "")
            link = None
            if target_type == "news":
                link = f"/news/{target_id}#comment-{parent_id}"
            elif target_type == "match":
                link = f"/matches/{target_id}#comment-{parent_id}"
            create_notification(
                conn,
                parent["user_id"],
                "reply",
                f"{reply_username} 回复了你的评论：{preview}",
                link,
            )

    conn.commit()

    floor_number = conn.execute(
        "SELECT COUNT(*) FROM comments WHERE target_type=? AND target_id=?",
        (target_type, target_id),
    ).fetchone()[0]

    user = conn.execute(
        "SELECT username, avatar, is_cheater FROM users WHERE id=?", (session["user_id"],)
    ).fetchone()
    conn.close()

    if is_ajax:
        return {
            "success": True,
            "comment": {
                "id": new_id,
                "floor_number": floor_number,
                "user_id": session["user_id"],
                "username": user["username"],
                "avatar": user["avatar"] or "",
                "is_cheater": bool(user["is_cheater"]),
                "content": content,
                "parent_id": parent_id,
                "created_at": "刚刚",
                "like_count": 0,
                "user_liked": 0,
            },
        }

    flash("评论发表成功", "success")
    if target_type == "news":
        return redirect(url_for("news_detail", news_id=target_id))
    else:
        return redirect(url_for("match_detail", slug=target_id))


@app.route("/comment/delete/<int:comment_id>", methods=["POST"])
@csrf_required
def delete_comment(comment_id):
    """删除评论（发布者或管理员）"""
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    conn = get_db()
    comment = conn.execute("SELECT * FROM comments WHERE id=?", (comment_id,)).fetchone()
    if not comment:
        conn.close()
        if is_ajax:
            return {"success": False, "error": "评论不存在"}, 404
        flash("评论不存在", "error")
        return redirect(safe_redirect_target("/"))

    is_author = session.get("user_id") and int(session["user_id"]) == comment["user_id"]
    is_admin = _helper_is_admin()

    if not is_author and not is_admin:
        conn.close()
        if is_ajax:
            return {"success": False, "error": "无权删除此评论"}, 403
        flash("无权删除此评论", "error")
        return redirect(safe_redirect_target("/"))

    # 级联删除：BFS 收集所有子孙评论 ID
    deleted_ids = []
    queue = [comment_id]
    while queue:
        pid = queue.pop(0)
        deleted_ids.append(pid)
        children = conn.execute("SELECT id FROM comments WHERE parent_id=?", (pid,)).fetchall()
        for child in children:
            queue.append(child["id"])

    for cid in deleted_ids:
        conn.execute("DELETE FROM comment_likes WHERE comment_id=?", (cid,))
        conn.execute("DELETE FROM comments WHERE id=?", (cid,))

    total = len(deleted_ids)
    if comment["target_type"] == "news":
        conn.execute(
            "UPDATE news SET comment_count = MAX(0, comment_count - ?) WHERE id=?",
            (total, comment["target_id"]),
        )
    elif comment["target_type"] == "forum_thread":
        last_reply = conn.execute(
            """SELECT user_id, created_at FROM comments
               WHERE target_type='forum_thread' AND target_id=?
               ORDER BY created_at DESC, id DESC LIMIT 1""",
            (comment["target_id"],),
        ).fetchone()
        conn.execute(
            """UPDATE forum_threads
               SET reply_count=(
                       SELECT COUNT(*) FROM comments
                       WHERE target_type='forum_thread' AND target_id=?
                   ),
                   last_reply_at=COALESCE(?, created_at),
                   last_reply_user_id=?
               WHERE id=?""",
            (
                comment["target_id"],
                last_reply["created_at"] if last_reply else None,
                last_reply["user_id"] if last_reply else None,
                comment["target_id"],
            ),
        )
    conn.commit()
    conn.close()

    if is_ajax:
        return {"success": True, "deleted_ids": deleted_ids}
    flash(f"评论及 {total - 1} 条回复已删除", "success")
    return redirect(safe_redirect_target("/"))


@app.route("/comment/like/<int:comment_id>", methods=["POST"])
@csrf_required
def comment_like(comment_id):
    """点赞/取消点赞评论"""
    if "user_id" not in session:
        return jsonify({"success": False, "error": "请先登录"}), 401
    if not rate_limit("like", 30, 60):
        return jsonify({"success": False, "error": "操作过于频繁，请稍后再试"}), 429

    conn = get_db()
    comment = conn.execute("SELECT id FROM comments WHERE id=?", (comment_id,)).fetchone()
    if not comment:
        conn.close()
        return jsonify({"success": False, "error": "评论不存在"}), 404
    existing = conn.execute(
        "SELECT 1 FROM comment_likes WHERE user_id=? AND comment_id=?",
        (session["user_id"], comment_id),
    ).fetchone()

    if existing:
        conn.execute(
            "DELETE FROM comment_likes WHERE user_id=? AND comment_id=?",
            (session["user_id"], comment_id),
        )
        conn.commit()
        count = conn.execute(
            "SELECT COUNT(*) FROM comment_likes WHERE comment_id=?", (comment_id,)
        ).fetchone()[0]
        conn.close()
        return jsonify({"success": True, "liked": False, "count": count})
    else:
        conn.execute(
            "INSERT INTO comment_likes(user_id, comment_id) VALUES(?,?)",
            (session["user_id"], comment_id),
        )
        conn.commit()
        count = conn.execute(
            "SELECT COUNT(*) FROM comment_likes WHERE comment_id=?", (comment_id,)
        ).fetchone()[0]
        conn.close()
        return jsonify({"success": True, "liked": True, "count": count})
