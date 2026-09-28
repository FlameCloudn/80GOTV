"""自动生成路由文档。用法: python gen_route_docs.py"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from web_app import app as flask_app

routes = []
for rule in sorted(flask_app.url_map.iter_rules(), key=lambda r: r.rule):
    if rule.rule.startswith("/static") or rule.rule.startswith("/resources"):
        continue
    methods = ",".join(sorted(rule.methods - {"HEAD", "OPTIONS"})) or "GET"
    routes.append(f"| `{methods}` | `{rule.rule}` | {rule.endpoint} |")

doc = (
    "# 80GOTV 路由文档\n\n自动生成，"
    + str(len(routes))
    + " 个路由\n\n| 方法 | 路径 | 函数 |\n|------|------|------|\n"
    + "\n".join(routes)
    + "\n"
)

out = os.path.join(os.path.dirname(__file__), "..", "ROUTES.md")
with open(out, "w", encoding="utf-8") as f:
    f.write(doc)
print("已生成 " + out + " (" + str(len(routes)) + " 个路由)")
