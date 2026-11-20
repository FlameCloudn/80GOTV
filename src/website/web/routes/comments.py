"""Comment create, delete and like endpoints."""

from flask import flash, jsonify, redirect, request, session, url_for

from src.website.domains.community import interactions as community
from src.website.runtime.database import db
from src.website.runtime.rate_limiter import rate_limit
from src.website.web.access import csrf_required, is_admin, safe_redirect_target, user_required
from src.website.web.localization import t as ui_message
from src.website.web.routing import site_routes


@site_routes.route("/comment/<target_type>/<int:target_id>", methods=["POST"])
@csrf_required
@user_required
def add_comment(target_type, target_id):
    if target_type not in community.PUBLIC_COMMENT_TARGETS:
        return "无效目标", 400

    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    if not rate_limit("comment", 10, 60):
        message = "评论过于频繁，请稍后再试"
        if is_ajax:
            return {"success": False, "error": message}, 429
        flash(message, "error")
        return redirect(safe_redirect_target(url_for("index")))

    redirect_to = (
        url_for("news_detail", news_id=target_id)
        if target_type == "news"
        else url_for("match_detail", slug=target_id)
    )
    content = request.form.get("content", "").strip()
    message = None
    if not content:
        message = "评论内容不能为空"
    elif len(content) > 2000:
        message = "评论最多 2000 字"
    if message:
        if is_ajax:
            return {"success": False, "error": message}, 400
        flash(message, "error")
        return redirect(redirect_to)

    parent_text = request.form.get("parent_id", "")
    parent_id = int(parent_text) if parent_text.isdecimal() and len(parent_text) <= 19 else None
    if parent_id is not None and parent_id > 2**63 - 1:
        parent_id = None
    try:
        with db() as conn:
            comment = community.publish_comment(
                conn,
                target_type,
                target_id,
                session["user_id"],
                session.get("user_username", ""),
                content,
                parent_id,
            )
    except community.CommunityError as exc:
        if is_ajax:
            return {"success": False, "error": str(exc)}, exc.status
        return str(exc), exc.status

    if is_ajax:
        comment.update(created_at="刚刚", like_count=0, user_liked=0)
        return {"success": True, "comment": comment}
    flash(ui_message("flash.comments.comment_posted"), "success")
    return redirect(redirect_to)


@site_routes.route("/comment/delete/<int:comment_id>", methods=["POST"])
@csrf_required
def delete_comment(comment_id):
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    user_id = session.get("user_id")
    try:
        with db() as conn:
            deleted_ids = community.delete_comment(
                conn,
                comment_id,
                int(user_id) if user_id else None,
                admin=is_admin(),
            )
    except community.CommunityError as exc:
        if is_ajax:
            return {"success": False, "error": str(exc)}, exc.status
        flash(str(exc), "error")
        return redirect(safe_redirect_target("/"))

    if is_ajax:
        return {"success": True, "deleted_ids": deleted_ids}
    flash(
        ui_message(
            "flash.comments.comment_and_value1_replies_deleted", value1=len(deleted_ids) - 1
        ),
        "success",
    )
    return redirect(safe_redirect_target("/"))


@site_routes.route("/comment/like/<int:comment_id>", methods=["POST"])
@csrf_required
def comment_like(comment_id):
    if "user_id" not in session:
        return jsonify({"success": False, "error": "请先登录"}), 401
    if not rate_limit("like", 30, 60):
        return jsonify({"success": False, "error": "操作过于频繁，请稍后再试"}), 429

    try:
        with db() as conn:
            liked, count = community.toggle_comment_like(conn, comment_id, session["user_id"])
    except community.CommunityError as exc:
        return jsonify({"success": False, "error": str(exc)}), exc.status
    return jsonify({"success": True, "liked": liked, "count": count})
