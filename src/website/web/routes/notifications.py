"""Signed-in user notification pages and APIs."""

from flask import jsonify, render_template, session

from src.website.domains.community import interactions as community
from src.website.runtime.database import db
from src.website.web.access import csrf_required, user_required
from src.website.web.routing import site_routes


@site_routes.route("/notifications")
@user_required
def notifications_list():
    """通知列表"""
    with db() as conn:
        notifications = community.list_notifications(conn, session["user_id"], limit=50)
    return render_template("public/account/notifications.html", notifications=notifications)


@site_routes.route("/notifications/read/<int:notif_id>", methods=["POST"])
@csrf_required
@user_required
def notification_read(notif_id):
    """标记单条已读"""
    with db() as conn:
        updated = community.mark_notification_read(conn, session["user_id"], notif_id)
    if not updated:
        return jsonify({"success": False, "error": "通知不存在"}), 404
    return jsonify({"success": True})


@site_routes.route("/notifications/read-all", methods=["POST"])
@csrf_required
@user_required
def notification_read_all():
    """全部已读"""
    with db() as conn:
        community.mark_all_notifications_read(conn, session["user_id"])
    return jsonify({"success": True})


@site_routes.route("/notifications/unread-count")
@user_required
def notification_unread_count():
    """AJAX 获取未读数"""
    with db() as conn:
        count = community.unread_notification_count(conn, session["user_id"])
    return jsonify({"count": count})
