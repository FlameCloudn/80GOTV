"""未使用import清理 — 扫描 routes/ blueprints/ 下 .py 文件，找出 import 了但未使用的模块。用法: python clean_imports.py"""
import os
import sys
import ast

# 项目根目录
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# 扫描目录
SCAN_DIRS = [
    os.path.join(ROOT, "routes"),
    os.path.join(ROOT, "blueprints"),
]

# Python 内置模块（不应标为未使用，因为可能在运行时用到）
BUILTIN_MODULES = {
    "os", "sys", "json", "re", "time", "datetime", "math", "random",
    "hashlib", "base64", "uuid", "io", "csv", "pathlib", "shutil",
    "subprocess", "logging", "traceback", "warnings", "functools",
    "itertools", "collections", "typing", "enum", "dataclasses",
    "urllib", "http", "ssl", "socket", "email", "html", "xml",
}


def find_unused_imports(filepath):
    """分析单个 Python 文件，找出可能未使用的 import"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
    except Exception:
        return []

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    # 收集所有使用的名字
    used_names = set()

    class NameCollector(ast.NodeVisitor):
        def visit_Name(self, node):
            if isinstance(node.ctx, (ast.Load, ast.Del)):
                used_names.add(node.id)
            self.generic_visit(node)

        def visit_Attribute(self, node):
            # 对于 a.b.c，收集 a（根对象名）
            if isinstance(node.value, ast.Name):
                used_names.add(node.value.id)
            elif isinstance(node.value, ast.Attribute):
                # 递归提取最左端名称
                current = node.value
                while isinstance(current, ast.Attribute):
                    current = current.value
                if isinstance(current, ast.Name):
                    used_names.add(current.id)
            self.generic_visit(node)

    NameCollector().visit(tree)

    # 分析 import 语句
    unused = []

    for node in ast.walk(tree):
        # import xxx
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name
                base_name = name.split(".")[0]
                if base_name not in used_names and name not in used_names:
                    unused.append((node.lineno, f"import {alias.name}", base_name))

        # from xxx import yyy
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            for alias in node.names:
                imported_name = alias.asname or alias.name
                if imported_name == "*":
                    continue  # import * 无法判断
                if imported_name not in used_names:
                    line = node.lineno
                    unused.append((line, f"from {node.module} import {imported_name}", imported_name))

    return unused


def main():
    print("=" * 50)
    print("未使用 import 扫描")
    print("=" * 50)

    total_unused = 0

    for scan_dir in SCAN_DIRS:
        if not os.path.exists(scan_dir):
            continue

        dir_name = os.path.basename(scan_dir)
        print(f"\n📁 {dir_name}/")

        py_files = sorted([
            f for f in os.listdir(scan_dir)
            if f.endswith(".py") and f != "__init__.py"
        ])

        if not py_files:
            print("  (无 .py 文件)")
            continue

        for py_file in py_files:
            filepath = os.path.join(scan_dir, py_file)
            unused = find_unused_imports(filepath)

            if unused:
                print(f"\n  📄 {py_file} — 可能未使用的 import：")
                for line_no, import_stmt, name in unused:
                    # 过滤明显误报（如模块被其他方式使用）
                    if name in BUILTIN_MODULES:
                        continue
                    print(f"      第{line_no}行: {import_stmt}")
                    total_unused += 1

    # 再次过滤后计数
    print(f"\n{'=' * 50}")
    print("💡 以上 import 在当前文件中未直接使用（但在其他文件或运行时可能用到）。")
    print("   建议手动检查确认后再删除，尤其是：")
    print("   - Flask blueprints/routes 的隐式注册")
    print("   - 通过字符串注册的路由处理器")
    print("   - 只在模板中使用的导入")

    return 0


if __name__ == "__main__":
    sys.exit(main())
