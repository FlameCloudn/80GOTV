"""Public match list, results, and legacy live redirect."""

import calendar
from datetime import datetime, timedelta

from flask import redirect, render_template, request, url_for

from src.website.domains.events.arg_event_service import ordinary_event_condition
from src.website.domains.matches.match_utils import (
    get_sql_effective_status,
    get_sql_match_completed,
    get_sql_match_live,
    get_sql_match_upcoming,
)
from src.website.domains.matches.opponents import supplement_temp_teams
from src.website.runtime.database import get_db
from src.website.web.routing import site_routes

_SQL_MATCH_COMPLETED = get_sql_match_completed()


_SQL_MATCH_UPCOMING = get_sql_match_upcoming()


_SQL_MATCH_LIVE = get_sql_match_live()


_SQL_EFFECTIVE_STATUS = get_sql_effective_status()


@site_routes.route("/matches")
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

    events = conn.execute(
        f"SELECT * FROM events WHERE {ordinary_event_condition()} ORDER BY start_date DESC"
    ).fetchall()
    completed_on_selected_date = 0
    if date_filter:
        # 与列表同一组条件：选了赛事时只看该赛事当天有没有已结束的比赛
        completed_sql = f"""
            SELECT COUNT(*)
            FROM matches m
            WHERE {_SQL_MATCH_COMPLETED}
              AND substr(COALESCE(m.match_time, ''), 1, 10)=?
        """
        completed_params = [date_filter]
        if event_filter:
            completed_sql += " AND m.event_id=?"
            completed_params.append(event_filter)
        completed_on_selected_date = conn.execute(completed_sql, completed_params).fetchone()[0]
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
        "public/matches/matches.html",
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


@site_routes.route("/results")
def results_list():
    """赛果列表（已结束）"""
    event_filter = request.args.get("event", "")
    page = request.args.get("page", 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page

    conn = get_db()
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
    events = conn.execute(
        f"SELECT * FROM events WHERE {ordinary_event_condition()} ORDER BY start_date DESC"
    ).fetchall()

    total_query = f"SELECT COUNT(*) as cnt FROM matches m WHERE {_SQL_MATCH_COMPLETED}"
    if event_filter:
        total_query += " AND m.event_id=?"
        total = conn.execute(total_query, (event_filter,)).fetchone()["cnt"]
    else:
        total = conn.execute(total_query).fetchone()["cnt"]

    conn.close()

    total_pages = (total + per_page - 1) // per_page
    return render_template(
        "public/matches/results.html",
        matches=matches,
        events=events,
        event_filter=event_filter,
        page=page,
        total_pages=total_pages,
    )


@site_routes.route("/matches/<int:match_id>/live")
def match_live(match_id):
    """旧的独立直播页已删除：数据直播就在比赛页里，旧链接直接跳过去。"""
    return redirect(url_for("match_detail", slug=match_id) + "#data-live")
