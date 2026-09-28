"""扫描未使用的CSS class。用法: python find_dead_css.py"""

import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CSS_DIR = os.path.join(ROOT, "static", "css")
TEMPLATE_DIR = os.path.join(ROOT, "templates")

used = set()
for r, _, fs in os.walk(TEMPLATE_DIR):
    for f in fs:
        if not f.endswith(".html"):
            continue
        t = open(os.path.join(r, f), "r", encoding="utf-8", errors="ignore").read()
        for m in re.findall(r'class=["\']([^"\']+)["\']', t):
            for c in m.split():
                used.add(c.strip())

found = 0
for r, _, fs in os.walk(CSS_DIR):
    for f in fs:
        if not f.endswith(".css"):
            continue
        t = open(os.path.join(r, f), "r", encoding="utf-8", errors="ignore").read()
        css_classes = set()
        for m in re.findall(r"\.([a-zA-Z_-][\w-]*)", t):
            css_classes.add(m.strip())
        dead = css_classes - used - {"active", "show", "hide", "open"}
        if dead:
            found += len(dead)
            print(f"{f}:")
            for c in sorted(dead):
                print(f"  .{c}")
            print()
print(f"共 {found} 个未使用的 class")
