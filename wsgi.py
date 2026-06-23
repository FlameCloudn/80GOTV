"""公网网站入口，由 Gunicorn 读取。"""

from app import app
from models import init_tables

# 每次启动都补齐缺少的数据表；已有资料不会被清空。
init_tables()

__all__ = ["app"]
