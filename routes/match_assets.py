"""Downloadable demos, generated posters and match reports."""

import json
import os

from flask import (
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
)

from models import get_db
from services.live_log_service import load_match_timeline, uses_run_timeline
from services.match_service import match_stat_belongs_to_side, supplement_temp_teams
from services.performance_service import stat_average_sql
from site_core.host import is_managed_event
from utils.demo_naming import build_demo_download_name
from utils.helpers import map_display_name, normalize_map_key, resolve_match_ref, row_get
from utils.stats_storage import stats_for_slot, stats_relation
from web_app import DEMOS_DIR, app


def _redirect_to_current_match_url(endpoint, requested_slug, match):
    canonical_slug = match["slug"] or str(match["id"])
    if str(requested_slug) == str(canonical_slug):
        return None
    target = url_for(endpoint, slug=canonical_slug)
    if request.query_string:
        target += "?" + request.query_string.decode("latin-1")
    return redirect(target, code=301)


@app.route("/matches/<slug>/download-demo")
def download_demo(slug):
    from contextlib import closing

    from flask import current_app

    from site_core.host import HostError, is_managed_match
    from site_core.matches.demo_storage import default_download, private_root
    from web_app import logger

    if not session.get("user_id") and not session.get("admin_id"):
        return redirect(url_for("user_login", next=request.full_path.rstrip("?")))
    match_ref = resolve_match_ref(slug)
    if not match_ref:
        return "比赛不存在", 404
    canonical_redirect = _redirect_to_current_match_url("download_demo", slug, match_ref)
    if canonical_redirect:
        return canonical_redirect
    match_id = match_ref["id"]
    slot = request.args.get("slot", 0, type=int)
    with closing(get_db()) as conn:
        if is_managed_match(conn, match_id):
            if not 0 <= slot < 5:
                return "找不到这张地图的 Demo", 404
            try:
                root = private_root(
                    current_app.instance_path,
                    current_app.static_folder,
                    current_app.config.get("HOST_DEMO_ROOT"),
                )
                path, demo_id, map_name = default_download(conn, root, match_id, slot)
                download_name = build_demo_download_name(f"demo-{demo_id}.dem", slot, map_name)
                return send_file(path, as_attachment=True, download_name=download_name)
            except HostError as exc:
                if exc.status >= 500:
                    logger.warning(
                        "托管 Demo 下载失败：比赛 %s，槽 %s（%s）", match_id, slot, exc.message
                    )
                return exc.message, exc.status
            except (FileNotFoundError, NotADirectoryError):
                return "服务器找不到完整的 Demo 原件", 404
            except OSError as exc:
                logger.warning(
                    "托管 Demo 下载失败：比赛 %s，槽 %s（%s）", match_id, slot, type(exc).__name__
                )
                return "服务器暂时无法读取 Demo 原件", 503
        match = conn.execute(
            "SELECT demo_file, map1, map2, map3, map4, map5 FROM matches WHERE id=?",
            (match_id,),
        ).fetchone()

    demo_file = row_get(match, "demo_file", "") if match else ""
    if not demo_file:
        return "这场比赛没有可下载的 Demo", 404

    try:
        demo_list = json.loads(demo_file)
    except (json.JSONDecodeError, TypeError):
        return "Demo 文件记录损坏", 500

    if slot < 0 or slot >= len(demo_list):
        return "找不到这张地图的 Demo", 404

    demo_item = demo_list[slot]
    demo_filename = demo_item.get("filename") if isinstance(demo_item, dict) else demo_item
    if not isinstance(demo_filename, str) or os.path.basename(demo_filename) != demo_filename:
        return "Demo 文件名无效", 400
    demo_path = os.path.join(DEMOS_DIR, demo_filename)

    if not os.path.isfile(demo_path):
        return "服务器上找不到 Demo 文件", 404

    map_name = row_get(match, f"map{slot + 1}", "")
    download_name = build_demo_download_name(demo_filename, slot, map_name)
    return send_from_directory(
        DEMOS_DIR, demo_filename, as_attachment=True, download_name=download_name
    )


@app.route("/matches/<slug>/poster")
def match_poster(slug):
    match_ref = resolve_match_ref(slug)
    if not match_ref:
        return "比赛不存在", 404
    canonical_redirect = _redirect_to_current_match_url("match_poster", slug, match_ref)
    if canonical_redirect:
        return canonical_redirect
    match_id = match_ref["id"]
    from utils.poster import generate_match_poster

    conn = get_db()
    match = conn.execute(
        """
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s,
               e.name AS event_name
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

    match = supplement_temp_teams(match, conn)
    valid_side = (
        "CASE WHEN LOWER(TRIM(ms.match_team_side)) IN ('t1','t2') "
        "THEN LOWER(TRIM(ms.match_team_side)) END"
    )
    player_ratings = conn.execute(
        f"""
        SELECT ms.team_id, p.nickname,
               CASE WHEN COUNT(DISTINCT {valid_side})=1 THEN MIN({valid_side}) END AS match_team_side,
               {stat_average_sql("rating")} AS rating
        FROM {stats_relation(conn)} ms
        JOIN players p ON p.id=ms.player_id
        WHERE ms.match_id=?
          AND COALESCE(ms.data_status, 'final') <> 'superseded'
        GROUP BY ms.team_id, p.id
        ORDER BY ms.team_id, rating DESC
    """,
        (match_id,),
    ).fetchall()
    conn.close()

    raw_maps = [
        (match["map1"], match["map1_t1"], match["map1_t2"], True),
        (match["map2"], match["map2_t1"], match["map2_t2"], True),
        (match["map3"], match["map3_t1"], match["map3_t2"], bool(match["has_map3"])),
        (match["map4"], match["map4_t1"], match["map4_t2"], bool(row_get(match, "has_map4", 1))),
        (match["map5"], match["map5_t1"], match["map5_t2"], bool(row_get(match, "has_map5", 1))),
    ]
    bo = (match["bo_format"] or "BO3").upper()
    if bo == "BO5":
        max_maps = 5
    elif bo == "BO3":
        max_maps = 3
    else:
        max_maps = 1

    map_scores = []
    for idx, (mn, t1, t2, active) in enumerate(raw_maps):
        if idx >= max_maps:
            break
        if idx < 2 and not mn:
            continue
        map_scores.append(
            {
                "name": mn or "TBA",
                "t1": t1,
                "t2": t2,
                "played": bool(mn and active and t1 is not None and t2 is not None),
            }
        )

    buf = generate_match_poster(match, map_scores, [dict(row) for row in player_ratings])
    return send_file(buf, mimetype="image/png")


@app.route("/matches/<int:match_id>/report")
def match_report(match_id):
    """显示可以复制和分享的完整比赛战报。"""
    conn = get_db()
    match = conn.execute(
        """
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s,
               t1.logo AS t1_logo, t2.logo AS t2_logo,
               e.name AS event_name
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
    match = supplement_temp_teams(match, conn)

    source = stats_relation(conn)
    managed = is_managed_event(conn, match["event_id"])

    def report_metric(field, aggregate):
        # 往届战报要求每张图都有该项；托管场按已采纳该项的样本计算。
        if managed:
            return aggregate
        return f"CASE WHEN COUNT(ms.{field})=COUNT(*) THEN {aggregate} END"

    overall_rows = [
        dict(row)
        for row in conn.execute(
            f"""
        WITH sided_stats AS (
            SELECT ms.*,
                   CASE WHEN LOWER(TRIM(COALESCE(ms.match_team_side, ''))) IN ('t1', 't2')
                        THEN LOWER(TRIM(ms.match_team_side))
                        WHEN ms.team_id=? THEN 't1'
                        WHEN ms.team_id=? THEN 't2' END AS report_side
            FROM {source} ms
            WHERE ms.match_id=?
              AND COALESCE(ms.data_status, 'final') <> 'superseded'
        )
        SELECT ms.player_id, ms.report_side AS match_team_side, p.nickname, p.avatar,
               {report_metric("kills", "SUM(ms.kills)")} AS kills,
               {report_metric("deaths", "SUM(ms.deaths)")} AS deaths,
               {report_metric("adr", stat_average_sql("adr"))} AS adr,
               {report_metric("kast", stat_average_sql("kast"))} AS kast,
               {report_metric("rating", stat_average_sql("rating"))} AS rating
        FROM sided_stats ms
        JOIN players p ON p.id=ms.player_id
        WHERE ms.report_side IS NOT NULL
        GROUP BY ms.report_side, ms.player_id
        ORDER BY rating DESC
    """,
            (match.get("team1_id"), match.get("team2_id"), match_id),
        ).fetchall()
    ]
    map_rows = [
        dict(row)
        for row in conn.execute(
            f"""
        SELECT ms.player_id, ms.team_id, ms.match_team_side, ms.map_name,
               ms.scheduled_map_id, ms.legacy_slot, p.nickname,
               ms.kills, ms.deaths, ms.adr, ms.kast, ms.rating
        FROM {source} ms
        JOIN players p ON p.id=ms.player_id
        WHERE ms.match_id=?
          AND COALESCE(ms.data_status, 'final') <> 'superseded'
        ORDER BY ms.map_name, ms.rating DESC
    """,
            (match_id,),
        ).fetchall()
    ]
    timeline = load_match_timeline(conn, match_id)
    if timeline and managed and uses_run_timeline(conn, match_id):
        run_plans = {
            row["map_run_id"]: row
            for row in conn.execute(
                """SELECT r.map_run_id,s.scheduled_map_id,s.legacy_slot,s.map_name
                   FROM scheduled_maps s JOIN map_runs r USING(scheduled_map_id)
                   WHERE s.match_id=?""",
                (match_id,),
            )
        }
        names = [normalize_map_key(match[f"map{i}"]) for i in range(1, 6)]
        for event in timeline:
            plan = run_plans[event["map_run_id"]]
            slot = plan["legacy_slot"]
            event.update(scheduled_map_id=plan["scheduled_map_id"], map_slot=slot)
            if names.count(normalize_map_key(plan["map_name"])) > 1:
                event["map_name"] = f"图{slot} · {map_display_name(plan['map_name'])}"
    conn.close()

    mvp = None
    if overall_rows and (not managed or overall_rows[0]["rating"] is not None):
        mvp = dict(overall_rows[0])
    if mvp:
        for key in ("adr", "kast", "rating"):
            value = mvp.get(key)
            mvp[key] = round(value, 2) if value is not None else None

    team1_id = match.get("team1_id")
    team2_id = match.get("team2_id")

    def team_summary(expected_side, team_id):
        rows = [
            row for row in overall_rows if match_stat_belongs_to_side(row, expected_side, team_id)
        ]

        def sum_known(key):
            values = [row[key] for row in rows if row.get(key) is not None]
            return sum(values) if values and (managed or len(values) == len(rows)) else None

        def average_known(key, digits):
            values = [row[key] for row in rows if row.get(key) is not None]
            if not values or (not managed and len(values) != len(rows)):
                return None
            return round(sum(values) / len(values), digits)

        return {
            "kills": sum_known("kills"),
            "deaths": sum_known("deaths"),
            "adr": average_known("adr", 1),
            "rating": average_known("rating", 2),
        }

    t1 = team_summary("t1", team1_id)
    t2 = team_summary("t2", team2_id)
    team_stats = {
        "t1_k": t1["kills"],
        "t2_k": t2["kills"],
        "t1_d": t1["deaths"],
        "t2_d": t2["deaths"],
        "t1_adr": t1["adr"],
        "t2_adr": t2["adr"],
        "t1_rating": t1["rating"],
        "t2_rating": t2["rating"],
    }

    bo = (match.get("bo_format") or "BO1").upper()
    max_maps = 5 if bo == "BO5" else (3 if bo == "BO3" else 1)
    map_reports = []
    for index in range(1, max_maps + 1):
        map_name = match.get(f"map{index}")
        if not map_name:
            continue
        score1 = match.get(f"map{index}_t1")
        score2 = match.get(f"map{index}_t2")
        current_rows = stats_for_slot(map_rows, index, map_name)
        t1_rows = [row for row in current_rows if match_stat_belongs_to_side(row, "t1", team1_id)]
        t2_rows = [row for row in current_rows if match_stat_belongs_to_side(row, "t2", team2_id)]
        map_reports.append(
            {
                "idx": index,
                "name": map_name,
                "t1": score1,
                "t2": score2,
                "played": bool(
                    current_rows
                    or (score1 is not None and score1 != 0)
                    or (score2 is not None and score2 != 0)
                ),
                "t1_winner": score1 is not None and score2 is not None and score1 > score2,
                "t2_winner": score1 is not None and score2 is not None and score2 > score1,
                "t1_best": max(
                    t1_rows,
                    key=lambda row: (row.get("rating") is not None, row.get("rating") or 0),
                )
                if t1_rows
                else None,
                "t2_best": max(
                    t2_rows,
                    key=lambda row: (row.get("rating") is not None, row.get("rating") or 0),
                )
                if t2_rows
                else None,
            }
        )

    return render_template(
        "match_report.html",
        match=match,
        mvp=mvp,
        map_reports=map_reports,
        team_stats=team_stats,
        timeline=timeline,
    )
