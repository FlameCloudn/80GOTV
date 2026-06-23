"""Admin team and player management pages."""

from flask import flash, redirect, render_template, request, url_for

from blueprints.admin import admin_bp
from config import BASE_DIR
from models import get_db
from services.player_service import record_player_nickname, update_player_nickname
from utils.db_helpers import save_uploaded_avatar
from utils.web_helpers import admin_required as login_required
from utils.web_helpers import csrf_required


@admin_bp.route("/teams")
@login_required
def admin_teams():
    conn = get_db()
    teams = conn.execute("SELECT * FROM teams ORDER BY created_at DESC").fetchall()
    conn.close()
    return render_template("admin/teams.html", teams=teams)


@admin_bp.route("/teams/add", methods=["GET", "POST"])
@csrf_required
@login_required
def admin_teams_add():
    if request.method == "POST":
        name = request.form.get("name")
        short_name = request.form.get("short_name")
        description = request.form.get("description")
        conn = get_db()
        conn.execute(
            "INSERT INTO teams(name, short_name, description) VALUES(?,?,?)",
            (name, short_name, description),
        )
        conn.commit()
        conn.close()
        flash("队伍添加成功", "success")
        return redirect(url_for("admin.admin_teams"))
    return render_template("admin/teams_form.html", team=None)


@admin_bp.route("/teams/edit/<int:team_id>", methods=["GET", "POST"])
@csrf_required
@login_required
def admin_teams_edit(team_id):
    conn = get_db()
    if request.method == "POST":
        name = request.form.get("name")
        short_name = request.form.get("short_name")
        description = request.form.get("description")
        conn.execute(
            "UPDATE teams SET name=?, short_name=?, description=? WHERE id=?",
            (name, short_name, description, team_id),
        )
        conn.commit()
        conn.close()
        flash("队伍更新成功", "success")
        return redirect(url_for("admin.admin_teams"))
    team = conn.execute("SELECT * FROM teams WHERE id=?", (team_id,)).fetchone()
    conn.close()
    return render_template("admin/teams_form.html", team=team)


@admin_bp.route("/teams/delete/<int:team_id>", methods=["POST"])
@csrf_required
@login_required
def admin_teams_delete(team_id):
    try:
        conn = get_db()
        conn.execute("DELETE FROM teams WHERE id=?", (team_id,))
        conn.commit()
        conn.close()
        flash("队伍删除成功", "success")
    except Exception as e:
        flash(f"删除失败：{str(e)}", "error")
    return redirect(url_for("admin.admin_teams"))


# ---- 选手管理 ----
@admin_bp.route("/players")
@login_required
def admin_players():
    conn = get_db()
    players = conn.execute("""
        SELECT p.*, t.name AS team_name FROM players p
        LEFT JOIN teams t ON p.team_id=t.id ORDER BY p.created_at DESC
    """).fetchall()
    conn.close()
    return render_template("admin/players.html", players=players)


@admin_bp.route("/players/add", methods=["GET", "POST"])
@csrf_required
@login_required
def admin_players_add():
    conn = get_db()
    if request.method == "POST":
        nickname = request.form.get("nickname")
        real_name = request.form.get("real_name")
        team_id = request.form.get("team_id")
        steam_id = request.form.get("steam_id")
        avatar_filename, _ = save_uploaded_avatar(request.files.get("avatar"), BASE_DIR)
        conn.execute(
            "INSERT INTO players(nickname, real_name, team_id, steam_id, avatar) VALUES(?,?,?,?,?)",
            (nickname, real_name, team_id if team_id else None, steam_id, avatar_filename),
        )
        player_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        record_player_nickname(conn, player_id, nickname, "website")
        conn.commit()
        conn.close()
        flash("选手添加成功", "success")
        return redirect(url_for("admin.admin_players"))
    teams = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
    conn.close()
    return render_template("admin/players_form.html", player=None, teams=teams)


@admin_bp.route("/players/edit/<int:player_id>", methods=["GET", "POST"])
@csrf_required
@login_required
def admin_players_edit(player_id):
    conn = get_db()
    if request.method == "POST":
        nickname = request.form.get("nickname")
        real_name = request.form.get("real_name")
        team_id = request.form.get("team_id")
        steam_id = request.form.get("steam_id")
        avatar_filename, _ = save_uploaded_avatar(request.files.get("avatar"), BASE_DIR)
        update_player_nickname(conn, player_id, nickname, "website")
        if avatar_filename:
            conn.execute(
                "UPDATE players SET real_name=?, team_id=?, steam_id=?, avatar=? WHERE id=?",
                (real_name, team_id if team_id else None, steam_id, avatar_filename, player_id),
            )
        else:
            conn.execute(
                "UPDATE players SET real_name=?, team_id=?, steam_id=? WHERE id=?",
                (real_name, team_id if team_id else None, steam_id, player_id),
            )
        conn.commit()
        conn.close()
        flash("选手更新成功", "success")
        return redirect(url_for("admin.admin_players"))
    player = conn.execute("SELECT * FROM players WHERE id=?", (player_id,)).fetchone()
    teams = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
    conn.close()
    return render_template("admin/players_form.html", player=player, teams=teams)


@admin_bp.route("/players/delete/<int:player_id>", methods=["POST"])
@csrf_required
@login_required
def admin_players_delete(player_id):
    try:
        conn = get_db()
        conn.execute("DELETE FROM players WHERE id=?", (player_id,))
        conn.commit()
        conn.close()
        flash("选手删除成功", "success")
    except Exception as e:
        flash(f"删除失败：{str(e)}", "error")
    return redirect(url_for("admin.admin_players"))
