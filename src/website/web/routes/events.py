"""Public event list, detail, awards and standings routes."""

from functools import lru_cache

from flask import (
    current_app,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    session,
)

from src.website.domains.awards.player_awards_service import find_event_award_player
from src.website.domains.events import reads as event_reads
from src.website.domains.events.arg_event_service import (
    ARG_EVENT_PATH,
    ARG_UNAVAILABLE_ALT,
    event_display_values,
    is_arg_event,
)
from src.website.domains.events.event_profile import build_event_page_context
from src.website.domains.events.event_references import event_path, resolve_event_ref
from src.website.domains.events.registration_reads import (
    _load_individual_registrations,
    _managed_registration_flags,
    registration_user,
)
from src.website.domains.events.status import add_effective_event_status
from src.website.domains.statistics.event_summary import (
    _event_matches_with_teams,
    _event_player_teams,
    _event_team_count,
    _event_team_rankings,
)
from src.website.domains.statistics.performance_service import stat_average_sql
from src.website.domains.statistics.stats_storage import (
    stat_map_count_sql,
    stat_map_key_sql,
    stats_relation,
)
from src.website.runtime.database import get_db
from src.website.runtime.rate_limiter import rate_limit
from src.website.runtime.storage import SOURCE_ROOT
from src.website.web.presentation.event_awards import build_event_award_poster
from src.website.web.routes import event_registration
from src.website.web.routing import site_routes


@site_routes.route(ARG_EVENT_PATH)
def arg_unavailable():
    return make_response(
        render_template("public/tools/arg_unavailable.html", alt_line=ARG_UNAVAILABLE_ALT), 503
    )


@site_routes.get("/api/events/<int:event_id>/display")
def event_display(event_id):
    if not rate_limit("event_display", 240, 60, by_ip=True):
        return jsonify({"ok": False}), 429
    conn = get_db()
    try:
        event = conn.execute("SELECT name,slug FROM events WHERE id=?", (event_id,)).fetchone()
    finally:
        conn.close()
    if not event or not is_arg_event(event):
        return jsonify({"ok": False}), 404
    return jsonify({"values": event_display_values(request.args.get("after", ""))})


@site_routes.route("/events")
def events_list():
    """赛事列表"""
    status_filter = request.args.get("status", "")
    view_mode = request.args.get("view", "")  # calendar / list
    if not view_mode and not status_filter:
        view_mode = "calendar"  # 不带筛选打开时默认按日历（按月分组）显示

    conn = get_db()
    events = conn.execute("""
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
    events = [add_effective_event_status(event_reads.public_event(conn, e)) for e in events]
    events.sort(key=lambda event: not is_arg_event(event))

    # 状态筛选
    if status_filter in ("ongoing", "completed", "upcoming"):
        events = [e for e in events if e["effective_event_status"] == status_filter]

    conn.close()

    return render_template(
        "public/events/events.html", events=events, status_filter=status_filter, view_mode=view_mode
    )


@site_routes.route("/events/<event_id>")
def event_detail(event_id):
    """赛事详情"""
    conn = get_db()
    # A settlement changes both the score and the downstream participant in one commit.
    if not conn.in_transaction:
        conn.execute("BEGIN")
    event_ref = str(event_id)
    event = resolve_event_ref(conn, event_ref)

    if not event:
        conn.close()
        return "赛事不存在", 404
    if is_arg_event(event):
        conn.close()
        return redirect(ARG_EVENT_PATH, code=302)
    if event["slug"] and event_ref != event["slug"]:
        conn.close()
        return redirect(event_path(event), code=301)
    context = build_event_page_context(conn, event)
    event = context["event"]
    current_user = registration_user(conn, session.get("user_id"))
    individual_registration = _load_individual_registrations(
        conn,
        event["id"],
        current_user["id"] if current_user else None,
    )
    flags = _managed_registration_flags(conn, event, individual_registration)
    conn.close()

    return render_template(
        "public/events/event_detail.html",
        **context,
        individual_registration=individual_registration,
        individual_registration_open=event_registration._individual_registration_is_open(),
        substitute_registration_open=event["effective_event_status"] != "completed",
        current_user=current_user,
        **flags,
    )


@site_routes.route("/events/<int:event_id>/mvp-poster.png")
def event_mvp_poster(event_id):
    """Public MVP card shown at the bottom of the event page."""
    conn = get_db()
    mvp_player = find_event_award_player(conn, event_id)
    if not mvp_player:
        conn.close()
        return "该赛事还没有设置 MVP", 404
    buffer = build_event_award_poster(conn, SOURCE_ROOT, event_id, mvp_player["id"], "MVP")
    conn.close()
    if not buffer:
        return "赛事或选手不存在", 404
    return send_file(buffer, mimetype="image/png", max_age=0)


@site_routes.route("/events/<int:event_id>/award-poster/<award_type>/<int:player_id>.png")
def event_award_poster(event_id, award_type, player_id):
    """Public MVP / EVP cards shown together at the bottom of the event page."""
    award_type = award_type.upper()
    if award_type not in ("MVP", "EVP"):
        return "荣誉类型不存在", 404
    conn = get_db()
    if not find_event_award_player(conn, event_id, award_type, player_id=player_id):
        conn.close()
        return "该赛事没有这张数据图", 404
    buffer = build_event_award_poster(conn, SOURCE_ROOT, event_id, player_id, award_type)
    conn.close()
    if not buffer:
        return "赛事或选手不存在", 404
    return send_file(buffer, mimetype="image/png", max_age=0)


class _KnownZeroRatio(float):
    def __bool__(self):
        # The original template uses truthiness to decide if a K/D exists.
        return True


@lru_cache(maxsize=1)
def _event_stats_environment(environment):
    """Let the original numeric cells display missing stats without changing other pages."""
    default_format = environment.filters["format"]

    def format_metric(pattern, *args, **kwargs):
        if pattern in ("%.1f", "%.2f") and args == (None,) and not kwargs:
            return "-"
        return default_format(pattern, *args, **kwargs)

    local = environment.overlay()
    local.filters = {**local.filters, "format": format_metric}
    return local


@site_routes.route("/events/<event_id>/stats")
def event_stats(event_id):
    """赛事数据统计"""
    conn = get_db()
    event_ref = str(event_id)
    event = resolve_event_ref(conn, event_ref)
    if not event:
        conn.close()
        return "赛事不存在", 404
    if is_arg_event(event):
        conn.close()
        return redirect(ARG_EVENT_PATH, code=302)
    if event["slug"] and event_ref != event["slug"]:
        conn.close()
        return redirect(event_path(event) + "/stats", code=301)
    event_id = event["id"]

    # 选手排行
    stats_source = stats_relation(conn)
    rankings = conn.execute(
        f"""
        SELECT p.nickname, p.id,
               CASE WHEN COUNT(DISTINCT ms.team_id)=1 THEN MAX(t.short_name) END AS team,
               {stat_average_sql("rating")} AS rating,
               (SUM(ms.kills) * 1.0 / NULLIF(SUM(ms.deaths), 0)) AS kd,
               {stat_average_sql("adr")} AS adr,
               {stat_average_sql("kast")} AS kast,
               {stat_average_sql("impact")} AS impact,
               {stat_average_sql("headshot_percentage", weight="kills")} AS hs,
               SUM(ms.clutches_won) AS clutch,
               COUNT(DISTINCT ms.match_id) AS matches,
               {stat_map_count_sql()} AS maps
        FROM {stats_source} ms
        JOIN players p ON ms.player_id=p.id
        LEFT JOIN teams t ON ms.team_id=t.id
        JOIN matches m ON ms.match_id=m.id
        WHERE m.event_id=?
          AND COALESCE(ms.data_status, 'final') <> 'superseded'
        GROUP BY p.id
        ORDER BY rating DESC LIMIT 30
    """,
        (event_id,),
    ).fetchall()
    matches = _event_matches_with_teams(conn, event_id)
    player_teams = _event_player_teams(conn, event_id, matches)
    # 认得出比赛里是哪一方的按比赛取；一条都认不出的才用正式队伍库的简称
    rankings = [
        dict(
            row,
            team=player_teams[row["id"]] if row["id"] in player_teams else row["team"],
            kd=_KnownZeroRatio(0) if row["kd"] == 0 else row["kd"],
        )
        for row in rankings
    ]

    # 地图统计
    map_stats = conn.execute(
        f"""
        SELECT MIN(ms.map_name) AS map_name,
               {stat_map_count_sql(per_player=False)} AS times_played,
               {stat_average_sql("rating")} AS avg_rating,
               (SUM(ms.kills) * 1.0 / NULLIF(SUM(ms.deaths), 0)) AS avg_kd
        FROM {stats_source} ms
        JOIN matches m ON ms.match_id=m.id
        WHERE m.event_id=? AND ms.map_name != '' AND ms.map_name IS NOT NULL
          AND COALESCE(ms.data_status, 'final') <> 'superseded'
        GROUP BY CASE WHEN ms.scheduled_map_id IS NULL THEN ms.map_name ELSE {stat_map_key_sql()} END
        ORDER BY times_played DESC
    """,
        (event_id,),
    ).fetchall()
    map_stats = [
        dict(row, avg_kd=_KnownZeroRatio(0) if row["avg_kd"] == 0 else row["avg_kd"])
        for row in map_stats
    ]

    # 队伍数据：只算已结束的比赛，临时组队、报名队伍也算
    team_rankings = _event_team_rankings(matches)

    team_count = _event_team_count(conn, event_id) or event["total_teams"]
    conn.close()
    return render_template(
        _event_stats_environment(current_app.jinja_env).get_template(
            "public/events/event_stats.html"
        ),
        event=event,
        rankings=rankings,
        map_stats=map_stats,
        team_rankings=team_rankings,
        team_count=team_count,
    )
