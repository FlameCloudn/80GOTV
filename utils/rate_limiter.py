"""频率限制器：限制短时间内重复操作，支持 IP 级和 session 级。"""

import threading
from datetime import datetime

from flask import request, session

_IP_RATE_LIMITS = {}
_IP_RATE_LIMIT_LOCK = threading.Lock()


def rate_limit(key, max_attempts=5, window_seconds=300, by_ip=False):
    """限制短时间内重复操作；登录类入口使用服务端记录。"""
    now = datetime.now().timestamp()
    if by_ip:
        bucket = f"{key}:{request.remote_addr or 'unknown'}"
        with _IP_RATE_LIMIT_LOCK:
            attempts = [t for t in _IP_RATE_LIMITS.get(bucket, []) if now - t < window_seconds]
            if len(attempts) >= max_attempts:
                _IP_RATE_LIMITS[bucket] = attempts
                return False
            attempts.append(now)
            _IP_RATE_LIMITS[bucket] = attempts
            if len(_IP_RATE_LIMITS) > 5000:
                oldest = sorted(
                    _IP_RATE_LIMITS,
                    key=lambda name: _IP_RATE_LIMITS[name][-1] if _IP_RATE_LIMITS[name] else 0,
                )[:1000]
                for name in oldest:
                    _IP_RATE_LIMITS.pop(name, None)
        return True

    attempts = session.get(f"_rl_{key}", [])
    attempts = [t for t in attempts if now - t < window_seconds]
    if len(attempts) >= max_attempts:
        return False
    attempts.append(now)
    session[f"_rl_{key}"] = attempts
    return True
