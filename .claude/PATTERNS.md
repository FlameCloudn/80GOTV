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

---

## 前台页面样式模板

写新页面时照这个骨架来，全站风格才会一致。不要写行内 `style="..."`，不要自己发明颜色。

```html
{% extends 'base.html' %}
{% block title %}页面名 - 80GOTV{% endblock %}
{% block layout_class %}no-side-layout{% endblock %}
{% block main %}
{# 页面标题条：小字英文标签 + 中文标题 #}
<header class="page-head">
  <div><span class="page-head-kicker" data-i18n-ignore>SECTION</span><h1>页面名</h1></div>
  <p class="page-head-meta">右侧的补充说明（可不写）</p>
</header>

{# 带标题栏的面板 #}
<section class="h-panel">
  <div class="h-panel-title">面板标题</div>
  <form method="post" class="ui-panel-body ui-form ui-form--narrow">
    <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
    <label class="ui-field">
      <span class="ui-label">输入框名字</span>
      <input type="text" name="example">
      <span class="ui-hint">输入框下面的小提示</span>
    </label>
    <button type="submit" class="ui-btn ui-btn--primary">主要按钮</button>
    <a href="/" class="ui-btn">次要按钮</a>
  </form>
</section>

<div class="empty-state">暂无数据</div>
{% endblock %}
{% block side %}{% endblock %}
```

规矩：

- **颜色、字号、间距**只用 `templates/_design_tokens.html` 里的变量，例如
  `var(--bg-card)` 面板底色、`var(--text-muted)` 次要文字、`var(--accent)` 强调蓝、
  `var(--color-green)` / `var(--color-red)` 胜负、`var(--font-sm)` 小字号。
- 通用组件都在 `static/css/hltv_refresh.css` 最后的"全站统一层"里，先找现成的再写新的。
- 全站老样式里有一条"所有元素 13px、不加粗"的强制规则，所以**改字号、加粗必须写 `!important`** 才生效。
- 不带导航栏的独立页面（登录、改密码）开头引入 `{% include "_standalone_head.html" %}`，样式放 `static/css/auth.css`。
- **手机端**的版式规则集中在 `static/css/mobile_hltv.css` 最后的"手机端 HLTV 版式"一段，数值是对照 HLTV 手机版量出来的
  （导航 46px、左右边距 10px、标题 13px 粗体写在页面底色上、卡片无边框细阴影）。新页面只要用上面的统一组件，手机上会自动套用。
- 需要再对照 HLTV 时：官网有人机验证打不开，用公开存档 `https://web.archive.org/web/2025/https://www.hltv.org/`（手机宽度打开）。
- **手机 / 电脑分界线是 760px**：≤760 用手机版式，≥761 用电脑版式。新写的媒体查询也用 760，不要再用 768（以前 761–768 两套样式叠在一起出过错位）。
- **顶部导航放不下时**不用改断点：`main.js` 会按实际宽度给 `.navbar` 逐级加 `nav-fit-1/2/3`，把次要入口收进“更多”。
  导航里新加入口时，在 `hltv_refresh.css` 的“顶部导航自动收纳”一段决定它在第几级被收起，并在“更多”菜单里补一个同名链接。
- **筛选链接只改自己那一项**：日历、赛事、阵营这类筛选，链接里要带上其他已选条件（参考 `matches.html` 顶部的 `filter_url`），
  不然点一下就把别的筛选清掉了。
- **提示条 / 确认框**用 `showToast('文字', 'success'|'error')`、`showConfirm('文字')`，定义在 `static/js/site_dialogs.js`。
  前台页面已自动引入；后台那种不继承 `base.html` 的独立页面要自己加 `<script src="{{ versioned_url('static/js/site_dialogs.js') }}">`。
- **数据缺失不要显示成 0**：旧 Demo 没有的字段（比如闪光弹投掷次数）显示“暂无数据”（`<span class="stat-missing">暂无数据</span>`）。
- **列表尺寸对照 HLTV**（规则集中在 `hltv_refresh.css` 第 19 节“容器尺寸与布局”）：
  - 列表里的队标、头像一律写死尺寸（赛果 20px、比赛列表 22px），用 `object-fit: contain`；上传的原图可能是 512px，不写尺寸就会把整行撑高。
  - 比赛条 `.card.match-card`：电脑上一行“队伍1 | 比分 | 队伍2 | 赛事信息”，队名贴着比分；手机上两行。
  - 只有“头像 + 名字”的列表（队伍列表、阵容）在电脑上排成多列网格，不要一行占满整个版心。
  - 普通数据表格按内容分配列宽、数字不换行，放不下时表格自己左右滑；只有 `.stats-dense-table` 用固定列宽。
  - 正文类页面（新闻详情）用窄版宽度 `var(--narrow-width)`，不要让一行字拉到 1100px。

## 队标（显示、上传、批量处理）

- **显示**：模板里队标地址一律写 `{{ 队标字段|team_logo_url }}`，不要再自己拼 `url_for('static', filename='uploads/' ~ ...)`。
  数据库里两种存法（队伍资料存 `team_logos/文件名`，赛事报名只存 `文件名`）这个过滤器都认得，
  地址后面还会带上文件修改时间，换了队标浏览器马上显示新的。
  Python 里用 `services/team_logo_service.py` 的 `team_logo_url()`；直播 HUD 接口要的 `/static/...` 路径用 `team_logo_static_path()`。
- **上传**：后台“队伍”和赛事报名都走 `utils/db_helpers.py` 的 `save_uploaded_team_logo()`：
  自动去掉纯色背景、裁掉空白、居中成 256×256 的透明 PNG；原图备份在 `instance/team_logo_originals/`（不对外公开）。
- **已有队标批量处理**：先运行 `python scripts/process_team_logos.py` 看报告（不改任何东西），确认后加 `--apply`。
  重复运行也安全（总是从原图备份重新处理）；还会把“队伍资料没有队标或文件丢了、但同名报名队伍有队标”的补上。
- 深色模式下队标外圈有一圈很淡的亮边（变量 `--logo-outline`），防止深色队标和背景混在一起，新页面不用另外处理。

## 翻译（中英文）约定

网站文字写中文，英文由 `static/js/i18n.js` 里的词典自动替换。

- 新加了界面文字 → 在 `i18n.js` 的 `laterPageTranslations` 里加一行 `'中文': 'English'`。
- 带数字的句子（如"第 3 回合"）→ 在 `zhToEnPatterns` 里加一条句式。
- 选手名、队名、新闻标题这类**用户自己写的内容**，标签上加 `data-i18n-ignore`，不要翻译。
- 不要给整个页面加 `data-i18n-ignore`（那样英文模式下整页都是中文）。
  如果一大块区域确实不能翻译，里面需要翻译的小标签可以单独加 `data-i18n-translate`。
- JS 里生成的提示文字用 `window.siteTranslate('中文')` 取翻译。
- 改完跑一下检查：`$env:PLAYWRIGHT_CHANNEL='msedge'; npx playwright test`（会检查英文模式下有没有漏翻）。
