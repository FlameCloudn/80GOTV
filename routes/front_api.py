"""Public JSON endpoints used by the frontend.

These routes are the first full-site API layer. Existing HTML pages stay in
place, while new frontend code can read the same data as JSON.
"""

from contextlib import closing
from datetime import datetime

from flask import jsonify, request, session, url_for

from models import get_db
from services.home_service import load_home_feed
from services.match_service import (
    add_effective_event_status,
    get_prediction_leaderboard,
    get_prediction_upcoming_matches,
    supplement_temp_teams,
)
from services.performance_service import summary_metric_sql
from services.player_remark_service import (
    private_player_identity,
    private_user_identity,
)
from services.public_data_service import (
    load_map_statistics,
    load_match_page,
    load_player_page,
    load_player_summary,
    load_statistics_totals,
    load_team_statistics,
)
from services.team_logo_service import team_logo_url
from utils.db_helpers import avatar_static_filename
from utils.filters import date_display_filter, datetime_display_filter, time_display_filter
from utils.helpers import event_abbr, event_path, news_path, team_abbr
from utils.match_utils import (
    get_sql_effective_status,
    get_sql_match_completed,
)
from utils.pagination import page_params
from utils.stats_display import optional_number
from web_app import app

_SQL_MATCH_COMPLETED = get_sql_match_completed()
_SQL_EFFECTIVE_STATUS = get_sql_effective_status()

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


def _text(value):
    return "" if value is None else str(value)


def _rounded(value, digits):
    number = optional_number(value)
    return round(number, digits) if number is not None else None


def _user_display_name(username, group_username, user_id=None):
    nickname, group_name = private_user_identity(user_id, username, group_username)
    nickname = _text(nickname).strip()
    group_name = _text(group_name).strip()
    if nickname and group_name:
        return f"{nickname} @{group_name}"
    return nickname or group_name


def _player_display_name(player_id, nickname):
    return _text(private_player_identity(player_id, nickname)[0])


def _keys(row):
    return row.keys() if hasattr(row, "keys") else []


def _has(row, key):
    return key in _keys(row)


def _get(row, key, default=None):
    if row is None:
        return default
    try:
        return row[key] if _has(row, key) else default
    except (KeyError, TypeError, IndexError):
        return default


def _page_params(default=20, maximum=100):
    return page_params(request.args, default, maximum)


def _avatar_url(filename):
    static_filename = avatar_static_filename(app.root_path, filename, thumbnail=True)
    return url_for("static", filename=static_filename) if static_filename else ""


def _logo_url(filename):
    return team_logo_url(filename, app.root_path)


def _match_url(match):
    return url_for("match_detail", slug=_get(match, "slug") or match["id"])


def _match_payload(match):
    return {
        "id": match["id"],
        "url": _match_url(match),
        "event_id": _get(match, "event_id"),
        "event": _text(_get(match, "event_name", "")),
        "team1": _text(_get(match, "team1_name", "TBD") or "TBD"),
        "team2": _text(_get(match, "team2_name", "TBD") or "TBD"),
        "team1_full": _text(_get(match, "team1_name", "TBD")),
        "team2_full": _text(_get(match, "team2_name", "TBD")),
        "team1_short": _text(_get(match, "t1s", "")),
        "team2_short": _text(_get(match, "t2s", "")),
        "team1_logo": _logo_url(_get(match, "team1_logo", "")),
        "team2_logo": _logo_url(_get(match, "team2_logo", "")),
        "score1": match["team1_score"],
        "score2": match["team2_score"],
        "bo": _text(match["bo_format"] or "BO1"),
        "status": _text(_get(match, "effective_status", "")),
        "time": time_display_filter(match["match_time"]) if match["match_time"] else "TBD",
        "date": date_display_filter(match["match_time"]) if match["match_time"] else "",
        "match_time": _text(_get(match, "match_time", "")),
        "stage": _text(_get(match, "stage", "")),
        "maps": [
            {
                "slot": slot,
                "name": _text(_get(match, f"map{slot}", "")),
                "team1_score": _get(match, f"map{slot}_t1"),
                "team2_score": _get(match, f"map{slot}_t2"),
                "picked_by": _text(_get(match, f"map{slot}_picked_by", "")),
            }
            for slot in range(1, 6)
            if _get(match, f"map{slot}") or _get(match, f"map{slot}_t1") is not None
        ],
    }


def _home_match_payload(match):
    payload = _match_payload(match)
    payload["team1"] = _text(_get(match, "t1s") or payload["team1"])
    payload["team2"] = _text(_get(match, "t2s") or payload["team2"])
    return payload


def _news_payload(row):
    return {
        "id": row["id"],
        "url": news_path(row),
        "title": _text(row["title"]),
        "summary": _text(_get(row, "summary", "")),
        "time": datetime_display_filter(row["publish_time"]) if row["publish_time"] else "",
        "raw_time": _text(_get(row, "publish_time", "")),
        "comments": _get(row, "actual_comment_count", _get(row, "comment_count", 0)) or 0,
    }


def _event_payload(row):
    status = _get(row, "effective_event_status") or _get(row, "status", "")
    return {
        "id": row["id"],
        "url": event_path(row),
        "name": _text(row["name"]),
        "short_name": _text(_get(row, "short_name", "")),
        "abbr": event_abbr(row["name"], _get(row, "short_name", "")),
        "description": _text(_get(row, "description", "")),
        "format": _text(_get(row, "format", "")),
        "status": _text(status),
        "start_date": date_display_filter(_get(row, "start_date"))
        if _get(row, "start_date")
        else "",
        "end_date": date_display_filter(_get(row, "end_date")) if _get(row, "end_date") else "",
        "registration_open": bool(_get(row, "registration_open", 0)),
        "match_count": _get(row, "match_count", 0),
        "team_count": _get(row, "team_count", 0),
    }


def _player_payload(row):
    rating = _get(row, "rating", _get(row, "avg_rating", None))
    school_status = _get(
        row,
        "managed_is_bashizhong_student",
        _get(row, "is_bashizhong_student", None),
    )
    nickname, group_username = private_player_identity(
        row["id"], row["nickname"], _get(row, "group_username", "")
    )
    return {
        "id": row["id"],
        "url": url_for("player_detail", player_id=row["id"]),
        "nickname": _text(nickname),
        "group_username": (_text(group_username) if school_status != 0 else ""),
        "is_bashizhong_student": school_status,
        "origin_symbol": "🌐" if school_status == 0 else "",
        "team_id": _get(row, "team_id"),
        "team": _text(_get(row, "team", _get(row, "team_name", ""))),
        "avatar": _avatar_url(_get(row, "avatar", "")),
        "rating": _rounded(rating, 2),
        "maps": _get(row, "maps", _get(row, "match_count", 0)),
        "kills": _get(row, "kills"),
        "deaths": _get(row, "deaths"),
        "assists": _get(row, "assists"),
        "adr": _rounded(_get(row, "adr"), 1),
        "hs": _rounded(_get(row, "hs"), 1),
    }


def _team_payload(row):
    return {
        "id": row["id"],
        "url": url_for("team_detail", team_id=row["id"]),
        "name": _text(row["name"]),
        "short_name": _text(_get(row, "short_name", "")),
        "abbr": team_abbr(row["name"], _get(row, "short_name", "")),
        "description": _text(_get(row, "description", "")),
        "logo": _logo_url(_get(row, "logo", "")),
        "players": _get(row, "players", 0),
        "rating": _rounded(_get(row, "rating"), 2),
        "maps": _get(row, "maps", 0),
    }


def _comment_payload(row):
    username, group_username = private_user_identity(
        _get(row, "user_id"),
        _get(row, "username", ""),
        _get(row, "group_username", ""),
    )
    username = _text(username)
    group_username = _text(group_username)
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "username": username,
        "group_username": group_username,
        "display_name": _user_display_name(username, group_username),
        "avatar": _avatar_url(_get(row, "avatar", "")),
        "is_cheater": bool(_get(row, "is_cheater", 0)),
        "content": _text(row["content"]),
        "created_at": datetime_display_filter(row["created_at"]) if row["created_at"] else "",
        "parent_id": _get(row, "parent_id"),
        "like_count": _get(row, "like_count", 0),
    }


@app.route("/api/front/home")
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


@app.route("/api/front/matches")
def api_front_matches():
    """Match list data for frontend clients."""
    date_filter = request.args.get("date", "").strip()
    event_filter = request.args.get("event", "").strip()
    status = request.args.get("status", "active").strip()
    if status not in ("active", "completed"):
        status = "active"

    page, per_page, offset = _page_params(default=50)
    with closing(get_db()) as conn:
        rows, total = load_match_page(
            conn,
            status=status,
            event=event_filter,
            date=date_filter,
            month=request.args.get("month", "").strip(),
            limit=per_page,
            offset=offset,
        )
    return jsonify(
        {
            "ok": True,
            "page": page,
            "per_page": per_page,
            "total": total,
            "matches": [_match_payload(row) for row in rows],
        }
    )


@app.route("/api/front/features")
def api_front_features():
    """Current site feature manifest for frontend navigation and docs."""
    return jsonify({"ok": True, "groups": PUBLIC_FEATURES})


@app.route("/api/front/news")
def api_front_news():
    """News list data."""
    page, per_page, offset = _page_params(default=20, maximum=80)
    conn = get_db()
    rows = conn.execute(
        """SELECT n.*, (SELECT COUNT(*) FROM comments c
                           WHERE c.target_type='news' AND c.target_id=n.id) AS actual_comment_count
           FROM news n ORDER BY n.publish_time DESC, n.id DESC LIMIT ? OFFSET ?""",
        (per_page, offset),
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) AS cnt FROM news").fetchone()["cnt"]
    conn.close()
    return jsonify(
        {
            "ok": True,
            "page": page,
            "per_page": per_page,
            "total": total,
            "news": [_news_payload(row) for row in rows],
        }
    )


@app.route("/api/front/news/<int:news_id>")
def api_front_news_detail(news_id):
    """News detail with comments."""
    conn = get_db()
    news = conn.execute(
        """SELECT n.*, (SELECT COUNT(*) FROM comments c
                           WHERE c.target_type='news' AND c.target_id=n.id) AS actual_comment_count
           FROM news n WHERE n.id=?""",
        (news_id,),
    ).fetchone()
    if not news:
        conn.close()
        return jsonify({"ok": False, "error": "新闻不存在"}), 404
    related_match = None
    if news["related_match_id"]:
        related_match = conn.execute(
            f"""
            SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
                   t1.short_name AS t1s, t2.short_name AS t2s, e.name AS event_name,
                   {_SQL_EFFECTIVE_STATUS}
            FROM matches m
            LEFT JOIN teams t1 ON m.team1_id=t1.id
            LEFT JOIN teams t2 ON m.team2_id=t2.id
            LEFT JOIN events e ON m.event_id=e.id
            WHERE m.id=?
        """,
            (news["related_match_id"],),
        ).fetchone()
        if related_match:
            related_match = supplement_temp_teams(related_match, conn)
    comments = conn.execute(
        """
        SELECT c.*, u.username,
               CASE WHEN COALESCE(u.is_bashizhong_student, 1)<>0
                    THEN u.group_username END AS group_username,
               u.avatar, u.is_cheater,
               (SELECT COUNT(*) FROM comment_likes WHERE comment_id=c.id) AS like_count
        FROM comments c
        JOIN users u ON c.user_id=u.id
        WHERE c.target_type='news' AND c.target_id=?
        ORDER BY c.created_at ASC
    """,
        (news_id,),
    ).fetchall()
    conn.close()
    payload = _news_payload(news)
    payload["content"] = _text(news["content"])
    payload["related_match"] = _match_payload(related_match) if related_match else None
    payload["comments"] = [_comment_payload(row) for row in comments]
    return jsonify({"ok": True, "news": payload})


@app.route("/api/front/results")
def api_front_results():
    """Completed match results."""
    event_filter = request.args.get("event", "").strip()
    page, per_page, offset = _page_params(default=20, maximum=80)
    conn = get_db()
    query = f"""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s, e.name AS event_name,
               {_SQL_EFFECTIVE_STATUS}
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id
        WHERE {_SQL_MATCH_COMPLETED}
    """
    params = []
    if event_filter:
        query += " AND m.event_id=?"
        params.append(event_filter)
    count_query = "SELECT COUNT(*) AS cnt FROM matches m WHERE " + _SQL_MATCH_COMPLETED
    count_params = []
    if event_filter:
        count_query += " AND m.event_id=?"
        count_params.append(event_filter)
    query += " ORDER BY m.match_time DESC, m.id DESC LIMIT ? OFFSET ?"
    rows = [
        supplement_temp_teams(row, conn)
        for row in conn.execute(query, (*params, per_page, offset)).fetchall()
    ]
    total = conn.execute(count_query, tuple(count_params)).fetchone()["cnt"]
    conn.close()
    return jsonify(
        {
            "ok": True,
            "page": page,
            "per_page": per_page,
            "total": total,
            "results": [_match_payload(row) for row in rows],
        }
    )


@app.route("/api/front/matches/<int:match_id>")
def api_front_match_detail(match_id):
    """Single match detail."""
    conn = get_db()
    match = conn.execute(
        f"""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s, e.name AS event_name,
               {_SQL_EFFECTIVE_STATUS}
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id
        WHERE m.id=?
    """,
        (match_id,),
    ).fetchone()
    if not match:
        conn.close()
        return jsonify({"ok": False, "error": "比赛不存在"}), 404
    match = supplement_temp_teams(match, conn)
    stats_rows = conn.execute(
        """
        SELECT ms.*, p.nickname, p.avatar, t.short_name AS team_short, t.name AS team_name
        FROM match_stats ms
        JOIN players p ON ms.player_id=p.id
        LEFT JOIN teams t ON ms.team_id=t.id
        WHERE ms.match_id=?
          AND COALESCE(ms.data_status, 'final') <> 'superseded'
        ORDER BY ms.team_id, ms.rating DESC
    """,
        (match_id,),
    ).fetchall()
    comments = conn.execute(
        """
        SELECT c.*, u.username,
               CASE WHEN COALESCE(u.is_bashizhong_student, 1)<>0
                    THEN u.group_username END AS group_username,
               u.avatar, u.is_cheater,
               (SELECT COUNT(*) FROM comment_likes WHERE comment_id=c.id) AS like_count
        FROM comments c
        JOIN users u ON c.user_id=u.id
        WHERE c.target_type='match' AND c.target_id=?
        ORDER BY c.created_at ASC
    """,
        (match_id,),
    ).fetchall()
    conn.close()
    return jsonify(
        {
            "ok": True,
            "match": _match_payload(match),
            "stats": [
                {
                    "player_id": row["player_id"],
                    "nickname": _player_display_name(row["player_id"], row["nickname"]),
                    "avatar": _avatar_url(_get(row, "avatar", "")),
                    "team_id": row["team_id"],
                    "team": _text(_get(row, "team_short", _get(row, "team_name", ""))),
                    "map": _text(row["map_name"]),
                    "kills": row["kills"],
                    "deaths": row["deaths"],
                    "assists": row["assists"],
                    "adr": row["adr"],
                    "rating": row["rating"],
                    "hs": row["headshot_percentage"],
                }
                for row in stats_rows
            ],
            "comments": [_comment_payload(row) for row in comments],
        }
    )


@app.route("/api/front/events")
def api_front_events():
    """Event list data."""
    status_filter = request.args.get("status", "").strip()
    conn = get_db()
    rows = conn.execute("""
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
        GROUP BY e.id
        ORDER BY e.start_date DESC
    """).fetchall()
    conn.close()
    events = [add_effective_event_status(row) for row in rows]
    if status_filter in ("ongoing", "completed", "upcoming"):
        events = [event for event in events if event.get("effective_event_status") == status_filter]
    return jsonify({"ok": True, "events": [_event_payload(row) for row in events]})


@app.route("/api/front/events/<int:event_id>")
def api_front_event_detail(event_id):
    """Event detail data with teams, matches and awards."""
    conn = get_db()
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not event:
        conn.close()
        return jsonify({"ok": False, "error": "赛事不存在"}), 404
    event = add_effective_event_status(event)
    matches = conn.execute(
        f"""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s, e.name AS event_name,
               {_SQL_EFFECTIVE_STATUS}
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id
        WHERE m.event_id=?
        ORDER BY m.match_time
    """,
        (event_id,),
    ).fetchall()
    matches = [supplement_temp_teams(row, conn) for row in matches]
    teams = conn.execute(
        """
        SELECT DISTINCT t.*, COUNT(p.id) AS players
        FROM teams t
        LEFT JOIN players p ON p.team_id=t.id
        WHERE t.id IN (
            SELECT team1_id FROM matches WHERE event_id=? AND team1_id>0
            UNION
            SELECT team2_id FROM matches WHERE event_id=? AND team2_id>0
        )
        GROUP BY t.id
        ORDER BY t.name
    """,
        (event_id, event_id),
    ).fetchall()
    awards = conn.execute(
        """
        SELECT pm.*, p.nickname, p.avatar, e.name AS event_name
        FROM player_medals pm
        JOIN players p ON pm.player_id=p.id
        LEFT JOIN events e ON pm.event_id=e.id
        WHERE pm.event_id=?
        ORDER BY CASE pm.type WHEN 'MVP' THEN 0 ELSE 1 END, pm.evp_rank, p.nickname
    """,
        (event_id,),
    ).fetchall()
    champions = conn.execute(
        """
        SELECT t.id, t.name, t.short_name, t.logo, t.description, ec.created_at
        FROM event_champions ec
        JOIN teams t ON ec.team_id=t.id
        WHERE ec.event_id=?
    """,
        (event_id,),
    ).fetchall()
    conn.close()
    return jsonify(
        {
            "ok": True,
            "event": _event_payload(event),
            "matches": [_match_payload(row) for row in matches],
            "teams": [_team_payload(row) for row in teams],
            "awards": [
                {
                    "type": row["type"],
                    "player_id": row["player_id"],
                    "nickname": _player_display_name(row["player_id"], row["nickname"]),
                    "avatar": _avatar_url(_get(row, "avatar", "")),
                    "rank": _get(row, "evp_rank"),
                    "reason": _text(_get(row, "reason", "")),
                }
                for row in awards
            ],
            "champions": [_team_payload(row) for row in champions],
        }
    )


@app.route("/api/front/players")
def api_front_players():
    """Player list and top player data."""
    page, per_page, offset = _page_params(default=50, maximum=120)
    filter_key = request.args.get("filter", "").strip().lower()
    team_filter = request.args.get("team", "").strip()
    if filter_key == "top20":
        filter_key = "top10"
    initial = request.args.get("initial", "all").strip().lower()
    if filter_key == "top10":
        per_page = min(10, per_page)
        offset = (page - 1) * per_page
    with closing(get_db()) as conn:
        rows, total = load_player_page(
            conn,
            team=team_filter,
            filter_key=filter_key,
            initial=initial,
            limit=per_page,
            offset=offset,
        )
    return jsonify(
        {
            "ok": True,
            "page": page,
            "per_page": per_page,
            "total": total,
            "players": [_player_payload(row) for row in rows],
        }
    )


@app.route("/api/front/players/<int:player_id>")
def api_front_player_detail(player_id):
    """Player profile and statistics data."""
    conn = get_db()
    player = conn.execute(
        """
        SELECT p.*, t.name AS team_name, t.short_name AS team,
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
               ), p.is_bashizhong_student) AS managed_is_bashizhong_student
        FROM players p
        LEFT JOIN teams t ON p.team_id=t.id
        WHERE p.id=?
    """,
        (player_id,),
    ).fetchone()
    if not player:
        conn.close()
        return jsonify({"ok": False, "error": "选手不存在"}), 404
    summary = load_player_summary(conn, player_id)
    recent = conn.execute(
        f"""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s, e.name AS event_name,
               {_SQL_EFFECTIVE_STATUS}
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id
        WHERE EXISTS (
            SELECT 1 FROM match_stats ms WHERE ms.match_id=m.id AND ms.player_id=?
              AND COALESCE(ms.data_status, 'final') <> 'superseded'
        )
        ORDER BY m.match_time DESC, m.id DESC
        LIMIT 10
    """,
        (player_id,),
    ).fetchall()
    recent = [supplement_temp_teams(row, conn) for row in recent]
    medals = conn.execute(
        """
        SELECT pm.*, e.name AS event_name
        FROM player_medals pm
        LEFT JOIN events e ON pm.event_id=e.id
        WHERE pm.player_id=?
        ORDER BY pm.created_at DESC
    """,
        (player_id,),
    ).fetchall()
    conn.close()
    return jsonify(
        {
            "ok": True,
            "player": _player_payload(player),
            "summary": {
                "maps": summary["maps"] or 0,
                "rounds": summary["rounds"] or 0,
                "kills": summary["kills"],
                "deaths": summary["deaths"],
                "assists": summary["assists"],
                "rating": _rounded(summary["rating"], 2),
                "adr": _rounded(summary["adr"], 1),
                "kast": _rounded(summary["kast"], 1),
                "hs": _rounded(summary["hs"], 1),
                "kpr": _rounded(summary["kpr"], 2),
                "dpr": _rounded(summary["dpr"], 2),
                "impact": _rounded(summary["impact"], 2),
            },
            "recent_matches": [_match_payload(row) for row in recent],
            "awards": [
                {
                    "type": row["type"],
                    "event_id": row["event_id"],
                    "event": _text(_get(row, "event_name", "")),
                    "rank": _get(row, "evp_rank"),
                    "reason": _text(_get(row, "reason", "")),
                }
                for row in medals
            ],
        }
    )


@app.route("/api/front/teams")
def api_front_teams():
    """Team list data."""
    conn = get_db()
    rows = load_team_statistics(conn)
    conn.close()
    return jsonify({"ok": True, "teams": [_team_payload(row) for row in rows]})


@app.route("/api/front/stats/overview")
def api_front_stats_overview():
    """Stats overview data for frontend pages."""
    conn = get_db()
    top_players = conn.execute(f"""
        SELECT p.id, p.nickname, p.avatar, t.short_name AS team,
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
               s.maps, {summary_metric_sql("avg_rating", "rating")} AS rating,
               {summary_metric_sql("total_kills", "kills")} AS kills,
               {summary_metric_sql("total_deaths", "deaths")} AS deaths,
               {summary_metric_sql("total_assists", "assists")} AS assists,
               {summary_metric_sql("avg_adr", "adr")} AS adr,
               {summary_metric_sql("avg_hs", "headshot_percentage")} AS hs
        FROM player_performance_summary s
        JOIN players p ON s.player_id=p.id
        LEFT JOIN teams t ON p.team_id=t.id
        WHERE s.maps > 0
        ORDER BY rating DESC, s.maps DESC, p.id
        LIMIT 10
    """).fetchall()
    top_teams = load_team_statistics(conn, ranked=True)
    top_maps = load_map_statistics(conn)
    overview = load_statistics_totals(conn)
    conn.close()
    return jsonify(
        {
            "ok": True,
            "summary": {
                "matches": overview["matches"] or 0,
                "players": overview["players"] or 0,
                "player_maps": overview["player_maps"] or 0,
                "avg_rating": _rounded(overview["rating"], 2),
                "kills": overview["kills"] if overview["player_maps"] else 0,
            },
            "top_players": [_player_payload(row) for row in top_players],
            "top_teams": [_team_payload(row) for row in top_teams],
            "top_maps": [
                {
                    "map": _text(row["map_name"]),
                    "maps": row["maps"],
                    "rating": _rounded(row["rating"], 2),
                    "adr": _rounded(row["adr"], 1),
                    "hs": _rounded(row["hs"], 1),
                }
                for row in top_maps
            ],
        }
    )


@app.route("/api/front/dashboard")
def api_front_dashboard():
    """首页数据合并端点 —— 一次请求获取 news、matches、events、top_players、MVP/EVP 等首页全部数据。"""
    conn = get_db()
    feed = load_home_feed(conn)
    news_rows = feed["news"]
    match_rows = feed["matches"]
    recent_rows = feed["recent"]
    top_players = feed["top_players"]

    # —— 赛事列表（含比赛/队伍数统计）——
    event_rows = conn.execute("""
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
    event_matches = conn.execute("""
        SELECT e.id, e.name, COUNT(m.id) AS matches
        FROM events e
        LEFT JOIN matches m ON e.id=m.event_id
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


@app.route("/api/front/predictions")
def api_front_predictions():
    """Prediction leaderboard and voted upcoming matches."""
    conn = get_db()
    leaderboard = get_prediction_leaderboard(conn)
    upcoming = get_prediction_upcoming_matches(conn)
    conn.close()
    return jsonify(
        {
            "ok": True,
            "leaderboard": [
                {
                    "user_id": row["user_id"],
                    "username": _user_display_name(row["username"], "", row["user_id"]),
                    "avatar": _avatar_url(_get(row, "avatar", "")),
                    "is_cheater": bool(_get(row, "is_cheater", 0)),
                    "votes": row["total_votes"],
                    "correct": row["correct_votes"] or 0,
                    "points": row["total_points"] or 0,
                }
                for row in leaderboard
            ],
            "upcoming_matches": [
                {
                    "id": row["id"],
                    "url": _match_url(row),
                    "time": datetime_display_filter(row["match_time"]) if row["match_time"] else "",
                    "bo": _text(row["bo_format"]),
                    "team1": _text(row["team1_name"]),
                    "team2": _text(row["team2_name"]),
                    "event": _text(row["event_name"]),
                    "votes": row["vote_count"],
                    "team1_votes": row["t1_votes"] or 0,
                    "team2_votes": row["t2_votes"] or 0,
                }
                for row in upcoming
            ],
        }
    )


@app.route("/api/front/forum")
def api_front_forum():
    """Forum thread list."""
    page, per_page, offset = _page_params(default=25, maximum=80)
    search_query = request.args.get("q", "").strip()
    category_slug = request.args.get("category", "").strip()
    sort_by = request.args.get("sort", "latest").strip()
    order_sql = {
        "latest": "t.is_pinned DESC, COALESCE(t.last_reply_at, t.created_at) DESC, t.id DESC",
        "newest": "t.is_pinned DESC, t.created_at DESC, t.id DESC",
        "popular": "t.is_pinned DESC, (t.reply_count * 8 + t.view_count) DESC, COALESCE(t.last_reply_at, t.created_at) DESC",
    }.get(sort_by, "t.is_pinned DESC, COALESCE(t.last_reply_at, t.created_at) DESC, t.id DESC")
    clauses = []
    params = []
    if search_query:
        clauses.append("(t.title LIKE ? OR t.content LIKE ?)")
        params.extend([f"%{search_query}%", f"%{search_query}%"])
    if category_slug:
        clauses.append("c.slug=?")
        params.append(category_slug)
    where_sql = " AND ".join(clauses) if clauses else "1=1"
    conn = get_db()
    categories = conn.execute(
        """SELECT c.name, c.slug, COUNT(t.id) AS thread_count
           FROM forum_categories c
           LEFT JOIN forum_threads t ON t.category_id=c.id
           GROUP BY c.id ORDER BY c.sort_order, c.id"""
    ).fetchall()
    rows = conn.execute(
        f"""
        SELECT t.*, c.name AS category_name, c.slug AS category_slug,
               u.username,
               CASE WHEN COALESCE(u.is_bashizhong_student, 1)<>0
                    THEN u.group_username END AS group_username,
               u.avatar, u.is_cheater,
               lr.username AS last_reply_username,
               CASE WHEN COALESCE(lr.is_bashizhong_student, 1)<>0
                    THEN lr.group_username END
                   AS last_reply_group_username,
               lr.is_cheater AS last_reply_is_cheater
        FROM forum_threads t
        JOIN forum_categories c ON t.category_id=c.id
        JOIN users u ON t.user_id=u.id
        LEFT JOIN users lr ON lr.id=t.last_reply_user_id
        WHERE {where_sql}
        ORDER BY {order_sql}
        LIMIT ? OFFSET ?
    """,
        (*params, per_page, offset),
    ).fetchall()
    total = conn.execute(
        f"""SELECT COUNT(*) AS cnt FROM forum_threads t
            JOIN forum_categories c ON t.category_id=c.id
            WHERE {where_sql}""",
        tuple(params),
    ).fetchone()["cnt"]
    conn.close()
    return jsonify(
        {
            "ok": True,
            "page": page,
            "per_page": per_page,
            "total": total,
            "categories": [
                {
                    "name": _text(row["name"]),
                    "slug": _text(row["slug"]),
                    "thread_count": row["thread_count"],
                }
                for row in categories
            ],
            "threads": [
                {
                    "id": row["id"],
                    "url": url_for("forum_thread", thread_id=row["id"]),
                    "title": _text(row["title"]),
                    "author": _user_display_name(
                        row["username"], _get(row, "group_username"), row["user_id"]
                    ),
                    "author_username": _text(row["username"]),
                    "author_is_cheater": bool(_get(row, "is_cheater", 0)),
                    "avatar": _avatar_url(_get(row, "avatar", "")),
                    "category": _text(row["category_name"]),
                    "category_slug": _text(row["category_slug"]),
                    "pinned": bool(row["is_pinned"]),
                    "locked": bool(row["is_locked"]),
                    "views": row["view_count"],
                    "replies": row["reply_count"],
                    "created_at": datetime_display_filter(row["created_at"])
                    if row["created_at"]
                    else "",
                    "last_reply_at": datetime_display_filter(row["last_reply_at"])
                    if row["last_reply_at"]
                    else "",
                    "last_reply_user": _user_display_name(
                        _get(row, "last_reply_username", ""),
                        _get(row, "last_reply_group_username"),
                        _get(row, "last_reply_user_id"),
                    ),
                    "last_reply_is_cheater": bool(_get(row, "last_reply_is_cheater", 0)),
                }
                for row in rows
            ],
        }
    )


@app.route("/api/front/notifications")
def api_front_notifications():
    """Current user's notification summary."""
    if "user_id" not in session:
        return jsonify({"ok": True, "authenticated": False, "unread": 0, "notifications": []})
    conn = get_db()
    rows = conn.execute(
        """
        SELECT * FROM notifications
        WHERE user_id=?
        ORDER BY created_at DESC
        LIMIT 20
    """,
        (session["user_id"],),
    ).fetchall()
    unread = conn.execute(
        "SELECT COUNT(*) AS cnt FROM notifications WHERE user_id=? AND is_read=0",
        (session["user_id"],),
    ).fetchone()["cnt"]
    conn.close()
    return jsonify(
        {
            "ok": True,
            "authenticated": True,
            "unread": unread,
            "notifications": [
                {
                    "id": row["id"],
                    "type": _text(_get(row, "type", "")),
                    "message": _text(_get(row, "message", "")),
                    "url": _text(_get(row, "link", "")),
                    "read": bool(_get(row, "is_read", 0)),
                    "created_at": datetime_display_filter(row["created_at"])
                    if row["created_at"]
                    else "",
                }
                for row in rows
            ],
        }
    )
