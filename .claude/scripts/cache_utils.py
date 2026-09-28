"""
内存缓存工具 — 用字典实现的简单缓存，不依赖第三方库。
用于缓存数据库查询结果，减少重复查询。

使用方法：
    from .claude.scripts.cache_utils import cache_result

    @cache_result(ttl_seconds=300)  # 缓存5分钟
    def get_top_players():
        return db.query("SELECT ...")  # 数据库查询
"""

import functools
import threading
import time


def cache_result(ttl_seconds=300):
    """
    缓存装饰器。在内存中用字典存储函数返回值，TTL（存活时间）过期后自动刷新。

    参数:
        ttl_seconds: 缓存有效期（秒），默认 300 秒（5 分钟）

    特点:
        - 纯字典实现，无需 redis 等外部依赖
        - 线程安全（用锁保护读写）
        - 参数敏感：不同参数分别缓存
        - 可手动清缓存：调用 函数名.cache_clear()
    """
    cache_store = {}  # 缓存存储：{参数key -> (过期时间戳, 返回值)}
    lock = threading.Lock()

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 构建缓存键（函数参数组合的字符串表示）
            cache_key = str(args) + str(sorted(kwargs.items()))

            # 读缓存（线程安全）
            with lock:
                entry = cache_store.get(cache_key)
                if entry is not None:
                    expire_time, cached_value = entry
                    if time.time() < expire_time:
                        return cached_value

            # 缓存未命中或已过期 → 执行原函数
            result = func(*args, **kwargs)

            # 写入缓存（线程安全）
            with lock:
                cache_store[cache_key] = (time.time() + ttl_seconds, result)

            return result

        # 提供手动清缓存的方法
        def cache_clear():
            """清空该函数的所有缓存"""
            with lock:
                cache_store.clear()

        wrapper.cache_clear = cache_clear
        return wrapper

    return decorator


# ===== 使用示例 =====
if __name__ == "__main__":
    import random

    call_count = [0]  # 用列表包装以便在闭包中修改

    @cache_result(ttl_seconds=2)
    def expensive_query(user_id):
        """模拟一个耗时的数据库查询"""
        call_count[0] += 1
        print(f"  → 执行真实查询 (第{call_count[0]}次)")
        return {"user_id": user_id, "score": random.randint(1, 100)}

    print("=== 第1次调用 user_id=1（应触发查询）===")
    print("结果:", expensive_query(1))

    print("\n=== 第2次调用 user_id=1（应命中缓存）===")
    print("结果:", expensive_query(1))

    print("\n=== 调用 user_id=2（不同参数，应触发查询）===")
    print("结果:", expensive_query(2))

    print("\n=== 等待2秒后调用 user_id=1（缓存过期，应触发查询）===")
    time.sleep(2.1)
    print("结果:", expensive_query(1))

    print("\n=== 手动清缓存后调用 user_id=1（应触发查询）===")
    expensive_query.cache_clear()
    print("结果:", expensive_query(1))

    print(f"\n总共执行了 {call_count[0]} 次真实查询")
