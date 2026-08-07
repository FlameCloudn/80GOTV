"""Match list, detail, live redirect and vote pages."""

import calendar
import json
from collections import defaultdict
from datetime import datetime, timedelta

from flask import jsonify, redirect, render_template, request, session, url_for

from models import get_db
from services.match_service import add_effective_event_status, supplement_temp_teams
from utils.helpers import (
    build_comment_tree,
    normalize_http_url,
    normalize_map_key,
    resolve_match_slug,
    row_get,
)
from utils.match_utils import (
    get_map_half_scores,
    get_sql_effective_status,
    get_sql_match_completed,
    get_sql_match_live,
    get_sql_match_upcoming,
    parse_map_halves,
)
from utils.rate_limiter import rate_limit
from utils.web_helpers import csrf_required
from web_app import app

_SQL_MATCH_COMPLETED = get_sql_match_completed()
_SQL_MATCH_UPCOMING = get_sql_match_upcoming()
_SQL_MATCH_LIVE = get_sql_match_live()
_SQL_EFFECTIVE_STATUS = get_sql_effective_status()


def _stat_belongs_to_match_side(row, expected_side, expected_team_id):
    """Prefer the explicit match side; keep old real-team rows compatible."""
    stored_side = str(row_get(row, "match_team_side", "") or "").strip().lower()
    if stored_side in {"t1", "t2"}:
        return stored_side == expected_side
    return row_get(row, "team_id") == expected_team_id


@app.route("/matches")
def matches_list():
    """比赛列表（未开始+进行中）"""
    event_filter = request.args.get("event", "")
    status_filter = request.args.get("status", "")
    date_filter = request.args.get("date", "").strip()
    month_filter = request.args.get("month", "").strip()
    if status_filter == "completed":
        target = url_for("results_list")
        if event_filter:
            target += f"?event={event_filter}"
        return redirect(target)

    try:
        selected_date = datetime.strptime(date_filter, "%Y-%m-%d").date()
    except ValueError:
        selected_date = None
        date_filter = ""
    try:
        calendar_month = datetime.strptime(month_filter, "%Y-%m").date().replace(day=1)
    except ValueError:
        calendar_month = (selected_date or datetime.now().date()).replace(day=1)

    conn = get_db()
    status_sql = f"({_SQL_MATCH_LIVE} OR {_SQL_MATCH_UPCOMING})"

    query = f"""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s,
               t1.logo AS team1_logo, t2.logo AS team2_logo,
               e.name AS event_name,
               {_SQL_EFFECTIVE_STATUS}
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id
        WHERE {status_sql}
    """
    params = []

    if event_filter:
        query += " AND m.event_id=?"
        params.append(event_filter)

    if date_filter:
        query += " AND substr(COALESCE(m.match_time, ''), 1, 10)=?"
        params.append(date_filter)

    query += """
        ORDER BY CASE WHEN effective_status='live' THEN 0 ELSE 1 END,
                 CASE WHEN m.match_time IS NULL OR m.match_time='' THEN 1 ELSE 0 END,
                 m.match_time
    """
    matches = conn.execute(query, params).fetchall()
    matches = [supplement_temp_teams(m, conn) for m in matches]

    events = conn.execute("SELECT * FROM events ORDER BY start_date DESC").fetchall()
    completed_on_selected_date = 0
    if date_filter:
        completed_on_selected_date = conn.execute(
            f"""
            SELECT COUNT(*)
            FROM matches m
            WHERE {_SQL_MATCH_COMPLETED}
              AND substr(COALESCE(m.match_time, ''), 1, 10)=?
            """,
            (date_filter,),
        ).fetchone()[0]
    conn.close()

    today = datetime.now().date()
    prev_month = (calendar_month.replace(day=1) - timedelta(days=1)).replace(day=1)
    next_month = (
        calendar_month.replace(
            day=calendar.monthrange(calendar_month.year, calendar_month.month)[1]
        )
        + timedelta(days=1)
    ).replace(day=1)
    calendar_weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(
        calendar_month.year,
        calendar_month.month,
    )

    return render_template(
        "matches.html",
        matches=matches,
        events=events,
        event_filter=event_filter,
        status_filter=status_filter,
        date_filter=date_filter,
        selected_date=selected_date,
        today=today,
        calendar_month=calendar_month,
        prev_month=prev_month,
        next_month=next_month,
        calendar_weeks=calendar_weeks,
        completed_on_selected_date=completed_on_selected_date,
    )


@app.route("/results")
def results_list():
    """赛果列表（已结束）"""
    event_filter = request.args.get("event", "")
    page = request.args.get("page", 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page

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

    query += " ORDER BY m.match_time DESC LIMIT ? OFFSET ?"
    params.extend([per_page, offset])

    matches = conn.execute(query, params).fetchall()
    matches = [supplement_temp_teams(m, conn) for m in matches]
    events = conn.execute("SELECT * FROM events ORDER BY start_date DESC").fetchall()

    total_query = f"SELECT COUNT(*) as cnt FROM matches m WHERE {_SQL_MATCH_COMPLETED}"
    if event_filter:
        total_query += " AND m.event_id=?"
        total = conn.execute(total_query, (event_filter,)).fetchone()["cnt"]
    else:
        total = conn.execute(total_query).fetchone()["cnt"]

    conn.close()

    total_pages = (total + per_page - 1) // per_page
    return render_template(
        "results.html",
        matches=matches,
        events=events,
        event_filter=event_filter,
        page=page,
        total_pages=total_pages,
    )


@app.route("/matches/<slug>/vote", methods=["POST"])
@csrf_required
def match_vote(slug):
    """赛前投票"""
    match_id = resolve_match_slug(slug)
    if not match_id:
        return jsonify({"ok": False, "msg": "比赛不存在"})
    if "user_id" not in session:
        return jsonify({"ok": False, "msg": "请先登录"})
    if not rate_limit("vote", 20, 60):
        return jsonify({"ok": False, "msg": "操作过于频繁，请稍后再试"})
    user_id = session["user_id"]
    voted_for = request.form.get("voted_for", "").strip()
    if voted_for not in ("t1", "t2"):
        return jsonify({"ok": False, "msg": "无效的投票选项"})

    score1 = request.form.get("score1", "").strip()
    score2 = request.form.get("score2", "").strip()
    try:
        score1_guess = int(score1) if score1 else None
        score2_guess = int(score2) if score2 else None
    except ValueError:
        return jsonify({"ok": False, "msg": "比分格式错误"})
    if any(score is not None and not 0 <= score <= 99 for score in (score1_guess, score2_guess)):
        return jsonify({"ok": False, "msg": "比分范围应为 0-99"})

    conn = get_db()
    match = conn.execute(
        f"SELECT id FROM matches m WHERE m.id=? AND ({_SQL_MATCH_UPCOMING})", (match_id,)
    ).fetchone()
    if not match:
        conn.close()
        return jsonify({"ok": False, "msg": "比赛已经开始或不存在，无法继续投票"})
    existing = conn.execute(
        "SELECT id FROM match_votes WHERE match_id=? AND user_id=?", (match_id, user_id)
    ).fetchone()
    if existing:
        conn.close()
        return jsonify({"ok": False, "msg": "您已投过票"})

    conn.execute(
        "INSERT INTO match_votes (match_id, user_id, voted_for, score1_guess, score2_guess) VALUES (?,?,?,?,?)",
        (match_id, user_id, voted_for, score1_guess, score2_guess),
    )
    conn.commit()

    vc = conn.execute(
        "SELECT voted_for, COUNT(*) as cnt FROM match_votes WHERE match_id=? GROUP BY voted_for",
        (match_id,),
    ).fetchall()
    conn.close()

    t1_count = 0
    t2_count = 0
    for r in vc:
        if r["voted_for"] == "t1":
            t1_count = r["cnt"]
        elif r["voted_for"] == "t2":
            t2_count = r["cnt"]

    return jsonify(
        {
            "ok": True,
            "t1_count": t1_count,
            "t2_count": t2_count,
            "total": t1_count + t2_count,
            "user_voted": voted_for,
        }
    )


@app.route("/matches/<slug>/stats")
@app.route("/matches/<slug>")
def match_detail(slug):
    """比赛详情（支持 slug 或数字 ID；ID 访问时 301 跳转到 slug 版）"""
    match_id = resolve_match_slug(slug)
    if not match_id:
        return "比赛不存在", 404
    conn = get_db()
    match = conn.execute(
        "SELECT id, slug FROM matches WHERE id=?",
        (match_id,),
    ).fetchone()
    conn.close()
    # 数字 ID 或旧网址名称都会跳到当前规范地址。
    if match["slug"] and slug != match["slug"]:
        return redirect(url_for("match_detail", slug=match["slug"]), code=301)
    return _render_match_detail(match_id)


def _render_match_detail(match_id):
    """比赛详情页渲染"""
    conn = get_db()
    match = conn.execute(
        f"""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s,
               t1.logo AS t1_logo, t2.logo AS t2_logo,
               e.name AS event_name, e.id AS event_id, e.slug AS event_slug,
               e.stream_url AS event_stream_url,
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
        return "比赛不存在", 404

    # 补充临时队伍名称
    match = supplement_temp_teams(match, conn)

    # 获取比赛数据
    stats = conn.execute(
        """
        SELECT ms.*, p.nickname, p.id AS player_id, t.short_name AS team_short
        FROM match_stats ms
        JOIN players p ON ms.player_id=p.id
        LEFT JOIN teams t ON ms.team_id=t.id
        WHERE ms.match_id=?
          AND COALESCE(ms.data_status, 'final') <> 'superseded'
        ORDER BY ms.map_name, ms.team_id DESC, ms.rating DESC
    """,
        (match_id,),
    ).fetchall()

    # 双方历史交锋记录
    h2h_matches = []
    t1_id = match["team1_id"]
    t2_id = match["team2_id"]
    if t1_id and t2_id:
        h2h_matches = conn.execute(
            """
            SELECT m.id, m.slug, m.match_time, m.team1_score, m.team2_score,
                   m.bo_format, e.name AS event_name,
                   t1.short_name AS t1s, t2.short_name AS t2s
            FROM matches m
            LEFT JOIN events e ON m.event_id = e.id
            LEFT JOIN teams t1 ON m.team1_id = t1.id
            LEFT JOIN teams t2 ON m.team2_id = t2.id
            WHERE m.id != ?
              AND COALESCE(m.status, '') = 'completed'
              AND m.team1_score IS NOT NULL
              AND m.team2_score IS NOT NULL
              AND (COALESCE(m.team1_score, 0) > 0 OR COALESCE(m.team2_score, 0) > 0)
              AND ((m.team1_id = ? AND m.team2_id = ?)
                OR (m.team1_id = ? AND m.team2_id = ?))
            ORDER BY m.match_time DESC LIMIT 10
        """,
            (match_id, t1_id, t2_id, t2_id, t1_id),
        ).fetchall()

    # 队伍名单 + 替补（队标悬停浮窗用）
    from routes.broadcast import _event_substitutes, _team_players

    roster_subs = []
    if match.get("event_id"):
        roster_subs = _event_substitutes(conn, match["event_id"])

    def _roster_with_subs(side):
        if not (match.get(f"team{side}_id") or match.get(f"team{side}_players")):
            return [], []
        roster = _team_players(conn, match, side)
        roster_ids = set()
        for p in roster:
            try:
                pid = int(p.get("id") or 0)
            except (TypeError, ValueError):
                pid = 0
            if pid > 0:
                roster_ids.add(pid)
        extras = []
        for p in roster_subs:
            try:
                pid = int(p.get("id") or 0)
            except (TypeError, ValueError):
                pid = 0
            if pid <= 0 or pid not in roster_ids:
                extras.append(p)
        return roster, extras

    team1_roster, team1_extra_subs = _roster_with_subs(1)
    team2_roster, team2_extra_subs = _roster_with_subs(2)

    conn.close()

    # 每图比分 + 分图 stats（按队伍分好）
    t1_key = match["team1_id"] if match["team1_id"] else -1
    t2_key = match["team2_id"] if match["team2_id"] else -2

    raw_maps = [
        (
            match["map1"],
            match["map1_t1"],
            match["map1_t2"],
            True,
            row_get(match, "map1_picked_by", ""),
        ),
        (
            match["map2"],
            match["map2_t1"],
            match["map2_t2"],
            True,
            row_get(match, "map2_picked_by", ""),
        ),
        (
            match["map3"],
            match["map3_t1"],
            match["map3_t2"],
            bool(match["has_map3"]),
            row_get(match, "map3_picked_by", ""),
        ),
        (
            match["map4"],
            match["map4_t1"],
            match["map4_t2"],
            bool(row_get(match, "has_map4", 1)),
            row_get(match, "map4_picked_by", ""),
        ),
        (
            match["map5"],
            match["map5_t1"],
            match["map5_t2"],
            bool(row_get(match, "has_map5", 1)),
            row_get(match, "map5_picked_by", ""),
        ),
    ]
    # 解析半场比分
    map_halves = parse_map_halves(match)

    bo = (match["bo_format"] or "BO3").upper()
    if bo == "BO5":
        max_maps = 5
    elif bo == "BO3":
        max_maps = 3
    else:
        max_maps = 1

    map_scores = []
    for idx, (mn, t1, t2, active, picked_by) in enumerate(raw_maps):
        if idx >= max_maps:
            break
        # 未开始的系列赛也要按 BO 数量完整显示地图槽位。
        all_for_map = [s for s in stats if s["map_name"] == mn] if mn else []
        t1s = [s for s in all_for_map if _stat_belongs_to_match_side(s, "t1", t1_key)]
        t2s = [s for s in all_for_map if _stat_belongs_to_match_side(s, "t2", t2_key)]
        halves = get_map_half_scores(match, idx, map_halves) if mn else None
        played = bool(mn and (t1 or t2))
        has_stats = bool(all_for_map)
        map_scores.append(
            {
                "name": mn or "TBA",
                "index": idx + 1,
                "t1": t1 or 0,
                "t2": t2 or 0,
                "picked_by": picked_by or "",
                "team1_stats": t1s,
                "team2_stats": t2s,
                "halves": halves,
                "played": played,
                "has_stats": has_stats,
                "display": bool(mn and (played or has_stats)),
            }
        )

    # 总览：按选手聚合（只统计归属明确的记录，防止串队）
    from collections import defaultdict

    team1_agg = defaultdict(
        lambda: {
            "kills": 0,
            "deaths": 0,
            "assists": 0,
            "adr": 0,
            "rating": 0,
            "kast": 0,
            "hs": 0,
            "impact": 0,
            "kpr": 0,
            "dpr": 0,
            "rounds_played": 0,
            "first_kills": 0,
            "first_deaths": 0,
            "clutches_won": 0,
            "multi2k": 0,
            "multi3k": 0,
            "multi4k": 0,
            "multi5k": 0,
            "trade_kills": 0,
            "trade_deaths": 0,
            "utility_damage": 0,
            "enemies_flashed": 0,
            "mvp_count": 0,
            "t_rating": 0,
            "ct_rating": 0,
            "t_kills": 0,
            "ct_kills": 0,
            "t_deaths": 0,
            "ct_deaths": 0,
            "t_adr": 0,
            "ct_adr": 0,
            "maps": 0,
            "t_maps": 0,
            "ct_maps": 0,
        }
    )
    team2_agg = defaultdict(
        lambda: {
            "kills": 0,
            "deaths": 0,
            "assists": 0,
            "adr": 0,
            "rating": 0,
            "kast": 0,
            "hs": 0,
            "impact": 0,
            "kpr": 0,
            "dpr": 0,
            "rounds_played": 0,
            "first_kills": 0,
            "first_deaths": 0,
            "clutches_won": 0,
            "multi2k": 0,
            "multi3k": 0,
            "multi4k": 0,
            "multi5k": 0,
            "trade_kills": 0,
            "trade_deaths": 0,
            "utility_damage": 0,
            "enemies_flashed": 0,
            "mvp_count": 0,
            "t_rating": 0,
            "ct_rating": 0,
            "t_kills": 0,
            "ct_kills": 0,
            "t_deaths": 0,
            "ct_deaths": 0,
            "t_adr": 0,
            "ct_adr": 0,
            "maps": 0,
            "t_maps": 0,
            "ct_maps": 0,
        }
    )

    for s in stats:
        if _stat_belongs_to_match_side(s, "t1", t1_key):
            agg = team1_agg
        elif _stat_belongs_to_match_side(s, "t2", t2_key):
            agg = team2_agg
        else:
            continue
        pid = s["player_id"]
        agg[pid]["kills"] += s["kills"]
        agg[pid]["deaths"] += s["deaths"]
        agg[pid]["assists"] += s["assists"]
        map_rounds = max(1, int(row_get(s, "rounds_played", 0) or 0))
        agg[pid]["adr"] += (s["adr"] or 0) * map_rounds
        agg[pid]["rating"] += (s["rating"] or 0) * map_rounds
        agg[pid]["kast"] += (s["kast"] or 0) * map_rounds
        agg[pid]["hs"] += (s["headshot_percentage"] or 0) * max(1, int(s["kills"] or 0))
        agg[pid]["impact"] += (s["impact"] or 0) * map_rounds
        agg[pid]["kpr"] += (row_get(s, "kpr", 0) or 0) * map_rounds
        agg[pid]["dpr"] += (row_get(s, "dpr", 0) or 0) * map_rounds
        agg[pid]["rounds_played"] += row_get(s, "rounds_played", 0) or 0
        agg[pid]["first_kills"] += row_get(s, "first_kills", 0) or 0
        agg[pid]["first_deaths"] += row_get(s, "first_deaths", 0) or 0
        agg[pid]["clutches_won"] += row_get(s, "clutches_won", 0) or 0
        agg[pid]["multi2k"] += row_get(s, "multi2k", 0) or 0
        agg[pid]["multi3k"] += row_get(s, "multi3k", 0) or 0
        agg[pid]["multi4k"] += row_get(s, "multi4k", 0) or 0
        agg[pid]["multi5k"] += row_get(s, "multi5k", 0) or 0
        agg[pid]["trade_kills"] += row_get(s, "trade_kills", 0) or 0
        agg[pid]["trade_deaths"] += row_get(s, "trade_deaths", 0) or 0
        agg[pid]["utility_damage"] += row_get(s, "utility_damage", 0) or 0
        agg[pid]["enemies_flashed"] += row_get(s, "enemies_flashed", 0) or 0
        agg[pid]["mvp_count"] += row_get(s, "mvp_count", 0) or 0
        has_t_data = (s["t_kills"] or 0) > 0 or (s["t_rating"] or 0) > 0
        has_ct_data = (s["ct_kills"] or 0) > 0 or (s["ct_rating"] or 0) > 0
        agg[pid]["t_rating"] += s["t_rating"] or 0
        agg[pid]["ct_rating"] += s["ct_rating"] or 0
        agg[pid]["t_kills"] += s["t_kills"] or 0
        agg[pid]["ct_kills"] += s["ct_kills"] or 0
        agg[pid]["t_deaths"] += s["t_deaths"] or 0
        agg[pid]["ct_deaths"] += s["ct_deaths"] or 0
        agg[pid]["t_adr"] += s["t_adr"] or 0
        agg[pid]["ct_adr"] += s["ct_adr"] or 0
        agg[pid]["maps"] += 1
        if has_t_data:
            agg[pid]["t_maps"] += 1
        if has_ct_data:
            agg[pid]["ct_maps"] += 1
        agg[pid]["nickname"] = s["nickname"]
        agg[pid]["player_id"] = pid

    def build_overall(agg_dict):
        result = []
        for pid, d in agg_dict.items():
            m = d["maps"]
            tm = max(d["t_maps"], 1)
            cm = max(d["ct_maps"], 1)
            result.append(
                {
                    "player_id": pid,
                    "nickname": d["nickname"],
                    "kills": d["kills"],
                    "deaths": d["deaths"],
                    "assists": d["assists"],
                    "adr": round(d["adr"] / max(d["rounds_played"], 1), 1)
                    if d["rounds_played"]
                    else 0,
                    "rating": round(d["rating"] / max(d["rounds_played"], 1), 2)
                    if d["rounds_played"]
                    else 0,
                    "kast": round(d["kast"] / max(d["rounds_played"], 1), 1)
                    if d["rounds_played"]
                    else 0,
                    "headshot_percentage": round(d["hs"] / max(d["kills"], 1), 1)
                    if d["kills"]
                    else 0,
                    "impact": round(d["impact"] / max(d["rounds_played"], 1), 2)
                    if d["rounds_played"]
                    else 0,
                    "kpr": round(d["kills"] / max(d["rounds_played"], 1), 2)
                    if d["rounds_played"]
                    else 0,
                    "dpr": round(d["deaths"] / max(d["rounds_played"], 1), 2)
                    if d["rounds_played"]
                    else 0,
                    "rounds_played": d["rounds_played"],
                    "first_kills": d["first_kills"],
                    "first_deaths": d["first_deaths"],
                    "clutches_won": d["clutches_won"],
                    "multi2k": d["multi2k"],
                    "multi3k": d["multi3k"],
                    "multi4k": d["multi4k"],
                    "multi5k": d["multi5k"],
                    "trade_kills": d["trade_kills"],
                    "trade_deaths": d["trade_deaths"],
                    "utility_damage": round(d["utility_damage"] / m, 1) if m else 0,
                    "enemies_flashed": d["enemies_flashed"],
                    "mvp_count": d["mvp_count"],
                    "t_rating": round(d["t_rating"] / tm, 2) if d["t_maps"] else 0,
                    "ct_rating": round(d["ct_rating"] / cm, 2) if d["ct_maps"] else 0,
                    "t_kills": d["t_kills"],
                    "ct_kills": d["ct_kills"],
                    "t_deaths": d["t_deaths"],
                    "ct_deaths": d["ct_deaths"],
                    "t_adr": round(d["t_adr"] / tm, 1) if d["t_maps"] else 0,
                    "ct_adr": round(d["ct_adr"] / cm, 1) if d["ct_maps"] else 0,
                    "maps": m,
                }
            )
        result.sort(key=lambda x: x["rating"], reverse=True)
        return result

    overall_t1 = build_overall(team1_agg)
    overall_t2 = build_overall(team2_agg)

    all_overall = []
    for item in overall_t1:
        row = dict(item)
        row["team_side"] = "t1"
        row["team_short"] = match["t1s"]
        row["team_name"] = match["team1_name"]
        all_overall.append(row)
    for item in overall_t2:
        row = dict(item)
        row["team_side"] = "t2"
        row["team_short"] = match["t2s"]
        row["team_name"] = match["team2_name"]
        all_overall.append(row)

    def _avg(rows, key):
        usable = [float(row.get(key) or 0) for row in rows]
        return round(sum(usable) / len(usable), 2) if usable else 0

    def _sum(rows, key):
        return sum(int(row.get(key) or 0) for row in rows)

    def _top(rows, key):
        if not rows:
            return None
        return max(rows, key=lambda row: float(row.get(key) or 0))

    match_breakdown = {
        "t1_rating": _avg(overall_t1, "rating"),
        "t2_rating": _avg(overall_t2, "rating"),
        "t1_first_kills": _sum(overall_t1, "first_kills"),
        "t2_first_kills": _sum(overall_t2, "first_kills"),
        "t1_clutches": _sum(overall_t1, "clutches_won"),
        "t2_clutches": _sum(overall_t2, "clutches_won"),
    }
    match_highlights = [
        {
            "label": "最高 RATING",
            "player": _top(all_overall, "rating"),
            "key": "rating",
            "unit": "",
        },
        {"label": "最高 ADR", "player": _top(all_overall, "adr"), "key": "adr", "unit": ""},
        {"label": "最多击杀", "player": _top(all_overall, "kills"), "key": "kills", "unit": ""},
        {"label": "最多助攻", "player": _top(all_overall, "assists"), "key": "assists", "unit": ""},
        {
            "label": "最多闪白",
            "player": _top(all_overall, "enemies_flashed"),
            "key": "enemies_flashed",
            "unit": "",
        },
    ]
    match_performance_rows = sorted(
        all_overall, key=lambda row: float(row.get("rating") or 0), reverse=True
    )
    for row in match_performance_rows:
        rating = float(row.get("rating") or 0)
        row["rating_bar"] = max(4, min(100, round((rating / 1.8) * 100, 1))) if rating else 0

    # 胜者排前面：按地图胜场数判定（BO1/BO3/BO5 通用）
    t1_map_wins = 0
    t2_map_wins = 0
    for mn, t1s, t2s, active, _pb in raw_maps:
        if mn and active:
            s1 = int(t1s or 0)
            s2 = int(t2s or 0)
            if s1 > s2:
                t1_map_wins += 1
            elif s2 > s1:
                t2_map_wins += 1
    t1_win = t1_map_wins > t2_map_wins
    # 平局时用总比分判定
    if t1_map_wins == t2_map_wins:
        t1_win = int(match["team1_score"] or 0) > int(match["team2_score"] or 0)

    conn = get_db()
    raw_comments = conn.execute(
        """
        SELECT c.*, u.username,
               CASE WHEN COALESCE(u.is_bashizhong_student, 1)<>0
                    THEN u.group_username END AS group_username,
               u.avatar, u.is_cheater,
               (SELECT COUNT(*) FROM comment_likes WHERE comment_id=c.id) as like_count,
               (SELECT 1 FROM comment_likes WHERE comment_id=c.id AND user_id=?) as user_liked
        FROM comments c
        JOIN users u ON c.user_id = u.id
        WHERE c.target_type='match' AND c.target_id=?
        ORDER BY c.created_at ASC, c.id ASC
    """,
        (session.get("user_id"), match_id),
    ).fetchall()
    conn.close()

    comments = build_comment_tree(raw_comments)

    # 侧边栏：赛事 / 比赛 / 新闻
    conn = get_db()
    sidebar_events = conn.execute(
        "SELECT * FROM events ORDER BY start_date DESC LIMIT 9"
    ).fetchall()
    sidebar_events = [add_effective_event_status(e) for e in sidebar_events]
    sidebar_events.sort(
        key=lambda e: {"ongoing": 0, "upcoming": 1, "completed": 2}.get(
            e.get("effective_event_status", ""), 3
        )
    )
    sidebar_matches = conn.execute(f"""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s,
               {_SQL_EFFECTIVE_STATUS}
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        ORDER BY
        CASE WHEN {_SQL_MATCH_COMPLETED} THEN 3 ELSE 1 END,
        m.match_time DESC LIMIT 9
    """).fetchall()
    sidebar_news = conn.execute(
        "SELECT id, title, created_at FROM news ORDER BY created_at DESC LIMIT 3"
    ).fetchall()
    conn.close()

    # 观赛平台链接
    watch_urls = []
    if row_get(match, "watch_urls"):
        try:
            watch_urls = json.loads(match["watch_urls"])
        except (json.JSONDecodeError, TypeError):
            pass
    watch_urls = [
        {"name": str(item.get("name", "")), "url": safe_url}
        for item in watch_urls
        if isinstance(item, dict)
        if (safe_url := normalize_http_url(item.get("url")))
    ]

    # 投票数据
    vote_data = {"t1_count": 0, "t2_count": 0, "total": 0, "user_voted": None}
    user_id = session.get("user_id")
    if user_id:
        conn = get_db()
        vc = conn.execute(
            "SELECT voted_for, COUNT(*) as cnt FROM match_votes WHERE match_id=? GROUP BY voted_for",
            (match_id,),
        ).fetchall()
        for r in vc:
            if r["voted_for"] == "t1":
                vote_data["t1_count"] = r["cnt"]
            elif r["voted_for"] == "t2":
                vote_data["t2_count"] = r["cnt"]
        vote_data["total"] = vote_data["t1_count"] + vote_data["t2_count"]
        uv = conn.execute(
            "SELECT voted_for FROM match_votes WHERE match_id=? AND user_id=?", (match_id, user_id)
        ).fetchone()
        if uv:
            vote_data["user_voted"] = uv["voted_for"]
        conn.close()

    return render_template(
        "match_detail.html",
        match=match,
        map_scores=map_scores,
        overall_t1=overall_t1,
        overall_t2=overall_t2,
        t1_win=t1_win,
        match_breakdown=match_breakdown,
        match_highlights=match_highlights,
        match_performance_rows=match_performance_rows,
        show_match_stats=request.path.endswith("/stats"),
        comments=comments,
        sidebar_events=sidebar_events,
        sidebar_matches=sidebar_matches,
        sidebar_news=sidebar_news,
        watch_urls=watch_urls,
        vote_data=vote_data,
        h2h_matches=h2h_matches,
        team1_roster=team1_roster,
        team2_roster=team2_roster,
        team1_extra_subs=team1_extra_subs,
        team2_extra_subs=team2_extra_subs,
    )


@app.route("/matches/<int:match_id>/live")
def match_live(match_id):
    """独立比赛数据直播页。"""
    conn = get_db()
    match = conn.execute(
        f"""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s,
               t1.logo AS t1_logo, t2.logo AS t2_logo,
               e.name AS event_name, {get_sql_effective_status()}
        FROM matches m LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id LEFT JOIN events e ON m.event_id=e.id
        WHERE m.id=?
    """,
        (match_id,),
    ).fetchone()
    if not match:
        conn.close()
        return "比赛不存在", 404
    match = supplement_temp_teams(match, conn)
    conn.close()

    watch_urls = []
    if row_get(match, "watch_urls"):
        try:
            watch_urls = json.loads(match["watch_urls"])
        except (json.JSONDecodeError, TypeError):
            pass
    watch_urls = [
        {"name": str(item.get("name", "")), "url": safe_url}
        for item in watch_urls
        if isinstance(item, dict)
        if (safe_url := normalize_http_url(item.get("url")))
    ]
    return render_template("match_live.html", match=match, watch_urls=watch_urls)


def _safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default=0):
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _avg_values(values, digits=2):
    values = [float(v) for v in values if v is not None]
    if not values:
        return 0
    return round(sum(values) / len(values), digits)


def _rating_bar_width(value):
    rating = _safe_float(value)
    if rating <= 0:
        return 0
    return max(4, min(100, round((rating / 1.6) * 100, 1)))


def _metric_pct(value, target, floor=4):
    number = _safe_float(value)
    if target <= 0 or number <= 0:
        return 0
    return max(floor, min(100, round(number / target * 100, 1)))


def _metric_tier(value, excellent, good, normal, poor, higher_better=True):
    number = _safe_float(value)
    if higher_better:
        if number >= excellent:
            return "tier-excellent"
        if number >= good:
            return "tier-good"
        if number >= normal:
            return "tier-normal"
        if number >= poor:
            return "tier-poor"
        return "tier-bad"
    if number <= excellent:
        return "tier-excellent"
    if number <= good:
        return "tier-good"
    if number <= normal:
        return "tier-normal"
    if number <= poor:
        return "tier-poor"
    return "tier-bad"


def _build_match_player_row(data, team_side, team_short, team_name):
    kills = _safe_int(data.get("kills"))
    deaths = _safe_int(data.get("deaths"))
    assists = _safe_int(data.get("assists"))
    hs_pct = _safe_float(data.get("headshot_percentage"))
    first_kills = _safe_int(data.get("first_kills"))
    first_deaths = _safe_int(data.get("first_deaths"))
    rating = _safe_float(data.get("rating"))
    multi_kills = (
        _safe_int(data.get("multi2k"))
        + _safe_int(data.get("multi3k"))
        + _safe_int(data.get("multi4k"))
        + _safe_int(data.get("multi5k"))
    )
    mk_rating = _safe_float(data.get("impact"))
    rws = _safe_float(data.get("rws", data.get("rws_basic")))
    return {
        "player_id": data.get("player_id"),
        "nickname": data.get("nickname") or "Unknown",
        "avatar": data.get("avatar"),
        "steam_id": str(data.get("steam_id") or data.get("steamid") or ""),
        "team_side": team_side,
        "team_short": team_short,
        "team_name": team_name,
        "maps": _safe_int(data.get("maps"), 1),
        "kills": kills,
        "deaths": deaths,
        "assists": assists,
        "adr": round(_safe_float(data.get("adr")), 1),
        "kast": round(_safe_float(data.get("kast")), 1),
        "rating": round(rating, 2),
        "impact": round(_safe_float(data.get("impact")), 2),
        "kpr": round(_safe_float(data.get("kpr")), 2),
        "dpr": round(_safe_float(data.get("dpr")), 2),
        "mk_rating": round(mk_rating, 2),
        "multi_kills": multi_kills,
        "headshot_percentage": round(hs_pct, 1),
        "headshot_kills": int(round(kills * hs_pct / 100)) if kills else 0,
        "first_kills": first_kills,
        "first_deaths": first_deaths,
        "opening_diff": first_kills - first_deaths,
        "clutches_won": _safe_int(data.get("clutches_won")),
        "clutch_1v1": _safe_int(data.get("clutch_1v1")),
        "clutch_1v2": _safe_int(data.get("clutch_1v2")),
        "clutch_1v3": _safe_int(data.get("clutch_1v3")),
        "clutch_1v4": _safe_int(data.get("clutch_1v4")),
        "clutch_1v5": _safe_int(data.get("clutch_1v5")),
        "trade_kills": _safe_int(data.get("trade_kills")),
        "trade_deaths": _safe_int(data.get("trade_deaths")),
        "enemies_flashed": _safe_int(data.get("enemies_flashed")),
        "utility_damage": round(_safe_float(data.get("utility_damage")), 1),
        "rounds_played": _safe_int(data.get("rounds_played")),
        "damage_delta_per_round": round(_safe_float(data.get("damage_delta_per_round")), 2),
        "rws": round(rws, 2),
        "t_kills": _safe_int(data.get("t_kills")),
        "t_deaths": _safe_int(data.get("t_deaths")),
        "t_adr": round(_safe_float(data.get("t_adr")), 1),
        "t_rating": round(_safe_float(data.get("t_rating")), 2),
        "ct_kills": _safe_int(data.get("ct_kills")),
        "ct_deaths": _safe_int(data.get("ct_deaths")),
        "ct_adr": round(_safe_float(data.get("ct_adr")), 1),
        "ct_rating": round(_safe_float(data.get("ct_rating")), 2),
        "rating_bar": _rating_bar_width(rating),
        "kpr_bar": _metric_pct(data.get("kpr"), 1.0),
        "dpr_bar": _metric_pct(data.get("dpr"), 1.0),
        "kast_bar": _metric_pct(data.get("kast"), 100),
        "mk_bar": _metric_pct(mk_rating, 1.5),
        "rws_bar": _metric_pct(rws, 20),
        "adr_bar": _metric_pct(data.get("adr"), 120),
        "kpr_tier": _metric_tier(data.get("kpr"), 0.85, 0.75, 0.65, 0.55),
        "dpr_tier": _metric_tier(data.get("dpr"), 0.55, 0.62, 0.70, 0.80, higher_better=False),
        "kast_tier": _metric_tier(data.get("kast"), 80, 75, 70, 65),
        "impact_tier": _metric_tier(mk_rating, 1.25, 1.10, 0.95, 0.80),
        "rws_tier": _metric_tier(rws, 18, 14, 10, 6),
        "adr_tier": _metric_tier(data.get("adr"), 90, 80, 70, 60),
        "rating_tier": _metric_tier(rating, 1.25, 1.10, 0.95, 0.80),
    }


def _display_rows_from_raw(rows, team_side, team_short, team_name):
    result = []
    for row in rows:
        data = dict(row)
        data["maps"] = 1
        result.append(_build_match_player_row(data, team_side, team_short, team_name))
    result.sort(key=lambda item: item["rating"], reverse=True)
    return result


def _aggregate_match_rows(rows, team_side, team_short, team_name):
    grouped = defaultdict(
        lambda: {
            "kills": 0,
            "deaths": 0,
            "assists": 0,
            "first_kills": 0,
            "first_deaths": 0,
            "clutches_won": 0,
            "clutch_1v1": 0,
            "clutch_1v2": 0,
            "clutch_1v3": 0,
            "clutch_1v4": 0,
            "clutch_1v5": 0,
            "trade_kills": 0,
            "trade_deaths": 0,
            "enemies_flashed": 0,
            "utility_damage": 0,
            "rounds_played": 0,
            "t_kills": 0,
            "t_deaths": 0,
            "ct_kills": 0,
            "ct_deaths": 0,
            "multi2k": 0,
            "multi3k": 0,
            "multi4k": 0,
            "multi5k": 0,
            "maps": 0,
            "adr_values": [],
            "kast_values": [],
            "rating_values": [],
            "impact_values": [],
            "hs_values": [],
            "swing_values": [],
            "kpr_values": [],
            "dpr_values": [],
            "rws_values": [],
            "t_adr_values": [],
            "t_rating_values": [],
            "ct_adr_values": [],
            "ct_rating_values": [],
        }
    )
    for row in rows:
        pid = row["player_id"]
        item = grouped[pid]
        item["player_id"] = pid
        item["nickname"] = row["nickname"]
        item["avatar"] = row_get(row, "avatar")
        item["steam_id"] = row_get(row, "steam_id")
        item["maps"] += 1
        for key in (
            "kills",
            "deaths",
            "assists",
            "first_kills",
            "first_deaths",
            "clutches_won",
            "clutch_1v1",
            "clutch_1v2",
            "clutch_1v3",
            "clutch_1v4",
            "clutch_1v5",
            "trade_kills",
            "trade_deaths",
            "enemies_flashed",
            "rounds_played",
            "t_kills",
            "t_deaths",
            "ct_kills",
            "ct_deaths",
            "multi2k",
            "multi3k",
            "multi4k",
            "multi5k",
        ):
            item[key] += _safe_int(row_get(row, key, 0))
        item["utility_damage"] += _safe_float(row_get(row, "utility_damage", 0))
        weight = max(1, _safe_int(row_get(row, "rounds_played", 0)))
        for _ in range(weight):
            item["adr_values"].append(_safe_float(row_get(row, "adr", 0)))
            item["kast_values"].append(_safe_float(row_get(row, "kast", 0)))
            item["rating_values"].append(_safe_float(row_get(row, "rating", 0)))
            item["impact_values"].append(_safe_float(row_get(row, "impact", 0)))
            item["kpr_values"].append(_safe_float(row_get(row, "kpr", 0)))
            item["dpr_values"].append(_safe_float(row_get(row, "dpr", 0)))
            item["rws_values"].append(_safe_float(row_get(row, "rws_basic", 0)))
        for _ in range(max(1, _safe_int(row_get(row, "kills", 0)))):
            item["hs_values"].append(_safe_float(row_get(row, "headshot_percentage", 0)))
        for _ in range(weight):
            item["swing_values"].append(_safe_float(row_get(row, "damage_delta_per_round", 0)))
        if _safe_float(row_get(row, "t_rating", 0)) or _safe_int(row_get(row, "t_kills", 0)):
            item["t_adr_values"].append(_safe_float(row_get(row, "t_adr", 0)))
            item["t_rating_values"].append(_safe_float(row_get(row, "t_rating", 0)))
        if _safe_float(row_get(row, "ct_rating", 0)) or _safe_int(row_get(row, "ct_kills", 0)):
            item["ct_adr_values"].append(_safe_float(row_get(row, "ct_adr", 0)))
            item["ct_rating_values"].append(_safe_float(row_get(row, "ct_rating", 0)))

    result = []
    for item in grouped.values():
        data = {
            "player_id": item.get("player_id"),
            "nickname": item.get("nickname"),
            "avatar": item.get("avatar"),
            "steam_id": item.get("steam_id"),
            "maps": item["maps"],
            "kills": item["kills"],
            "deaths": item["deaths"],
            "assists": item["assists"],
            "first_kills": item["first_kills"],
            "first_deaths": item["first_deaths"],
            "clutches_won": item["clutches_won"],
            "clutch_1v1": item["clutch_1v1"],
            "clutch_1v2": item["clutch_1v2"],
            "clutch_1v3": item["clutch_1v3"],
            "clutch_1v4": item["clutch_1v4"],
            "clutch_1v5": item["clutch_1v5"],
            "trade_kills": item["trade_kills"],
            "trade_deaths": item["trade_deaths"],
            "enemies_flashed": item["enemies_flashed"],
            "utility_damage": item["utility_damage"],
            "rounds_played": item["rounds_played"],
            "multi2k": item["multi2k"],
            "multi3k": item["multi3k"],
            "multi4k": item["multi4k"],
            "multi5k": item["multi5k"],
            "t_kills": item["t_kills"],
            "t_deaths": item["t_deaths"],
            "ct_kills": item["ct_kills"],
            "ct_deaths": item["ct_deaths"],
            "adr": _avg_values(item["adr_values"], 1),
            "kast": _avg_values(item["kast_values"], 1),
            "rating": _avg_values(item["rating_values"], 2),
            "impact": _avg_values(item["impact_values"], 2),
            "kpr": _avg_values(item["kpr_values"], 2),
            "dpr": _avg_values(item["dpr_values"], 2),
            "rws_basic": _avg_values(item["rws_values"], 2),
            "headshot_percentage": _avg_values(item["hs_values"], 1),
            "damage_delta_per_round": _avg_values(item["swing_values"], 2),
            "t_adr": _avg_values(item["t_adr_values"], 1),
            "t_rating": _avg_values(item["t_rating_values"], 2),
            "ct_adr": _avg_values(item["ct_adr_values"], 1),
            "ct_rating": _avg_values(item["ct_rating_values"], 2),
        }
        result.append(_build_match_player_row(data, team_side, team_short, team_name))
    result.sort(key=lambda item: item["rating"], reverse=True)
    return result


def _team_summary(rows):
    return {
        "rating": _avg_values([row["rating"] for row in rows], 2),
        "adr": _avg_values([row["adr"] for row in rows], 1),
        "kills": sum(row["kills"] for row in rows),
        "deaths": sum(row["deaths"] for row in rows),
        "assists": sum(row["assists"] for row in rows),
        "first_kills": sum(row["first_kills"] for row in rows),
        "clutches": sum(row["clutches_won"] for row in rows),
    }


def _highlight_rows(players):
    def top_by(key):
        usable = [player for player in players if _safe_float(player.get(key, 0)) > 0]
        return max(usable, key=lambda player: _safe_float(player.get(key, 0))) if usable else None

    highlights = [
        {"label": "最高 Rating", "player": top_by("rating"), "key": "rating", "digits": 2},
        {"label": "最高 ADR", "player": top_by("adr"), "key": "adr", "digits": 1},
        {"label": "最多击杀", "player": top_by("kills"), "key": "kills", "digits": 0},
        {"label": "最多首杀", "player": top_by("first_kills"), "key": "first_kills", "digits": 0},
        {"label": "最多助攻", "player": top_by("assists"), "key": "assists", "digits": 0},
        {"label": "最多残局", "player": top_by("clutches_won"), "key": "clutches_won", "digits": 0},
    ]
    for item in highlights:
        player = item.get("player")
        if not player:
            item["value"] = "-"
            continue
        value = player.get(item["key"], 0)
        item["value"] = (
            f"{_safe_float(value):.{item['digits']}f}" if item["digits"] else str(_safe_int(value))
        )
    return highlights


def _identity_key(value):
    return str(value or "").strip().casefold()


def _load_persisted_kill_events(conn, match_id):
    """Load compact kill rows saved during Demo import."""
    rows = conn.execute(
        """
        SELECT match_id, map_name, round_number, tick,
               killer_player_id, victim_player_id, assister_player_id,
               killer_steam_id, victim_steam_id, assister_steam_id,
               killer_name, victim_name, assister_name,
               killer_side, victim_side, assister_side,
               weapon, headshot
        FROM match_kill_events
        WHERE match_id=?
        ORDER BY map_name, round_number, tick, id
        """,
        (match_id,),
    ).fetchall()
    return [
        {
            "map_name": row["map_name"],
            "round_number": row["round_number"],
            "tick": row["tick"],
            "killer_player_id": row["killer_player_id"],
            "victim_player_id": row["victim_player_id"],
            "assister_player_id": row["assister_player_id"],
            "killer_steamid": row["killer_steam_id"],
            "victim_steamid": row["victim_steam_id"],
            "assister_steamid": row["assister_steam_id"],
            "killer": row["killer_name"],
            "victim": row["victim_name"],
            "assister": row["assister_name"],
            "killer_side": row["killer_side"],
            "victim_side": row["victim_side"],
            "assister_side": row["assister_side"],
            "weapon": row["weapon"],
            "headshot": bool(row["headshot"]),
        }
        for row in rows
    ]


def _build_player_alias_map(conn, player_ids):
    if not player_ids:
        return {}
    placeholders = ",".join("?" for _ in player_ids)
    rows = conn.execute(
        f"SELECT player_id, nickname FROM player_nickname_history WHERE player_id IN ({placeholders})",
        tuple(player_ids),
    ).fetchall()
    aliases = defaultdict(set)
    for row in rows:
        aliases[row["player_id"]].add(row["nickname"])
    return aliases


def _build_player_lookup(team1_rows, team2_rows, aliases):
    lookup = {}
    for row in team1_rows + team2_rows:
        pid = row["player_id"]
        if row.get("steam_id"):
            lookup[f"steam:{row['steam_id']}"] = pid
        names = {row.get("nickname") or ""}
        names.update(aliases.get(pid, set()))
        for name in names:
            key = _identity_key(name)
            if key:
                lookup[f"name:{key}"] = pid
    return lookup


def _event_player_id(lookup, steamid="", name=""):
    steam_key = f"steam:{steamid}" if steamid else ""
    if steam_key and steam_key in lookup:
        return lookup[steam_key]
    name_key = f"name:{_identity_key(name)}" if name else ""
    return lookup.get(name_key)


def _add_demo_stat_aliases(lookup, rows, kill_events):
    demo_stats = {}

    def key_for(steamid, name):
        steamid = str(steamid or "").strip()
        name = str(name or "").strip()
        if steamid:
            return f"steam:{steamid}", steamid, name
        name_key = _identity_key(name)
        return (f"name:{name_key}", "", name) if name_key else ("", "", "")

    for event in kill_events or []:
        killer_key, killer_steamid, killer_name = key_for(
            event.get("killer_steamid"), event.get("killer")
        )
        if killer_key:
            item = demo_stats.setdefault(
                killer_key,
                {
                    "steamid": killer_steamid,
                    "name": killer_name,
                    "kills": 0,
                    "deaths": 0,
                },
            )
            item["kills"] += 1
            if killer_name:
                item["name"] = killer_name
        victim_key, victim_steamid, victim_name = key_for(
            event.get("victim_steamid"), event.get("victim")
        )
        if victim_key:
            item = demo_stats.setdefault(
                victim_key,
                {
                    "steamid": victim_steamid,
                    "name": victim_name,
                    "kills": 0,
                    "deaths": 0,
                },
            )
            item["deaths"] += 1
            if victim_name:
                item["name"] = victim_name

    for item in demo_stats.values():
        if _event_player_id(lookup, item.get("steamid"), item.get("name")):
            continue
        scored = []
        for row in rows:
            score = abs(_safe_int(row.get("kills")) - item["kills"]) + abs(
                _safe_int(row.get("deaths")) - item["deaths"]
            )
            scored.append((score, row["player_id"]))
        scored.sort()
        if not scored:
            continue
        best_score, best_pid = scored[0]
        next_score = scored[1][0] if len(scored) > 1 else best_score + 99
        total_duels = item["kills"] + item["deaths"]
        limit = 4 if total_duels >= 40 else 2
        if best_score <= limit and best_score < next_score:
            if item.get("steamid"):
                lookup[f"steam:{item['steamid']}"] = best_pid
            name_key = _identity_key(item.get("name"))
            if name_key:
                lookup[f"name:{name_key}"] = best_pid


def _build_kill_matrix(team1_rows, team2_rows, aliases, kill_events):
    lookup = _build_player_lookup(team1_rows, team2_rows, aliases)
    _add_demo_stat_aliases(lookup, team1_rows + team2_rows, kill_events)
    team1_ids = {row["player_id"] for row in team1_rows}
    team2_ids = {row["player_id"] for row in team2_rows}

    def empty_matrix():
        return {
            t1["player_id"]: {t2["player_id"]: {"t1": 0, "t2": 0} for t2 in team2_rows}
            for t1 in team1_rows
        }

    def add_to_matrix(matrix, duel):
        matrix[duel["row_id"]][duel["col_id"]][duel["side"]] += 1

    def is_awp_kill(event):
        weapon = str(event.get("weapon") or "").strip().lower()
        weapon = weapon.removeprefix("weapon_")
        return weapon == "awp"

    matrices = {
        "all": empty_matrix(),
        "first": empty_matrix(),
        "awp": empty_matrix(),
    }
    total_events = 0
    matched_counts = {"all": 0, "first": 0, "awp": 0}
    duels_by_round = defaultdict(list)

    for event in kill_events:
        total_events += 1
        killer_id = event.get("killer_player_id") or _event_player_id(
            lookup, event.get("killer_steamid"), event.get("killer")
        )
        victim_id = event.get("victim_player_id") or _event_player_id(
            lookup, event.get("victim_steamid"), event.get("victim")
        )
        if not killer_id or not victim_id or killer_id == victim_id:
            continue
        if killer_id in team1_ids and victim_id in team2_ids:
            duel = {
                "row_id": killer_id,
                "col_id": victim_id,
                "side": "t1",
                "tick": _safe_int(event.get("tick")),
                "round_key": (
                    event.get("map_slot", 0),
                    _safe_int(event.get("round_number") or event.get("round")),
                ),
                "event": event,
            }
        elif killer_id in team2_ids and victim_id in team1_ids:
            duel = {
                "row_id": victim_id,
                "col_id": killer_id,
                "side": "t2",
                "tick": _safe_int(event.get("tick")),
                "round_key": (
                    event.get("map_slot", 0),
                    _safe_int(event.get("round_number") or event.get("round")),
                ),
                "event": event,
            }
        else:
            continue

        add_to_matrix(matrices["all"], duel)
        matched_counts["all"] += 1
        if is_awp_kill(event):
            add_to_matrix(matrices["awp"], duel)
            matched_counts["awp"] += 1
        if duel["round_key"][1] > 0:
            duels_by_round[duel["round_key"]].append(duel)

    for round_duels in duels_by_round.values():
        round_duels.sort(key=lambda item: item["tick"])
        if not round_duels:
            continue
        add_to_matrix(matrices["first"], round_duels[0])
        matched_counts["first"] += 1

    modes = [
        {
            "id": "all",
            "label": "全部",
            "cells": matrices["all"],
            "matched_events": matched_counts["all"],
        },
        {
            "id": "first",
            "label": "首杀",
            "cells": matrices["first"],
            "matched_events": matched_counts["first"],
        },
        {
            "id": "awp",
            "label": "AWP 击杀",
            "cells": matrices["awp"],
            "matched_events": matched_counts["awp"],
        },
    ]

    return {
        "rows": team1_rows,
        "cols": team2_rows,
        "cells": matrices["all"],
        "modes": modes,
        "total_events": total_events,
        "matched_events": matched_counts["all"],
    }


def _build_match_detailed_context(match_id):
    conn = get_db()
    match = conn.execute(
        f"""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s,
               t1.logo AS t1_logo, t2.logo AS t2_logo,
               e.name AS event_name, e.id AS event_id, e.slug AS event_slug,
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
        return None
    match = supplement_temp_teams(match, conn)

    stats = conn.execute(
        """
        SELECT ms.*, p.nickname, p.avatar, p.steam_id, p.id AS player_id
        FROM match_stats ms
        JOIN players p ON ms.player_id=p.id
        WHERE ms.match_id=?
          AND COALESCE(ms.data_status, 'final') <> 'superseded'
        ORDER BY ms.map_name, ms.team_id, ms.rating DESC
    """,
        (match_id,),
    ).fetchall()
    player_ids = sorted({row["player_id"] for row in stats})
    player_aliases = _build_player_alias_map(conn, player_ids)
    persisted_kill_events = _load_persisted_kill_events(conn, match_id)
    conn.close()

    t1_key = match["team1_id"] if match["team1_id"] else -1
    t2_key = match["team2_id"] if match["team2_id"] else -2
    raw_maps = [
        (
            match["map1"],
            match["map1_t1"],
            match["map1_t2"],
            True,
            row_get(match, "map1_picked_by", ""),
        ),
        (
            match["map2"],
            match["map2_t1"],
            match["map2_t2"],
            True,
            row_get(match, "map2_picked_by", ""),
        ),
        (
            match["map3"],
            match["map3_t1"],
            match["map3_t2"],
            bool(match["has_map3"]),
            row_get(match, "map3_picked_by", ""),
        ),
        (
            match["map4"],
            match["map4_t1"],
            match["map4_t2"],
            bool(row_get(match, "has_map4", 1)),
            row_get(match, "map4_picked_by", ""),
        ),
        (
            match["map5"],
            match["map5_t1"],
            match["map5_t2"],
            bool(row_get(match, "has_map5", 1)),
            row_get(match, "map5_picked_by", ""),
        ),
    ]
    bo = (match["bo_format"] or "BO3").upper()
    max_maps = 5 if bo == "BO5" else 3 if bo == "BO3" else 1
    map_halves = parse_map_halves(match)

    map_scores = []
    for idx, (map_name, t1_score, t2_score, active, picked_by) in enumerate(raw_maps):
        if idx >= max_maps:
            break
        map_rows = [row for row in stats if map_name and row["map_name"] == map_name]
        team1_raw = [row for row in map_rows if _stat_belongs_to_match_side(row, "t1", t1_key)]
        team2_raw = [row for row in map_rows if _stat_belongs_to_match_side(row, "t2", t2_key)]
        team1_rows = _display_rows_from_raw(team1_raw, "t1", match["t1s"], match["team1_name"])
        team2_rows = _display_rows_from_raw(team2_raw, "t2", match["t2s"], match["team2_name"])
        played = bool(map_name and (t1_score or t2_score))
        has_stats = bool(map_rows)
        map_scores.append(
            {
                "index": idx + 1,
                "name": map_name or "TBA",
                "t1": _safe_int(t1_score),
                "t2": _safe_int(t2_score),
                "active": active,
                "picked_by": picked_by or "",
                "halves": get_map_half_scores(match, idx, map_halves) if map_name else None,
                "played": played,
                "has_stats": has_stats,
                "team1_stats": team1_rows,
                "team2_stats": team2_rows,
                "performance_rows": sorted(
                    team1_rows + team2_rows, key=lambda item: item["rating"], reverse=True
                ),
                "summary": {"t1": _team_summary(team1_rows), "t2": _team_summary(team2_rows)},
            }
        )

    team1_all_raw = [row for row in stats if _stat_belongs_to_match_side(row, "t1", t1_key)]
    team2_all_raw = [row for row in stats if _stat_belongs_to_match_side(row, "t2", t2_key)]
    overall_t1 = _aggregate_match_rows(team1_all_raw, "t1", match["t1s"], match["team1_name"])
    overall_t2 = _aggregate_match_rows(team2_all_raw, "t2", match["t2s"], match["team2_name"])
    all_players = sorted(overall_t1 + overall_t2, key=lambda item: item["rating"], reverse=True)

    map_cards = [item for item in map_scores if item["name"] != "TBA"]
    requested_map = (request.args.get("map") or "all").strip().lower()
    selected_map = None
    if requested_map not in ("", "all"):
        try:
            requested_index = int(requested_map)
        except ValueError:
            requested_index = 0
        selected_map = next((item for item in map_cards if item["index"] == requested_index), None)

    if selected_map:
        team1_rows = selected_map["team1_stats"]
        team2_rows = selected_map["team2_stats"]
        performance_rows = selected_map["performance_rows"]
        selected_map_index = selected_map["index"]
        selected_label = selected_map["name"]
        score_t1 = selected_map["t1"]
        score_t2 = selected_map["t2"]
    else:
        team1_rows = overall_t1
        team2_rows = overall_t2
        performance_rows = all_players
        selected_map_index = 0
        selected_label = "All"
        score_t1 = match["team1_score"] if match["team1_score"] is not None else "-"
        score_t2 = match["team2_score"] if match["team2_score"] is not None else "-"

    map_slots = {
        normalize_map_key(card["name"]): card["index"] - 1 for card in map_cards if card.get("name")
    }
    kill_events = []
    for event in persisted_kill_events:
        event_map_key = normalize_map_key(event.get("map_name") or "")
        if selected_map and event_map_key != normalize_map_key(selected_map["name"]):
            continue
        event["map_slot"] = map_slots.get(event_map_key, 0)
        kill_events.append(event)
    summary = {"t1": _team_summary(team1_rows), "t2": _team_summary(team2_rows)}
    kill_matrix = _build_kill_matrix(team1_rows, team2_rows, player_aliases, kill_events)
    selected_tab = (request.args.get("tab") or "overview").strip().lower()
    if selected_tab not in ("overview", "performance"):
        selected_tab = "overview"

    return {
        "match": match,
        "map_cards": map_cards,
        "selected_map_index": selected_map_index,
        "selected_label": selected_label,
        "score_t1": score_t1,
        "score_t2": score_t2,
        "summary": summary,
        "team1_rows": team1_rows,
        "team2_rows": team2_rows,
        "performance_rows": performance_rows,
        "highlights": _highlight_rows(performance_rows),
        "kill_matrix": kill_matrix,
        "selected_tab": selected_tab,
        "has_any_stats": bool(stats),
    }


@app.route("/matches/<slug>/detailed")
def match_detailed_stats(slug):
    """HLTV 风格的比赛详细数据页。"""
    match_id = resolve_match_slug(slug)
    if not match_id:
        return "比赛不存在", 404
    context = _build_match_detailed_context(match_id)
    if not context:
        return "比赛不存在", 404
    return render_template("match_detailed.html", **context)
