"""Admin Blueprint assembly entry."""

import logging

from flask import Blueprint, session

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")
logger = logging.getLogger(__name__)

# 待审核账号的口径和后台首页一致：占位账号只有验证过邮箱（认领）才算
PENDING_USERS_SQL = """SELECT COUNT(*) AS cnt FROM users
    WHERE approval_status='pending' AND (is_placeholder=0 OR email_verified_at IS NOT NULL)"""
# 待处理反馈：还没标成已处理 / 已关闭的
OPEN_FEEDBACK_SQL = (
    "SELECT COUNT(*) AS cnt FROM feedback WHERE COALESCE(status, 'open') IN ('open', 'reviewing')"
)


@admin_bp.context_processor
def admin_nav_counts():
    """后台左侧导航上的待办数量（只读）。没登录后台时不查；查询失败只是不显示数字，不影响页面。"""
    if not session.get("admin_id"):
        return {"admin_nav_counts": {}}
    from models import get_db  # noqa: PLC0415

    conn = None
    try:
        conn = get_db()
        return {
            "admin_nav_counts": {
                "pending_users": conn.execute(PENDING_USERS_SQL).fetchone()["cnt"],
                "open_feedback": conn.execute(OPEN_FEEDBACK_SQL).fetchone()["cnt"],
            }
        }
    except Exception:
        logger.exception("读取后台待办数量失败")
        return {"admin_nav_counts": {}}
    finally:
        if conn is not None:
            conn.close()


# Importing these modules registers their pages on admin_bp.
from blueprints import (  # noqa: E402,F401
    admin_catalog,
    admin_core,
    admin_events,
    admin_matches,
    admin_news,
    admin_operations,
)
