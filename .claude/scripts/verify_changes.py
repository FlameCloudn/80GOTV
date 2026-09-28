"""改完代码后快速验证页面是否正常。用法: python verify_changes.py [--all]"""

import os
import sys
import time
import urllib.request

BASE = os.environ.get("PUBLIC_BASE_URL", "http://127.0.0.1:5000").rstrip("/")

# 核心页面（快速检查）
CORE_PAGES = [
    ("/", "首页"),
    ("/matches", "比赛"),
    ("/players", "选手"),
    ("/events", "赛事"),
    ("/news", "新闻"),
    ("/stats", "数据"),
    ("/results", "赛果"),
    ("/teams", "队伍"),
    ("/login", "登录"),
    ("/admin/login", "后台登录"),
]

# 扩展页面（--all 时检查）
EXTRA_PAGES = [
    ("/forum", "论坛"),
]


def check_url(url, name):
    """访问一个页面，返回 (成功?, HTTP状态码, 耗时秒)"""
    start = time.time()
    try:
        req = urllib.request.Request(BASE + url, headers={"User-Agent": "Claude-Verify/1.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        elapsed = time.time() - start
        return True, resp.status, elapsed
    except urllib.error.HTTPError as e:
        elapsed = time.time() - start
        return False, e.code, elapsed
    except Exception as e:
        elapsed = time.time() - start
        return False, str(e)[:50], elapsed


def check_log_for_errors():
    """检查最新日志中的错误"""
    log_file = os.path.join(os.path.dirname(__file__), "..", "..", "logs", "flask.log")
    if not os.path.exists(log_file):
        return None
    with open(log_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    errors = [l.strip() for l in lines if "[ERROR]" in l or "[CRITICAL]" in l]
    return errors[-10:] if errors else []


def main():
    print(f"🔍 检查 {BASE}\n")

    pages = CORE_PAGES
    if "--all" in sys.argv:
        pages += EXTRA_PAGES

    ok, fail = 0, 0
    for url, name in pages:
        success, code, elapsed = check_url(url, name)
        icon = "✅" if success else "❌"
        print(f"  {icon} {name:6s}  {url:25s}  HTTP {code}  {elapsed:.2f}s")
        if success:
            ok += 1
        else:
            fail += 1

    print(f"\n{'=' * 50}")
    print(f"结果: {ok} 个正常, {fail} 个失败")

    # 检查错误日志
    errors = check_log_for_errors()
    if errors:
        print(f"\n⚠️ 日志中有 {len(errors)} 条错误:")
        for e in errors[-5:]:
            print(f"  {e[:120]}")
    elif errors is not None:
        print("📋 日志正常，无错误")
    else:
        print("📋 日志文件不存在（Flask 启动过吗？）")

    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
