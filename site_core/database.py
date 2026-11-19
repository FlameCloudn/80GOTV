"""宿主运行时的数据库连接和事务。建表、升级仍由 models.init_tables 负责。"""

import logging
import os
import sqlite3
from contextlib import contextmanager

from config import Config

logger = logging.getLogger("80gotv")
TURSO_URL = os.environ.get("TURSO_URL", "")
TURSO_TOKEN = os.environ.get("TURSO_TOKEN", "")
_CONFIGURED_DATABASE = Config.DATABASE


def using_turso():
    return bool(
        TURSO_URL
        and TURSO_TOKEN
        and Config.DATABASE == _CONFIGURED_DATABASE
        and os.environ.get("FLASK_ENV", "").strip().lower() != "testing"
    )


def get_db():
    from flask import g, has_request_context

    if using_turso():
        import libsql_experimental as libsql

        conn = libsql.connect(database=TURSO_URL, auth_token=TURSO_TOKEN)
        conn.sync()
    else:
        conn = sqlite3.connect(Config.DATABASE, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA cache_size=-16384")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA mmap_size=67108864")

    if has_request_context():
        g.setdefault("_database_connections", []).append(conn)
    return conn


def close_request_connections(error=None):
    from flask import g

    for conn in g.pop("_database_connections", []):
        try:
            conn.close()
        except Exception:
            logger.exception("请求结束时关闭数据库连接失败")


@contextmanager
def db():
    """自己持有连接的普通读写；成功提交，失败撤销，退出关闭。"""
    conn = get_db()
    try:
        yield conn
        conn.commit()
    except BaseException:
        try:
            conn.rollback()
        except Exception as exc:
            logger.warning("回退数据库操作失败：%s", type(exc).__name__)
        raise
    finally:
        try:
            conn.close()
        except Exception as exc:
            logger.warning("关闭数据库连接失败：%s", type(exc).__name__)


@contextmanager
def write_transaction(conn):
    """先取得写入权再核对状态；组合调用时只释放自己的保存点。"""
    nested = getattr(conn, "in_transaction", False)
    conn.execute("SAVEPOINT site_write" if nested else "BEGIN IMMEDIATE")
    try:
        yield conn
        if nested:
            conn.execute("RELEASE site_write")
        else:
            conn.commit()
    except BaseException:
        if nested:
            conn.execute("ROLLBACK TO site_write")
            conn.execute("RELEASE site_write")
        else:
            conn.rollback()
        raise
