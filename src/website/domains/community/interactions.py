"""评论、论坛和通知的业务规则。提交或回滚由调用方负责。"""

from collections import deque
from collections.abc import Callable
from typing import Literal

PublicCommentTarget = Literal["news", "match"]
CommentTarget = Literal["news", "match", "forum_thread"]

PUBLIC_COMMENT_TARGETS = {
    "news": ("news", "/news"),
    "match": ("matches", "/matches"),
}

FORUM_SORT_ORDERS = {
    "latest": "t.is_pinned DESC, COALESCE(t.last_reply_at, t.created_at) DESC, t.id DESC",
    "newest": "t.is_pinned DESC, t.created_at DESC, t.id DESC",
    "popular": "t.is_pinned DESC, (t.reply_count * 8 + t.view_count) DESC, COALESCE(t.last_reply_at, t.created_at) DESC",
}

_FORUM_ACTIONS = {
    "pin": ("is_pinned", 1, "帖子已置顶"),
    "unpin": ("is_pinned", 0, "已取消置顶"),
    "lock": ("is_locked", 1, "帖子已锁定"),
    "unlock": ("is_locked", 0, "帖子已解锁"),
}


class CommunityError(ValueError):
    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


def list_comments(
    conn,
    target_type: CommentTarget,
    target_id: int,
    user_id: int | None = None,
    *,
    limit: int = -1,
    offset: int = 0,
):
    return conn.execute(
        """SELECT c.*, u.username,
                  CASE WHEN COALESCE(u.is_bashizhong_student, 1)<>0
                       THEN u.group_username END AS group_username,
                  u.avatar, u.is_cheater,
                  (SELECT COUNT(*) FROM comment_likes WHERE comment_id=c.id) AS like_count,
                  (SELECT 1 FROM comment_likes WHERE comment_id=c.id AND user_id=?) AS user_liked
           FROM comments c JOIN users u ON c.user_id=u.id
           WHERE c.target_type=? AND c.target_id=?
           ORDER BY c.created_at, c.id LIMIT ? OFFSET ?""",
        (user_id, target_type, target_id, limit, offset),
    ).fetchall()


def count_comments(conn, target_type: CommentTarget, target_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM comments WHERE target_type=? AND target_id=?",
        (target_type, target_id),
    ).fetchone()[0]


def build_comment_tree(comments):
    """按整页顺序给评论编号，回复依然保留自己的楼层。"""
    tree = []
    lookup = {}
    for floor_number, row in enumerate(comments, start=1):
        comment = dict(row, replies=[], floor_number=floor_number)
        lookup[comment["id"]] = comment

    for comment in lookup.values():
        parent = lookup.get(comment.get("parent_id"))
        if parent:
            parent["replies"].append(comment)
        else:
            tree.append(comment)

    def mark_depth(comment, depth):
        comment["depth"] = depth
        for reply in comment["replies"]:
            mark_depth(reply, depth + 1)

    for comment in tree:
        mark_depth(comment, 0)
    return tree


def _insert_comment(
    conn,
    target_type: CommentTarget,
    target_id: int,
    user_id: int,
    content: str,
    parent_id: int | None = None,
) -> int:
    return conn.execute(
        "INSERT INTO comments(user_id, target_type, target_id, content, parent_id) VALUES(?,?,?,?,?)",
        (user_id, target_type, target_id, content, parent_id),
    ).lastrowid


def _set_news_comment_count(conn, news_id: int, count: int):
    conn.execute("UPDATE news SET comment_count=? WHERE id=?", (count, news_id))


def publish_comment(
    conn,
    target_type: PublicCommentTarget,
    target_id: int,
    user_id: int,
    username: str,
    content: str,
    parent_id: int | None,
):
    table, path = PUBLIC_COMMENT_TARGETS[target_type]
    if not conn.execute(f"SELECT 1 FROM {table} WHERE id=?", (target_id,)).fetchone():
        raise CommunityError("评论目标不存在", 404)

    parent = None
    if parent_id is not None:
        parent = conn.execute(
            "SELECT id, user_id FROM comments WHERE id=? AND target_type=? AND target_id=?",
            (parent_id, target_type, target_id),
        ).fetchone()
    parent_id = parent["id"] if parent else None
    comment_id = _insert_comment(conn, target_type, target_id, user_id, content, parent_id)
    floor_number = count_comments(conn, target_type, target_id)
    if target_type == "news":
        _set_news_comment_count(conn, target_id, floor_number)
    if parent and parent["user_id"] != user_id:
        _notify_reply(
            conn,
            parent["user_id"],
            "reply",
            f"{username} 回复了你的评论：",
            content,
            f"{path}/{target_id}#comment-{parent_id}",
        )

    author = conn.execute(
        """SELECT username, group_username, avatar, is_cheater, is_bashizhong_student
           FROM users WHERE id=?""",
        (user_id,),
    ).fetchone()
    return {
        "id": comment_id,
        "floor_number": floor_number,
        "user_id": user_id,
        "username": author["username"],
        "group_username": (author["group_username"] or "")
        if author["is_bashizhong_student"] != 0
        else "",
        "avatar": author["avatar"] or "",
        "is_cheater": bool(author["is_cheater"]),
        "content": content,
        "parent_id": parent_id,
    }


def delete_comment(conn, comment_id: int, user_id: int | None, *, admin: bool) -> list[int]:
    comment = conn.execute(
        "SELECT user_id, target_type, target_id FROM comments WHERE id=?", (comment_id,)
    ).fetchone()
    if not comment:
        raise CommunityError("评论不存在", 404)
    if not admin and user_id != comment["user_id"]:
        raise CommunityError("无权删除此评论", 403)

    target_type, target_id = comment["target_type"], comment["target_id"]
    pending = deque([comment_id])
    deleted_ids = []
    while pending:
        parent_id = pending.popleft()
        deleted_ids.append(parent_id)
        pending.extend(
            row["id"]
            for row in conn.execute(
                "SELECT id FROM comments WHERE parent_id=? AND target_type=? AND target_id=?",
                (parent_id, target_type, target_id),
            )
        )

    ids = [(deleted_id,) for deleted_id in deleted_ids]
    conn.executemany("DELETE FROM comment_likes WHERE comment_id=?", ids)
    conn.executemany("DELETE FROM comments WHERE id=?", ids)
    if target_type == "news":
        _set_news_comment_count(conn, target_id, count_comments(conn, target_type, target_id))
    elif target_type == "forum_thread":
        last_reply = conn.execute(
            """SELECT user_id, created_at FROM comments
               WHERE target_type='forum_thread' AND target_id=?
               ORDER BY created_at DESC, id DESC LIMIT 1""",
            (target_id,),
        ).fetchone()
        conn.execute(
            """UPDATE forum_threads SET reply_count=?, last_reply_at=COALESCE(?, created_at),
                       last_reply_user_id=? WHERE id=?""",
            (
                count_comments(conn, target_type, target_id),
                last_reply["created_at"] if last_reply else None,
                last_reply["user_id"] if last_reply else None,
                target_id,
            ),
        )
    return deleted_ids


def delete_target_comments(conn, target_type: CommentTarget, target_id: int):
    """由新闻、比赛或帖子删除操作调用，保持在原操作的事务内。"""
    conn.execute(
        """DELETE FROM comment_likes WHERE comment_id IN (
               SELECT id FROM comments WHERE target_type=? AND target_id=?
           )""",
        (target_type, target_id),
    )
    conn.execute(
        "DELETE FROM comments WHERE target_type=? AND target_id=?", (target_type, target_id)
    )


def toggle_comment_like(conn, comment_id: int, user_id: int) -> tuple[bool, int]:
    if not conn.execute("SELECT 1 FROM comments WHERE id=?", (comment_id,)).fetchone():
        raise CommunityError("评论不存在", 404)
    removed = conn.execute(
        "DELETE FROM comment_likes WHERE user_id=? AND comment_id=?", (user_id, comment_id)
    ).rowcount
    if not removed:
        conn.execute(
            "INSERT INTO comment_likes(user_id, comment_id) VALUES(?,?)", (user_id, comment_id)
        )
    count = conn.execute(
        "SELECT COUNT(*) FROM comment_likes WHERE comment_id=?", (comment_id,)
    ).fetchone()[0]
    return not removed, count


def list_forum_categories(conn):
    return conn.execute(
        """SELECT c.*, COUNT(t.id) AS thread_count
           FROM forum_categories c LEFT JOIN forum_threads t ON t.category_id=c.id
           GROUP BY c.id ORDER BY c.sort_order, c.id"""
    ).fetchall()


def list_forum_threads(
    conn,
    *,
    search_query: str,
    category_slug: str,
    sort_by: str,
    page: int,
    per_page: int,
    user_id: int | None = None,
    clamp_page: bool = False,
):
    clauses = []
    params = []
    if search_query:
        clauses.append("(t.title LIKE ? OR t.content LIKE ?)")
        params.extend((f"%{search_query}%", f"%{search_query}%"))
    if category_slug:
        clauses.append("c.slug=?")
        params.append(category_slug)
    if user_id is not None:
        clauses.append("t.user_id=?")
        params.append(user_id)
    where_sql = " AND ".join(clauses) if clauses else "1=1"
    order_sql = FORUM_SORT_ORDERS.get(sort_by, FORUM_SORT_ORDERS["latest"])
    total = conn.execute(
        f"""SELECT COUNT(*) FROM forum_threads t
            JOIN forum_categories c ON t.category_id=c.id WHERE {where_sql}""",
        params,
    ).fetchone()[0]
    total_pages = (total + per_page - 1) // per_page
    if clamp_page:
        page = min(max(1, page), max(1, total_pages))
    rows = conn.execute(
        f"""SELECT t.*, c.name AS category_name, c.slug AS category_slug,
                   u.username,
                   CASE WHEN COALESCE(u.is_bashizhong_student, 1)<>0
                        THEN u.group_username END AS group_username,
                   u.avatar, u.is_cheater,
                   lr.username AS last_reply_username,
                   CASE WHEN COALESCE(lr.is_bashizhong_student, 1)<>0
                        THEN lr.group_username END AS last_reply_group_username,
                   lr.is_cheater AS last_reply_is_cheater
            FROM forum_threads t
            JOIN forum_categories c ON t.category_id=c.id
            JOIN users u ON t.user_id=u.id
            LEFT JOIN users lr ON lr.id=t.last_reply_user_id
            WHERE {where_sql} ORDER BY {order_sql} LIMIT ? OFFSET ?""",
        (*params, per_page, (page - 1) * per_page),
    ).fetchall()
    return rows, total, page, total_pages


def visit_forum_thread(conn, thread_id: int):
    thread = conn.execute(
        """SELECT t.*, c.name AS category_name, c.slug AS category_slug,
                  u.username,
                  CASE WHEN COALESCE(u.is_bashizhong_student, 1)<>0
                       THEN u.group_username END AS group_username,
                  u.avatar, u.is_cheater
           FROM forum_threads t JOIN forum_categories c ON t.category_id=c.id
           JOIN users u ON t.user_id=u.id WHERE t.id=?""",
        (thread_id,),
    ).fetchone()
    if not thread:
        raise CommunityError("帖子不存在", 404)
    conn.execute("UPDATE forum_threads SET view_count=view_count+1 WHERE id=?", (thread_id,))
    return thread


def _require_forum_thread(conn, thread_id: int):
    thread = conn.execute("SELECT * FROM forum_threads WHERE id=?", (thread_id,)).fetchone()
    if not thread:
        raise CommunityError("帖子不存在", 404)
    return thread


def can_manage_thread(thread, user_id: int | None, *, admin: bool) -> bool:
    return admin or user_id == thread["user_id"]


def get_editable_thread(conn, thread_id: int, user_id: int | None, *, admin: bool):
    thread = _require_forum_thread(conn, thread_id)
    if not user_id and not admin:
        raise CommunityError("请先登录", 401)
    if not can_manage_thread(thread, user_id, admin=admin):
        raise CommunityError("无权编辑此帖子", 403)
    return thread


def _require_category(conn, category_id: int | None, use_default: bool = False) -> int:
    if use_default:
        category = conn.execute(
            "SELECT id FROM forum_categories ORDER BY sort_order, id LIMIT 1"
        ).fetchone()
    else:
        category = conn.execute(
            "SELECT id FROM forum_categories WHERE id=?", (category_id,)
        ).fetchone()
    if not category:
        raise CommunityError("请选择有效的论坛版块", 400)
    return category["id"]


def create_forum_thread(
    conn,
    user_id: int,
    title: str,
    content: str,
    category_id: int | None,
    *,
    use_default_category: bool,
) -> int:
    if not title or not content:
        raise CommunityError("请填写标题和内容", 400)
    if len(title) > 120:
        raise CommunityError("标题最多 120 字", 400)
    if len(content) > 10000:
        raise CommunityError("内容最多 10000 字", 400)

    category_id = _require_category(conn, category_id, use_default_category)
    return conn.execute(
        """INSERT INTO forum_threads(category_id, user_id, title, content, last_reply_at)
           VALUES(?,?,?,?,CURRENT_TIMESTAMP)""",
        (category_id, user_id, title, content),
    ).lastrowid


def edit_forum_thread(
    conn,
    thread_id: int,
    user_id: int | None,
    title: str,
    content: str,
    category_id: int | None,
    *,
    admin: bool,
):
    get_editable_thread(conn, thread_id, user_id, admin=admin)
    if not title or not content:
        raise CommunityError("请填写标题和内容", 400)
    if len(title) > 120 or len(content) > 10000:
        raise CommunityError("标题最多 120 字，内容最多 10000 字", 400)
    category_id = _require_category(conn, category_id)
    conn.execute(
        "UPDATE forum_threads SET title=?, content=?, category_id=? WHERE id=?",
        (title, content, category_id, thread_id),
    )


def manage_forum_thread(
    conn, thread_id: int, action: str, user_id: int | None, *, admin: bool
) -> str:
    thread = _require_forum_thread(conn, thread_id)
    if action in _FORUM_ACTIONS:
        if not admin:
            raise CommunityError("仅管理员可执行此操作", 403)
        column, enabled, message = _FORUM_ACTIONS[action]
        conn.execute(f"UPDATE forum_threads SET {column}=? WHERE id=?", (enabled, thread_id))
        return message

    if action != "delete":
        raise CommunityError("无效操作", 400)
    if not admin and not (thread["user_id"] == user_id and not thread["reply_count"]):
        raise CommunityError("有回复的帖子只能由管理员删除", 403)
    delete_target_comments(conn, "forum_thread", thread_id)
    conn.execute("DELETE FROM forum_threads WHERE id=?", (thread_id,))
    link = f"/forum/t/{thread_id}"
    conn.execute("DELETE FROM notifications WHERE link=? OR link LIKE ?", (link, f"{link}#%"))
    return "帖子已删除"


def publish_forum_reply(
    conn,
    thread_id: int,
    user_id: int,
    username: str,
    content: str,
    *,
    consume_quota: Callable[[], bool],
):
    thread = _require_forum_thread(conn, thread_id)
    if thread["is_locked"]:
        raise CommunityError("该帖子已锁定，无法回复", 409)
    if not content:
        raise CommunityError("回复内容不能为空", 400)
    if len(content) > 5000:
        raise CommunityError("回复最多 5000 字", 400)
    if not consume_quota():
        raise CommunityError("回复过于频繁，请稍后再试", 429)

    _insert_comment(conn, "forum_thread", thread_id, user_id, content)
    conn.execute(
        """UPDATE forum_threads SET reply_count=reply_count+1, last_reply_at=CURRENT_TIMESTAMP,
                   last_reply_user_id=? WHERE id=?""",
        (user_id, thread_id),
    )
    if thread["user_id"] != user_id:
        _notify_reply(
            conn,
            thread["user_id"],
            "forum_reply",
            f"{username} 回复了你的帖子《{thread['title']}》：",
            content,
            f"/forum/t/{thread_id}",
        )


def create_notification(conn, user_id: int, type: str, message: str, link: str | None):
    conn.execute(
        "INSERT INTO notifications(user_id, type, message, link) VALUES(?,?,?,?)",
        (user_id, type, message, link),
    )


def _notify_reply(conn, user_id: int, notice_type: str, prefix: str, content: str, link: str):
    preview = content[:50] + ("..." if len(content) > 50 else "")
    create_notification(conn, user_id, notice_type, prefix + preview, link)


def list_notifications(conn, user_id: int, *, limit: int):
    return conn.execute(
        "SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()


def unread_notification_count(conn, user_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0", (user_id,)
    ).fetchone()[0]


def mark_notification_read(conn, user_id: int, notif_id: int) -> bool:
    return (
        conn.execute(
            "UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?", (notif_id, user_id)
        ).rowcount
        == 1
    )


def mark_all_notifications_read(conn, user_id: int):
    conn.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (user_id,))
