# API 接口约定

前台 JSON API，都在 `routes/front_api.py` 里。

## 通用说明
- 成功返回: `{ "ok": true, ... }`
- 失败返回: `{ "ok": false, "error": "错误描述" }`，HTTP 状态码 404 或 400
- 分页参数: `?page=1&per_page=20`

---

| # | 路径 | 方法 | 参数 | 返回 |
|---|------|------|------|------|
| 1 | `/api/front/home` | GET | 无 | `news[12]`, `matches[10]`, `recent_results[8]`, `top_players[5]` |
| 2 | `/api/front/features` | GET | 无 | `groups[]` (全站功能清单) |
| 3 | `/api/front/matches` | GET | `?status=active\|completed`, `?date=`, `?event=` | `matches[]` (比赛列表，最多50条) |
| 4 | `/api/front/matches/<id>` | GET | 路径参数 id | `match`, `stats[]`, `comments[]` |
| 5 | `/api/front/news` | GET | `?tag=`, `?page=`, `?per_page=` | `news[]`, `tags[]`, `total`, `page` |
| 6 | `/api/front/news/<id>` | GET | 路径参数 id | `news` (含 content, comments, related_match) |
| 7 | `/api/front/results` | GET | `?event=`, `?page=`, `?per_page=` | `results[]`, `total`, `page` |
| 8 | `/api/front/events` | GET | `?status=ongoing\|completed\|upcoming` | `events[]` |
| 9 | `/api/front/events/<id>` | GET | 路径参数 id | `event`, `matches[]`, `teams[]`, `awards[]`, `champions[]` |
| 10 | `/api/front/players` | GET | `?filter=top10`, `?team=`, `?page=`, `?per_page=` | `players[]`, `total`, `page` |
