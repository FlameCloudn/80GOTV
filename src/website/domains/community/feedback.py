"""Store submitted site feedback and read or resolve it for administrators."""

_OPEN = "COALESCE(status, 'open') IN ('open', 'reviewing')"


def submit_feedback(conn, *, kind, content, contact, page_path, user_agent, user_id):
    conn.execute(
        """INSERT INTO feedback (type, content, contact, page_url, user_agent, user_id)
           VALUES (?,?,?,?,?,?)""",
        (kind, content, contact, page_path, user_agent, user_id),
    )


def list_feedback(conn):
    return conn.execute(
        "SELECT f.*, COALESCE(u.username,'匿名') as username FROM feedback f"
        " LEFT JOIN users u ON f.user_id=u.id ORDER BY f.created_at DESC LIMIT 200"
    ).fetchall()


def recent_open_feedback(conn):
    return conn.execute(
        f"""SELECT id, type, content, page_url, created_at FROM feedback
            WHERE {_OPEN} ORDER BY created_at DESC LIMIT 4"""
    ).fetchall()


def count_open_feedback(conn):
    return conn.execute(f"SELECT COUNT(*) AS cnt FROM feedback WHERE {_OPEN}").fetchone()["cnt"]


def update_feedback(conn, feedback_id, status, reply):
    if not conn.execute("SELECT id FROM feedback WHERE id=?", (feedback_id,)).fetchone():
        return False
    conn.execute(
        "UPDATE feedback SET status=?, admin_reply=? WHERE id=?", (status, reply, feedback_id)
    )
    return True
