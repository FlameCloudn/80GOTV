"""Notification write helpers shared by comments and forum posts."""


def create_notification(conn, user_id, type, message, link):
    """创建通知"""
    conn.execute(
        "INSERT INTO notifications(user_id, type, message, link) VALUES(?,?,?,?)",
        (user_id, type, message, link),
    )
