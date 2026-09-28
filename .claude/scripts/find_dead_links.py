"""检查模板中内部链接的有效性。用法: python find_dead_links.py"""

import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from web_app import app

TEMPLATE_DIR = os.path.join(ROOT, "templates")
found = 0

for r, _, fs in os.walk(TEMPLATE_DIR):
    for f in fs:
        if not f.endswith(".html"):
            continue
        path = os.path.join(r, f)
        text = open(path, "r", encoding="utf-8", errors="ignore").read()

        for m in re.findall(r"""url_for\(['"](\w+)['"]""", text):
            try:
                app.url_map.bind("").match(f"/{m}", "GET")
            except:
                if m != "static":
                    print(f"  {os.path.basename(path)}: url_for({m!r}) 可能无效")
                    found += 1

print(f"\n共 {found} 个可疑链接" if found else "\n未发现死链接")
