# 项目常用代码模式

每个模式是一个可复制的代码模板，写新功能时直接参考。

---

## 新路由文件模板

```python
# 用途：创建一个新的前台路由文件（放 routes/ 下）
from flask import render_template, request, redirect, url_for
from models import get_db
from web_app import app


@app.route('/你的路径')
def your_view():
    """页面说明"""
    conn = get_db()
    data = conn.execute("SELECT * FROM 表名 ORDER BY id DESC LIMIT 20").fetchall()
    conn.close()
    return render_template('你的模板.html', data=data)
```

---

## 数据库查询模板

```python
# 用途：查询数据库，获取多条记录
from models import get_db

conn = get_db()
rows = conn.execute("SELECT * FROM 表名 WHERE 条件=? ORDER BY id DESC LIMIT ?", (参数, 数量)).fetchall()
conn.close()
# 返回的是 sqlite3.Row 对象列表，可以像字典一样用 row['字段名']
```

```python
# 用途：插入或更新数据（用 execute_db 或 db() 上下文）
from models import execute_db

# 简单执行（不需要返回值）
execute_db("INSERT INTO 表名 (列1, 列2) VALUES (?, ?)", (值1, 值2))

# 需要事务或多次操作时用 db() 上下文
from models import db
with db() as conn:
    conn.execute("INSERT INTO ...", (...))
    conn.execute("UPDATE ...", (...))
    # 自动 commit，出错自动 rollback
```

---

## 表单提交 + CSRF 模板

```html
<!-- 用途：在任何页面上加一个需要防止跨站攻击的表单 -->
<form method="post" action="/提交地址">
  <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
  <!-- 你的表单项 -->
  <input type="text" name="字段名" required>
  <button type="submit">提交</button>
</form>
```

```python
# 对应后端处理（CSRF 验证由 before_request 自动完成）
@app.route('/提交地址', methods=['POST'])
def handle_form():
    value = request.form.get('字段名', '').strip()
    # 处理数据...
    return redirect(url_for('某个页面'))
```

---

## API 返回 JSON 模板

```python
# 用途：写一个返回 JSON 数据的接口（给前端 JS 调用）
from flask import jsonify, request

@app.route('/api/路径')
def api_example():
    # 读取查询参数
    page = request.args.get('page', 1, type=int)
    # 查数据库
    conn = get_db()
    rows = conn.execute("SELECT * FROM 表名 LIMIT 10").fetchall()
    conn.close()
    # 返回 JSON
    return jsonify({
        'ok': True,
        'data': [{'id': r['id'], 'name': r['name']} for r in rows]
    })
```

---

## 模板继承模板

```html
<!-- 用途：创建一个新页面，继承 base.html 的导航栏、样式等 -->
{% extends 'base.html' %}
{% block title %}页面标题 - 80GOTV{% endblock %}

{% block main %}
<h1>页面内容</h1>
<p>你的内容写在这里</p>
{% endblock %}

{% block side %}
<h3 class="section-title">侧边栏标题</h3>
<div class="card small">
  侧边栏内容
</div>
{% endblock %}
```
