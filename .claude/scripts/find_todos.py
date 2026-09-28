#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TODO 扫描工具
扫描所有 .py .html .css .js 文件，找 TODO, FIXME, HACK, XXX, 以后再改 等标记
按文件分组输出
用法: python find_todos.py
"""

import os
import re
from collections import defaultdict

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

# 要扫描的文件扩展名
SCAN_EXTENSIONS = {".py", ".html", ".css", ".js"}

# 要搜索的标记（正则模式）
MARKERS = {
    "TODO": r"TODO[:\s]",
    "FIXME": r"FIXME[:\s]",
    "HACK": r"HACK[:\s]",
    "XXX": r"XXX[:\s]",
    "以后再改": r"以后再改",
    "待完成": r"待完成",
    "暂未实现": r"暂未实现",
    "需要修改": r"需要修改",
    "临时方案": r"临时方案",
}

# 要忽略的目录
IGNORE_DIRS = {
    ".git", ".rollback", "__pycache__", "node_modules",
    ".venv", "venv", "instance", ".claude/worktrees",
    "cs2demoview_src", "gotv_relay",
}


def scan_file(filepath: str) -> list:
    """扫描单个文件，返回发现的标记列表"""
    results = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception:
        return results

    for line_no, line in enumerate(lines, 1):
        # 跳过纯注释行（整行都是注释）
        stripped = line.strip()
        for marker_name, marker_pattern in MARKERS.items():
            match = re.search(marker_pattern, stripped, re.IGNORECASE)
            if match:
                # 查找同一行里的注释内容
                comment_text = stripped
                results.append({
                    "file": filepath,
                    "line": line_no,
                    "marker": marker_name,
                    "text": comment_text.strip()[:120],  # 截断过长的行
                })
                break  # 一行只算一次

    return results


def main():
    print("=" * 60)
    print("TODO 扫描 — 搜索未完成标记")
    print("=" * 60)

    all_results = defaultdict(list)  # 按文件分组

    # 遍历项目文件
    file_count = 0
    for root, dirs, files in os.walk(PROJECT_ROOT):
        # 过滤忽略目录
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".")]

        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in SCAN_EXTENSIONS:
                continue

            file_count += 1
            filepath = os.path.join(root, fname)
            found = scan_file(filepath)
            if found:
                all_results[filepath].extend(found)

    print(f"已扫描 {file_count} 个文件\n")

    if not all_results:
        print("✓ 没有发现待办标记，太棒了！")
        return

    # 统计各类型数量
    marker_count = defaultdict(int)
    for file_results in all_results.values():
        for r in file_results:
            marker_count[r["marker"]] += 1

    # 输出统计
    print("标记统计:")
    for marker, count in sorted(marker_count.items(), key=lambda x: x[1], reverse=True):
        bar = "█" * min(count, 30)
        print(f"  {marker}: {count} {bar}")
    print()

    # 按文件分组输出详情
    total = sum(marker_count.values())
    print(f"共找到 {total} 处标记，分布在 {len(all_results)} 个文件中:")
    print("=" * 60)

    for filepath, items in sorted(all_results.items()):
        rel_path = os.path.relpath(filepath, PROJECT_ROOT)
        print(f"\n📄 {rel_path} ({len(items)}处)")
        print("-" * 50)
        for item in items:
            print(f"  第{item['line']:4d}行 [{item['marker']}] {item['text']}")


if __name__ == "__main__":
    main()
