"""每日自动备份 — 检查今天是否已备份，没有则自动备份，保留最近7天。适合放计划任务。用法: python auto_backup.py"""

import datetime
import os
import subprocess
import sys

# 项目根目录
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS_DIR = os.path.join(ROOT, ".claude", "scripts")
BACKUP_DIR = os.path.join(ROOT, ".backups")


def get_today_str():
    """返回今天的日期字符串，如 20260615"""
    return datetime.datetime.now().strftime("%Y%m%d")


def find_todays_backup():
    """检查今天是否已有备份"""
    if not os.path.exists(BACKUP_DIR):
        return False

    today = get_today_str()
    for f in os.listdir(BACKUP_DIR):
        if f.startswith(f"backup_{today}"):
            return True
    return False


def clean_old_backups(keep_days=7):
    """删除超过 keep_days 天的备份"""
    if not os.path.exists(BACKUP_DIR):
        return

    cutoff = datetime.datetime.now() - datetime.timedelta(days=keep_days)
    cutoff_str = cutoff.strftime("%Y%m%d")

    deleted = 0
    for f in os.listdir(BACKUP_DIR):
        if not f.endswith(".zip"):
            continue
        # 从文件名中提取日期，如 backup_20260615_120000.zip
        try:
            date_part = f.replace("backup_", "").split("_")[0]
            if len(date_part) == 8 and date_part < cutoff_str:
                filepath = os.path.join(BACKUP_DIR, f)
                os.remove(filepath)
                deleted += 1
        except Exception:
            continue

    if deleted > 0:
        print(f"  已清理 {deleted} 个旧备份（保留最近 {keep_days} 天）")


def run_backup():
    """运行 backup.py 脚本"""
    backup_script = os.path.join(SCRIPTS_DIR, "backup.py")
    if not os.path.exists(backup_script):
        print("❌ backup.py 不存在")
        return False

    result = subprocess.run(
        f'python "{backup_script}"',
        shell=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )

    # 只输出关键信息
    for line in result.stdout.strip().split("\n"):
        if "备份完成" in line or "✅" in line:
            print(line.strip())
            break

    return result.returncode == 0


def main():
    today = get_today_str()

    # 检查今天是否已有备份
    if find_todays_backup():
        print(f"✅ {today} 已有备份，跳过")
    else:
        print(f"📦 {today} 正在备份...")
        ok = run_backup()
        if not ok:
            print("❌ 备份失败")
            return 1

    # 清理旧备份
    clean_old_backups(keep_days=7)

    return 0


if __name__ == "__main__":
    sys.exit(main())
