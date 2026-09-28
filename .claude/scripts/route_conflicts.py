"""路由冲突检测 — 检查 Flask 应用中是否有两个路由指向同一路径和方法。用法: python route_conflicts.py"""
import os
import sys
from collections import defaultdict

# 项目根目录
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)


def get_all_routes(app):
    """从 Flask app 中提取所有路由信息"""
    routes = []  # [(路径, 方法列表, 处理函数名)]

    for rule in app.url_map.iter_rules():
        # 跳过静态文件路由
        if rule.endpoint == "static":
            continue
        path = rule.rule
        methods = sorted([m for m in rule.methods if m not in {"HEAD", "OPTIONS"}])
        endpoint = rule.endpoint
        routes.append((path, methods, endpoint))

    return routes


def find_conflicts(routes):
    """查找冲突：相同路径 + 相同方法的两个不同处理函数"""
    # 按 (路径, 方法) 分组
    groups = defaultdict(list)
    for path, methods, endpoint in routes:
        for method in methods:
            key = (path, method)
            groups[key].append(endpoint)

    conflicts = []
    for (path, method), endpoints in groups.items():
        if len(endpoints) > 1:
            conflicts.append((path, method, endpoints))

    return conflicts


def main():
    print("=" * 50)
    print("路由冲突检测")
    print("=" * 50)

    # 尝试导入 app
    try:
        from app import app
    except Exception as e:
        print(f"\n❌ 无法导入 Flask 应用: {e}")
        print("   请确保在项目根目录运行，且环境配置正确")
        return 1

    # 获取所有路由
    routes = get_all_routes(app)
    print(f"\n📋 共注册 {len(routes)} 条路由规则")

    # 查找冲突
    conflicts = find_conflicts(routes)

    if not conflicts:
        print("✅ 未发现路由冲突！所有路径+方法的组合都是唯一的。")
    else:
        print(f"\n⚠️  发现 {len(conflicts)} 个路由冲突：\n")
        for path, method, endpoints in conflicts:
            print(f"🔴 路径: {path}  方法: {method}")
            for ep in endpoints:
                print(f"     → {ep}")
            print()

    # 顺便列出所有路由（方便查看）
    print(f"\n{'─' * 50}")
    print("📋 完整路由列表:")
    print(f"{'─' * 50}")
    print(f"{'路径':<35} {'方法':<25} {'处理函数'}")
    print(f"{'─' * 50}")

    for path, methods, endpoint in sorted(routes, key=lambda x: x[0]):
        methods_str = ", ".join(methods)
        print(f"{path:<35} {methods_str:<25} {endpoint}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
