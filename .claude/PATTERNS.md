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

写新页面时照这个骨架来，全站风格才会一致。不要写行内 `style="..."`（按数据算出来的宽度、背景图除外），不要自己发明颜色。

```html
{% extends 'base.html' %}
{% block title %}页面名 - 80GOTV{% endblock %}
{% block head %}<link rel="stylesheet" href="{{ versioned_url('static/css/pages/页面名.css') }}">{% endblock %}
{% block layout_class %}no-side-layout{% endblock %}
{% block main %}
{# 页面标题条：小字英文标签 + 中文标题；右边放补充说明或一个链接 #}
<header class="page-head">
  <div><span class="page-head-kicker" data-i18n-ignore>SECTION</span><h1>页面名</h1></div>
  <p class="page-head-meta">右侧的补充说明（可不写）</p>
</header>

{# 带标题栏的面板（圆角、边框、底色都由 .panel 负责） #}
<section class="panel">
  <div class="panel-head"><h2 class="panel-title">面板标题</h2><span class="panel-count">12</span></div>
  <form method="post" class="panel-body form form-narrow">
    <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
    <label class="field">
      <span class="field-label">输入框名字</span>
      <input type="text" name="example">
      <span class="field-hint">输入框下面的小提示</span>
    </label>
    <div class="form-actions">
      <a href="/" class="btn">次要按钮</a>
      <button type="submit" class="btn btn-primary">主要按钮</button>
    </div>
  </form>
</section>

{# 一行一条的列表：a.list-row，左边 .grow 吃掉剩余宽度，右边 .meta 小字 #}
<section class="panel">
  <div class="panel-head"><h2 class="panel-title">列表</h2></div>
  <div class="list">
    <a class="list-row" href="#"><span class="grow title">标题</span><span class="meta">小字</span></a>
  </div>
</section>

<div class="panel empty-state">暂无数据</div>
{% endblock %}
{% block side %}{% endblock %}
```

常用组件（都在 `static/css/app.css`，先找现成的再写新的）：

| 用途 | 类名 |
|------|------|
| 面板 / 标题栏 / 内容区 | `.panel` `.panel-head` `.panel-title` `.panel-count` `.panel-link` `.panel-body` |
| 列表行 | `.list` > `.list-row`（`.grow` `.title` `.meta`） |
| 按钮 | `.btn`，加 `.btn-primary`（主要）`.btn-danger`（删除）`.btn-sm`（小号） |
| 表单 | `.form` `.form-narrow` `.field` `.field-label` `.field-hint` `.field-required` `.form-row` `.form-actions` |
| 下划线标签 / 分段按钮 | `.tabs` > `.tab.active`；`.segmented` > `a.active`（每日/自由、双方/T/CT 这类切换） |
| 表格 | `.table-wrap` > `table.table`，数字列 `th.num`/`td.num`，居中 `.center`，可排序 `th.sortable` |
| 小角标 | `.badge`（`.badge-live` `.badge-gold` `.badge-purple` `.badge-green` `.badge-red`，方一点用 `.badge-square`） |
| 数字格 / 两列事实 | `.stat-grid` > `.stat`（`.stat-label` `.stat-value`）；`dl.facts` |
| 队标 / 头像 | `.team-logo sm/md/lg/xl`、`.logo-fallback`；`.avatar xs/sm/md/lg/xl` |
| 比赛条 | `.card-list` > `a.match-card`（`.team` `.vs` `.team.right` `.meta`） |
| 提示条 / 翻页 / 返回链接 | `.alert alert-error/success/info`、`.pagination`、`.back-link` |
| 空状态 | `.empty-state`（放在面板里时写 `class="panel empty-state"`） |

规矩：

- **颜色、字号、间距、圆角**只用 `templates/_design_tokens.html` 里的变量，例如
  `var(--bg-card)` 面板底色、`var(--text-muted)` 次要文字、`var(--accent)` 强调蓝、
  `var(--color-green)` / `var(--color-red)` 胜负、`var(--color-ct)` / `var(--color-t)` 阵营、`var(--font-sm)` 小字号、
  `var(--radius-sm/md/lg)` 圆角。缺颜色就先在变量文件里加（深色、浅色两套都要写），再用。
- **全站都是圆角**：面板 `--radius-lg`，按钮、输入框、小卡片 `--radius-md`，角标、小格子 `--radius-sm`。
  面板里贴边的整行（表头、列表行）本身不用圆角，由面板裁掉；贴着面板上下边又带底色的，记得给面板加 `overflow: hidden`。
- **每个页面一个样式文件**：放 `static/css/pages/`（比赛页 `match.css`、选手 `player.css`、队伍 `teams.css`、
  数据统计 `stats.css`、论坛 `forum.css`、个人页/通知/搜索/预测 `account.css`、看板/荣誉堂 `dashboard.css`……），
  在模板的 `{% block head %}` 里引入；全站共用的东西才写进 `app.css`。小游戏用 `games.css`、`guess_player.css`。
  `static/css/style.css` 只给后台用，前台不要再引用。
- 不带导航栏的独立页面（登录、注册、改密码）开头引入 `{% include "_standalone_head.html" %}`，样式放 `static/css/auth.css`。
- **断点**：≤760px 手机版式；≤960px 顶栏换成手机抽屉；≤1080px 右侧栏排到正文下面。新写的媒体查询也用这几个数。
- **顶部导航放不下时**不用改断点：`main.js` 会按实际宽度给 `.navbar` 逐级加 `nav-fit-1/2/3/4`，把次要入口收进“更多”，
  对应规则在 `app.css` 第 3 节。新加入口时决定它在第几级被收起，并在“更多”菜单里补一个同名链接。
- **布局照 HLTV**：拿不准就打开 HLTV 对应页面对照（官网有人机验证打不开，用公开存档
  `https://web.archive.org/web/2025/https://www.hltv.org/...`）。HLTV 的条形图数值和颜色写在页面的 `data-fusionchart-config` 里，可以直接读出来。
- **筛选链接只改自己那一项**：日历、赛事、阵营这类筛选，链接里要带上其他已选条件（参考 `matches.html` 顶部的 `filter_url`），
  不然点一下就把别的筛选清掉了。
- **提示条 / 确认框**用 `showToast('文字', 'success'|'error')`、`showConfirm('文字')`，定义在 `static/js/site_dialogs.js`。
  前台页面已自动引入；后台那种不继承 `base.html` 的独立页面要自己加 `<script src="{{ versioned_url('static/js/site_dialogs.js') }}">`。
- **数据缺失不要显示成 0**：旧 Demo 没有的字段（比如闪光弹投掷次数）显示“暂无数据”（`<span class="stat-missing">暂无数据</span>`）。
- **列表尺寸**：
  - 列表里的队标、头像一律写死尺寸（用上面的 `sm/md/...`），上传的原图可能是 512px，不写尺寸就会把整行撑高。
  - 只有“头像 + 名字”的列表（队伍列表、阵容）在电脑上排成多列网格，不要一行占满整个版心。
  - 数据表格放不下时由 `.table-wrap` 左右滑，页面本身不能出现横向滚动条（手机 390px 宽也要检查）。
  - 正文类页面（新闻详情、表单）用窄版：`{% block layout_class %}no-side-layout narrow-layout{% endblock %}`。

## 队标（显示、上传、批量处理）

- **显示**：模板里队标地址一律写 `{{ 队标字段|team_logo_url }}`，不要再自己拼 `url_for('static', filename='uploads/' ~ ...)`。
- **没有队标时圆圈里的字**：一律写 `{{ 队名|team_abbr(简称) }}`（赛事用 `event_abbr`），不要自己切 `[:2]`。
  规则（utils/helpers.py）：有 4 个字以内的简称就用简称；临时队伍 TEAM X → TX；赛事取第一个词前两个字母 + 年份后两位或届数（SU26、SP26、CH1）。
  搜索弹窗等脚本里的缩写由接口的 `abbr` 字段给出，同一套规则。
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
- **术语不翻译**：Rating、Impact、KAST、ADR、K/D、HS%、MVP/EVP、T/CT、地图名（Mirage……）、武器名中文界面也写英文，
  写在模板里时加 `data-i18n-ignore`（或放进 `i18n.js` 的 `KEEP_ENGLISH_TERMS`），免得被反向翻成中文。
  描述性的数据名称用玩家平时的说法（“每回合首杀”），英文照搬 HLTV 原词（“Opening kills per round”）。对阵写“VS”，不写“对”。
- 不要给整个页面加 `data-i18n-ignore`（那样英文模式下整页都是中文）。
  如果一大块区域确实不能翻译，里面需要翻译的小标签可以单独加 `data-i18n-translate`。
- JS 里生成的提示文字用 `window.siteTranslate('中文')` 取翻译。
- 改完跑一下检查：`$env:PLAYWRIGHT_CHANNEL='msedge'; npx playwright test`（会检查英文模式下有没有漏翻）。
