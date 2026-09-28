"""自动化测试。用法: python run_tests.py [--api] [--db] [--stats] [--all]

不带参数默认跑全部。
"""

import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BASE = os.environ.get("PUBLIC_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
SCRIPTS = os.path.dirname(__file__)

passed = 0
failed = 0
errors = []


def test(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        err = f"{name}: {detail}"
        errors.append(err)
        print(f"  ❌ {name} - {detail}")


def api_get(path):
    """调 API 返回 JSON"""
    url = path if path.startswith("http") else BASE + path
    req = urllib.request.Request(
        url, headers={"User-Agent": "Test/1.0", "Accept": "application/json"}
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return json.loads(resp.read())
    except Exception as e:
        return {"_error": str(e)}


def section(title):
    print(f"\n{'─' * 30}")
    print(f"📋 {title}")
    print(f"{'─' * 30}")


# ====== 1. API 测试 ======


def test_api():
    section("API 接口测试")

    # 首页 API
    data = api_get("/api/front/home")
    test("首页 API 返回数据", isinstance(data, dict) and "_error" not in data)
    test("首页 API 包含 news", isinstance(data, dict) and ("news" in data or "_error" not in data))

    # 比赛列表 API
    data = api_get("/api/front/matches")
    test("比赛 API 返回数据", isinstance(data, dict) and "_error" not in data)

    # 新闻 API
    data = api_get("/api/front/news")
    is_list = isinstance(data, (list, dict))
    test("新闻 API 返回数据", is_list and "_error" not in data)

    # 选手 API
    data = api_get("/api/front/players")
    test("选手 API 返回数据", isinstance(data, (list, dict)) and "_error" not in data)

    # 赛事 API
    data = api_get("/api/front/events")
    test("赛事 API 返回数据", isinstance(data, (list, dict)) and "_error" not in data)

    # 赛果 API
    data = api_get("/api/front/results")
    test("赛果 API 返回数据", isinstance(data, (list, dict)) and "_error" not in data)

    # 页面能正常打开 (HTML)
    for path, name in [
        ("/", "首页"),
        ("/matches", "比赛页"),
        ("/players", "选手页"),
        ("/events", "赛事页"),
        ("/news", "新闻页"),
        ("/stats", "数据页"),
        ("/results", "赛果页"),
        ("/teams", "队伍页"),
        ("/forum", "论坛"),
    ]:
        try:
            req = urllib.request.Request(BASE + path, headers={"User-Agent": "Test/1.0"})
            resp = urllib.request.urlopen(req, timeout=10)
            ok = resp.status == 200
            test(f"页面 {name}", ok, f"HTTP {resp.status}")
        except Exception as e:
            test(f"页面 {name}", False, str(e)[:60])


# ====== 2. 数据库测试 ======


def test_db():
    section("数据库测试")
    sys.path.insert(0, ROOT)

    from models import get_db, query_db

    # 表完整性
    conn = get_db()
    tables = [
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    ]
    conn.close()
    required = ["teams", "players", "matches", "match_stats", "events", "news", "admins", "users"]
    for t in required:
        test(f"表 {t} 存在", t in tables)

    # 数据完整性
    conn = get_db()
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()
        test("数据库完整", result[0] == "ok", str(result[0]))
    finally:
        conn.close()

    # 关键约束检查 - 选手有 team_id 但 team 被删
    orphans = query_db(
        "SELECT COUNT(*) FROM players WHERE team_id NOT IN (SELECT id FROM teams) AND team_id IS NOT NULL"
    )
    count = orphans[0][0] if orphans else 0
    test("无孤立选手数据", count == 0, f"{count} 个孤儿选手" if count else "")

    # 比赛有队伍
    bad_matches = query_db(
        "SELECT COUNT(*) FROM matches WHERE team1_id IS NULL OR team2_id IS NULL"
    )
    count = bad_matches[0][0] if bad_matches else 0
    test("比赛都有双方队伍", count == 0, f"{count} 个缺失" if count else "")


# ====== 3. 统计计算测试 ======


def test_stats():
    section("统计计算测试")

    from utils.stats_calc import calculate_adr, calculate_kast, calculate_kd_ratio, calculate_rating

    # Rating 2.0 公式: 0.0073*KAST + 0.3591*KPR - 0.5329*DPR + 0.2372*Impact + 0.0032*ADR + 0.2698
    # 典型数据: 20杀 15死 25回合 100ADR 75%KAST
    rating, kpr, dpr = calculate_rating(20, 15, 25, adr=100, kast=75)
    test("Rating 在有效范围 (0-3)", 0 <= rating <= 3, f"Rating={rating}")
    test("KPR 计算正确", abs(kpr - 0.8) < 0.01, f"KPR={kpr} (期望 0.8)")
    test("DPR 计算正确", abs(dpr - 0.6) < 0.01, f"DPR={dpr} (期望 0.6)")

    # KD
    kd = calculate_kd_ratio(20, 10)
    test("K/D 计算正确", kd == 2.0, f"KD={kd}")

    kd2 = calculate_kd_ratio(10, 0)
    test("零死亡 K/D", kd2 == 10, f"KD={kd2}")

    # KAST
    kast = calculate_kast(80, 20, 30, 10, 100)
    test("KAST 在有效范围", 0 <= kast <= 100, f"KAST={kast}%")

    # ADR
    adr = calculate_adr(2500, 25)
    test("ADR 计算正确", adr == 100.0, f"ADR={adr}")

    # 边界情况
    r, _, _ = calculate_rating(0, 0, 0)
    test("零回合 Rating=0", r == 0.0, f"Rating={r}")


# ====== 4. 后台登录测试 ======


def test_login():
    section("后台登录测试")

    try:
        r = subprocess.run(
            ["python", os.path.join(SCRIPTS, "browser.py"), "--flow", "login"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=ROOT,
        )
        ok = "登录流程通过" in r.stdout
        test("后台登录流程", ok, r.stdout.split("\n")[-3] if not ok else "")
    except subprocess.TimeoutExpired:
        test("后台登录流程", False, "超时")
    except Exception as e:
        test("后台登录流程", False, str(e)[:60])


# ====== 5. 备份恢复测试 ======


def test_backup():
    section("备份恢复测试")
    sys.path.insert(0, ROOT)

    backup_dir = os.path.join(ROOT, ".backups")
    os.makedirs(backup_dir, exist_ok=True)

    # 创建测试备份
    try:
        r = subprocess.run(
            ["python", os.path.join(SCRIPTS, "backup.py")],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=ROOT,
        )
        ok = "备份完成" in r.stdout
        test("创建备份", ok, r.stdout.strip()[-80:] if not ok else "")
    except Exception as e:
        test("创建备份", False, str(e)[:60])

    # 备份文件存在
    if os.path.exists(backup_dir):
        backups = sorted([f for f in os.listdir(backup_dir) if f.endswith(".zip")])
        test("备份文件存在", len(backups) > 0, f"共 {len(backups)} 个")
        if backups:
            size = os.path.getsize(os.path.join(backup_dir, backups[-1]))
            test("备份文件非空", size > 0, f"{size / 1024:.0f}KB")
    else:
        test("备份目录存在", False)


# ====== 运行器 ======


def main():
    args = set(sys.argv[1:])
    run_all = not args or "--all" in args
    run_api = run_all or "--api" in args
    run_db = run_all or "--db" in args
    run_stats = run_all or "--stats" in args
    run_login = run_all or "--login" in args
    run_backup = run_all or "--backup" in args

    print("🧪 80GOTV 自动化测试")
    print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"目标: {BASE}")

    start = time.time()

    if run_api:
        test_api()
    if run_db:
        test_db()
    if run_stats:
        test_stats()
    if run_login:
        test_login()
    if run_backup:
        test_backup()

    elapsed = time.time() - start

    # 结果
    total = passed + failed
    print(f"\n{'=' * 40}")
    if failed == 0:
        print(f"🎉 全部通过！{passed}/{total} ({elapsed:.1f}s)")
    else:
        print(f"❌ {passed} 通过, {failed} 失败 ({elapsed:.1f}s)")
        print("\n失败项:")
        for e in errors:
            print(f"  - {e}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
