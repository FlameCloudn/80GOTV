"""Public home feed, dashboard, and feature listings."""

from datetime import datetime

from flask import jsonify, url_for

from src.website.domains.events.arg_event_service import ordinary_event_condition
from src.website.domains.events.status import add_effective_event_status
from src.website.runtime.database import get_db
from src.website.web.read_models.front_payloads import (
    _event_payload,
    _home_match_payload,
    _news_payload,
    _player_display_name,
    _player_payload,
    _rounded,
    _text,
)
from src.website.web.read_models.home_service import load_home_feed
from src.website.web.routing import site_routes

PUBLIC_FEATURES = [
    {
        "group": "内容",
        "features": [
            {"name": "首页信息流", "page": "/", "api": "/api/front/home"},
            {"name": "新闻列表", "page": "/news", "api": "/api/front/news"},
            {"name": "新闻详情与评论", "page": "/news/<id>", "api": "/api/front/news/<id>"},
            {"name": "站内搜索", "page": "/search", "api": "/api/search"},
        ],
    },
    {
        "group": "比赛",
        "features": [
            {"name": "比赛列表", "page": "/matches", "api": "/api/front/matches"},
            {"name": "赛果列表", "page": "/results", "api": "/api/front/results"},
            {"name": "比赛详情", "page": "/matches/<id>", "api": "/api/front/matches/<id>"},
            {"name": "数据直播", "page": "/matches/<id>#data-live", "api": "/api/live/<id>"},
            {"name": "赛前投票", "page": "/matches/<id>", "api": "/matches/<id>/vote"},
            {"name": "BP 房间", "page": "/bp/<id>", "api": "/api/bp/<id>/state"},
        ],
    },
    {
        "group": "赛事",
        "features": [
            {"name": "赛事列表", "page": "/events", "api": "/api/front/events"},
            {"name": "赛事详情", "page": "/events/<id>", "api": "/api/front/events/<id>"},
            {"name": "赛事数据", "page": "/events/<id>/stats", "api": "/api/front/events/<id>"},
            {
                "name": "MVP/EVP 数据图",
                "page": "/events/<id>",
                "api": "/events/<id>/award-poster/<type>/<player>.png",
            },
            {"name": "赛事报名与加入队伍", "page": "/events/<id>", "api": "HTML form / POST"},
        ],
    },
    {
        "group": "数据",
        "features": [
            {"name": "数据总览", "page": "/stats", "api": "/api/front/stats/overview"},
            {
                "name": "数据子榜单",
                "page": "/stats/overview/<section>",
                "api": "/api/front/stats/overview",
            },
            {
                "name": "选手完整数据",
                "page": "/stats/players/<id>",
                "api": "/api/front/players/<id>",
            },
            {"name": "数据看板", "page": "/dashboard", "api": "/api/front/dashboard"},
            {"name": "积分预测榜", "page": "/predictions", "api": "/api/front/predictions"},
        ],
    },
    {
        "group": "选手与队伍",
        "features": [
            {"name": "选手列表", "page": "/players", "api": "/api/front/players"},
            {"name": "选手主页", "page": "/players/<id>", "api": "/api/front/players/<id>"},
            {"name": "选手对比", "page": "/players/compare", "api": "HTML page"},
            {"name": "队伍列表", "page": "/teams", "api": "/api/front/teams"},
        ],
    },
    {
        "group": "账号与互动",
        "features": [
            {"name": "登录/注册", "page": "/login / /register", "api": "HTML form / Steam OpenID"},
            {"name": "Steam 验证", "page": "/auth/steam/start", "api": "/auth/steam/callback"},
            {"name": "个人资料", "page": "/profile", "api": "HTML form"},
            {"name": "通知", "page": "/notifications", "api": "/api/front/notifications"},
            {"name": "评论点赞/删除", "page": "评论区", "api": "/comment/*"},
            {"name": "论坛", "page": "/forum", "api": "/api/front/forum"},
        ],
    },
    {
        "group": "后台",
        "features": [
            {"name": "后台 Dashboard", "page": "/admin", "api": "HTML admin"},
            {"name": "新闻/赛事/比赛/队伍/选手管理", "page": "/admin/*", "api": "HTML admin"},
            {
                "name": "Demo 导入与统计录入",
                "page": "/admin/matches/<id>/import-demo",
                "api": "HTML admin",
            },
            {
                "name": "直播状态与 GOTV/GSI 接收",
                "page": "/admin/live",
                "api": "/api/gotv/stats / /api/gsi/receive",
            },
        ],
    },
]


@site_routes.route("/api/front/home")
def api_front_home():
    """Home page data for progressive frontend rendering."""
    conn = get_db()
    try:
        feed = load_home_feed(conn)
    finally:
        conn.close()
    news_rows = feed["news"]
    forum_rows = feed["forum_activity"]
    match_rows = feed["matches"]
    recent_rows = feed["recent"]
    top_players = feed["top_players"]

    return jsonify(
        {
            "ok": True,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "news": [_news_payload(row) for row in news_rows],
            "forum_activity": [
                {
                    "id": row["id"],
                    "url": url_for("forum_thread", thread_id=row["id"]),
                    "title": _text(row["title"]),
                    "replies": int(row["reply_count"] or 0),
                }
                for row in forum_rows
            ],
            "matches": [_home_match_payload(row) for row in match_rows],
            "recent_results": [_home_match_payload(row) for row in recent_rows],
            "top_players": [
                {
                    "id": row["id"],
                    "url": url_for("player_detail", player_id=row["id"]),
                    "nickname": _player_display_name(row["id"], row["nickname"]),
                    "rating": _rounded(row["avg_rating"], 2),
                }
                for row in top_players
            ],
        }
    )


@site_routes.route("/api/front/features")
def api_front_features():
    """Current site feature manifest for frontend navigation and docs."""
    return jsonify({"ok": True, "groups": PUBLIC_FEATURES})


@site_routes.route("/api/front/dashboard")
def api_front_dashboard():
    """首页数据合并端点 —— 一次请求获取 news、matches、events、top_players、MVP/EVP 等首页全部数据。"""
    conn = get_db()
    feed = load_home_feed(conn)
    news_rows = feed["news"]
    match_rows = feed["matches"]
    recent_rows = feed["recent"]
    top_players = feed["top_players"]

    # —— 赛事列表（含比赛/队伍数统计）——
    event_rows = conn.execute(f"""
        SELECT e.*,
               COUNT(DISTINCT CASE
                   WHEN COALESCE(m.status, '') != 'cancelled' THEN m.id
               END) AS match_count,
               (SELECT COUNT(DISTINCT team_id) FROM (
                   SELECT team1_id AS team_id FROM matches
                   WHERE event_id = e.id AND COALESCE(status, '') != 'cancelled'
                   UNION
                   SELECT team2_id FROM matches
                   WHERE event_id = e.id AND COALESCE(status, '') != 'cancelled'
               )) AS team_count
        FROM events e
        LEFT JOIN matches m ON e.id=m.event_id
        WHERE {ordinary_event_condition("e")}
        GROUP BY e.id
        ORDER BY e.start_date DESC
    """).fetchall()
    event_rows = [add_effective_event_status(row) for row in event_rows]

    # —— MVP 排行 TOP 5 ——
    mvp = conn.execute("""
        SELECT p.id, p.nickname, p.avatar,
               COALESCE((
                   SELECT NULLIF(TRIM(u.group_username), '')
                   FROM users u
                   WHERE u.steam_id64=p.steam_id
                   ORDER BY COALESCE(u.is_placeholder, 0), u.id DESC
                   LIMIT 1
                ), NULLIF(TRIM(p.group_username_override), ''), '') AS group_username,
               COALESCE((
                   SELECT u.is_bashizhong_student
                   FROM users u
                   WHERE u.steam_id64=p.steam_id
                   ORDER BY COALESCE(u.is_placeholder, 0), u.id DESC
                   LIMIT 1
               ), p.is_bashizhong_student) AS managed_is_bashizhong_student,
               COUNT(pm.id) AS count
        FROM player_medals pm
        JOIN players p ON pm.player_id=p.id
        WHERE pm.type='MVP'
        GROUP BY p.id
        ORDER BY count DESC, p.nickname ASC
        LIMIT 5
    """).fetchall()

    # —— EVP 排行 TOP 5 ——
    evp = conn.execute("""
        SELECT p.id, p.nickname, p.avatar,
               COALESCE((
                   SELECT NULLIF(TRIM(u.group_username), '')
                   FROM users u
                   WHERE u.steam_id64=p.steam_id
                   ORDER BY COALESCE(u.is_placeholder, 0), u.id DESC
                   LIMIT 1
                ), NULLIF(TRIM(p.group_username_override), ''), '') AS group_username,
               COALESCE((
                   SELECT u.is_bashizhong_student
                   FROM users u
                   WHERE u.steam_id64=p.steam_id
                   ORDER BY COALESCE(u.is_placeholder, 0), u.id DESC
                   LIMIT 1
               ), p.is_bashizhong_student) AS managed_is_bashizhong_student,
               COUNT(pm.id) AS count
        FROM player_medals pm
        JOIN players p ON pm.player_id=p.id
        WHERE pm.type='EVP'
        GROUP BY p.id
        ORDER BY count DESC, p.nickname ASC
        LIMIT 5
    """).fetchall()

    # —— 各赛事比赛数统计 ——
    event_matches = conn.execute(f"""
        SELECT e.id, e.name, COUNT(m.id) AS matches
        FROM events e
        LEFT JOIN matches m ON e.id=m.event_id
        WHERE {ordinary_event_condition("e")}
        GROUP BY e.id
        ORDER BY matches DESC, e.start_date DESC
        LIMIT 10
    """).fetchall()

    conn.close()

    return jsonify(
        {
            "ok": True,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            # 首页合并数据
            "news": [_news_payload(row) for row in news_rows],
            "matches": [_home_match_payload(row) for row in match_rows],
            "recent_results": [_home_match_payload(row) for row in recent_rows],
            "events": [_event_payload(row) for row in event_rows],
            "top_players": [
                {
                    "id": row["id"],
                    "url": url_for("player_detail", player_id=row["id"]),
                    "nickname": _player_display_name(row["id"], row["nickname"]),
                    "rating": _rounded(row["avg_rating"], 2),
                }
                for row in top_players
            ],
            # 原有 dashboard 数据（MVP / EVP / 赛事统计）
            "mvp_top5": [{**_player_payload(row), "count": row["count"]} for row in mvp],
            "evp_top5": [{**_player_payload(row), "count": row["count"]} for row in evp],
            "event_matches": [
                {"id": row["id"], "name": _text(row["name"]), "matches": row["matches"]}
                for row in event_matches
            ],
        }
    )
