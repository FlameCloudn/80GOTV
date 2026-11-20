"""Public and account-bound JSON contracts for news, forum, and notifications."""

from contextlib import closing

from flask import jsonify, request, session, url_for

from src.website.domains.community import interactions as community
from src.website.domains.matches.opponents import supplement_temp_teams
from src.website.runtime.database import get_db
from src.website.web.presentation.filters import datetime_display_filter
from src.website.web.read_models.front_payloads import (
    _SQL_EFFECTIVE_STATUS,
    _avatar_url,
    _comment_payload,
    _get,
    _match_payload,
    _news_payload,
    _page_params,
    _text,
    _user_display_name,
)
from src.website.web.routing import site_routes


@site_routes.route("/api/front/news")
def api_front_news():
    """News list data."""
    page, per_page, offset = _page_params(default=20, maximum=80)
    conn = get_db()
    rows = conn.execute(
        """SELECT n.*, (SELECT COUNT(*) FROM comments c
                           WHERE c.target_type='news' AND c.target_id=n.id) AS actual_comment_count
           FROM news n ORDER BY n.publish_time DESC, n.id DESC LIMIT ? OFFSET ?""",
        (per_page, offset),
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) AS cnt FROM news").fetchone()["cnt"]
    conn.close()
    return jsonify(
        {
            "ok": True,
            "page": page,
            "per_page": per_page,
            "total": total,
            "news": [_news_payload(row) for row in rows],
        }
    )


@site_routes.route("/api/front/news/<int:news_id>")
def api_front_news_detail(news_id):
    """News detail with comments."""
    conn = get_db()
    news = conn.execute(
        """SELECT n.*, (SELECT COUNT(*) FROM comments c
                           WHERE c.target_type='news' AND c.target_id=n.id) AS actual_comment_count
           FROM news n WHERE n.id=?""",
        (news_id,),
    ).fetchone()
    if not news:
        conn.close()
        return jsonify({"ok": False, "error": "新闻不存在"}), 404
    related_match = None
    if news["related_match_id"]:
        related_match = conn.execute(
            f"""
            SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
                   t1.short_name AS t1s, t2.short_name AS t2s, e.name AS event_name,
                   {_SQL_EFFECTIVE_STATUS}
            FROM matches m
            LEFT JOIN teams t1 ON m.team1_id=t1.id
            LEFT JOIN teams t2 ON m.team2_id=t2.id
            LEFT JOIN events e ON m.event_id=e.id
            WHERE m.id=?
        """,
            (news["related_match_id"],),
        ).fetchone()
        if related_match:
            related_match = supplement_temp_teams(related_match, conn)
    comments = community.list_comments(conn, "news", news_id)
    conn.close()
    payload = _news_payload(news)
    payload["content"] = _text(news["content"])
    payload["related_match"] = _match_payload(related_match) if related_match else None
    payload["comments"] = [_comment_payload(row) for row in comments]
    return jsonify({"ok": True, "news": payload})


@site_routes.route("/api/front/forum")
def api_front_forum():
    """Forum thread list."""
    page, per_page, _ = _page_params(default=25, maximum=80)
    search_query = request.args.get("q", "").strip()
    category_slug = request.args.get("category", "").strip()
    sort_by = request.args.get("sort", "latest").strip()
    with closing(get_db()) as conn:
        categories = community.list_forum_categories(conn)
        rows, total, _, _ = community.list_forum_threads(
            conn,
            search_query=search_query,
            category_slug=category_slug,
            sort_by=sort_by,
            page=page,
            per_page=per_page,
        )
    return jsonify(
        {
            "ok": True,
            "page": page,
            "per_page": per_page,
            "total": total,
            "categories": [
                {
                    "name": _text(row["name"]),
                    "slug": _text(row["slug"]),
                    "thread_count": row["thread_count"],
                }
                for row in categories
            ],
            "threads": [
                {
                    "id": row["id"],
                    "url": url_for("forum_thread", thread_id=row["id"]),
                    "title": _text(row["title"]),
                    "author": _user_display_name(
                        row["username"], _get(row, "group_username"), row["user_id"]
                    ),
                    "author_username": _text(row["username"]),
                    "author_is_cheater": bool(_get(row, "is_cheater", 0)),
                    "avatar": _avatar_url(_get(row, "avatar", "")),
                    "category": _text(row["category_name"]),
                    "category_slug": _text(row["category_slug"]),
                    "pinned": bool(row["is_pinned"]),
                    "locked": bool(row["is_locked"]),
                    "views": row["view_count"],
                    "replies": row["reply_count"],
                    "created_at": datetime_display_filter(row["created_at"])
                    if row["created_at"]
                    else "",
                    "last_reply_at": datetime_display_filter(row["last_reply_at"])
                    if row["last_reply_at"]
                    else "",
                    "last_reply_user": _user_display_name(
                        _get(row, "last_reply_username", ""),
                        _get(row, "last_reply_group_username"),
                        _get(row, "last_reply_user_id"),
                    ),
                    "last_reply_is_cheater": bool(_get(row, "last_reply_is_cheater", 0)),
                }
                for row in rows
            ],
        }
    )


@site_routes.route("/api/front/notifications")
def api_front_notifications():
    """Current user's notification summary."""
    if "user_id" not in session:
        return jsonify({"ok": True, "authenticated": False, "unread": 0, "notifications": []})
    with closing(get_db()) as conn:
        rows = community.list_notifications(conn, session["user_id"], limit=20)
        unread = community.unread_notification_count(conn, session["user_id"])
    return jsonify(
        {
            "ok": True,
            "authenticated": True,
            "unread": unread,
            "notifications": [
                {
                    "id": row["id"],
                    "type": _text(_get(row, "type", "")),
                    "message": _text(_get(row, "message", "")),
                    "url": _text(_get(row, "link", "")),
                    "read": bool(_get(row, "is_read", 0)),
                    "created_at": datetime_display_filter(row["created_at"])
                    if row["created_at"]
                    else "",
                }
                for row in rows
            ],
        }
    )
