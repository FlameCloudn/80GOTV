"""命令速查表 — 扫描 .claude/scripts/ 下所有 .py 脚本，提取说明，生成 Markdown 表格。用法: python gen_cheatsheet.py"""
import os
import sys
import re
import datetime

# 项目根目录
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS_DIR = os.path.join(ROOT, ".claude", "scripts")
OUTPUT_FILE = os.path.join(ROOT, ".claude", "CHEATSHEET.md")


def extract_docstring(filepath):
    """从 Python 文件中提取第一个 docstring（注释块的第一句话）"""
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # 匹配模块级别的 docstring: """...""" 或 '''...'''
    patterns = [
        r'"""(.*?)"""',
        r"'''(.*?)'''",
    ]

    for pattern in patterns:
        match = re.search(pattern, content, re.DOTALL)
        if match:
            doc = match.group(1).strip()
            # 取第一句话（到第一个句号或第一个中文句号或第一个换行）
            first_line = doc.split("\n")[0].strip()
            # 如果包含"用法:"，截取前面的部分
            if "用法:" in first_line or "用法：" in first_line:
                first_line = re.split(r'用法[：:]', first_line)[0].strip()
            # 去掉末尾的句号
            first_line = first_line.rstrip("。.").strip()
            return first_line

    return "（无说明）"


def extract_usage(filepath):
    """提取用法说明"""
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    match = re.search(r'用法[：:]\s*(.+?)(?:"""|\n)', content)
    if match:
        return match.group(1).strip()

    # 备选：看第一行 docstring 中是否包含用法
    match = re.search(r'""".*?用法[：:]\s*(.+?)"""', content, re.DOTALL)
    if match:
        return match.group(1).strip()

    return f"python {os.path.basename(filepath)}"


def main():
    print("=" * 50)
    print("生成命令速查表")
    print("=" * 50)

    if not os.path.exists(SCRIPTS_DIR):
        print(f"❌ scripts 目录不存在: {SCRIPTS_DIR}")
        return 1

    # 扫描所有 .py 文件
    py_files = sorted([
        f for f in os.listdir(SCRIPTS_DIR)
        if f.endswith(".py") and f != "__init__.py"
    ])

    # 按用途分类
    categories = {
        "🔍 检查与诊断": [],
        "🛠️  开发工具": [],
        "📊 分析与报告": [],
        "💾 备份与恢复": [],
        "🧪 测试与验证": [],
        "📋 其他": [],
    }

    # 关键词 → 分类映射
    for py_file in py_files:
        filepath = os.path.join(SCRIPTS_DIR, py_file)
        desc = extract_docstring(filepath)

        # 根据文件名和描述分类
        lower_name = py_file.lower()
        lower_desc = desc.lower()

        if any(kw in lower_name for kw in ["check", "verify", "audit", "scan", "find", "doctor", "env", "type"]):
            cat = "🔍 检查与诊断"
        elif any(kw in lower_name for kw in ["gen", "scaffold", "live", "browser", "add", "cache", "toggle"]):
            cat = "🛠️  开发工具"
        elif any(kw in lower_name for kw in ["report", "stat", "heatmap", "weekly", "cheatsheet", "prompt"]):
            cat = "📊 分析与报告"
        elif any(kw in lower_name for kw in ["backup", "rollback", "restore", "db"]):
            cat = "💾 备份与恢复"
        elif any(kw in lower_name for kw in ["test", "run_test", "api_bench", "visual", "compare"]):
            cat = "🧪 测试与验证"
        else:
            cat = "📋 其他"

        categories[cat].append((py_file, desc))

    # 生成 Markdown
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = []
    lines.append("# 命令速查表")
    lines.append(f"\n> 自动生成于 {now} | 运行 `python gen_cheatsheet.py` 刷新")
    lines.append(f"\n共 {len(py_files)} 个工具脚本\n")

    for cat_name, scripts in categories.items():
        if not scripts:
            continue
        lines.append(f"## {cat_name}\n")
        lines.append("| 脚本文件 | 用途 | 运行命令 |")
        lines.append("|----------|------|----------|")

        for filename, desc in scripts:
            # 截断过长的描述
            display_desc = desc[:60] + "..." if len(desc) > 60 else desc
            lines.append(f"| `{filename}` | {display_desc} | `python {filename}` |")

        lines.append("")

    # 写入文件
    content = "\n".join(lines)
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"\n✅ 速查表已生成: {OUTPUT_FILE}")
    print(f"   包含 {len(py_files)} 个脚本的说明")
    print(f"   分为 {sum(1 for s in categories.values() if s)} 个类别")

    return 0


if __name__ == "__main__":
    sys.exit(main())
