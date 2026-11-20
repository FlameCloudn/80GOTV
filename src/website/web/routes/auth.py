"""用户登录、注册和登出。"""

import hmac
import logging
import re
import time
from contextlib import closing

from flask import flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from src.website.domains.directory.player_service import update_player_nickname
from src.website.domains.identity import accounts
from src.website.domains.identity.email_challenges import normalize_email
from src.website.runtime.database import get_db
from src.website.runtime.rate_limiter import rate_limit
from src.website.runtime.storage import site_paths
from src.website.runtime.uploads import save_uploaded_avatar
from src.website.web.access import csrf_required
from src.website.web.localization import t as ui_message
from src.website.web.routes.account_profile import _parse_school_status, _validate_group_username
from src.website.web.routes.captcha import _check_captcha, _generate_captcha
from src.website.web.routes.email_verification import (
    _consume_verified_registration_email,
    _get_verified_registration_email,
)
from src.website.web.routes.session_navigation import (
    _login_destination,
    _safe_next_target,
    _start_login_session,
)
from src.website.web.routes.steam_login import _get_verified_steam_id
from src.website.web.routing import site_routes

logger = logging.getLogger("80gotv")


@site_routes.route("/auth/csrf-token")
def current_csrf_token():
    """供长时间打开的登录/注册页刷新当前会话的安全令牌。"""
    response = jsonify({"success": True, "csrf_token": session["csrf_token"]})
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


@site_routes.route("/login", methods=["GET", "POST"])
@csrf_required
def user_login():
    """用户登录"""
    next_target = _safe_next_target()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        captcha_input = request.form.get("captcha", "").strip()

        if not rate_limit(f"user_login:{username.lower()}", 5, 300, by_ip=True):
            flash(ui_message("flash.auth.too_many_login_attempts_try_again"), "error")
            _generate_captcha()
            return render_template("public/account/login.html", next_target=next_target)

        with closing(get_db()) as conn:
            admin = conn.execute("SELECT * FROM admins WHERE username=?", (username,)).fetchone()
            if admin:
                if not rate_limit("admin_login_ip", 20, 300, by_ip=True):
                    flash(ui_message("flash.auth.too_many_login_attempts_try_again"), "error")
                    _generate_captcha()
                    return render_template(
                        "public/account/login.html", next_target=next_target
                    ), 429
                # 只有密码已验证的管理员可跳过验证码，不能只检查用户名。
                if check_password_hash(admin["password_hash"], password):
                    user = conn.execute(
                        "SELECT * FROM users WHERE username=?", (username,)
                    ).fetchone()
                    if user and accounts.approval_status(user) != "approved":
                        user = None
                    _start_login_session(user=user, admin=admin)
                    flash(ui_message("flash.auth.logged_in"), "success")
                    return redirect(_login_destination(next_target))

            if not _check_captcha(captcha_input):
                flash(ui_message("flash.auth.wrong_captcha"), "error")
                _generate_captcha()
                return render_template("public/account/login.html", next_target=next_target)

            user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            if user and check_password_hash(user["password_hash"], password):
                status = accounts.approval_status(user)
                if status != "approved":
                    message = {
                        "pending": "账号正在等待管理员审核，审核通过后才能登录",
                        "rejected": "账号申请未通过，请联系管理员",
                    }.get(status, "账号当前不可登录，请联系管理员")
                    flash(message, "error")
                    _generate_captcha()
                    return render_template("public/account/login.html", next_target=next_target)
                _start_login_session(user=user)
                flash(ui_message("flash.auth.logged_in"), "success")
                return redirect(_login_destination(next_target))

        flash(ui_message("flash.auth.wrong_username_or_password"), "error")
        _generate_captcha()
    else:
        _generate_captcha()

    return render_template("public/account/login.html", next_target=next_target)


@site_routes.route("/register", methods=["GET", "POST"])
@csrf_required
def user_register():
    """仅接受 Steam 选手申请，申请通过后台审核后才能登录。"""
    verified_steam_id = _get_verified_steam_id("register")
    verified_email = _get_verified_registration_email()

    def _render_register(reset_timer=False):
        if reset_timer:
            session["register_form_started_at"] = time.time()
        return render_template(
            "public/account/login.html",
            tab="register",
            steam_verified_id=verified_steam_id,
            verified_email=verified_email,
            registration_email=verified_email or session.get("register_email", ""),
        )

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        school_status = _parse_school_status(request.form.get("is_bashizhong_student"))
        group_username = ""
        group_username_error = ""
        if school_status == 1:
            group_username, group_username_error = _validate_group_username(
                request.form.get("group_username", "")
            )
        email = normalize_email(request.form.get("email", ""))
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")
        steam_id64 = verified_steam_id
        captcha_input = request.form.get("captcha", "").strip()

        if request.form.get("website", "").strip():
            flash(ui_message("flash.auth.the_application_did_not_pass_the"), "error")
            return _render_register()

        started_at = float(session.get("register_form_started_at", 0) or 0)
        if not started_at or time.time() - started_at < 2:
            flash(ui_message("flash.auth.too_fast_wait_two_seconds_and"), "error")
            return _render_register()

        if not rate_limit("register_hour", 5, 3600, by_ip=True) or not rate_limit(
            "register_day", 20, 86400, by_ip=True
        ):
            flash(ui_message("flash.auth.too_many_sign_up_attempts_please"), "error")
            _generate_captcha()
            return _render_register()

        if not _check_captcha(captcha_input):
            flash(ui_message("flash.auth.wrong_captcha"), "error")
            _generate_captcha()
            return _render_register()

        if not username or not password:
            flash(ui_message("flash.auth.username_and_password_are_required"), "error")
            _generate_captcha()
            return _render_register()

        if school_status is None:
            flash(ui_message("flash.auth.choose_whether_you_are_or_were"), "error")
            _generate_captcha()
            return _render_register()

        if group_username_error:
            flash(group_username_error, "error")
            _generate_captcha()
            return _render_register()

        if not email:
            flash(ui_message("flash.auth.enter_a_valid_email_address"), "error")
            _generate_captcha()
            return _render_register()

        if not verified_email or not hmac.compare_digest(email, verified_email):
            flash(ui_message("flash.auth.verify_your_email_code_first"), "error")
            _generate_captcha()
            return _render_register()

        if len(username) < 2 or len(username) > 20:
            flash(ui_message("flash.auth.usernames_must_be_2_20_characters"), "error")
            _generate_captcha()
            return _render_register()

        if not re.fullmatch(r"[A-Za-z0-9_\-\u4e00-\u9fff]+", username):
            flash(ui_message("flash.auth.usernames_may_only_contain_chinese_characters"), "error")
            _generate_captcha()
            return _render_register()

        if password != password2:
            flash(ui_message("flash.auth.the_passwords_do_not_match"), "error")
            _generate_captcha()
            return _render_register()

        if (
            len(password) < 10
            or not re.search(r"[A-Za-z]", password)
            or not re.search(r"\d", password)
        ):
            flash(ui_message("flash.auth.passwords_need_at_least_10_characters"), "error")
            _generate_captcha()
            return _render_register()

        if not steam_id64:
            flash(ui_message("flash.auth.verify_with_steam_before_submitting"), "error")
            _generate_captcha()
            return _render_register()

        conn = get_db()
        existing_steam = accounts.steam_account(conn, steam_id64)

        # 检查用户名唯一
        existing_user = conn.execute(
            "SELECT id FROM users WHERE LOWER(username)=LOWER(?)", (username,)
        ).fetchone()
        existing_email = conn.execute(
            "SELECT id FROM users WHERE LOWER(email)=LOWER(?)", (email,)
        ).fetchone()
        claimable_steam = (
            existing_steam
            if existing_steam is not None and existing_steam["is_placeholder"]
            else None
        )
        if existing_user and (
            claimable_steam is None or existing_user["id"] != claimable_steam["id"]
        ):
            conn.close()
            flash(ui_message("flash.auth.this_username_is_taken"), "error")
            _generate_captcha()
            return _render_register()

        if existing_email and (
            claimable_steam is None or existing_email["id"] != claimable_steam["id"]
        ):
            conn.close()
            flash(ui_message("flash.auth.this_email_is_already_registered"), "error")
            _generate_captcha()
            return _render_register()

        if existing_steam and claimable_steam is None:
            conn.close()
            flash(ui_message("flash.auth.this_steam_account_is_already_registered"), "error")
            _generate_captcha()
            return _render_register()

        existing_nick = conn.execute(
            "SELECT steam_id FROM players WHERE nickname=?", (username,)
        ).fetchone()
        if existing_nick and str(existing_nick["steam_id"] or "") != steam_id64:
            conn.close()
            flash(ui_message("flash.auth.a_player_already_uses_this_nickname"), "error")
            _generate_captcha()
            return _render_register()

        # 处理头像上传
        avatar_filename = None
        avatar_file = request.files.get("avatar")
        if avatar_file and avatar_file.filename:
            avatar_filename, _ = save_uploaded_avatar(avatar_file, site_paths().root)
            if not avatar_filename:
                conn.close()
                flash(ui_message("flash.auth.invalid_avatar_upload_a_png_jpg"), "error")
                _generate_captcha()
                return _render_register()

        password_hash = generate_password_hash(password)
        if not _consume_verified_registration_email(conn, email):
            conn.rollback()
            conn.close()
            verified_email = ""
            session.pop("registration_email_verified", None)
            flash(ui_message("flash.auth.your_email_verification_is_no_longer"), "error")
            return _render_register()
        try:
            submitted_user_id, claimed = accounts.submit_verified_registration(
                conn,
                steam_id=steam_id64,
                username=username,
                password_hash=password_hash,
                email=email,
                school_status=school_status,
                group_username=group_username,
                avatar=avatar_filename,
            )
        except accounts.SteamAccountInUse:
            conn.rollback()
            conn.close()
            flash(ui_message("flash.auth.this_steam_account_is_already_registered"), "error")
            _generate_captcha()
            return _render_register()
        if claimed:
            claimed_players = conn.execute(
                "SELECT id FROM players WHERE steam_id=?", (steam_id64,)
            ).fetchall()
            for claimed_player in claimed_players:
                update_player_nickname(conn, claimed_player["id"], username, "website")
            conn.execute(
                "UPDATE players SET avatar=COALESCE(?, avatar) WHERE steam_id=?",
                (avatar_filename, steam_id64),
            )
        conn.commit()
        logger.info(
            "Registration application submitted: user_id=%s placeholder_claim=%s",
            submitted_user_id,
            claimed,
        )
        conn.close()
        session.pop("steam_verified", None)
        session.pop("registration_email_verified", None)
        session.pop("register_email", None)
        session.pop("register_email_last_sent", None)

        flash(ui_message("flash.auth.application_submitted_you_can_log_in"), "success")
        return redirect(url_for("user_login"))

    _generate_captcha()
    return _render_register(reset_timer=True)


@site_routes.route("/logout")
def user_logout():
    """前台登出：退出当前浏览器里的全部前台/管理员身份。

    这里必须整体清空 session。原先只 pop 固定的 6 个键，导致 steam_verified
    这类"找回密码专用"的短期凭证会残留——在同一台电脑上登出后，其他人仍能
    在有效期内直接改掉该 Steam 账号的密码。下一个请求会重新生成 CSRF 令牌。
    """
    session.clear()
    flash(ui_message("flash.auth.logged_out"), "success")
    return redirect(url_for("index"))
