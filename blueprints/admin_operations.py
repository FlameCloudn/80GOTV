"""Admin live operations, nickname management, award cards and backups."""

import json
from datetime import datetime

from flask import flash, redirect, render_template, request, send_file, url_for

from blueprints.admin import admin_bp
from config import BASE_DIR
from models import get_db
from services.award_service import build_event_award_poster
from services.backup_service import create_backup_zip
from services.player_service import merge_player_records
from utils.match_utils import get_sql_effective_status
from utils.web_helpers import admin_required as login_required
from utils.web_helpers import csrf_required


@admin_bp.route("/live")
@login_required
def admin_live_status():
    """Show whether GSI, GOTV and scheduled live matches are healthy."""
    conn = get_db()
    receiver_rows = conn.execute("""
        SELECT s.*, m.match_time, t1.name AS team1_name, t2.name AS team2_name
        FROM live_ingest_status s
        LEFT JOIN matches m ON s.match_id=m.id
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        ORDER BY s.source
    """).fetchall()
    match_rows = conn.execute(f"""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               l.live_state, l.updated_at, {get_sql_effective_status()}
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN live_match_data l ON l.match_id=m.id
        WHERE COALESCE(m.status, '') NOT IN ('completed', 'cancelled')
        ORDER BY CASE WHEN m.match_time IS NULL THEN 1 ELSE 0 END, m.match_time
    """).fetchall()
    conn.close()

    matches = []
    for row in match_rows:
        match = dict(row)
        try:
            state = json.loads(match.get("live_state") or "{}")
        except (TypeError, ValueError):
            state = {}
        gsi = state.get("gsi", {}) or {}
        gotv = state.get("gotv", {}) or {}
        a2s = state.get("a2s", {}) or {}
        match["current_map"] = (
            (gsi.get("map", {}) or {}).get("name")
            or gotv.get("map_name")
            or (a2s.get("server", {}) or {}).get("map_name")
            or "-"
        )
        match["live_source"] = "GSI" if gsi else ("GOTV" if gotv else ("A2S" if a2s else "-"))
        matches.append(match)
    return render_template("admin/live_status.html", receivers=receiver_rows, matches=matches)


@admin_bp.route("/nicknames")
@login_required
def admin_nicknames():
    """Review canonical player nicknames and aliases."""
    conn = get_db()
    players = conn.execute("""
        SELECT p.*, t.name AS team_name, COUNT(h.id) AS alias_count
        FROM players p
        LEFT JOIN teams t ON p.team_id=t.id
        LEFT JOIN player_nickname_history h ON h.player_id=p.id
        GROUP BY p.id
        ORDER BY p.nickname COLLATE NOCASE
    """).fetchall()
    aliases = conn.execute("""
        SELECT player_id, nickname, source, created_at
        FROM player_nickname_history
        ORDER BY player_id, created_at DESC, id DESC
    """).fetchall()
    conn.close()
    alias_map = {}
    for alias in aliases:
        alias_map.setdefault(alias["player_id"], []).append(alias)
    return render_template("admin/nicknames.html", players=players, alias_map=alias_map)


@admin_bp.route("/nicknames/merge", methods=["POST"])
@csrf_required
@login_required
def admin_nicknames_merge():
    """Merge a duplicate profile only after an explicit admin action."""
    source_id = request.form.get("source_id", "").strip()
    target_id = request.form.get("target_id", "").strip()
    if not source_id.isdigit() or not target_id.isdigit():
        flash("请选择要合并的两个选手", "error")
        return redirect(url_for("admin.admin_nicknames"))
    conn = get_db()
    try:
        result = merge_player_records(conn, int(source_id), int(target_id))
        conn.commit()
        flash(f"已将重复档案“{result['source']}”合并到“{result['target']}”", "success")
    except Exception as exc:
        conn.rollback()
        flash(f"合并失败：{exc}", "error")
    finally:
        conn.close()
    return redirect(url_for("admin.admin_nicknames"))


@admin_bp.route("/awards/poster")
@login_required
def admin_award_poster():
    """Award-card form and preview."""
    conn = get_db()
    events = conn.execute("SELECT id, name FROM events ORDER BY start_date DESC").fetchall()
    players = conn.execute("""
        SELECT p.id, p.nickname, t.short_name AS team_short
        FROM players p LEFT JOIN teams t ON p.team_id=t.id
        ORDER BY p.nickname COLLATE NOCASE
    """).fetchall()
    conn.close()
    selected_event = request.args.get("event_id", type=int)
    selected_player = request.args.get("player_id", type=int)
    award_type = "EVP" if request.args.get("award_type", "").upper() == "EVP" else "MVP"
    return render_template(
        "admin/award_poster.html",
        events=events,
        players=players,
        selected_event=selected_event,
        selected_player=selected_player,
        award_type=award_type,
    )


@admin_bp.route("/awards/poster.png")
@login_required
def admin_award_poster_image():
    """Generate a shareable MVP / EVP image from saved event stats."""
    event_id = request.args.get("event_id", type=int)
    player_id = request.args.get("player_id", type=int)
    award_type = "EVP" if request.args.get("award_type", "").upper() == "EVP" else "MVP"
    if not event_id or not player_id:
        return "请选择赛事和选手", 400
    conn = get_db()
    buffer = build_event_award_poster(conn, BASE_DIR, event_id, player_id, award_type)
    conn.close()
    if not buffer:
        return "赛事或选手不存在", 404
    filename = f"{award_type.lower()}_{event_id}_{player_id}.png"
    return send_file(buffer, mimetype="image/png", as_attachment=True, download_name=filename)


@admin_bp.route("/backup/download")
@login_required
def admin_backup_download():
    """Download database, avatar, demo and upload files as one ZIP."""
    filename = f"80gotv_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    return send_file(
        create_backup_zip(),
        mimetype="application/zip",
        as_attachment=True,
        download_name=filename,
    )


@admin_bp.route("/feedback")
@login_required
def admin_feedback():
    """查看用户反馈列表"""
    conn = get_db()
    items = conn.execute(
        "SELECT f.*, COALESCE(u.username,'匿名') as username FROM feedback f"
        " LEFT JOIN users u ON f.user_id=u.id ORDER BY f.created_at DESC LIMIT 200"
    ).fetchall()
    conn.close()
    return render_template("admin/feedback.html", items=items)


@admin_bp.route("/feedback/<int:fb_id>/status", methods=["POST"])
@login_required
@csrf_required
def admin_feedback_status(fb_id):
    """更新反馈状态"""
    status = request.form.get("status", "open")
    reply = request.form.get("reply", "").strip()
    conn = get_db()
    conn.execute("UPDATE feedback SET status=?, admin_reply=? WHERE id=?", (status, reply, fb_id))
    conn.commit()
    conn.close()
    flash("已更新", "success")
    return redirect(url_for("admin.admin_feedback"))
