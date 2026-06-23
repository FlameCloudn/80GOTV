"""Admin event and bracket management pages."""

import json

from flask import flash, redirect, render_template, request, url_for

from blueprints.admin import admin_bp
from models import get_db
from services.match_service import add_effective_event_status
from utils.demo_naming import normalize_event_short_name
from utils.web_helpers import admin_required as login_required
from utils.web_helpers import csrf_required


def _event_form_values(include_status=False):
    short_name = normalize_event_short_name(request.form.get("short_name"), "NEW")
    return (
        request.form.get("name"),
        short_name,
        request.form.get("description"),
        request.form.get("start_date"),
        request.form.get("end_date"),
        request.form.get("format"),
        request.form.get("status", "upcoming") if include_status else "upcoming",
        request.form.get("stream_url", "").strip() or None,
        1 if request.form.get("registration_open") == "1" else 0,
    )


def _save_event_awards(conn, event_id):
    """赛后荣誉只在编辑已有赛事时保存。"""
    champion_team_id = request.form.get("champion_team_id", "")
    conn.execute("DELETE FROM event_champions WHERE event_id=?", (event_id,))
    if champion_team_id.isdigit():
        conn.execute(
            "INSERT INTO event_champions(event_id, team_id) VALUES(?,?)",
            (event_id, int(champion_team_id)),
        )

    mvp_player_id = request.form.get("mvp_player_id", "")
    conn.execute("DELETE FROM player_medals WHERE event_id=? AND type='MVP'", (event_id,))
    if mvp_player_id.isdigit():
        conn.execute(
            "INSERT INTO player_medals(player_id, type, event_id) VALUES(?,?,?)",
            (int(mvp_player_id), "MVP", event_id),
        )

    conn.execute("DELETE FROM player_medals WHERE event_id=? AND type='EVP'", (event_id,))
    for rank, player_id in enumerate(request.form.getlist("evp_player_ids"), start=1):
        if player_id.isdigit():
            conn.execute(
                "INSERT INTO player_medals(player_id, type, event_id, evp_rank) VALUES(?,?,?,?)",
                (int(player_id), "EVP", event_id, rank),
            )


def _event_award_options(conn, event_id):
    champion_team = conn.execute(
        "SELECT t.* FROM event_champions ec JOIN teams t ON ec.team_id=t.id WHERE ec.event_id=?",
        (event_id,),
    ).fetchone()
    teams = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
    players = conn.execute("""SELECT p.*, t.name AS team_name
        FROM players p LEFT JOIN teams t ON p.team_id=t.id ORDER BY p.nickname""").fetchall()
    mvp_player = conn.execute(
        """SELECT p.* FROM player_medals pm JOIN players p ON pm.player_id=p.id
        WHERE pm.event_id=? AND pm.type='MVP' LIMIT 1""",
        (event_id,),
    ).fetchone()
    evp_players = conn.execute(
        """SELECT p.*, pm.evp_rank FROM player_medals pm JOIN players p ON pm.player_id=p.id
        WHERE pm.event_id=? AND pm.type='EVP' ORDER BY pm.evp_rank ASC""",
        (event_id,),
    ).fetchall()
    return teams, players, champion_team, mvp_player, evp_players


@admin_bp.route("/events")
@login_required
def admin_events():
    conn = get_db()
    events = conn.execute("SELECT * FROM events ORDER BY start_date DESC").fetchall()
    events = [add_effective_event_status(e) for e in events]
    conn.close()
    return render_template("admin/events.html", events=events)


@admin_bp.route("/events/add", methods=["GET", "POST"])
@csrf_required
@login_required
def admin_events_add():
    if request.method == "POST":
        conn = get_db()
        conn.execute(
            """INSERT INTO events(name, short_name, description, start_date, end_date, format, status, stream_url, registration_open)
                        VALUES(?,?,?,?,?,?,?,?,?)""",
            _event_form_values(),
        )
        conn.commit()
        conn.close()
        flash("赛事添加成功", "success")
        return redirect(url_for("admin.admin_events"))
    return render_template("admin/events_form.html", event=None)


@admin_bp.route("/events/edit/<int:event_id>", methods=["GET", "POST"])
@csrf_required
@login_required
def admin_events_edit(event_id):
    conn = get_db()
    if request.method == "POST":
        conn.execute(
            """UPDATE events SET name=?, short_name=?, description=?, start_date=?, end_date=?, format=?, status=?, stream_url=?, registration_open=?
                        WHERE id=?""",
            _event_form_values(include_status=True) + (event_id,),
        )
        _save_event_awards(conn, event_id)
        conn.commit()
        conn.close()
        flash("赛事更新成功", "success")
        return redirect(url_for("admin.admin_events"))
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not event:
        conn.close()
        return "赛事不存在", 404
    teams, players, champion_team, mvp_player, evp_players = _event_award_options(conn, event_id)
    conn.close()
    return render_template(
        "admin/events_form.html",
        event=event,
        teams=teams,
        champion_team=champion_team,
        mvp_player=mvp_player,
        evp_players=evp_players,
        all_players=players,
    )


@admin_bp.route("/events/delete/<int:event_id>", methods=["POST"])
@csrf_required
@login_required
def admin_events_delete(event_id):
    try:
        conn = get_db()
        conn.execute("DELETE FROM events WHERE id=?", (event_id,))
        conn.commit()
        conn.close()
        flash("赛事删除成功", "success")
    except Exception as e:
        flash(f"删除失败：{str(e)}", "error")
    return redirect(url_for("admin.admin_events"))


@admin_bp.route("/events/<int:event_id>/bracket", methods=["GET", "POST"])
@csrf_required
@login_required
def admin_event_bracket(event_id):
    conn = get_db()
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not event:
        conn.close()
        return "赛事不存在", 404
    if request.method == "POST":
        bracket_data = request.form.get("bracket_data", "").strip()
        if bracket_data:
            try:
                json.loads(bracket_data)
            except json.JSONDecodeError as e:
                flash(f"JSON 格式错误：{str(e)}", "error")
                conn.close()
                return render_template(
                    "admin/event_bracket.html", event=event, bracket_data=bracket_data
                )
        conn.execute(
            "UPDATE events SET bracket_data=? WHERE id=?", (bracket_data or None, event_id)
        )
        conn.commit()
        conn.close()
        flash("对阵图保存成功", "success")
        return redirect(url_for("admin.admin_events"))
    matches = conn.execute(
        """SELECT m.id, m.match_time, t1.name AS t1_name, t2.name AS t2_name
        FROM matches m LEFT JOIN teams t1 ON m.team1_id=t1.id LEFT JOIN teams t2 ON m.team2_id=t2.id
        WHERE m.event_id=? ORDER BY m.match_time""",
        (event_id,),
    ).fetchall()
    conn.close()
    return render_template(
        "admin/event_bracket.html",
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
    conn.execute(
        "UPDATE events SET bracket_data=? WHERE id=?",
        (json.dumps(data, ensure_ascii=False), event_id),
    )
    conn.commit()
    conn.close()
    return {"success": True, "message": "对阵图保存成功"}
