#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
变更摘要工具
读取最近24小时的 git log，生成"今天改了啥"的摘要
用法: python dev_summary.py
"""

import subprocess
import sys
import os
from datetime import datetime


def run_git(cmd: str) -> str:
    """运行 git 命令并返回输出"""
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True,
        cwd=os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    )
    if result.returncode != 0:
        print(f"[错误] 命令执行失败: {cmd}")
        print(result.stderr)
        sys.exit(1)
    return result.stdout.strip()


def main():
    print("=" * 60)
    print(f"📋 变更摘要 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    # 获取最近24小时的提交记录
    output = run_git('git log --since="24 hours ago" --pretty=format:"%h | %an | %s" --stat')

    if not output:
        print("最近24小时没有新的提交。")
        return

    lines = output.split("\n")
    commit_count = 0
    files_changed = set()

    for line in lines:
        # 提交信息行（格式: hash | 作者 | 消息）
        if "|" in line and not line.strip().startswith(("create", "delete", "rename")):
            commit_count += 1
            # 给提交信息行加亮显示
            print(f"\n  {line}")
            print("  " + "-" * 50)
        # 文件变更行（带 | 的统计行）
        elif "|" in line:
            file_path = line.split("|")[0].strip()
            files_changed.add(file_path)
            print(f"    {line.strip()}")
        elif line.strip():
            print(f"    {line.strip()}")

    # 输出统计摘要
    print("\n" + "=" * 60)
    print(f"  提交次数: {commit_count}")
    print(f"  改动文件数: {len(files_changed)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
