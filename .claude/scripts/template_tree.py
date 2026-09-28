"""模板继承图 — 分析 templates/ 下所有 .html 的 extends/include 关系，输出树状结构。用法: python template_tree.py"""

import os
import re
import sys

# 项目根目录
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TEMPLATES_DIR = os.path.join(ROOT, "templates")


def parse_template(filepath):
    """解析模板文件，返回 (extends列表, includes列表)"""
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # 匹配 {% extends "xxx.html" %} 或 {% extends 'xxx.html' %}
    extends = re.findall(r'\{%\s*extends\s+["\']([^"\']+)["\']', content)

    # 匹配 {% include "xxx.html" %} 或 {% include 'xxx.html' %}
    includes = re.findall(r'\{%\s*include\s+["\']([^"\']+)["\']', content)

    return extends, includes


def get_short_path(filepath):
    """返回 templates/ 下的相对路径"""
    rel = os.path.relpath(filepath, TEMPLATES_DIR)
    return rel.replace("\\", "/")


def build_tree():
    """构建继承和包含关系图"""
    # extends: 子模板 → 父模板
    extends_map = {}  # {子模板: 父模板}
    # includes: 父模板 → [子模板列表]
    includes_map = {}  # {父模板: [被包含的模板列表]}
    # 所有模板的 extends 和 includes 信息
    all_info = {}  # {模板: (extends, includes)}

    # 递归扫描 templates 目录
    for dirpath, dirnames, filenames in os.walk(TEMPLATES_DIR):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for filename in filenames:
            if not filename.endswith(".html"):
                continue
            filepath = os.path.join(dirpath, filename)
            short = get_short_path(filepath)

            exts, incs = parse_template(filepath)
            all_info[short] = (exts, incs)

            if exts:
                extends_map[short] = exts[0]  # 只取第一个 extends（通常只有一个）

            if incs:
                includes_map[short] = incs

    return extends_map, includes_map, all_info


def find_root(extends_map):
    """找根模板（没有被任何模板 extends 的模板）"""
    parents = set(extends_map.values())
    # 根模板：作为父模板但不作为子模板
    roots = parents - set(extends_map.keys())
    if not roots:
        roots = {"base.html"}  # 默认
    return roots


def print_tree(extends_map, includes_map, all_info):
    """以树形输出继承关系"""
    # 构建反向映射：父模板 → 子模板列表
    children_map = {}
    for child, parent in extends_map.items():
        if parent not in children_map:
            children_map[parent] = []
        children_map[parent].append(child)

    # 找根
    roots = find_root(extends_map)

    def print_branch(name, prefix="", is_last=True):
        """递归输出一棵树"""
        connector = "└── " if is_last else "├── "
        print(f"{prefix}{connector}{name}")

        # 显示 includes（如果存在）
        if name in includes_map:
            for inc in includes_map[name]:
                inc_prefix = prefix + ("    " if is_last else "│   ")
                print(f"{inc_prefix}    📎 include: {inc}")

        # 显示子模板
        if name in children_map:
            children = sorted(children_map[name])
            for i, child in enumerate(children):
                child_prefix = prefix + ("    " if is_last else "│   ")
                is_child_last = i == len(children) - 1
                print_branch(child, child_prefix, is_child_last)

    # 输出每个根
    for root in sorted(roots):
        print_branch(root, "", True)
        print()

    # 没有父也没有子的孤立模板
    all_templates = set(all_info.keys())
    in_tree = set(extends_map.keys()) | set(extends_map.values())
    orphans = all_templates - in_tree
    if orphans:
        # 但检查是否有 include 关系
        referenced_by_include = set()
        for incs in includes_map.values():
            referenced_by_include.update(incs)

        true_orphans = orphans - referenced_by_include
        if true_orphans:
            print("📌 孤立模板（未被继承也未引用其他模板）:")
            for t in sorted(true_orphans):
                print(f"  - {t}")


def main():
    print("=" * 60)
    print("📂 模板继承图")
    print("=" * 60)

    if not os.path.exists(TEMPLATES_DIR):
        print(f"❌ templates/ 目录不存在: {TEMPLATES_DIR}")
        return 1

    extends_map, includes_map, all_info = build_tree()

    total = len(all_info)
    print(f"\n📄 共 {total} 个模板文件")

    # 统计
    extends_count = len(extends_map)
    includes_count = sum(len(incs) for incs in includes_map.values())
    print(f"🔗 继承关系: {extends_count} 条")
    print(f"📎 引用关系: {includes_count} 条")

    print(f"\n{'─' * 60}")
    print("🌳 继承树:\n")

    print_tree(extends_map, includes_map, all_info)

    # 额外统计
    print(f"\n{'─' * 60}")
    print("📊 模板统计:")
    print(f"  直接继承 base.html: {sum(1 for p in extends_map.values() if p == 'base.html')} 个")
    print(f"  没有继承任何模板: {total - len(extends_map)} 个")

    return 0


if __name__ == "__main__":
    sys.exit(main())
