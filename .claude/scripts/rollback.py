#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
改前备份工具
用法:
  备份: python rollback.py <文件路径>
  恢复: python rollback.py --restore <文件路径>
  列出备份: python rollback.py --list
会将文件复制到 .rollback/ 目录，保留目录结构和时间戳
"""

import os
import sys
import shutil
from datetime import datetime

# 项目根目录和备份目录
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
BACKUP_DIR = os.path.join(PROJECT_ROOT, ".rollback")


def ensure_backup_dir():
    """确保备份目录存在"""
    os.makedirs(BACKUP_DIR, exist_ok=True)


def get_backup_path(file_path: str, timestamp: str = None) -> str:
    """
    根据原文件路径生成备份路径
    例如: E:/项目/src/app.py → .rollback/src/app.py.20250101_120000.bak
    """
    # 获取相对于项目根目录的路径
    rel_path = os.path.relpath(file_path, PROJECT_ROOT)
    # 备份文件名: 原文件名.时间戳.bak
    if timestamp:
        backup_name = os.path.basename(rel_path) + f".{timestamp}.bak"
    else:
        backup_name = os.path.basename(rel_path)
    # 保留目录结构
    dir_part = os.path.dirname(rel_path)
    backup_full_dir = os.path.join(BACKUP_DIR, dir_part)
    return os.path.join(backup_full_dir, backup_name)


def backup_file(file_path: str):
    """备份指定文件"""
    if not os.path.exists(file_path):
        print(f"[错误] 文件不存在: {file_path}")
        sys.exit(1)

    if not os.path.isfile(file_path):
        print(f"[错误] 路径不是文件: {file_path}")
        sys.exit(1)

    ensure_backup_dir()

    # 生成带时间戳的备份名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = get_backup_path(file_path, timestamp)

    # 确保备份目录存在
    os.makedirs(os.path.dirname(backup_path), exist_ok=True)

    # 复制文件（保留修改时间）
    shutil.copy2(file_path, backup_path)
    # 同样存一个"最新"副本（覆盖式，方便 restore）
    latest_path = get_backup_path(file_path)
    os.makedirs(os.path.dirname(latest_path), exist_ok=True)
    shutil.copy2(file_path, latest_path)

    print(f"✓ 已备份: {file_path}")
    print(f"  → {backup_path}")


def restore_file(file_path: str):
    """从备份恢复文件"""
    # 先找带时间戳的备份，找最新的
    rel_path = os.path.relpath(file_path, PROJECT_ROOT)
    backup_dir = os.path.join(BACKUP_DIR, os.path.dirname(rel_path))
    base_name = os.path.basename(rel_path)

    if not os.path.exists(backup_dir):
        print(f"[错误] 没有找到备份目录: {backup_dir}")
        sys.exit(1)

    # 搜集所有匹配的备份文件
    backups = []
    for f in os.listdir(backup_dir):
        if f.startswith(base_name + ".") and f.endswith(".bak"):
            backups.append(os.path.join(backup_dir, f))
        elif f == base_name:
            backups.append(os.path.join(backup_dir, f))

    if not backups:
        print(f"[错误] 没有找到 {file_path} 的备份文件")
        sys.exit(1)

    # 按修改时间排序，取最新
    backups.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    latest_backup = backups[0]

    # 恢复
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    shutil.copy2(latest_backup, file_path)
    print(f"✓ 已恢复: {latest_backup}")
    print(f"  → {file_path}")


def list_backups():
    """列出所有备份文件"""
    if not os.path.exists(BACKUP_DIR):
        print("还没有任何备份。")
        return

    print("备份列表:")
    print("-" * 60)
    for root, dirs, files in os.walk(BACKUP_DIR):
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, BACKUP_DIR)
            size = os.path.getsize(full)
            mtime = datetime.fromtimestamp(os.path.getmtime(full))
            print(f"  {rel}")
            print(f"    大小: {size} 字节 | 时间: {mtime.strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 60)


def main():
    if len(sys.argv) < 2:
        print("用法:")
        print("  备份文件: python rollback.py <文件路径>")
        print("  恢复文件: python rollback.py --restore <文件路径>")
        print("  列出备份: python rollback.py --list")
        sys.exit(1)

    if sys.argv[1] == "--restore":
        if len(sys.argv) < 3:
            print("[错误] 请指定要恢复的文件路径")
            sys.exit(1)
        restore_file(sys.argv[2])
    elif sys.argv[1] == "--list":
        list_backups()
    else:
        backup_file(sys.argv[1])


if __name__ == "__main__":
    main()
