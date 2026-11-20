"""公网网站入口，由 Gunicorn 读取。"""

from app import app

__all__ = ["app"]
