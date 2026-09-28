# 命名约定

## Python 变量: snake_case
```python
player_name = "s1mple"
team_short_name = "NaVi"
match_count = 5
```

## 数据库字段: snake_case
```sql
short_name, team_id, match_time, created_at
```

## CSS class: kebab-case
```css
.match-card { }
.player-avatar { }
.nav-link { }
```

## 路由函数: 功能_动作
```python
# 比赛相关
match_detail      # 比赛详情页
match_list        # 比赛列表页
match_search      # 比赛搜索

# 选手相关
player_detail     # 选手详情页
player_stats      # 选手统计
player_search     # 选手搜索

# 赛事相关
event_detail      # 赛事详情页
event_list        # 赛事列表
```

## 模板文件: 功能_子页.html
```
match_detail.html     # 比赛详情
match_list.html       # 比赛列表（文件名可用 matches.html）
player_detail.html    # 选手详情
event_detail.html     # 赛事详情
news_detail.html      # 新闻详情
```

## 后台路由（blueprints/admin/）
加 `admin_` 前缀：
```python
admin_match_form      # 后台比赛编辑页
admin_player_list     # 后台选手列表
```
