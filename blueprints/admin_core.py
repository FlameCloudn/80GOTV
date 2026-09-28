"""Admin login, dashboard and editor image upload."""

import uuid

from flask import flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from blueprints.admin import admin_bp
from config import BASE_DIR
from models import get_db
from services.player_service import record_player_nickname
from services.steam_playtime_service import attach_latest_playtime
from utils.db_helpers import save_news_image
from utils.rate_limiter import rate_limit
from utils.web_helpers import admin_required as login_required
from utils.web_helpers import csrf_required


@admin_bp.route("/upload/image", methods=["POST"])
@csrf_required
@login_required
def upload_image():
    if "image" not in request.files:
        return jsonify({"error": "没有文件"}), 400
    file = request.files["image"]
    if not file or not file.filename:
        return jsonify({"error": "空文件"}), 400
    url, error = save_news_image(file, BASE_DIR)
    if error:
        return jsonify({"error": error}), 400
    return jsonify({"url": url})


# ---- 登录/登出 ----
@admin_bp.route("/login", methods=["GET", "POST"])
@csrf_required
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        # 两道桶：账号维度 5 次 / 5 分钟，另加一道与用户名无关的 IP 桶 20 次 / 5 分钟。
        # 只有账号维度时，攻击者只要换用户名就能各试 5 次；管理员账号是唯一的，
        # 一旦被猜中即可下载整库备份，因此再加一道全球 IP 桶兜底。
        if not rate_limit(f"admin_login:{username.lower()}", 5, 300, by_ip=True) or not rate_limit(
            "admin_login_ip", 20, 300, by_ip=True
        ):
            flash("登录尝试次数过多，请 5 分钟后再试", "error")
            return render_template("admin/login.html"), 429
        conn = get_db()
        admin = conn.execute("SELECT * FROM admins WHERE username=?", (username,)).fetchone()
        if admin and check_password_hash(admin["password_hash"], password):
            user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            conn.close()
            session.clear()
            session.permanent = True
            session["csrf_token"] = uuid.uuid4().hex
            if user and (user["approval_status"] or "approved") == "approved":
                session["user_id"] = user["id"]
                session["user_username"] = user["username"]
                if user["is_bashizhong_student"] is None or (
                    user["is_bashizhong_student"] == 1
                    and not str(user["group_username"] or "").strip()
                ):
                    session["profile_completion_required"] = True
            session["admin_id"] = admin["id"]
            session["admin_username"] = admin["username"]
            flash("登录成功", "success")
            return redirect(url_for("admin.admin_dashboard"))
        else:
            conn.close()
            flash("用户名或密码错误", "error")
    return render_template("admin/login.html")


@admin_bp.route("/logout")
def admin_logout():
    """管理员登出。

    整体清空 session：原先只 pop admin_id/admin_username，前台 user_id 会留下来，
    在共享电脑上管理员以为已经完全登出，实际前台身份仍然有效。
    """
    session.clear()
    flash("已退出登录", "success")
    return redirect(url_for("admin.admin_login"))


@admin_bp.route("/")
@admin_bp.route("")
@login_required
def admin_dashboard():
    conn = get_db()
    stats = {
        "teams": conn.execute("SELECT COUNT(*) as cnt FROM teams").fetchone()["cnt"],
        "players": conn.execute("SELECT COUNT(*) as cnt FROM players").fetchone()["cnt"],
        "events": conn.execute("SELECT COUNT(*) as cnt FROM events").fetchone()["cnt"],
        "matches": conn.execute("SELECT COUNT(*) as cnt FROM matches").fetchone()["cnt"],
        "news": conn.execute("SELECT COUNT(*) as cnt FROM news").fetchone()["cnt"],
        "pending_users": conn.execute(
            """SELECT COUNT(*) as cnt
               FROM users
               WHERE approval_status='pending'
                 AND (is_placeholder=0 OR email_verified_at IS NOT NULL)"""
        ).fetchone()["cnt"],
    }
    conn.close()
    return render_template("admin/dashboard.html", stats=stats)


@admin_bp.route("/registrations")
@login_required
def registration_reviews():
    status = request.args.get("status", "pending")
    if status not in {"pending", "approved", "rejected", "all"}:
        status = "pending"
    conn = get_db()
    if status == "all":
        users = conn.execute(
            """SELECT id, username, group_username, is_bashizhong_student,
                      email, email_verified_at, steam_id64, avatar, approval_status,
                      approval_note, created_at, approved_at
               FROM users
               WHERE is_placeholder=0 OR email_verified_at IS NOT NULL
               ORDER BY created_at DESC"""
        ).fetchall()
    else:
        users = conn.execute(
            """SELECT id, username, group_username, is_bashizhong_student,
                      email, email_verified_at, steam_id64, avatar, approval_status,
                      approval_note, created_at, approved_at
               FROM users
               WHERE approval_status=?
                 AND (is_placeholder=0 OR email_verified_at IS NOT NULL)
               ORDER BY created_at DESC""",
            (status,),
        ).fetchall()
    users = attach_latest_playtime(conn, users, "steam_id64")
    conn.close()
    return render_template("admin/registrations.html", users=users, current_status=status)


@admin_bp.route("/registrations/create", methods=["POST"])
@csrf_required
@login_required
def create_registration():
    flash("创建账号已合并到选手管理，请在同一张表单中添加", "info")
    return redirect(url_for("admin.admin_players_add"))


@admin_bp.route("/registrations/<int:user_id>/<action>", methods=["POST"])
@csrf_required
@login_required
def review_registration(user_id, action):
    if action not in {"approve", "reject"}:
        return "无效操作", 400
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        conn.close()
        flash("申请不存在", "error")
        return redirect(url_for("admin.registration_reviews"))

    if action == "approve":
        conn.execute(
            """UPDATE users
               SET approval_status='approved', approval_note=NULL,
                   approved_at=CURRENT_TIMESTAMP, approved_by=?
               WHERE id=?""",
            (session["admin_id"], user_id),
        )
        if user["steam_id64"]:
            player = conn.execute(
                "SELECT id FROM players WHERE steam_id=?", (user["steam_id64"],)
            ).fetchone()
            if not player:
                conn.execute(
                    """INSERT INTO players(
                           nickname, group_username_override,
                           is_bashizhong_student, steam_id, avatar
                       ) VALUES(?,?,?,?,?)""",
                    (
                        user["username"],
                        (user["group_username"] if user["is_bashizhong_student"] == 1 else None),
                        user["is_bashizhong_student"],
                        user["steam_id64"],
                        user["avatar"],
                    ),
                )
                player_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                record_player_nickname(conn, player_id, user["username"], "admin_approval")
            else:
                conn.execute(
                    """UPDATE players
                       SET is_bashizhong_student=?,
                           group_username_override=CASE
                               WHEN ?=1 THEN ?
                               ELSE group_username_override
                           END
                       WHERE id=?""",
                    (
                        user["is_bashizhong_student"],
                        user["is_bashizhong_student"],
                        user["group_username"],
                        player["id"],
                    ),
                )
        message = f"已通过 {user['username']} 的申请"
    else:
        note = request.form.get("approval_note", "").strip()[:300]
        conn.execute(
            """UPDATE users
               SET approval_status='rejected', approval_note=?,
                   approved_at=NULL, approved_by=?
               WHERE id=?""",
            (note or "管理员未通过该申请", session["admin_id"], user_id),
        )
        message = f"已拒绝 {user['username']} 的申请"
    conn.commit()
    conn.close()
    flash(message, "success")
    return redirect(url_for("admin.registration_reviews"))
