#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
代码片段生成器
生成常用的代码模板
用法:
  python gen_scaffold.py route <名称>     → 生成新路由模板
  python gen_scaffold.py api <名称>       → 生成新API模板
  python gen_scaffold.py template <名称>  → 生成新HTML模板
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

# --- 路由模板 ---
ROUTE_TEMPLATE = '''# -*- coding: utf-8 -*-
"""{name} 相关路由"""

from flask import Blueprint, render_template, request, redirect, url_for, flash

{name}_bp = Blueprint("{name}", __name__, url_prefix="/{name}")


@{name}_bp.route("/")
def index():
    """列表页"""
    return render_template("{name}/index.html")


@{name}_bp.route("/<int:item_id>")
def detail(item_id: int):
    """详情页"""
    return render_template("{name}/detail.html", item_id=item_id)


@{name}_bp.route("/create", methods=["GET", "POST"])
def create():
    """创建"""
    if request.method == "POST":
        # TODO: 处理表单数据
        flash("创建成功", "success")
        return redirect(url_for("{name}.index"))
    return render_template("{name}/form.html")


@{name}_bp.route("/<int:item_id>/edit", methods=["GET", "POST"])
def edit(item_id: int):
    """编辑"""
    if request.method == "POST":
        # TODO: 处理表单数据
        flash("更新成功", "success")
        return redirect(url_for("{name}.detail", item_id=item_id))
    return render_template("{name}/form.html", item_id=item_id)


@{name}_bp.route("/<int:item_id>/delete", methods=["POST"])
def delete(item_id: int):
    """删除"""
    # TODO: 执行删除操作
    flash("删除成功", "success")
    return redirect(url_for("{name}.index"))
'''

# --- API模板 ---
API_TEMPLATE = '''# -*- coding: utf-8 -*-
"""{name} API 接口"""

from flask import Blueprint, request, jsonify

{name}_api = Blueprint("{name}_api", __name__, url_prefix="/api/{name}")


@{name}_api.route("/", methods=["GET"])
def list_items():
    """获取列表 GET /api/{name}/"""
    # TODO: 从数据库查询
    items = []
    return jsonify({{"data": items, "total": len(items)}})


@{name}_api.route("/<int:item_id>", methods=["GET"])
def get_item(item_id: int):
    """获取单个 GET /api/{name}/<id>"""
    # TODO: 从数据库查询
    item = {{"id": item_id}}
    if not item:
        return jsonify({{"error": "未找到"}}), 404
    return jsonify({{"data": item}})


@{name}_api.route("/", methods=["POST"])
def create_item():
    """创建 POST /api/{name}/"""
    data = request.get_json()
    if not data:
        return jsonify({{"error": "请提供JSON数据"}}), 400
    # TODO: 保存到数据库
    return jsonify({{"message": "创建成功", "data": data}}), 201


@{name}_api.route("/<int:item_id>", methods=["PUT"])
def update_item(item_id: int):
    """更新 PUT /api/{name}/<id>"""
    data = request.get_json()
    # TODO: 更新数据库
    return jsonify({{"message": "更新成功"}})


@{name}_api.route("/<int:item_id>", methods=["DELETE"])
def delete_item(item_id: int):
    """删除 DELETE /api/{name}/<id>"""
    # TODO: 从数据库删除
    return jsonify({{"message": "删除成功"}})
'''

# --- HTML模板 ---
HTML_TEMPLATE = '''{{% extends "base.html" %}}

{{% block title %}}{name} - 80GOTV{{% endblock %}}

{{% block content %}}
<div class="container">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h1>{name}</h1>
        <a href="{{{{ url_for('{name}.create') }}}}" class="btn btn-primary">新建</a>
    </div>

    <!-- 搜索框 -->
    <div class="card mb-4">
        <div class="card-body">
            <form method="GET" class="row g-3">
                <div class="col-md-8">
                    <input type="text" name="search" class="form-control"
                           placeholder="搜索..." value="{{{{ request.args.get('search', '') }}}}">
                </div>
                <div class="col-md-4">
                    <button type="submit" class="btn btn-outline-primary w-100">搜索</button>
                </div>
            </form>
        </div>
    </div>

    <!-- 列表 -->
    <div class="card">
        <div class="card-body">
            <table class="table table-striped">
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>名称</th>
                        <th>操作</th>
                    </tr>
                </thead>
                <tbody>
                    <!-- TODO: 遍历数据 -->
                    <tr>
                        <td colspan="3" class="text-center text-muted">暂无数据</td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>
</div>
{{% endblock %}}
'''

# --- 表单模板 ---
FORM_TEMPLATE = '''{{% extends "base.html" %}}

{{% block title %}}{name} 表单 - 80GOTV{{% endblock %}}

{{% block content %}}
<div class="container">
    <h1 class="mb-4">{{{{ "编辑" if item else "新建" }}}}{name}</h1>

    <div class="card">
        <div class="card-body">
            <form method="POST" class="row g-3">
                <div class="col-md-6">
                    <label for="name" class="form-label">名称</label>
                    <input type="text" class="form-control" id="name" name="name"
                           value="{{{{ item.name if item else '' }}}}" required>
                </div>

                <div class="col-md-6">
                    <label for="description" class="form-label">描述</label>
                    <textarea class="form-control" id="description" name="description"
                              rows="3">{{{{ item.description if item else '' }}}}</textarea>
                </div>

                <div class="col-12">
                    <button type="submit" class="btn btn-primary">保存</button>
                    <a href="{{{{ url_for('{name}.index') }}}}" class="btn btn-secondary">取消</a>
                </div>
            </form>
        </div>
    </div>
</div>
{{% endblock %}}
'''

# --- 详情模板 ---
DETAIL_TEMPLATE = '''{{% extends "base.html" %}}

{{% block title %}}{name} 详情 - 80GOTV{{% endblock %}}

{{% block content %}}
<div class="container">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h1>{name} 详情</h1>
        <div>
            <a href="{{{{ url_for('{name}.edit', item_id=item.id) }}}}" class="btn btn-warning">编辑</a>
            <a href="{{{{ url_for('{name}.index') }}}}" class="btn btn-secondary">返回列表</a>
        </div>
    </div>

    <div class="card">
        <div class="card-body">
            <!-- TODO: 显示详情字段 -->
            <p class="text-muted">详情内容待实现</p>
        </div>
    </div>
</div>
{{% endblock %}}
'''


def to_class_name(name: str) -> str:
    """把 snake-case 或 snake_case 转成 首字母大写的显示名"""
    return name.replace("-", " ").replace("_", " ").title()


def generate_route(name: str):
    """生成路由文件"""
    filename = f"{name}.py"
    filepath = os.path.join(PROJECT_ROOT, "routes", filename)

    if os.path.exists(filepath):
        print(f"[跳过] 已存在: {filepath}")
        return

    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    content = ROUTE_TEMPLATE.format(name=name)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✓ 已生成路由: {filepath}")


def generate_api(name: str):
    """生成API文件"""
    filename = f"{name}_api.py"
    filepath = os.path.join(PROJECT_ROOT, "routes", filename)

    if os.path.exists(filepath):
        print(f"[跳过] 已存在: {filepath}")
        return

    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    content = API_TEMPLATE.format(name=name)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✓ 已生成API: {filepath}")


def generate_template(name: str):
    """生成HTML模板文件"""
    display_name = to_class_name(name)
    template_dir = os.path.join(PROJECT_ROOT, "templates", name)

    if os.path.exists(template_dir):
        print(f"[跳过] 模板目录已存在: {template_dir}")
        return

    os.makedirs(template_dir, exist_ok=True)

    # 生成 index.html
    index_path = os.path.join(template_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(HTML_TEMPLATE.format(name=name))
    print(f"✓ 已生成模板: {index_path}")

    # 生成 form.html
    form_path = os.path.join(template_dir, "form.html")
    with open(form_path, "w", encoding="utf-8") as f:
        f.write(FORM_TEMPLATE.format(name=name))
    print(f"✓ 已生成模板: {form_path}")

    # 生成 detail.html
    detail_path = os.path.join(template_dir, "detail.html")
    with open(detail_path, "w", encoding="utf-8") as f:
        f.write(DETAIL_TEMPLATE.format(name=name))
    print(f"✓ 已生成模板: {detail_path}")


def main():
    if len(sys.argv) < 3:
        print("用法:")
        print("  python gen_scaffold.py route <名称>     → 生成路由文件到 routes/")
        print("  python gen_scaffold.py api <名称>       → 生成API文件到 routes/")
        print("  python gen_scaffold.py template <名称>  → 生成HTML模板到 templates/<名称>/")
        print()
        print(f"项目路径: {PROJECT_ROOT}")
        sys.exit(1)

    cmd = sys.argv[1].lower()
    name = sys.argv[2].lower()

    # 验证名称：只允许字母、数字、下划线、连字符
    if not name.replace("-", "").replace("_", "").isalnum():
        print(f"[错误] 名称只能包含字母、数字、下划线和连字符: {name}")
        sys.exit(1)

    if cmd == "route":
        generate_route(name)
    elif cmd == "api":
        generate_api(name)
    elif cmd == "template":
        generate_template(name)
    else:
        print(f"[错误] 未知命令: {cmd}")
        print("支持的命令: route, api, template")
        sys.exit(1)


if __name__ == "__main__":
    main()
