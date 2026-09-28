#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
周报工具
用 git log --since="7 days ago" 统计本周改动
输出: 提交次数、改动文件数、新增/删除行数
用法: python weekly_report.py
"""

import subprocess
import sys
import os
from datetime import datetime, timedelta
from collections import defaultdict

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def run_git(cmd: str) -> str:
    """运行 git 命令"""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            cwd=PROJECT_ROOT, timeout=15
        )
        return result.stdout.strip()
    except Exception as e:
        print(f"[错误] git 命令失败: {e}")
        return ""


def main():
    today = datetime.now()
    week_start = today - timedelta(days=7)
    week_start_str = week_start.strftime("%Y-%m-%d")

    print("=" * 60)
    print(f"📊 周报 — {week_start_str} ~ {today.strftime('%Y-%m-%d')}")
    print("=" * 60)

    # 判断具体用多久 -- 确保覆盖7天
    since_str = "7 days ago"

    # 1. 获取提交次数和基本信息
    log_output = run_git(f'git log --since="{since_str}" --pretty=format:"%h|%an|%ai|%s"')
    commits = []
    if log_output:
        for line in log_output.split("\n"):
            parts = line.split("|", 3)
            if len(parts) == 4:
                commits.append({
                    "hash": parts[0],
                    "author": parts[1],
                    "date": parts[2][:10],
                    "message": parts[3],
                })

    commit_count = len(commits)
    print(f"\n📝 提交次数: {commit_count}")

    if commit_count == 0:
        print("本周没有新的提交。")
        print("=" * 60)
        return

    # 2. 获取改动文件列表
    files_output = run_git(f'git log --since="{since_str}" --name-only --pretty=format:"" --diff-filter=AM')
    changed_files = set()
    file_change_count = defaultdict(int)

    for line in files_output.split("\n"):
        line = line.strip()
        if line and not line.startswith("__pycache__") and not line.startswith("instance/"):
            changed_files.add(line)
            file_change_count[line] += 1

    print(f"📁 改动文件数: {len(changed_files)}")

    # 3. 获取新增/删除行数
    stat_output = run_git(f'git log --since="{since_str}" --shortstat --pretty=format:""')
    total_added = 0
    total_deleted = 0

    import re
    for line in stat_output.split("\n"):
        # 格式: 3 files changed, 50 insertions(+), 20 deletions(-)
        added_match = re.search(r'(\d+) insertion', line)
        deleted_match = re.search(r'(\d+) deletion', line)
        if added_match:
            total_added += int(added_match.group(1))
        if deleted_match:
            total_deleted += int(deleted_match.group(1))

    print(f"➕ 新增行数: {total_added}")
    print(f"➖ 删除行数: {total_deleted}")
    print(f"📏 净变化:   {total_added - total_deleted} 行")

    # 4. 按作者统计
    print("\n" + "-" * 40)
    print("👤 按提交者统计:")
    author_commits = defaultdict(int)
    for c in commits:
        author_commits[c["author"]] += 1
    for author, count in sorted(author_commits.items(), key=lambda x: x[1], reverse=True):
        print(f"  {author}: {count} 次提交")

    # 5. 按日期统计
    print("\n" + "-" * 40)
    print("📅 按日期统计:")
    date_commits = defaultdict(int)
    for c in commits:
        date_commits[c["date"]] += 1
    for date in sorted(date_commits.keys()):
        bar = "█" * date_commits[date]
        print(f"  {date}: {date_commits[date]} {bar}")

    # 6. 最常改动的文件 (Top 10)
    print("\n" + "-" * 40)
    print("🔥 最常改动的文件 (Top 10):")
    top_files = sorted(file_change_count.items(), key=lambda x: x[1], reverse=True)[:10]
    for filepath, count in top_files:
        print(f"  [{count}次] {filepath}")

    # 7. 最近提交列表
    print("\n" + "-" * 40)
    print("📋 最近提交 (最多10条):")
    for c in commits[:10]:
        print(f"  [{c['date']}] {c['hash']} - {c['message']}")

    # 汇总
    print("\n" + "=" * 60)
    print(f"📊 本周汇总: {commit_count} 次提交 | {total_added}+ {total_deleted}- | {len(changed_files)} 文件")
    print("=" * 60)


if __name__ == "__main__":
    main()
