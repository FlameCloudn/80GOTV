#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
依赖检查工具
读 requirements.txt，用 pip list --outdated 检查哪些包过期
输出版本对比
用法: python check_deps.py
"""

import os
import re
import subprocess
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def parse_requirements(filepath: str) -> dict:
    """解析 requirements.txt，返回 {包名: 版本约束}"""
    deps = {}
    if not os.path.exists(filepath):
        return deps

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # 跳过空行和注释
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            # 处理包名和版本约束
            # 格式: Flask==2.3.0 或 Flask>=2.0 或 Flask
            match = re.match(
                r"^([a-zA-Z0-9_.-]+)\s*([><=!~]+\s*[0-9.*]+(?:\s*,\s*[><=!~]+\s*[0-9.*]+)*)?", line
            )
            if match:
                name = match.group(1).lower()
                constraint = match.group(2).strip() if match.group(2) else "任意版本"
                deps[name] = constraint
    return deps


def get_outdated() -> dict:
    """运行 pip list --outdated，返回 {包名: {当前版本, 最新版本}}"""
    outdated = {}
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--outdated", "--format=columns"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            print("[警告] pip list --outdated 执行失败")
            print(result.stderr)
            return outdated

        lines = result.stdout.strip().split("\n")
        # 跳过表头（前两行通常是 header 和分隔线）
        for line in lines[2:]:
            parts = line.split()
            if len(parts) >= 3:
                pkg_name = parts[0].lower()
                current_ver = parts[1]
                latest_ver = parts[2]
                outdated[pkg_name] = {
                    "current": current_ver,
                    "latest": latest_ver,
                }
    except subprocess.TimeoutExpired:
        print("[警告] pip list --outdated 超时")
    except Exception as e:
        print(f"[警告] 检查过期包时出错: {e}")

    return outdated


def get_installed() -> dict:
    """运行 pip list，返回 {包名: 版本}"""
    installed = {}
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--format=columns"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            return installed

        lines = result.stdout.strip().split("\n")
        for line in lines[2:]:
            parts = line.split()
            if len(parts) >= 2:
                installed[parts[0].lower()] = parts[1]
    except Exception:
        pass
    return installed


def main():
    print("=" * 60)
    print("依赖检查 — requirements.txt vs 已安装")
    print("=" * 60)

    req_path = os.path.join(PROJECT_ROOT, "requirements.txt")
    if not os.path.exists(req_path):
        print(f"[错误] 未找到 requirements.txt: {req_path}")
        sys.exit(1)

    requirements = parse_requirements(req_path)
    outdated = get_outdated()
    installed = get_installed()

    print(f"\nrequirements.txt 中定义了 {len(requirements)} 个包\n")

    # 检查每个依赖
    matching = 0
    missing = 0
    expired = 0

    for pkg_name, constraint in sorted(requirements.items()):
        installed_ver = installed.get(pkg_name)
        outdated_info = outdated.get(pkg_name)

        if outdated_info:
            # 有过期
            expired += 1
            print(f"[过期] {pkg_name}")
            print(f"       已安装: {outdated_info['current']}")
            print(f"       最新版: {outdated_info['latest']}")
            print(f"       要求:   {constraint}")
            print(f"       → 建议升级: pip install --upgrade {pkg_name}")
        elif installed_ver:
            # 已安装且最新
            matching += 1
            print(f"  [✓] {pkg_name} {installed_ver} (要求: {constraint})")
        else:
            # 未安装
            missing += 1
            print(f"[缺失] {pkg_name} — 未安装 (要求: {constraint})")
            print(f"       → pip install {pkg_name}")

        print()

    # 汇总
    print("=" * 60)
    print(f"汇总: {matching} 正常 | {expired} 过期 | {missing} 缺失 | 共 {len(requirements)} 包")
    print("=" * 60)

    if expired > 0:
        print("\n升级所有过期包的命令:")
        names = [n for n in requirements if n in outdated]
        print(f"  pip install --upgrade {' '.join(names)}")


if __name__ == "__main__":
    main()
