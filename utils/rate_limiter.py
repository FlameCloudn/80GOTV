"""服务器端频率限制：按账号或 IP 记录，重放旧登录信息不会重置。"""

import hashlib
import logging
import time

from flask import request, session

from models import get_db

logger = logging.getLogger("80gotv.rate_limit")


def rate_limit(key, max_attempts=5, window_seconds=300, by_ip=False):
    """把检查与计数放在同一笔数据库事务里，避免同时请求突破上限。"""
    now = time.time()
    if by_ip:
        principal = f"ip:{request.remote_addr or 'unknown'}"
    elif session.get("user_id") is not None:
        principal = f"user:{session['user_id']}"
    elif session.get("admin_id") is not None:
        principal = f"admin:{session['admin_id']}"
    else:
        principal = f"ip:{request.remote_addr or 'unknown'}"
    bucket = hashlib.sha256(f"{principal}\0{key}".encode()).hexdigest()
    conn = None
    try:
        conn = get_db()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM request_rate_limits WHERE expires_at<=?", (now,))
        attempts = conn.execute(
            "SELECT COUNT(*) FROM request_rate_limits WHERE bucket=? AND attempted_at>?",
            (bucket, now - window_seconds),
        ).fetchone()[0]
        allowed = attempts < max_attempts
        if allowed:
            conn.execute(
                "INSERT INTO request_rate_limits(bucket,attempted_at,expires_at) VALUES(?,?,?)",
                (bucket, now, now + window_seconds),
            )
        conn.commit()
        return allowed
    except Exception:
        if conn is not None:
            conn.rollback()
        logger.exception("频率限制服务暂不可用，已停止本次操作")
        return False
    finally:
        if conn is not None:
            conn.close()
