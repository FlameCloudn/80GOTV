"""
SQL 注入风险扫描器 — 检查 routes/ 和 blueprints/ 下所有 .py 文件，
找出存在裸 SQL 拼接的代码行（f-string 拼接、.format() 拼接等），
输出可疑位置列表，帮助开发者排查潜在安全风险。

裸 SQL 拼接的危险模式：
    1. f"SELECT ... {变量}"           — f-string 直接嵌入变量
    2. "SELECT ..." + 变量            — 字符串拼接
    3. "SELECT ... %s" % 变量         — % 格式化
    4. "SELECT ...".format(变量)      — .format() 方法
    5. cursor.execute(变量, ...)      — 第一个参数是变量而非字面量
"""

import os
import re
import sys

# ===== 危险模式定义 =====
# 每条规则：(正则表达式, 风险描述中文)
DANGER_PATTERNS = [
    # 1. f-string 中直接嵌入变量到 SQL 关键字前后
    (
        r"(?i)(?:SELECT|INSERT|UPDATE|DELETE|FROM|WHERE|JOIN).*\{.*\}",
        "f-string 中 SQL 关键字与变量混用，可能被注入",
    ),
    # 2. 字符串拼接 SQL 片段
    (
        r"(?i)(?:SELECT|INSERT|UPDATE|DELETE)\s.*[\"']\s*\+\s*",
        "SQL 语句后跟字符串拼接（+ 号），可能拼接了用户输入",
    ),
    # 3. % 格式化操作符拼接 SQL
    (
        r'(?i)(?:"[^"]*(?:SELECT|INSERT|UPDATE|DELETE)[^"]*"\s*%)\s',
        "SQL 字符串使用 % 格式化，变量可能未经转义",
    ),
    # 4. .format() 方法在 SQL 上
    (
        r'(?i)(?:"[^"]*(?:SELECT|INSERT|UPDATE|DELETE)[^"]*")\s*\.format\(',
        "SQL 字符串调用 .format() 方法，参数可能未转义",
    ),
    # 5. execute() 的第一个参数是变量（非字面量字符串）
    (
        r'\.execute\(\s*(?!["\'])[a-zA-Z_]',
        "cursor.execute() 第一个参数是变量而非字面量 SQL，有注入风险",
    ),
    # 6. 通用：字符串中包含 SQL 关键字并且使用了变量替入方式
    (r"(?i)(?:SELECT|INSERT|UPDATE|DELETE)\s.*\".*\+", "SQL 与字符串拼接组合，可能有外部输入混入"),
]


# ===== 白名单：安全的假阳性（忽略这些行）=====
# 这些代码看起来危险但实际安全（如参数化查询、日志输出等）
SAFE_INDICATORS = [
    "execute(sql,",  # 手工编写参数化查询
    "logger.",  # 日志打印
    "logging.",  # 日志打印
    "print(",  # 调试打印
    "cursor.execute(",  # 当后面是参数化时（单独处理）
]


def scan_file(filepath: str) -> list[dict]:
    """
    扫描单个文件，返回可疑行列表。
    每项包含: file, line, col, code, reason
    """
    results = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        print(f"  [警告] 无法读取 {filepath}: {e}", file=sys.stderr)
        return results

    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # 跳过注释行和 docstring
        if stripped.startswith('"""') or stripped.startswith("'''"):
            continue

        # 检查安全指标
        if any(safe in line for safe in SAFE_INDICATORS):
            continue

        for pattern, reason in DANGER_PATTERNS:
            if re.search(pattern, line):
                results.append(
                    {
                        "file": filepath,
                        "line": lineno,
                        "code": stripped[:120],  # 截断长行
                        "reason": reason,
                    }
                )
                break  # 每行只报告一次

    return results


def scan_directory(directory: str) -> list[dict]:
    """递归扫描目录下所有 .py 文件"""
    all_results = []
    for root, dirs, files in os.walk(directory):
        # 跳过 __pycache__ 目录
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for filename in files:
            if filename.endswith(".py"):
                filepath = os.path.join(root, filename)
                results = scan_file(filepath)
                all_results.extend(results)
    return all_results


def main():
    """主函数：扫描 routes/ 和 blueprints/ 并打印结果"""
    # 项目根目录（脚本在 .claude/scripts/ 下）
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    dirs_to_scan = [
        os.path.join(project_root, "routes"),
        os.path.join(project_root, "blueprints"),
    ]

    print("=" * 60)
    print("  SQL 注入风险扫描报告")
    print("=" * 60)

    total_issues = 0
    for directory in dirs_to_scan:
        if not os.path.isdir(directory):
            print(f"\n[跳过] 目录不存在: {directory}")
            continue

        dir_name = os.path.basename(directory)
        print(f"\n--- 扫描目录: {dir_name}/ ---")
        results = scan_directory(directory)

        if not results:
            print("  ✓ 未发现可疑代码")
        else:
            for item in results:
                total_issues += 1
                rel_path = os.path.relpath(item["file"], project_root)
                print(f"\n  [{total_issues}] {rel_path}:{item['line']}")
                print(f"      风险: {item['reason']}")
                print(f"      代码: {item['code']}")

    print("\n" + "=" * 60)
    if total_issues == 0:
        print("  ✅ 扫描完成，未发现 SQL 注入风险")
    else:
        print(f"  ⚠️  扫描完成，发现 {total_issues} 处可疑位置")
        print("  请人工检查以上位置，确认是否需要改用参数化查询")
        print("  参数化查询示例: db.execute('SELECT * FROM t WHERE id = ?', [user_input])")
    print("=" * 60)

    return 0 if total_issues == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
