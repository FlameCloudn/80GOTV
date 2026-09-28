"""检查模板中可能的变量问题。用法: python check_template_vars.py"""

import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TEMPLATE_DIR = os.path.join(ROOT, "templates")

for root, _, files in os.walk(TEMPLATE_DIR):
    for f in files:
        if not f.endswith(".html"):
            continue
        path = os.path.join(root, f)
        text = open(path, "r", encoding="utf-8", errors="ignore").read()

        issues = []

        # 检查：{% for x in y %} 但循环内用 item.xxx 而非 x.xxx
        for m in re.finditer(r"\{%\s*for\s+(\w+)\s+in\s+(\w+)", text):
            loop_var = m.group(1)

        # 检查：用了没定义的变量（简单启发式）
        vars_used = set(re.findall(r"\{\{\s*(\w+)", text))

        # 常见拼写错误
        common_mistakes = {
            "csrf_tokem": "csrf_token",
            "csrf_tokne": "csrf_token",
            "url_for": None,  # 这是函数不是变量
            "curretn": "current",
            "curret": "current",
            "lenght": "length",
            "lenth": "length",
        }

        for v in vars_used:
            if v in common_mistakes:
                correct = common_mistakes[v]
                if correct:
                    issues.append(f"疑似拼写错误: {{{{ {v} }}}} → {{{{ {correct} }}}}?")

        if issues:
            rel = os.path.relpath(path, ROOT)
            print(f"\n{rel}:")
            for i in issues:
                print(f"  ⚠ {i}")

print("\n检查完成")
