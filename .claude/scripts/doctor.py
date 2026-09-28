"""一键体检：检查网站各项指标，出具健康报告。用法: python doctor.py"""

import datetime
import os
import subprocess
import sys
import urllib.request

BASE = os.environ.get("PUBLIC_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.dirname(__file__)

results = {"ok": 0, "warn": 0, "fail": 0}
start_time = datetime.datetime.now()


def check(name, ok, detail=""):
    if ok:
        results["ok"] += 1
        print(f"  ok {name} {detail}")
    elif ok is None:
        results["warn"] += 1
        print(f"  ?? {name} {detail}")
    else:
        results["fail"] += 1
        print(f"  !! {name} {detail}")


print("== 80GOTV ==")

# 1. Flask
print("\n-- 服务")
try:
    req = urllib.request.Request(BASE + "/", headers={"User-Agent": "Doctor/1.0"})
    resp = urllib.request.urlopen(req, timeout=5)
    check("Flask", resp.status == 200, "HTTP " + str(resp.status))
except Exception as e:
    check("Flask", False, str(e)[:60])
    print("  Flask not running, stop.")
    sys.exit(1)

# 2. Database
print("\n-- 数据库")
sys.path.insert(0, ROOT)
os.chdir(ROOT)
try:
    from models import get_db, query_db

    conn = get_db()
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    conn.close()
    check("库文件", True, str(len(tables)) + "表")

    conn2 = get_db()
    ok_db = conn2.execute("PRAGMA integrity_check").fetchone()
    conn2.close()
    check("完整性", ok_db[0] == "ok")

    orphans = query_db(
        "SELECT COUNT(*) FROM players WHERE team_id NOT IN (SELECT id FROM teams) AND team_id IS NOT NULL"
    )
    check("无孤儿选手", orphans[0][0] == 0)

    bad_matches = query_db(
        "SELECT COUNT(*) FROM matches WHERE team1_id IS NULL OR team2_id IS NULL"
    )
    bad_count = bad_matches[0][0] if bad_matches else 0
    check("比赛队伍完整", bad_count == 0, str(bad_count) + "缺" if bad_count else "")
except Exception as e:
    check("数据库", False, str(e)[:60])

# 3. Pages
print("\n-- 页面")
pages = [
    ("/", "首页"),
    ("/matches", "比赛"),
    ("/players", "选手"),
    ("/events", "赛事"),
    ("/news", "新闻"),
    ("/stats", "数据"),
    ("/results", "赛果"),
    ("/teams", "队伍"),
    ("/admin/login", "后台登录"),
    ("/forum", "论坛"),
]
for path, name in pages:
    try:
        req = urllib.request.Request(BASE + path, headers={"User-Agent": "Doc/1"})
        resp = urllib.request.urlopen(req, timeout=10)
        check(name, resp.status == 200, path)
    except Exception as e:
        check(name, False, str(e)[:40])

# 4. Admin login
print("\n-- 后台登录")
try:
    r = subprocess.run(
        ["python", os.path.join(SCRIPTS, "browser.py"), "--flow", "login"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=ROOT,
    )
    check("登录", "登录流程通过" in r.stdout)
except Exception as e:
    check("登录", None, str(e)[:40])

# 5. Error log
print("\n-- 错误日志")
logp = os.path.join(ROOT, "logs", "flask.log")
if os.path.exists(logp):
    with open(logp, "r", encoding="utf-8") as f:
        lines = f.readlines()
    today = start_time.strftime("%Y-%m-%d")
    recent_err = [l for l in lines if "[ERROR]" in l or "[CRITICAL]" in l]
    recent_err = [l for l in recent_err if today in l]
    check("近期错误", len(recent_err) == 0, str(len(recent_err)) + "条" if recent_err else "无")
else:
    check("日志文件", None, "不存在")

# 6. Backup
print("\n-- 备份")
bud = os.path.join(ROOT, ".backups")
if os.path.exists(bud):
    bfs = sorted([f for f in os.listdir(bud) if f.endswith(".zip")])
    check("备份", len(bfs) > 0, "最新 " + bfs[-1] if bfs else "无")
else:
    check("备份", None, "未创建")

# 7. Kimi balance
print("\n-- Kimi余额")
try:
    r = subprocess.run(
        ["python", os.path.join(SCRIPTS, "check_balance.py")],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=ROOT,
    )
    total = None
    for l in r.stdout.split("\n"):
        if "总额:" in l:
            parts = l.split(":")[1].strip().split()
            if parts:
                total = float(parts[0])
    if total is not None:
        if total < 5:
            check("Kimi", False, str(total) + "元 快没了!")
        elif total < 10:
            check("Kimi", True, str(total) + "元 建议充值")
        else:
            check("Kimi", True, str(total) + "元")
    else:
        check("Kimi", None, "查不到")
except:
    check("Kimi", None, "查询失败")

# Summary
print(f"\n{'=' * 40}")
elapsed = (datetime.datetime.now() - start_time).total_seconds()
total = results["ok"] + results["warn"] + results["fail"]
pct = (results["ok"] / total * 100) if total > 0 else 0
if pct >= 90:
    status = "HEALTHY"
elif pct >= 70:
    status = "WARN"
else:
    status = "SICK"
print(
    f"{status}  ok:{results['ok']} warn:{results['warn']} fail:{results['fail']}  ({total}项 {elapsed:.1f}s)"
)
