"""Admin login, dashboard and editor image upload."""

import uuid

from flask import flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from blueprints.admin import admin_bp
from config import BASE_DIR
from models import get_db
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
        if not rate_limit(f"admin_login:{username.lower()}", 5, 300, by_ip=True):
            flash("登录尝试次数过多，请 5 分钟后再试", "error")
            return render_template("admin/login.html"), 429
        conn = get_db()
        admin = conn.execute("SELECT * FROM admins WHERE username=?", (username,)).fetchone()
        if admin and check_password_hash(admin["password_hash"], password):
            user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            conn.close()
            session.clear()
            session["csrf_token"] = uuid.uuid4().hex
            if user:
                session["user_id"] = user["id"]
                session["user_username"] = user["username"]
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
    session.pop("admin_id", None)
    session.pop("admin_username", None)
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
    }
    conn.close()
    return render_template("admin/dashboard.html", stats=stats)
