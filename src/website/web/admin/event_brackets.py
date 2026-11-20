"""Administrative event bracket reads and edits."""

import json

from flask import flash, redirect, render_template, request, url_for

from src.website.domains.matches.bracket_service import build_event_bracket, refresh_event_bracket
from src.website.domains.matches.opponents import supplement_temp_teams
from src.website.runtime.database import get_db
from src.website.runtime.host import is_managed_event
from src.website.web.access import admin_required as login_required
from src.website.web.access import csrf_required
from src.website.web.admin.admin import admin_bp
from src.website.web.localization import t as ui_message


def _event_bracket_matches(conn, event_id):
    matches = conn.execute(
        """SELECT m.*,
                  t1.name AS team1_name, t1.short_name AS t1s,
                  t2.name AS team2_name, t2.short_name AS t2s
        FROM matches m LEFT JOIN teams t1 ON m.team1_id=t1.id LEFT JOIN teams t2 ON m.team2_id=t2.id
        WHERE m.event_id=? AND m.status!='cancelled'
        ORDER BY CASE WHEN m.match_time IS NULL OR m.match_time='' THEN 1 ELSE 0 END,
                 m.match_time, m.id""",
        (event_id,),
    ).fetchall()
    result = []
    for match in matches:
        display = supplement_temp_teams(match, conn)
        # 只返回编辑器原有字段；阵容与报名资料仅用于补全对阵名称。
        item = {
            key: display[key]
            for key in (
                "id",
                "match_time",
                "bo_format",
                "team1_score",
                "team2_score",
                "status",
                "stage",
                "team1_id",
                "team2_id",
            )
        }
        for side in (1, 2):
            item[f"t{side}_name"] = display[f"team{side}_name"]
            item[f"t{side}_short_name"] = display[f"t{side}s"]
        result.append(item)
    return result


@admin_bp.route("/events/<int:event_id>/bracket", methods=["GET", "POST"])
@csrf_required
@login_required
def admin_event_bracket(event_id):
    conn = get_db()
    if request.method == "POST":
        conn.execute("BEGIN IMMEDIATE")
        if is_managed_event(conn, event_id):
            conn.close()
            return "本届尚未接管签表写入，请通过比赛管理安排赛前对阵", 409
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not event:
        conn.close()
        return "赛事不存在", 404
    if request.method == "POST":
        bracket_data = request.form.get("bracket_data", "").strip()
        if bracket_data:
            try:
                parsed = json.loads(bracket_data)
                validated = refresh_event_bracket(conn, event_id, data=parsed)
                bracket_data = json.dumps(validated, ensure_ascii=False)
            except (ValueError, TypeError) as exc:
                conn.rollback()
                flash(ui_message("flash.admin_events.bracket_save_failed_exc", exc=exc), "error")
                matches = _event_bracket_matches(conn, event_id)
                conn.close()
                return render_template(
                    "admin/events/event_bracket.html",
                    event=event,
                    bracket_data=bracket_data,
                    event_matches=[dict(row) for row in matches],
                ), 400
        conn.execute(
            "UPDATE events SET bracket_data=? WHERE id=?", (bracket_data or None, event_id)
        )
        conn.commit()
        conn.close()
        flash(ui_message("flash.admin_events.bracket_saved"), "success")
        return redirect(url_for("admin.admin_events"))
    matches = _event_bracket_matches(conn, event_id)
    if is_managed_event(conn, event_id):
        from src.website.domains.matches.managed_bracket import get_bracket_links

        links = get_bracket_links(conn, event_id)
        entrants = [
            dict(r)
            for r in conn.execute(
                """SELECT ee.event_entrant_id, r.team_name, g.club_id, t.name AS club_name
                   FROM event_entrants ee
                   JOIN event_registration_groups g ON g.registration_id=ee.registration_id
                   JOIN event_registrations r ON r.id=g.registration_id
                   LEFT JOIN teams t ON t.id=g.club_id
                   WHERE ee.event_id=? ORDER BY ee.event_entrant_id""",
                (event_id,),
            ).fetchall()
        ]
        conn.close()
        return render_template(
            "admin/events/event_bracket_managed.html",
            event=event,
            event_matches=[dict(r) for r in matches],
            managed_links=links,
            entrants=entrants,
        )
    conn.close()
    return render_template(
        "admin/events/event_bracket.html",
        event=event,
        bracket_data=event["bracket_data"] or "",
        event_matches=[dict(r) for r in matches],
    )


@admin_bp.route("/events/<int:event_id>/bracket/api/teams")
@login_required
def bracket_api_teams(event_id):
    conn = get_db()
    teams = conn.execute(
        """SELECT DISTINCT t.* FROM teams t
        JOIN matches m ON (t.id=m.team1_id OR t.id=m.team2_id) WHERE m.event_id=?""",
        (event_id,),
    ).fetchall()
    all_teams = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
    conn.close()
    return {"event_teams": [dict(t) for t in teams], "all_teams": [dict(t) for t in all_teams]}


@admin_bp.route("/events/<int:event_id>/bracket/api/save", methods=["POST"])
@csrf_required
@login_required
def bracket_api_save(event_id):
    data = request.get_json(force=True, silent=True)
    if not data:
        return {"success": False, "error": "无效的 JSON"}, 400
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if is_managed_event(conn, event_id):
            return {
                "success": False,
                "error": "本届尚未接管自动签表，请通过比赛管理安排赛前对阵",
            }, 409
        saved = build_event_bracket(conn, event_id, data)
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        return {"success": False, "error": str(exc)}, 400
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {
        "success": True,
        "message": "对阵图与全部比赛已生成",
        "bracket": saved,
    }
