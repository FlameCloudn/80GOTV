# 注释规范

## Python
每个函数一行中文 docstring 说明用途：

```python
def get_player_stats(player_id):
    """根据选手 ID 查询所有比赛统计数据。"""
    return query_db("SELECT * FROM match_stats WHERE player_id=?", (player_id,))
```

- 用三引号 `""" """` 写在函数定义下一行
- 一句话说清楚这个函数是干什么的
- 复杂的函数可以在 docstring 里多写几行

## HTML（Jinja2 模板）
区块用 `{# 说明 #}` 标记：

```html
{# 导航栏 #}
<nav class="navbar">...</nav>

{# 比赛列表 #}
<div class="match-list">...</div>
```

- 每个大区块（导航、列表、侧边栏、页脚）前面加一句注释
- Jinja2 注释不会出现在最终 HTML 里

## CSS
每个 section 用 `/* === 标题 === */` 分隔：

```css
/* === 导航栏 === */
.navbar { ... }

/* === 比赛卡片 === */
.match-card { ... }

/* === 页脚 === */
.footer { ... }
```

- 等于号数量随意，保持整齐就好
- 每个独立区域之间空一行
