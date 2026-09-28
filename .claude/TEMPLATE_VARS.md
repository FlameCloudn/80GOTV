# 模板变量参考

列出项目中最常用的5个模板，以及每个模板需要的变量。  
写新页面或排查"变量未定义"错误时看这里。

---

## base.html

所有页面共用的基础模板。

| 变量 | 类型 | 说明 |
|------|------|------|
| csrf_token | str | CSRF 令牌，防跨站攻击，每个页面都必须有 |
| session.user_id | int / None | 当前登录用户的 ID |
| session.user_username | str / None | 当前登录用户的用户名 |
| session.admin_id | int / None | 管理员 ID（登录后台后才有） |
| unread_count | int | 未读通知数量（base.html 里通知铃铛用） |

---

## index.html

首页。

| 变量 | 类型 | 说明 |
|------|------|------|
| news | list[Row] | 新闻列表，第一条作焦点新闻，其余作列表 |
| matches | list[Row] | 今日比赛列表 |
| recent | list[Row] | 近期赛果列表 |
| team_ranking | list[Row] | 队伍排行（按胜场排序） |
| active_events | list[Row] | 活跃赛事列表 |
| top_players | list[Row] | TOP 5 高分选手 |

---

## match_detail.html

比赛详情页，最复杂的模板。

| 变量 | 类型 | 说明 |
|------|------|------|
| match | Row / dict | 比赛完整信息（队伍、比分、时间、状态等） |
| map_scores | list[dict] | 每张地图的分数和选手数据 |
| show_match_stats | bool | 是否显示统计模式（有 Demo 数据时为 True） |
| overall_t1 / overall_t2 | list[Row] | 两队选手总数据 |
| t1_win | bool | 队1 是否获胜 |
| h2h_matches | list[Row] | 历史交锋记录 |
| comments | list[Row] | 评论列表 |
| vote_data | dict | 赛前投票数据（t1_count, t2_count, total, user_voted） |
| sidebar_events / sidebar_matches / sidebar_news | list[Row] | 侧边栏数据 |
| match_breakdown | dict | 比赛数据总览（rating、首杀、残局） |
| match_highlights | list[dict] | 比赛亮点（最高 rating、最多击杀等） |
| match_performance_rows | list[Row] | 表现条数据（rating 进度条用） |

---

## news_detail.html

新闻详情页。

| 变量 | 类型 | 说明 |
|------|------|------|
| news | Row | 新闻完整信息（title, content, author, publish_time, tags 等） |
| comments | list[Row] | 评论列表 |
| related_match | Row / None | 关联比赛信息 |
| hot_tags | list[tuple] | 热门标签（(tag, count) 元组列表） |

---

## player_detail.html

选手主页。

| 变量 | 类型 | 说明 |
|------|------|------|
| player | Row | 选手基本信息（nickname, real_name, team_name, avatar 等） |
| player_summary | Row | 选手生涯总数据（rating, maps 等） |
| recent_matches | list[Row] | 近期比赛记录 |
| medals | list[Row] | 荣誉列表（MVP/EVP） |
| championships | list[Row] | 冠军记录 |
| teammates | list[Row] | 同队队友列表 |
| nickname_history | list[Row] | 历史昵称记录 |
| player_category_cards | list[dict] | 选手能力卡片数据 |
