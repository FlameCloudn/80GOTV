"""Manual map statistics editing and the managed statistics handoff."""

from flask import flash, redirect, render_template, request, url_for

from src.website.domains.matches.map_names import normalize_map_key
from src.website.domains.matches.opponents import supplement_temp_teams
from src.website.domains.statistics.manual_stats_service import (
    FORM_FIELDS,
    StatsRevisionConflict,
    manual_map_revision,
    save_manual_map_stats,
    stats_editor_players,
)
from src.website.domains.statistics.performance_service import refresh_player_performance
from src.website.runtime.database import get_db
from src.website.runtime.host import HostError, is_managed_match
from src.website.web.access import admin_required as login_required
from src.website.web.access import csrf_required
from src.website.web.admin.admin import admin_bp
from src.website.web.localization import t as ui_message


@admin_bp.route("/matches/<int:match_id>/stats", methods=["GET", "POST"])
@csrf_required
@login_required
def admin_match_stats(match_id):
    conn = get_db()
    if is_managed_match(conn, match_id):
        conn.close()
        if request.method == "POST":
            if request.is_json:
                from src.website.web.admin.match_operations import managed_operation

                return managed_operation(match_id, "stats")
            return "请在比赛运营中选择实际局、选手和统计版本，旧表单不能覆盖整场统计。", 409
        return redirect(url_for("admin.managed_match_operate", match_id=match_id) + "#stats")
    if request.method == "POST":
        # 取得写锁后再读取状态、阵容和统计，避免保存期间读到旧状态。
        conn.execute("BEGIN IMMEDIATE")
    match = conn.execute(
        """SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
        e.name AS event_name, e.short_name AS event_short_name
        FROM matches m LEFT JOIN teams t1 ON m.team1_id=t1.id LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id WHERE m.id=?""",
        (match_id,),
    ).fetchone()
    if not match:
        conn.close()
        return "比赛不存在", 404
    match = supplement_temp_teams(match, conn)

    team1_players = stats_editor_players(conn, match, 1)
    team2_players = stats_editor_players(conn, match, 2)
    sides = {1: team1_players, 2: team2_players}

    stats_by_map = {}
    for row in conn.execute(
        """SELECT * FROM match_stats
           WHERE match_id=? AND COALESCE(data_status, 'final') <> 'superseded'""",
        (match_id,),
    ):
        if key := normalize_map_key(row["map_name"]):
            stats_by_map.setdefault(key, []).append(row)
    total_played = (match["team1_score"] or 0) + (match["team2_score"] or 0)
    bo = match["bo_format"] or "BO3"
    bo_max = {"BO1": 1, "BO3": 3, "BO5": 5}.get(bo, 3)
    maps = []
    for slot in range(1, bo_max + 1):
        mn = match[f"map{slot}"]
        rounds = (match[f"map{slot}_t1"] or 0) + (match[f"map{slot}_t2"] or 0)
        if total_played > 0:
            is_active = slot <= total_played or rounds > 0
        else:
            is_active = slot <= 2 or match.get(f"has_map{slot}", 1)
        if not is_active:
            continue
        key = normalize_map_key(mn)
        existing_map = stats_by_map.get(key, [])
        map_stats = {s["player_id"]: s for s in existing_map}
        maps.append(
            {
                "name": mn,
                "disabled": not mn,
                "has_data": len(map_stats) > 0,
                "stats": map_stats,
                "index": slot - 1,
                "key": key,
                "rounds": rounds,
                "revision": manual_map_revision(match, mn, sides, existing_map),
            }
        )
    if not maps:
        maps.append({"name": None, "disabled": True, "has_data": False, "stats": {}, "index": 0})
    active_tab = next((i for i, m in enumerate(maps) if not m["disabled"]), 0)
    readonly = match["status"] == "completed"
    response_status = 200

    if request.method == "POST":
        if match["status"] == "completed":
            flash(ui_message("flash.match_statistics.demo_stats_cannot_be_changed_after"), "error")
            conn.close()
            return redirect(url_for("admin.admin_match_stats", match_id=match_id))
        key = normalize_map_key(request.form.get("map_name", ""))
        selected = next((m for m in maps if not m["disabled"] and m["key"] == key), None)
        try:
            if selected is None:
                raise ValueError("请选择本场已有地图")
            if request.form.get("stats_revision") != selected["revision"]:
                raise StatsRevisionConflict(
                    "该地图的统计、比分或阵容已更新，请刷新页面核对后再保存"
                )
            affected_player_ids = save_manual_map_stats(
                conn,
                match,
                selected["name"],
                selected["rounds"],
                sides,
                stats_by_map.get(key, []),
                request.form,
            )
            refresh_player_performance(conn, affected_player_ids)
            conn.commit()
            flash(
                ui_message("flash.match_statistics.value1_stats_saved", value1=selected["name"]),
                "success",
            )
        except Exception as e:
            conn.rollback()
            if isinstance(e, HostError) and e.code == "map_score_unconfirmed":
                reason = ui_message("stats.error.map_score_unconfirmed")
            elif isinstance(e, StatsRevisionConflict):
                reason = ui_message("stats.error.revision_conflict")
            else:
                reason = str(e)
            flash(
                ui_message("flash.match_statistics.stats_save_failed_value1", value1=reason),
                "error",
            )
            response_status = 409 if isinstance(e, StatsRevisionConflict) else 400
            # 只回填本次提交地图的可编辑数字，不能靠浏览器草稿来保住整张表。
            if selected is not None:
                active_tab = maps.index(selected)
                selected["server_rejected"] = True
                # 被拒的旧表单不能拿到新版本号后再次覆盖；刷新后才重新核对。
                selected["revision"] = request.form.get("stats_revision", "")
                for player in team1_players + team2_players:
                    player_id = player["id"]
                    saved = selected["stats"].get(player_id)
                    values = (
                        dict(saved)
                        if saved
                        else {
                            "kills": 0,
                            "deaths": 0,
                            "assists": 0,
                            "adr": 0,
                            "impact": 0,
                            "rating": 1.0,
                            "kast": 70,
                            "headshot_percentage": 50,
                        }
                    )
                    for field, (column, _, _) in FORM_FIELDS.items():
                        field_name = f"{field}_{player_id}"
                        if field_name in request.form:
                            values[column] = request.form[field_name]
                    selected["stats"][player_id] = values
        else:
            conn.close()
            return redirect(url_for("admin.admin_match_stats", match_id=match_id))
    conn.close()
    return render_template(
        "admin/operations/match_stats.html",
        match=match,
        team1_players=team1_players,
        team2_players=team2_players,
        maps=maps,
        active_tab=active_tab,
        readonly=readonly,
    ), response_status
