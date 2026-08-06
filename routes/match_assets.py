"""Downloadable demos, generated posters and match reports."""

import json
import os

from flask import render_template, request, send_file, send_from_directory

from models import get_db
from services.live_log_service import load_match_timeline
from services.match_service import supplement_temp_teams
from utils.demo_naming import build_demo_download_name
from utils.helpers import normalize_map_key, resolve_match_slug, row_get
from web_app import DEMOS_DIR, app


@app.route("/matches/<slug>/download-demo")
def download_demo(slug):
    match_id = resolve_match_slug(slug)
    if not match_id:
        return "比赛不存在", 404
    conn = get_db()
    match = conn.execute(
        "SELECT demo_file, map1, map2, map3, map4, map5 FROM matches WHERE id=?",
        (match_id,),
    ).fetchone()
    conn.close()

    demo_file = row_get(match, "demo_file", "") if match else ""
    if not demo_file:
        return "这场比赛没有可下载的 Demo", 404

    try:
        demo_list = json.loads(demo_file)
    except (json.JSONDecodeError, TypeError):
        return "Demo 文件记录损坏", 500

    slot = request.args.get("slot", 0, type=int)
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
    match_id = resolve_match_slug(slug)
    if not match_id:
        return "比赛不存在", 404
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
    player_ratings = conn.execute(
        """
        SELECT ms.team_id, p.nickname, AVG(ms.rating) AS rating
        FROM match_stats ms
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
                "t1": t1 or 0,
                "t2": t2 or 0,
                "played": bool(mn and (t1 or t2)),
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

    overall_rows = [
        dict(row)
        for row in conn.execute(
            """
        SELECT ms.player_id, ms.team_id, p.nickname,
               SUM(ms.kills) AS kills, SUM(ms.deaths) AS deaths,
               AVG(ms.adr) AS adr, AVG(ms.kast) AS kast, AVG(ms.rating) AS rating
        FROM match_stats ms
        JOIN players p ON p.id=ms.player_id
        WHERE ms.match_id=?
          AND COALESCE(ms.data_status, 'final') <> 'superseded'
        GROUP BY ms.team_id, ms.player_id
        ORDER BY rating DESC
    """,
            (match_id,),
        ).fetchall()
    ]
    map_rows = [
        dict(row)
        for row in conn.execute(
            """
        SELECT ms.player_id, ms.team_id, ms.map_name, p.nickname,
               ms.kills, ms.deaths, ms.adr, ms.kast, ms.rating
        FROM match_stats ms
        JOIN players p ON p.id=ms.player_id
        WHERE ms.match_id=?
          AND COALESCE(ms.data_status, 'final') <> 'superseded'
        ORDER BY ms.map_name, ms.rating DESC
    """,
            (match_id,),
        ).fetchall()
    ]
    timeline = load_match_timeline(conn, match_id)
    conn.close()

    mvp = overall_rows[0] if overall_rows else None
    if mvp:
        for key in ("adr", "kast", "rating"):
            mvp[key] = round(mvp.get(key) or 0, 2)

    team1_id = match.get("team1_id")
    team2_id = match.get("team2_id")

    def team_summary(team_id):
        rows = [row for row in overall_rows if row.get("team_id") == team_id]
        count = len(rows)
        return {
            "kills": sum(row.get("kills") or 0 for row in rows),
            "deaths": sum(row.get("deaths") or 0 for row in rows),
            "adr": round(sum(row.get("adr") or 0 for row in rows) / count, 1) if count else 0,
            "rating": round(sum(row.get("rating") or 0 for row in rows) / count, 2) if count else 0,
        }

    t1 = team_summary(team1_id)
    t2 = team_summary(team2_id)
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
        score1 = match.get(f"map{index}_t1") or 0
        score2 = match.get(f"map{index}_t2") or 0
        current_rows = [
            row
            for row in map_rows
            if normalize_map_key(row.get("map_name")) == normalize_map_key(map_name)
        ]
        t1_rows = [row for row in current_rows if row.get("team_id") == team1_id]
        t2_rows = [row for row in current_rows if row.get("team_id") == team2_id]
        map_reports.append(
            {
                "idx": index,
                "name": map_name,
                "t1": score1,
                "t2": score2,
                "played": bool(score1 or score2 or current_rows),
                "t1_winner": score1 > score2,
                "t2_winner": score2 > score1,
                "t1_best": max(t1_rows, key=lambda row: row.get("rating") or 0)
                if t1_rows
                else None,
                "t2_best": max(t2_rows, key=lambda row: row.get("rating") or 0)
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
