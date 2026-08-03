"""Admin team and player management pages."""

import json
import re

from flask import flash, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from blueprints.admin import admin_bp
from config import BASE_DIR
from models import get_db
from services.player_service import record_player_nickname, update_player_nickname
from services.steam_playtime_service import (
    attach_latest_playtime,
    refresh_player_playtimes,
)
from utils.db_helpers import save_uploaded_avatar
from utils.web_helpers import admin_required as login_required
from utils.web_helpers import csrf_required


def _duplicate_value(conn, table, column, value, exclude_id=None):
    sql = f"SELECT id FROM {table} WHERE LOWER(TRIM({column}))=LOWER(TRIM(?))"
    params = [value]
    if exclude_id is not None:
        sql += " AND id<>?"
        params.append(exclude_id)
    return conn.execute(sql, params).fetchone()


def _team_form_values():
    return (
        request.form.get("name", "").strip(),
        request.form.get("short_name", "").strip(),
        request.form.get("description", "").strip(),
    )


def _team_validation_error(conn, name, short_name, exclude_id=None):
    if not name or not short_name:
        return "队名和简称不能为空"
    if _duplicate_value(conn, "teams", "name", name, exclude_id):
        return "已存在同名队伍"
    if _duplicate_value(conn, "teams", "short_name", short_name, exclude_id):
        return "已存在相同简称的队伍"
    return None


def _player_form_values():
    school_value = request.form.get("is_bashizhong_student", "").strip()
    return {
        "nickname": request.form.get("nickname", "").strip(),
        "group_username": request.form.get("group_username", "").strip(),
        "team_id": request.form.get("team_id", "").strip(),
        "steam_id": request.form.get("steam_id", "").strip(),
        "is_bashizhong_student": (int(school_value) if school_value in {"0", "1"} else None),
        "create_account": request.form.get("create_account") == "1",
        "account_email": request.form.get("account_email", "").strip().lower(),
        "password": request.form.get("password", ""),
        "password2": request.form.get("password2", ""),
    }


def _player_validation_error(conn, values, exclude_id=None):
    if not values["nickname"]:
        return "选手昵称不能为空"
    if _duplicate_value(conn, "players", "nickname", values["nickname"], exclude_id):
        return "已存在同名选手"
    if len(values["group_username"]) > 40 or any(
        char in values["group_username"] for char in ("\r", "\n", "\x00")
    ):
        return "群内昵称不能超过 40 个字符，也不能包含换行"
    if values["is_bashizhong_student"] not in {0, 1}:
        return "请选择选手是否是或曾经是八十中学生"
    if values["is_bashizhong_student"] == 1 and not values["group_username"]:
        return "八十中选手必须填写群内昵称"
    if values["steam_id"] and not re.fullmatch(r"\d{17}", values["steam_id"]):
        return "Steam ID 必须为 17 位数字"
    if values["steam_id"] and _duplicate_value(
        conn, "players", "steam_id", values["steam_id"], exclude_id
    ):
        return "该 Steam ID 已绑定其他选手"
    if values["team_id"]:
        if not values["team_id"].isdigit():
            return "所选队伍无效"
        if not conn.execute("SELECT id FROM teams WHERE id=?", (values["team_id"],)).fetchone():
            return "所选队伍不存在"
    if values["create_account"]:
        if not values["steam_id"]:
            return "同时创建登录账号时必须填写 Steam ID"
        if not 8 <= len(values["password"]) <= 128:
            return "初始密码必须为 8-128 个字符"
        if values["password"] != values["password2"]:
            return "两次输入的初始密码不一致"
        if values["account_email"] and (
            len(values["account_email"]) > 254
            or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", values["account_email"])
        ):
            return "邮箱格式不正确"
        steam_account = conn.execute(
            "SELECT id, is_placeholder FROM users WHERE steam_id64=?",
            (values["steam_id"],),
        ).fetchone()
        claimable_id = (
            steam_account["id"] if steam_account and steam_account["is_placeholder"] else None
        )
        if steam_account and claimable_id is None:
            return "该 Steam ID 已关联其他网站账号"
        duplicate_user = conn.execute(
            "SELECT id FROM users WHERE LOWER(username)=LOWER(?)",
            (values["nickname"],),
        ).fetchone()
        if duplicate_user and duplicate_user["id"] != claimable_id:
            return "该昵称已被网站账号使用"
        if values["account_email"]:
            duplicate_email = conn.execute(
                "SELECT id FROM users WHERE LOWER(email)=LOWER(?)",
                (values["account_email"],),
            ).fetchone()
            if duplicate_email and duplicate_email["id"] != claimable_id:
                return "该邮箱已被其他网站账号使用"
    return None


def _render_player_form(conn, player, status=200):
    teams = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
    if player is not None:
        player = dict(player)
        if "managed_group_username" in player:
            player["group_username"] = player["managed_group_username"]
        if "managed_is_bashizhong_student" in player:
            player["is_bashizhong_student"] = player["managed_is_bashizhong_student"]
    conn.close()
    return render_template("admin/players_form.html", player=player, teams=teams), status


def _sync_linked_user_profile(conn, steam_id, group_username, school_status):
    if not steam_id:
        return
    conn.execute(
        """
        UPDATE users
        SET is_bashizhong_student=?,
            group_username=CASE WHEN ?=1 THEN ? ELSE group_username END
        WHERE steam_id64=? AND COALESCE(is_placeholder, 0)=0
        """,
        (
            school_status,
            school_status,
            group_username or None,
            steam_id,
        ),
    )


def _player_used_in_roster(conn, player_id):
    for match in conn.execute(
        "SELECT team1_players, team2_players FROM matches "
        "WHERE team1_players IS NOT NULL OR team2_players IS NOT NULL"
    ).fetchall():
        for key in ("team1_players", "team2_players"):
            try:
                player_ids = json.loads(match[key]) if match[key] else []
            except (TypeError, json.JSONDecodeError):
                continue
            if any(str(value) == str(player_id) for value in player_ids):
                return True
    return False


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
        name, short_name, description = _team_form_values()
        conn = get_db()
        error = _team_validation_error(conn, name, short_name)
        if error:
            conn.close()
            flash(error, "error")
            return render_template(
                "admin/teams_form.html",
                team={"name": name, "short_name": short_name, "description": description},
            ), 400
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
    team = conn.execute("SELECT * FROM teams WHERE id=?", (team_id,)).fetchone()
    if not team:
        conn.close()
        return "队伍不存在", 404
    if request.method == "POST":
        name, short_name, description = _team_form_values()
        error = _team_validation_error(conn, name, short_name, team_id)
        if error:
            conn.close()
            flash(error, "error")
            return render_template(
                "admin/teams_form.html",
                team={
                    "id": team_id,
                    "name": name,
                    "short_name": short_name,
                    "description": description,
                },
            ), 400
        conn.execute(
            "UPDATE teams SET name=?, short_name=?, description=? WHERE id=?",
            (name, short_name, description, team_id),
        )
        conn.commit()
        conn.close()
        flash("队伍更新成功", "success")
        return redirect(url_for("admin.admin_teams"))
    conn.close()
    return render_template("admin/teams_form.html", team=team)


@admin_bp.route("/teams/delete/<int:team_id>", methods=["POST"])
@csrf_required
@login_required
def admin_teams_delete(team_id):
    conn = get_db()
    team = conn.execute("SELECT id FROM teams WHERE id=?", (team_id,)).fetchone()
    if not team:
        conn.close()
        flash("队伍不存在", "error")
        return redirect(url_for("admin.admin_teams"))
    references = conn.execute(
        """SELECT
             (SELECT COUNT(*) FROM players WHERE team_id=?) +
             (SELECT COUNT(*) FROM matches WHERE team1_id=? OR team2_id=?) +
             (SELECT COUNT(*) FROM event_champions WHERE team_id=?) +
             (SELECT COUNT(*) FROM match_stats WHERE team_id=?)""",
        (team_id, team_id, team_id, team_id, team_id),
    ).fetchone()[0]
    if references:
        conn.close()
        flash("该队伍仍被选手、比赛或赛事数据使用，不能直接删除", "error")
        return redirect(url_for("admin.admin_teams"))
    try:
        conn.execute("DELETE FROM teams WHERE id=?", (team_id,))
        conn.commit()
        flash("队伍删除成功", "success")
    except Exception as e:
        conn.rollback()
        flash(f"删除失败：{str(e)}", "error")
    finally:
        conn.close()
    return redirect(url_for("admin.admin_teams"))


# ---- 选手管理 ----
@admin_bp.route("/players")
@login_required
def admin_players():
    conn = get_db()
    players = conn.execute("""
        SELECT p.*, t.name AS team_name, u.id AS user_id,
               u.username AS account_username,
               COALESCE(u.is_bashizhong_student, p.is_bashizhong_student)
                   AS managed_is_bashizhong_student,
               COALESCE(
                   NULLIF(TRIM(u.group_username), ''),
                   NULLIF(TRIM(p.group_username_override), ''),
                   ''
               ) AS managed_group_username
        FROM players p
        LEFT JOIN teams t ON p.team_id=t.id
        LEFT JOIN users u ON u.id=(
            SELECT u2.id
            FROM users u2
            WHERE u2.steam_id64=p.steam_id AND COALESCE(u2.is_placeholder, 0)=0
            ORDER BY u2.id DESC
            LIMIT 1
        )
        ORDER BY p.created_at DESC
    """).fetchall()
    players = attach_latest_playtime(conn, players, "steam_id")
    conn.close()
    return render_template("admin/players.html", players=players)


@admin_bp.route("/players/refresh-playtime", methods=["POST"])
@csrf_required
@login_required
def admin_players_refresh_playtime():
    conn = get_db()
    players = conn.execute(
        """
        SELECT id, steam_id, cs2_playtime_minutes, playtime_status,
               playtime_checked_at
        FROM players
        WHERE TRIM(COALESCE(steam_id, '')) <> ''
        ORDER BY id
        """
    ).fetchall()
    if not players:
        conn.close()
        flash("暂无填写 Steam ID 的选手可更新", "error")
        return redirect(url_for("admin.admin_players"))

    result = refresh_player_playtimes(conn, players, force=True)
    if not result["configured"]:
        conn.close()
        flash("Steam 接口尚未配置，暂时无法获取游戏时长", "error")
        return redirect(url_for("admin.admin_players"))

    refreshed_players = conn.execute(
        """
        SELECT steam_id, cs2_playtime_minutes, playtime_status,
               playtime_checked_at
        FROM players
        WHERE TRIM(COALESCE(steam_id, '')) <> ''
        """
    ).fetchall()
    for player in refreshed_players:
        conn.execute(
            """
            UPDATE event_individual_registrations
            SET cs2_playtime_minutes=?, playtime_status=?, playtime_checked_at=?
            WHERE steam_id=?
            """,
            (
                player["cs2_playtime_minutes"],
                player["playtime_status"],
                player["playtime_checked_at"],
                player["steam_id"],
            ),
        )

    conn.commit()
    conn.close()
    message = f"已更新 {result['refreshed']} 位选手的 CS2 时长"
    if result["unavailable"]:
        message += "；部分 Steam 资料不可见或读取失败"
    flash(message, "success")
    return redirect(url_for("admin.admin_players"))


def _linked_account_for_player(conn, player_id):
    return conn.execute(
        """
        SELECT p.id AS player_id, p.nickname, p.steam_id,
               u.id AS user_id, u.username
        FROM players p
        LEFT JOIN users u ON u.id=(
            SELECT u2.id
            FROM users u2
            WHERE u2.steam_id64=p.steam_id AND COALESCE(u2.is_placeholder, 0)=0
            ORDER BY u2.id DESC
            LIMIT 1
        )
        WHERE p.id=?
        """,
        (player_id,),
    ).fetchone()


@admin_bp.route("/players/password/<int:player_id>", methods=["GET", "POST"])
@csrf_required
@login_required
def admin_player_password(player_id):
    conn = get_db()
    account = _linked_account_for_player(conn, player_id)
    if not account:
        conn.close()
        flash("选手不存在", "error")
        return redirect(url_for("admin.admin_players"))
    if not account["user_id"]:
        conn.close()
        flash("该选手尚未关联可登录的网站账号，无法修改密码", "error")
        return redirect(url_for("admin.admin_players"))

    if request.method == "POST":
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")
        if len(password) < 8:
            conn.close()
            flash("新密码至少 8 位", "error")
            return render_template("admin/player_password.html", account=account), 400
        if len(password) > 128:
            conn.close()
            flash("新密码不能超过 128 位", "error")
            return render_template("admin/player_password.html", account=account), 400
        if password != password2:
            conn.close()
            flash("两次输入的密码不一致", "error")
            return render_template("admin/player_password.html", account=account), 400

        conn.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (generate_password_hash(password), account["user_id"]),
        )
        conn.commit()
        conn.close()
        flash(
            f"已修改选手【{account['nickname']}】的网站账号密码",
            "success",
        )
        return redirect(url_for("admin.admin_players"))

    conn.close()
    return render_template("admin/player_password.html", account=account)


@admin_bp.route("/players/add", methods=["GET", "POST"])
@csrf_required
@login_required
def admin_players_add():
    conn = get_db()
    if request.method == "POST":
        values = _player_form_values()
        error = _player_validation_error(conn, values)
        if error:
            flash(error, "error")
            return _render_player_form(conn, values, 400)
        avatar = request.files.get("avatar")
        avatar_filename, _ = save_uploaded_avatar(avatar, BASE_DIR)
        if avatar and avatar.filename and not avatar_filename:
            flash("头像文件无效，请上传 jpg、png 或 gif 图片", "error")
            return _render_player_form(conn, values, 400)
        cursor = conn.execute(
            """INSERT INTO players(
                   nickname, group_username_override, is_bashizhong_student,
                   team_id, steam_id, avatar
               ) VALUES(?,?,?,?,?,?)""",
            (
                values["nickname"],
                values["group_username"] or None,
                values["is_bashizhong_student"],
                values["team_id"] or None,
                values["steam_id"] or None,
                avatar_filename,
            ),
        )
        player_id = cursor.lastrowid
        if values["create_account"]:
            existing_placeholder = conn.execute(
                "SELECT id FROM users WHERE steam_id64=? AND is_placeholder=1",
                (values["steam_id"],),
            ).fetchone()
            account_values = (
                values["nickname"],
                generate_password_hash(values["password"]),
                values["account_email"] or None,
                values["steam_id"],
                (values["group_username"] if values["is_bashizhong_student"] == 1 else None),
                values["is_bashizhong_student"],
                avatar_filename,
            )
            if existing_placeholder:
                conn.execute(
                    """UPDATE users
                       SET username=?, password_hash=?, email=?, steam_id64=?,
                           group_username=?, is_bashizhong_student=?,
                           avatar=COALESCE(?, avatar), is_placeholder=0,
                           approval_status='approved', approval_note=NULL,
                           approved_at=CURRENT_TIMESTAMP
                       WHERE id=?""",
                    (*account_values, existing_placeholder["id"]),
                )
            else:
                conn.execute(
                    """INSERT INTO users(
                           username, password_hash, email, steam_id64,
                           group_username, is_bashizhong_student, avatar,
                           is_placeholder, approval_status, approved_at
                       ) VALUES(?,?,?,?,?,?,?,0,'approved',CURRENT_TIMESTAMP)""",
                    account_values,
                )
        _sync_linked_user_profile(
            conn,
            values["steam_id"],
            values["group_username"],
            values["is_bashizhong_student"],
        )
        record_player_nickname(conn, player_id, values["nickname"], "website")
        conn.commit()
        conn.close()
        flash(
            "选手和登录账号添加成功" if values["create_account"] else "选手添加成功",
            "success",
        )
        return redirect(url_for("admin.admin_players"))
    return _render_player_form(conn, None)


@admin_bp.route("/players/edit/<int:player_id>", methods=["GET", "POST"])
@csrf_required
@login_required
def admin_players_edit(player_id):
    conn = get_db()
    player = conn.execute(
        """
        SELECT p.*,
               COALESCE(u.is_bashizhong_student, p.is_bashizhong_student)
                   AS managed_is_bashizhong_student,
               COALESCE(
                   NULLIF(TRIM(u.group_username), ''),
                   NULLIF(TRIM(p.group_username_override), ''),
                   ''
               ) AS managed_group_username
        FROM players p
        LEFT JOIN users u ON u.id=(
            SELECT u2.id
            FROM users u2
            WHERE u2.steam_id64=p.steam_id AND COALESCE(u2.is_placeholder, 0)=0
            ORDER BY u2.id DESC
            LIMIT 1
        )
        WHERE p.id=?
        """,
        (player_id,),
    ).fetchone()
    if not player:
        conn.close()
        return "选手不存在", 404
    if request.method == "POST":
        values = _player_form_values()
        error = _player_validation_error(conn, values, player_id)
        if error:
            flash(error, "error")
            values["id"] = player_id
            values["avatar"] = player["avatar"]
            return _render_player_form(conn, values, 400)
        avatar = request.files.get("avatar")
        avatar_filename, _ = save_uploaded_avatar(avatar, BASE_DIR)
        if avatar and avatar.filename and not avatar_filename:
            flash("头像文件无效，请上传 jpg、png 或 gif 图片", "error")
            values["id"] = player_id
            values["avatar"] = player["avatar"]
            return _render_player_form(conn, values, 400)
        update_player_nickname(conn, player_id, values["nickname"], "website")
        if avatar_filename:
            conn.execute(
                """UPDATE players
                   SET group_username_override=?, is_bashizhong_student=?,
                       team_id=?, steam_id=?, avatar=?
                   WHERE id=?""",
                (
                    values["group_username"] or None,
                    values["is_bashizhong_student"],
                    values["team_id"] or None,
                    values["steam_id"] or None,
                    avatar_filename,
                    player_id,
                ),
            )
        else:
            conn.execute(
                """UPDATE players
                   SET group_username_override=?, is_bashizhong_student=?,
                       team_id=?, steam_id=?
                   WHERE id=?""",
                (
                    values["group_username"] or None,
                    values["is_bashizhong_student"],
                    values["team_id"] or None,
                    values["steam_id"] or None,
                    player_id,
                ),
            )
        _sync_linked_user_profile(
            conn,
            values["steam_id"],
            values["group_username"],
            values["is_bashizhong_student"],
        )
        conn.commit()
        conn.close()
        flash("选手更新成功", "success")
        return redirect(url_for("admin.admin_players"))
    return _render_player_form(conn, player)


@admin_bp.route("/players/delete/<int:player_id>", methods=["POST"])
@csrf_required
@login_required
def admin_players_delete(player_id):
    conn = get_db()
    try:
        player = conn.execute(
            "SELECT id, steam_id FROM players WHERE id=?", (player_id,)
        ).fetchone()
        if not player:
            flash("选手不存在", "error")
            return redirect(url_for("admin.admin_players"))
        direct_references = conn.execute(
            """SELECT
                 (SELECT COUNT(*) FROM match_stats WHERE player_id=?) +
                 (SELECT COUNT(*) FROM player_medals WHERE player_id=?)""",
            (player_id, player_id),
        ).fetchone()[0]
        linked_user = bool(
            player["steam_id"]
            and conn.execute(
                "SELECT id FROM users WHERE steam_id64=? LIMIT 1", (player["steam_id"],)
            ).fetchone()
        )
        if direct_references or linked_user or _player_used_in_roster(conn, player_id):
            flash("该选手仍被账号、比赛或荣誉数据使用，不能直接删除", "error")
            return redirect(url_for("admin.admin_players"))
        conn.execute("DELETE FROM player_nickname_history WHERE player_id=?", (player_id,))
        conn.execute("DELETE FROM players WHERE id=?", (player_id,))
        conn.commit()
        flash("选手删除成功", "success")
    except Exception as e:
        conn.rollback()
        flash(f"删除失败：{str(e)}", "error")
    finally:
        conn.close()
    return redirect(url_for("admin.admin_players"))
