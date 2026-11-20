"""Admin Blueprint assembly entry."""

import logging

from flask import Blueprint, session

from src.website.domains.community.feedback import count_open_feedback

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")
logger = logging.getLogger(__name__)

# 待审核账号的口径和后台首页一致：占位账号只有验证过邮箱（认领）才算
PENDING_USERS_SQL = """SELECT COUNT(*) AS cnt FROM users
    WHERE approval_status='pending' AND (is_placeholder=0 OR email_verified_at IS NOT NULL)"""


@admin_bp.context_processor
def admin_nav_counts():
    """后台左侧导航上的待办数量（只读）。没登录后台时不查；查询失败只是不显示数字，不影响页面。"""
    if not session.get("admin_id"):
        return {"admin_nav_counts": {}}
    from src.website.runtime.database import get_db  # noqa: PLC0415

    conn = None
    try:
        conn = get_db()
        return {
            "admin_nav_counts": {
                "pending_users": conn.execute(PENDING_USERS_SQL).fetchone()["cnt"],
                "open_feedback": count_open_feedback(conn),
            }
        }
    except Exception:
        logger.exception("读取后台待办数量失败")
        return {"admin_nav_counts": {}}
    finally:
        if conn is not None:
            conn.close()


# Importing these modules registers their pages on admin_bp.
from src.website.web.admin import (  # noqa: E402,F401
    admin_core,
    admin_events,
    admin_matches,
    admin_news,
    admin_players,
    admin_teams,
    event_awards,
    event_brackets,
    event_registration,
    match_demo_import,
    match_operations,
    match_statistics,
    site_maintenance,
)
