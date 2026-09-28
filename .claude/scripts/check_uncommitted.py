#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
未提交提醒工具
运行 git status --porcelain，如果有未提交文件，打印提醒
用法: python check_uncommitted.py
"""

import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def main():
    print("=" * 50)
    print(f"未提交检查 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)

    try:
        result = subprocess.run(
            "git status --porcelain",
            shell=True,
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        print("[错误] git status 超时")
        sys.exit(1)
    except Exception as e:
        print(f"[错误] 执行失败: {e}")
        sys.exit(1)

    if result.returncode != 0:
        print("[错误] 无法执行 git status")
        print(result.stderr)
        sys.exit(1)

    output = result.stdout.strip()

    if not output:
        print("\n✓ 工作区干净，没有未提交的文件。")
        return

    # 分类统计
    lines = output.split("\n")
    categories = defaultdict(list)

    for line in lines:
        if not line:
            continue
        status = line[:2]
        filepath = line[3:].strip()

        # 状态说明
        # 左侧：暂存区状态  右侧：工作区状态
        # M = 已修改, A = 新增, D = 已删除, R = 重命名
        # ? = 未跟踪, ! = 被忽略
        if status == "??":
            categories["未跟踪的新文件"].append(filepath)
        elif status == " M":
            categories["工作区已修改（未暂存）"].append(filepath)
        elif status == "M ":
            categories["暂存区已修改（待提交）"].append(filepath)
        elif status == "MM":
            categories["暂存区和工作区都已修改"].append(filepath)
        elif status == "A ":
            categories["暂存区新增"].append(filepath)
        elif status == " D":
            categories["工作区已删除"].append(filepath)
        elif status == "D ":
            categories["暂存区已删除"].append(filepath)
        elif "R" in status:
            categories["重命名"].append(filepath)
        else:
            categories[f"其他 ({status})"].append(filepath)

    # 输出分类结果
    total = len(lines)
    print(f"\n发现 {total} 个未提交的变更:\n")

    emoji_map = {
        "未跟踪的新文件": "📄",
        "工作区已修改（未暂存）": "✏️",
        "暂存区已修改（待提交）": "📦",
        "暂存区和工作区都已修改": "🔄",
        "暂存区新增": "➕",
        "工作区已删除": "🗑️",
        "暂存区已删除": "🗑️",
        "重命名": "📝",
    }

    for category, files in categories.items():
        emoji = emoji_map.get(category, "•")
        print(f"  {emoji} {category} ({len(files)}个):")
        for f in files:
            print(f"      {f}")
        print()

    # 提醒
    print("=" * 50)
    if total > 10:
        print(f"⚠️  有 {total} 个文件未提交，改动较多，建议尽早提交。")
    elif total > 5:
        print(f"⚠️  有 {total} 个文件未提交，可以考虑提交了。")
    else:
        print(f"💡 有 {total} 个文件未提交。")

    print("\n提交建议:")
    print("  git add -A")
    print('  git commit -m "描述你的改动"')


if __name__ == "__main__":
    main()
