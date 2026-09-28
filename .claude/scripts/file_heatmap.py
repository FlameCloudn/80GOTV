#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件热度分析工具
用 git log --name-only 统计每个文件的改动次数
按热度排序，输出前20
用法: python file_heatmap.py
"""

import os
import subprocess
import sys
from collections import Counter

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

# 要忽略的目录/文件模式
IGNORE_PATTERNS = [
    "__pycache__",
    ".rollback",
    "node_modules",
    ".venv",
    "venv",
    ".git",
    ".claude/worktrees",
    "instance",
    "*.pyc",
]


def is_ignored(filepath: str) -> bool:
    """检查文件是否应该被忽略"""
    parts = filepath.replace("\\", "/").split("/")
    for pattern in IGNORE_PATTERNS:
        if pattern.startswith("*"):
            # 扩展名匹配
            ext = pattern[1:]
            if filepath.endswith(ext):
                return True
        else:
            if pattern in parts:
                return True
    return False


def get_file_changes() -> Counter:
    """获取 git log 中每个文件的改动次数"""
    counter = Counter()

    try:
        result = subprocess.run(
            'git log --name-only --pretty=format:"" --diff-filter=AM',
            shell=True,
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        print("[错误] git log 执行超时")
        return counter
    except Exception as e:
        print(f"[错误] 执行 git log 失败: {e}")
        return counter

    if result.returncode != 0:
        print(f"[错误] git log 失败: {result.stderr}")
        return counter

    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        if is_ignored(line):
            continue
        counter[line] += 1

    return counter


def main():
    print("=" * 60)
    print("文件热度分析 — 基于 git log 的改动次数统计")
    print("=" * 60)

    # 先检查是否是 git 仓库
    if not os.path.exists(os.path.join(PROJECT_ROOT, ".git")):
        print("[错误] 当前目录不是 Git 仓库")
        sys.exit(1)

    counter = get_file_changes()

    if not counter:
        print("没有找到任何文件改动记录。")
        return

    total_files = len(counter)
    total_changes = sum(counter.values())
    print(f"共 {total_files} 个文件被改动过，总计 {total_changes} 次改动")
    print()

    # 按热度排序取前20
    top20 = counter.most_common(20)

    # 计算柱状图的最大宽度
    max_count = top20[0][1] if top20 else 1
    bar_max_width = 30

    print(f"{'排名':<5} {'改动次数':<8} {'热度':<{bar_max_width + 2}} 文件路径")
    print("-" * 80)

    for rank, (filepath, count) in enumerate(top20, 1):
        # 热度条
        bar_len = int(count / max_count * bar_max_width)
        bar = "█" * bar_len
        print(f"{rank:<5} {count:<8} {bar:<{bar_max_width + 2}} {filepath}")

    # 统计最热门文件类型
    print("\n" + "=" * 60)
    print("按文件类型统计:")
    ext_counter = Counter()
    for filepath, count in counter.items():
        ext = os.path.splitext(filepath)[1] or "(无扩展名)"
        ext_counter[ext] += count

    for ext, count in ext_counter.most_common(10):
        print(f"  {ext}: {count} 次改动")


if __name__ == "__main__":
    main()
