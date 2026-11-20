"""旧通知写入口，实际规则由社区模块维护。"""

from src.website.domains.community.interactions import create_notification

__all__ = ["create_notification"]
