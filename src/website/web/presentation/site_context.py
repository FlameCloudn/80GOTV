"""模板共享的头像、队标及会话视图。"""

import logging

from flask import current_app, g, session, url_for

from src.website.domains.community.interactions import unread_notification_count
from src.website.runtime.database import get_db
from src.website.runtime.storage import site_paths
from src.website.runtime.uploads import avatar_static_filename
from src.website.web.presentation.team_logos import team_logo_url

logger = logging.getLogger("80gotv")


def versioned_url(path):
    """给静态文件加版本号防缓存。用法: {{ versioned_url('css/style.css') }}"""
    import os as _os

    if not path.startswith(("/", "http")):
        path = "/" + path
    if path.startswith("/static/") or path.startswith("/resources/"):
        full = _os.path.join(current_app.root_path, path.lstrip("/"))
        if _os.path.exists(full):
            ts = int(_os.path.getmtime(full))
            return f"{path}?v={ts}"
    return path


def team_logo_url_filter(value):
    """队标地址：数据库里各种写法的队标都换成统一地址。用法: {{ team.logo|team_logo_url }}"""
    return team_logo_url(value, site_paths().root)


def avatar_thumbnail_url(filename):
    """列表优先使用小头像；没有小图时自动退回原头像。"""
    static_filename = avatar_static_filename(site_paths().root, filename, thumbnail=True)
    return url_for("static", filename=static_filename) if static_filename else ""


def _csrf_context():
    unread = 0
    current_user_is_cheater = False
    current_user_group_username = ""
    current_user_saved_group_username = ""
    current_user_school_status = None
    if "user_id" in session:
        conn = None
        try:
            conn = get_db()
            unread = unread_notification_count(conn, session["user_id"])
            user_row = getattr(g, "current_user_row", None)
            if user_row is None:
                user_row = conn.execute(
                    """SELECT is_cheater, group_username, is_bashizhong_student
                       FROM users WHERE id=?""",
                    (session["user_id"],),
                ).fetchone()
            current_user_is_cheater = bool(user_row and user_row["is_cheater"])
            current_user_school_status = user_row["is_bashizhong_student"] if user_row else None
            current_user_saved_group_username = (
                (user_row["group_username"] or "") if user_row else ""
            )
            if current_user_school_status != 0:
                current_user_group_username = current_user_saved_group_username
        except Exception:
            logger.exception("读取页面账号信息失败")
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
    return {
        "csrf_token": session.get("csrf_token", ""),
        "unread_count": unread,
        "current_user_is_cheater": current_user_is_cheater,
        "current_user_group_username": current_user_group_username,
        "current_user_saved_group_username": current_user_saved_group_username,
        "current_user_school_status": current_user_school_status,
        "profile_completion_required": bool(session.get("profile_completion_required")),
    }
