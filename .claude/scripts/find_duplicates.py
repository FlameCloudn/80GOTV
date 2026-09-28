#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重复代码检测工具
扫描 routes/ 和 blueprints/ 下的 .py 文件，找相同或高度相似的函数
用简单的行数 + 结构比较
用法: python find_duplicates.py
"""

import ast
import os
from collections import defaultdict

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
SCAN_DIRS = ["routes", "blueprints"]


def get_function_info(node) -> dict:
    """从 AST 函数节点提取特征信息"""
    # 获取函数体的行数
    body_lines = 0
    if hasattr(node, "body"):
        for stmt in node.body:
            if hasattr(stmt, "lineno") and hasattr(stmt, "end_lineno"):
                body_lines += stmt.end_lineno - stmt.lineno + 1
            else:
                body_lines += 1

    # 统计函数体内不同类型的节点数量（作为结构特征）
    # 这能粗略反映函数的"形状"
    node_types = defaultdict(int)
    for child in ast.walk(node):
        node_types[type(child).__name__] += 1

    # 检查是否有装饰器
    decorators = []
    if hasattr(node, "decorator_list"):
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name):
                decorators.append(dec.id)
            elif isinstance(dec, ast.Attribute):
                decorators.append(ast.unparse(dec))

    return {
        "name": node.name,
        "body_lines": body_lines,
        "node_types": dict(node_types),
        "decorators": decorators,
    }


def extract_functions(filepath: str) -> list:
    """从一个 Python 文件中提取所有函数信息"""
    functions = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        return functions

    # 收集所有函数定义（包括类方法）
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            info = get_function_info(node)
            info["file"] = filepath
            info["line"] = node.lineno
            functions.append(info)

    return functions


def similarity_score(f1: dict, f2: dict) -> float:
    """
    计算两个函数的相似度 (0~1)
    比较：行数接近程度 + 节点类型分布相似度
    """
    # 行数比较：越接近得分越高
    lines1, lines2 = f1["body_lines"], f2["body_lines"]
    if max(lines1, lines2) == 0:
        line_score = 1.0
    else:
        line_score = 1.0 - abs(lines1 - lines2) / max(lines1, lines2)

    # 节点类型分布比较（Jaccard-like）
    types1 = set(f1["node_types"].keys())
    types2 = set(f2["node_types"].keys())
    if not types1 and not types2:
        type_score = 1.0
    else:
        intersection = types1 & types2
        union = types1 | types2
        type_score = len(intersection) / len(union) if union else 0

    # 如果函数名完全相同，加大权重
    name_bonus = 0.3 if f1["name"] == f2["name"] else 0

    return (line_score * 0.4 + type_score * 0.6) + name_bonus


def main():
    print("=" * 60)
    print("重复代码扫描 — 扫描 routes/ 和 blueprints/")
    print("=" * 60)

    all_functions = []

    # 扫描所有 .py 文件
    for scan_dir in SCAN_DIRS:
        full_dir = os.path.join(PROJECT_ROOT, scan_dir)
        if not os.path.exists(full_dir):
            print(f"[跳过] 目录不存在: {full_dir}")
            continue

        for root, dirs, files in os.walk(full_dir):
            for fname in files:
                if fname.endswith(".py"):
                    filepath = os.path.join(root, fname)
                    funcs = extract_functions(filepath)
                    all_functions.extend(funcs)

    print(f"共扫描到 {len(all_functions)} 个函数")
    print()

    # 两两比较
    threshold = 0.7  # 相似度阈值
    suspicious_pairs = []
    checked = set()

    for i in range(len(all_functions)):
        for j in range(i + 1, len(all_functions)):
            f1, f2 = all_functions[i], all_functions[j]
            # 跳过同一文件
            if f1["file"] == f2["file"]:
                continue
            # 跳过函数名不同但太短的（容易误报）
            if f1["body_lines"] < 3 and f1["name"] != f2["name"]:
                continue

            score = similarity_score(f1, f2)
            if score >= threshold:
                pair_key = tuple(sorted([(f1["file"], f1["line"]), (f2["file"], f2["line"])]))
                if pair_key not in checked:
                    checked.add(pair_key)
                    suspicious_pairs.append((f1, f2, score))

    # 按相似度从高到低排序
    suspicious_pairs.sort(key=lambda x: x[2], reverse=True)

    # 输出结果
    if not suspicious_pairs:
        print("✓ 没有发现可疑的重复函数。")
    else:
        print(f"发现 {len(suspicious_pairs)} 对可疑重复:\n")
        for idx, (f1, f2, score) in enumerate(suspicious_pairs, 1):
            print(f"#{idx} 相似度: {score:.1%}")
            file1_rel = os.path.relpath(f1["file"], PROJECT_ROOT)
            file2_rel = os.path.relpath(f2["file"], PROJECT_ROOT)
            print(f"  A) {f1['name']}() — {file1_rel}:{f1['line']} ({f1['body_lines']}行)")
            print(f"  B) {f2['name']}() — {file2_rel}:{f2['line']} ({f2['body_lines']}行)")
            print()


if __name__ == "__main__":
    main()
