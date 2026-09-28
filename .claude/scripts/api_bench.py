#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API 性能测试工具
测试关键API的响应时间，输出每个API的平均、最快、最慢
用法: python api_bench.py
注意: 需要先启动 Flask 应用
"""

import time
import urllib.request
import urllib.error
import sys
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

# 默认配置
BASE_URL = "http://127.0.0.1:5000"
TEST_COUNT = 5  # 每个API测试次数
TIMEOUT = 10    # 请求超时秒数

# 要测试的API列表
# 每个: (名称, URL路径, HTTP方法)
API_LIST = [
    ("首页", "/", "GET"),
    ("赛事列表", "/events", "GET"),
    ("新闻列表", "/news", "GET"),
    ("队伍列表", "/teams", "GET"),
    ("选手列表", "/players", "GET"),
    ("比赛结果", "/results", "GET"),
    ("统计数据", "/stats", "GET"),
    ("登录页", "/login", "GET"),
]


def test_single_api(name: str, path: str, method: str = "GET") -> dict:
    """测试单个API的响应时间"""
    url = f"{BASE_URL}{path}"
    times = []

    for i in range(TEST_COUNT):
        try:
            start = time.perf_counter()
            req = urllib.request.Request(url, method=method)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                _ = resp.read()  # 读取响应体
            elapsed = time.perf_counter() - start
            times.append(elapsed)
        except urllib.error.URLError as e:
            return {
                "name": name,
                "url": url,
                "error": f"连接失败: {e.reason}",
                "avg": None,
                "min": None,
                "max": None,
                "status": "失败",
            }
        except Exception as e:
            return {
                "name": name,
                "url": url,
                "error": str(e),
                "avg": None,
                "min": None,
                "max": None,
                "status": "失败",
            }

    if not times:
        return {
            "name": name, "url": url,
            "error": "无响应",
            "avg": None, "min": None, "max": None,
            "status": "失败",
        }

    avg_time = sum(times) / len(times)

    return {
        "name": name,
        "url": url,
        "avg": avg_time,
        "min": min(times),
        "max": max(times),
        "status": "成功",
        "samples": times,
    }


def format_time(seconds: float) -> str:
    """格式化时间"""
    if seconds is None:
        return "N/A"
    ms = seconds * 1000
    if ms < 1:
        return f"{ms*1000:.1f}μs"
    elif ms < 1000:
        return f"{ms:.1f}ms"
    else:
        return f"{ms/1000:.2f}s"


def main():
    print("=" * 65)
    print("API 性能测试")
    print(f"目标: {BASE_URL} | 每个接口测试 {TEST_COUNT} 次")
    print("=" * 65)

    # 先检查服务器是否在线
    print("\n检查服务器状态...")
    try:
        req = urllib.request.Request(BASE_URL)
        with urllib.request.urlopen(req, timeout=5) as resp:
            print(f"✓ 服务器在线 (状态码: {resp.status})")
    except urllib.error.URLError:
        print(f"[错误] 无法连接到 {BASE_URL}")
        print("请先启动 Flask 应用: python app.py")
        sys.exit(1)
    except Exception as e:
        print(f"[错误] {e}")
        sys.exit(1)

    print(f"\n开始测试 {len(API_LIST)} 个接口...\n")

    results = []
    for name, path, method in API_LIST:
        result = test_single_api(name, path, method)
        results.append(result)

        if result["status"] == "成功":
            print(f"  {result['name']:<10} "
                  f"平均: {format_time(result['avg']):>8}  "
                  f"最快: {format_time(result['min']):>8}  "
                  f"最慢: {format_time(result['max']):>8}")
        else:
            print(f"  {result['name']:<10} [失败] {result.get('error', '未知错误')}")

    # 汇总
    successful = [r for r in results if r["status"] == "成功"]
    failed = [r for r in results if r["status"] != "成功"]

    print("\n" + "=" * 65)
    print(f"汇总: {len(successful)} 成功 | {len(failed)} 失败")

    if successful:
        # 找出最快和最慢的API
        fastest = min(successful, key=lambda x: x["avg"])
        slowest = max(successful, key=lambda x: x["avg"])

        # 计算总平均
        total_avg = sum(r["avg"] for r in successful) / len(successful)
        print(f"总平均响应时间: {format_time(total_avg)}")
        print(f"最快接口: {fastest['name']} ({format_time(fastest['avg'])})")
        print(f"最慢接口: {slowest['name']} ({format_time(slowest['avg'])})")
    print("=" * 65)


if __name__ == "__main__":
    main()
