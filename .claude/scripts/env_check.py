#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
环境检查工具
启动前检查 .env 中必需项是否存在: SECRET_KEY, ADMIN_PASSWORD
缺少时给出警告，但允许继续
用法: python env_check.py
"""

import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
ENV_FILE = os.path.join(PROJECT_ROOT, ".env")

# 必需的配置项
REQUIRED_KEYS = ["SECRET_KEY", "ADMIN_PASSWORD"]

# 推荐的配置项（缺少时给出善意提醒）
RECOMMENDED_KEYS = ["DATABASE_URL", "FLASK_ENV"]


def read_env_file(filepath: str) -> dict:
    """读取 .env 文件，返回键值对字典"""
    env_vars = {}
    if not os.path.exists(filepath):
        return env_vars
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # 跳过空行和注释
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                env_vars[key] = value
    return env_vars


def main():
    print("=" * 50)
    print("环境检查 — 80GOTV")
    print("=" * 50)

    # 检查 .env 是否存在
    if not os.path.exists(ENV_FILE):
        print(f"[警告] 未找到 .env 文件: {ENV_FILE}")
        print("请参考 .env.example 创建 .env 文件")
        print("\n可以继续，但应用可能无法正常运行。")
        return

    print("✓ 找到 .env 文件")

    env_vars = read_env_file(ENV_FILE)

    # 检查必需项
    missing_required = []
    for key in REQUIRED_KEYS:
        value = env_vars.get(key, "")
        if not value:
            missing_required.append(key)
            print(f"[警告] 缺少必需配置: {key}")
        elif value == "change-me" or value == "your-secret-key" or len(value) < 8:
            print(f"[警告] {key} 的值看起来不够安全（太短或是默认值），建议更换")
        else:
            print(f"✓ {key}: 已设置")

    # 检查推荐项
    for key in RECOMMENDED_KEYS:
        value = env_vars.get(key, "")
        if not value:
            print(f"[提醒] 推荐配置 {key} 未设置（非必需）")
        else:
            print(f"✓ {key}: 已设置")

    # 汇总
    print("-" * 50)
    if missing_required:
        print(f"[警告] 共 {len(missing_required)} 个必需项未设置: {', '.join(missing_required)}")
        print("应用可能无法正常启动。")
    else:
        print("✓ 所有必需项已设置，可以启动。")


if __name__ == "__main__":
    main()
