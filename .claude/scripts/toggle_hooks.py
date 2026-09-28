#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Git Hooks 开关工具
临时禁用/恢复 pre-commit hooks
用法:
  python toggle_hooks.py off  → 临时禁用 pre-commit hooks
  python toggle_hooks.py on   → 恢复 pre-commit hooks
  python toggle_hooks.py status → 查看当前状态
"""

import os
import shutil
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
HOOKS_DIR = os.path.join(PROJECT_ROOT, ".git", "hooks")
PRE_COMMIT_HOOK = os.path.join(HOOKS_DIR, "pre-commit")
PRE_COMMIT_BACKUP = os.path.join(HOOKS_DIR, "pre-commit.disabled")

# 另外检查 .claude/settings.json 中的 hooks 配置
SETTINGS_FILE = os.path.join(PROJECT_ROOT, ".claude", "settings.json")


def check_hooks_dir() -> bool:
    """检查 hooks 目录是否存在"""
    if not os.path.exists(HOOKS_DIR):
        print(f"[警告] .git/hooks 目录不存在: {HOOKS_DIR}")
        return False
    return True


def status():
    """查看当前 hooks 状态"""
    print("=" * 50)
    print("Git Hooks 状态")
    print("=" * 50)

    if not check_hooks_dir():
        return

    # 检查 pre-commit
    has_hook = os.path.exists(PRE_COMMIT_HOOK)
    has_backup = os.path.exists(PRE_COMMIT_BACKUP)

    if has_hook:
        # 检查是否是可执行文件
        if os.access(PRE_COMMIT_HOOK, os.X_OK):
            print("✓ pre-commit: 已启用 (可执行)")
        else:
            print("⚠ pre-commit: 文件存在但不可执行")
        print(f"  路径: {PRE_COMMIT_HOOK}")

        # 读取内容，显示前几行
        try:
            with open(PRE_COMMIT_HOOK, "r", encoding="utf-8") as f:
                content = f.read(200)
            if content:
                print(f"  内容预览: {content[:100]}...")
        except Exception:
            pass
    elif has_backup:
        print("✗ pre-commit: 已禁用（备份在 pre-commit.disabled）")
        print(f"  备份: {PRE_COMMIT_BACKUP}")
    else:
        print("○ pre-commit: 未配置")

    # 列出所有已安装的 hooks
    print("\n已安装的 hooks:")
    if os.path.exists(HOOKS_DIR):
        hooks_found = False
        for fname in sorted(os.listdir(HOOKS_DIR)):
            fpath = os.path.join(HOOKS_DIR, fname)
            # 跳过 .sample 文件和 disabled 备份
            if fname.endswith(".sample") or fname.endswith(".disabled"):
                continue
            if os.path.isfile(fpath):
                hooks_found = True
                executable = "可执行" if os.access(fpath, os.X_OK) else "不可执行"
                print(f"  - {fname} ({executable})")
        if not hooks_found:
            print("  (无)")
    print("=" * 50)


def disable_hooks():
    """禁用 pre-commit hooks"""
    if not check_hooks_dir():
        sys.exit(1)

    # 检查 pre-commit
    if os.path.exists(PRE_COMMIT_BACKUP):
        print("[信息] pre-commit 已经是禁用状态")
        print(f"  备份文件: {PRE_COMMIT_BACKUP}")
        return

    if not os.path.exists(PRE_COMMIT_HOOK):
        print("[信息] 没有 pre-commit hook，无需禁用")
        return

    # 重命名：移走 hook 文件
    shutil.move(PRE_COMMIT_HOOK, PRE_COMMIT_BACKUP)
    print("✓ pre-commit 已禁用")
    print(f"  原文件已备份到: {PRE_COMMIT_BACKUP}")
    print("  恢复: python toggle_hooks.py on")


def enable_hooks():
    """恢复 pre-commit hooks"""
    if not check_hooks_dir():
        sys.exit(1)

    # 检查备份
    if os.path.exists(PRE_COMMIT_HOOK):
        print("[信息] pre-commit 已经是启用状态")
        print(f"  文件: {PRE_COMMIT_HOOK}")
        return

    if not os.path.exists(PRE_COMMIT_BACKUP):
        print("[信息] 没有找到被禁用的 pre-commit 备份")
        print("  (可能是手动删除的，或本来就没有)")
        return

    # 恢复
    shutil.move(PRE_COMMIT_BACKUP, PRE_COMMIT_HOOK)
    # 尝试设置可执行权限（Windows 上可能无效）
    try:
        os.chmod(PRE_COMMIT_HOOK, 0o755)
    except Exception:
        pass
    print("✓ pre-commit 已恢复")
    print(f"  文件: {PRE_COMMIT_HOOK}")


def main():
    if len(sys.argv) < 2:
        print("用法:")
        print("  python toggle_hooks.py off    → 临时禁用 pre-commit")
        print("  python toggle_hooks.py on     → 恢复 pre-commit")
        print("  python toggle_hooks.py status → 查看当前状态")
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "off":
        disable_hooks()
    elif cmd == "on":
        enable_hooks()
    elif cmd == "status":
        status()
    else:
        print(f"[错误] 未知命令: {cmd}")
        print("支持的命令: on, off, status")
        sys.exit(1)


if __name__ == "__main__":
    main()
