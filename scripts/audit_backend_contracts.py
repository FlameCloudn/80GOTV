"""Generate route and frontend contract inventories without opening a database."""

import ast
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    os.environ["FLASK_ENV"] = "testing"
    os.environ["DATABASE_PATH"] = str(ROOT / "output" / "contract-inventory-unused.db")
    os.environ["TURSO_URL"] = ""
    os.environ["TURSO_TOKEN"] = ""
    sys.path.insert(0, str(ROOT))
    from jinja2 import nodes

    from app import app

    rules = sorted(app.url_map.iter_rules(), key=lambda rule: (rule.rule, rule.endpoint))
    modules = Counter()
    endpoints = {rule.endpoint for rule in rules}
    route_lines = [
        "# 后端功能与路由清单",
        "",
        "由 `scripts/audit_backend_contracts.py` 从实际 Flask 注册结果生成；不会初始化或修改数据库。",
        "现有前端是 Jinja 页面与浏览器局部数据更新并用，不是单独的 SPA。页面布局保留。",
        "",
        "| 方法 | 路径 | 处理模块与函数 |",
        "| --- | --- | --- |",
    ]
    for rule in rules:
        handler = app.view_functions[rule.endpoint]
        module = handler.__module__
        modules[module] += 1
        methods = ", ".join(sorted(rule.methods - {"HEAD", "OPTIONS"}))
        route_lines.append(f"| {methods} | `{rule.rule}` | `{module}.{handler.__name__}` |")
    route_lines += ["", "## 模块覆盖", "", "| 模块 | 地址数 |", "| --- | ---: |"]
    route_lines += [f"| `{name}` | {count} |" for name, count in sorted(modules.items())]

    missing_endpoints = []
    references = []
    for filename in sorted((ROOT / "templates").rglob("*.html")):
        source = filename.read_text(encoding="utf-8")
        parsed = app.jinja_env.parse(source)
        for call in parsed.find_all(nodes.Call):
            if isinstance(call.node, nodes.Name) and call.node.name == "url_for" and call.args:
                if isinstance(call.args[0], nodes.Const):
                    endpoint = call.args[0].value
                    item = {
                        "file": filename.relative_to(ROOT).as_posix(),
                        "line": call.lineno,
                        "endpoint": endpoint,
                    }
                    references.append(item)
                    if endpoint not in endpoints:
                        missing_endpoints.append(item)

    fetches = []
    for folder, extension in (("static/js", "*.js"), ("templates", "*.html")):
        for filename in sorted((ROOT / folder).rglob(extension)):
            source = filename.read_text(encoding="utf-8")
            for found in re.finditer(r"\bfetch(?:Json)?\s*\(", source):
                end = source.find("\n", found.end())
                line = source[found.start() : end if end != -1 else len(source)].strip()
                fetches.append(
                    {
                        "file": filename.relative_to(ROOT).as_posix(),
                        "line": source.count("\n", 0, found.start()) + 1,
                        "call": line[:180],
                    }
                )
    # Parse backend files too so incomplete Python is caught by the inventory command.
    python_modules = []
    for folder in ("routes", "services", "blueprints", "utils"):
        for filename in sorted((ROOT / folder).glob("*.py")):
            ast.parse(filename.read_text(encoding="utf-8-sig"), filename=str(filename))
            python_modules.append(filename.relative_to(ROOT).as_posix())
    frontend_lines = [
        "# 新版前端接口对照",
        "",
        "本表来自当前副本的模板与 JavaScript。静态引用检查不代替真实请求和业务验证。",
        f"实际地址数：{len(rules)}；模板固定 endpoint 引用：{len(references)}；未注册引用：{len(missing_endpoints)}。",
        "",
        "## 浏览器请求",
        "",
        "动态拼接的比赛、BP、评论、通知等地址在真实浏览器和针对性接口测试中另行验证。",
        "",
        "| 前端位置 | 请求入口 |",
        "| --- | --- |",
    ]
    frontend_lines += [
        f"| `{item['file']}:{item['line']}` | `{item['call'].replace('|', '&#124;').replace('`', '')}` |"
        for item in fetches
    ]
    frontend_lines += ["", "## 模板引用缺口", ""]
    frontend_lines += [str(item) for item in missing_endpoints] or [
        "没有发现固定 `url_for` 指向未注册地址。"
    ]
    output = ROOT / "output"
    output.mkdir(exist_ok=True)
    (ROOT / "docs" / "REFACTOR_ROUTE_INVENTORY.md").write_text(
        "\n".join(route_lines) + "\n", encoding="utf-8"
    )
    (ROOT / "docs" / "REFACTOR_FRONTEND_CONTRACTS.md").write_text(
        "\n".join(frontend_lines) + "\n", encoding="utf-8"
    )
    report = {
        "route_count": len(rules),
        "python_modules": python_modules,
        "template_references": references,
        "missing_endpoints": missing_endpoints,
        "browser_calls": fetches,
    }
    (output / "backend-contract-inventory.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"路由清单已生成：{len(rules)} 个地址，{len(python_modules)} 个 Python 模块。")
    print(
        f"模板固定引用 {len(references)} 处，未注册引用 {len(missing_endpoints)} 处；浏览器请求入口 {len(fetches)} 处。"
    )
    if missing_endpoints:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
