"""Signed-in user notification pages and APIs."""

from flask import jsonify, render_template, session

from models import get_db
from utils.web_helpers import csrf_required, user_required
from web_app import app


@app.route("/notifications")
@user_required
def notifications_list():
    """通知列表"""
    conn = get_db()
    notifications = conn.execute(
        "SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 50",
        (session["user_id"],),
    ).fetchall()
    conn.close()
    return render_template("notifications.html", notifications=notifications)


@app.route("/notifications/read/<int:notif_id>", methods=["POST"])
@csrf_required
@user_required
def notification_read(notif_id):
    """标记单条已读"""
    conn = get_db()
    conn.execute(
        "UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?",
        (notif_id, session["user_id"]),
    )
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/notifications/read-all", methods=["POST"])
@csrf_required
@user_required
def notification_read_all():
    """全部已读"""
    conn = get_db()
    conn.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (session["user_id"],))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/notifications/unread-count")
@user_required
def notification_unread_count():
    """AJAX 获取未读数"""
    conn = get_db()
    count = conn.execute(
        "SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0", (session["user_id"],)
    ).fetchone()[0]
    conn.close()
    return jsonify({"count": count})
