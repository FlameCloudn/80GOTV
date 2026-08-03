"""Admin event and bracket management pages."""

import json
import re

from flask import flash, redirect, render_template, request, url_for

from blueprints.admin import admin_bp
from models import get_db
from services.bracket_service import build_event_bracket
from services.match_service import add_effective_event_status
from utils.demo_naming import normalize_event_short_name
from utils.helpers import (
    ensure_unique_match_slug,
    make_event_slug,
    make_match_slug,
)
from utils.web_helpers import admin_required as login_required
from utils.web_helpers import csrf_required


def _event_form_values(include_status=False):
    raw_short_name = request.form.get("short_name", "").strip()
    short_name = (
        normalize_event_short_name(raw_short_name, "NEW")
        if re.search(r"[A-Za-z0-9]", raw_short_name)
        else ""
    )
    name = request.form.get("name", "").strip()
    raw_slug = request.form.get("slug", "").strip()
    slug_source = raw_slug if re.search(r"[A-Za-z0-9]", raw_slug) else name or short_name
    return (
        name,
        short_name,
        make_event_slug(slug_source),
        request.form.get("description", "").strip(),
        request.form.get("start_date", "").strip(),
        request.form.get("end_date", "").strip(),
        request.form.get("format", "").strip(),
        request.form.get("status", "upcoming") if include_status else "upcoming",
        request.form.get("stream_url", "").strip() or None,
        1 if request.form.get("registration_open") == "1" else 0,
    )


def _event_validation_error(conn, values, exclude_id=None):
    name, short_name, slug, _, start_date, end_date, _, status, _, _ = values
    if not name or not short_name:
        return "赛事名和简称不能为空"
    if not start_date or not end_date:
        return "开始时间和结束时间不能为空"
    if end_date < start_date:
        return "结束时间不能早于开始时间"
    if status not in ("upcoming", "ongoing", "completed"):
        return "赛事状态无效"
    for column, value, message in (
        ("name", name, "已存在同名赛事"),
        ("short_name", short_name, "已存在相同简称的赛事"),
        ("slug", slug, "该网址名称已被其他赛事使用"),
    ):
        sql = f"SELECT id FROM events WHERE LOWER(TRIM({column}))=LOWER(TRIM(?))"
        params = [value]
        if exclude_id is not None:
            sql += " AND id<>?"
            params.append(exclude_id)
        if conn.execute(sql, params).fetchone():
            return message
    alias = conn.execute("SELECT event_id FROM event_slug_aliases WHERE slug=?", (slug,)).fetchone()
    if alias and (exclude_id is None or alias["event_id"] != exclude_id):
        return "该网址名称是其他赛事使用过的旧地址"
    return None


def _event_dict(values, event_id=None):
    keys = (
        "name",
        "short_name",
        "slug",
        "description",
        "start_date",
        "end_date",
        "format",
        "status",
        "stream_url",
        "registration_open",
    )
    result = dict(zip(keys, values))
    if event_id is not None:
        result["id"] = event_id
    return result


def _refresh_event_match_slugs(conn, event_id):
    rows = conn.execute(
        """SELECT m.id, m.slug, m.match_time,
                  COALESCE(t1.short_name, t1.name, 'team1') AS team1_name,
                  COALESCE(t2.short_name, t2.name, 'team2') AS team2_name,
                  COALESCE(e.slug, e.short_name, e.name, 'event') AS event_name
           FROM matches m
           LEFT JOIN teams t1 ON m.team1_id=t1.id
           LEFT JOIN teams t2 ON m.team2_id=t2.id
           LEFT JOIN events e ON m.event_id=e.id
           WHERE m.event_id=? ORDER BY m.id""",
        (event_id,),
    ).fetchall()
    for match in rows:
        base = make_match_slug(
            match["team1_name"],
            match["team2_name"],
            match["match_time"],
            match["event_name"],
        )
        new_slug = ensure_unique_match_slug(conn, match["id"], base)
        if match["slug"] and match["slug"] != new_slug:
            conn.execute(
                "INSERT OR IGNORE INTO match_slug_aliases(slug,match_id) VALUES(?,?)",
                (match["slug"], match["id"]),
            )
        conn.execute(
            "UPDATE matches SET slug=? WHERE id=?",
            (new_slug, match["id"]),
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
    seen_player_ids = set()
    rank = 1
    for player_id in request.form.getlist("evp_player_ids"):
        if player_id.isdigit() and player_id not in seen_player_ids:
            seen_player_ids.add(player_id)
            conn.execute(
                "INSERT INTO player_medals(player_id, type, event_id, evp_rank) VALUES(?,?,?,?)",
                (int(player_id), "EVP", event_id, rank),
            )
            rank += 1


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
        values = _event_form_values()
        error = _event_validation_error(conn, values)
        if error:
            conn.close()
            flash(error, "error")
            return render_template("admin/events_form.html", event=_event_dict(values)), 400
        conn.execute(
            """INSERT INTO events(name, short_name, slug, description, start_date, end_date, format, status, stream_url, registration_open)
                        VALUES(?,?,?,?,?,?,?,?,?,?)""",
            values,
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
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not event:
        conn.close()
        return "赛事不存在", 404
    if request.method == "POST":
        values = _event_form_values(include_status=True)
        error = _event_validation_error(conn, values, event_id)
        if error:
            teams, players, champion_team, mvp_player, evp_players = _event_award_options(
                conn, event_id
            )
            conn.close()
            flash(error, "error")
            return render_template(
                "admin/events_form.html",
                event=_event_dict(values, event_id),
                teams=teams,
                champion_team=champion_team,
                mvp_player=mvp_player,
                evp_players=evp_players,
                all_players=players,
            ), 400
        if event["slug"] and event["slug"] != values[2]:
            conn.execute(
                "INSERT OR IGNORE INTO event_slug_aliases(slug,event_id) VALUES(?,?)",
                (event["slug"], event_id),
            )
        conn.execute(
            """UPDATE events SET name=?, short_name=?, slug=?, description=?, start_date=?, end_date=?, format=?, status=?, stream_url=?, registration_open=?
                        WHERE id=?""",
            values + (event_id,),
        )
        _refresh_event_match_slugs(conn, event_id)
        _save_event_awards(conn, event_id)
        conn.commit()
        conn.close()
        flash("赛事更新成功", "success")
        return redirect(url_for("admin.admin_events"))
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
    conn = get_db()
    try:
        event = conn.execute("SELECT id FROM events WHERE id=?", (event_id,)).fetchone()
        if not event:
            flash("赛事不存在", "error")
            return redirect(url_for("admin.admin_events"))
        references = conn.execute(
            """SELECT
                 (SELECT COUNT(*) FROM matches WHERE event_id=?) +
                 (SELECT COUNT(*) FROM event_registrations WHERE event_id=?) +
                 (SELECT COUNT(*) FROM event_individual_registrations WHERE event_id=?)""",
            (event_id, event_id, event_id),
        ).fetchone()[0]
        if references:
            flash("该赛事仍有比赛或报名数据，不能直接删除", "error")
            return redirect(url_for("admin.admin_events"))
        conn.execute("DELETE FROM event_champions WHERE event_id=?", (event_id,))
        conn.execute("DELETE FROM player_medals WHERE event_id=?", (event_id,))
        conn.execute("DELETE FROM event_slug_aliases WHERE event_id=?", (event_id,))
        conn.execute("DELETE FROM events WHERE id=?", (event_id,))
        conn.commit()
        flash("赛事删除成功", "success")
    except Exception as e:
        conn.rollback()
        flash(f"删除失败：{str(e)}", "error")
    finally:
        conn.close()
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
        """SELECT m.id, m.match_time, m.bo_format, m.team1_score, m.team2_score,
                  m.status, m.stage, m.team1_id, m.team2_id,
                  t1.name AS t1_name, t1.short_name AS t1_short_name,
                  t2.name AS t2_name, t2.short_name AS t2_short_name
        FROM matches m LEFT JOIN teams t1 ON m.team1_id=t1.id LEFT JOIN teams t2 ON m.team2_id=t2.id
        WHERE m.event_id=? AND m.status!='cancelled'
        ORDER BY CASE WHEN m.match_time IS NULL OR m.match_time='' THEN 1 ELSE 0 END,
                 m.match_time, m.id""",
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
    try:
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
