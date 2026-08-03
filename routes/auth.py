"""用户登录、注册和 Steam 身份验证。"""

import hashlib
import hmac
import io
import ipaddress
import os
import re
import secrets
import smtplib
import time
import urllib.parse
import urllib.request
import uuid
from email.message import EmailMessage

from flask import Response, flash, jsonify, redirect, render_template, request, session, url_for
from PIL import Image, ImageDraw, ImageFont
from werkzeug.security import check_password_hash, generate_password_hash

from config import Config
from models import get_db
from services.player_service import update_player_nickname
from utils.db_helpers import save_uploaded_avatar
from utils.rate_limiter import rate_limit
from utils.web_helpers import csrf_required, user_required
from web_app import app, logger

# ============ CAPTCHA ============


CAPTCHA_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CAPTCHA_MAX_AGE = 5 * 60
EMAIL_CODE_MAX_AGE = 10 * 60
EMAIL_VERIFICATION_MAX_AGE = 30 * 60


def _captcha_digest(nonce, answer):
    key = str(app.secret_key or Config.SECRET_KEY).encode("utf-8")
    value = f"{nonce}:{answer.upper()}".encode("utf-8")
    return hmac.new(key, value, hashlib.sha256).hexdigest()


def _generate_captcha():
    """清除旧验证码；图片请求会生成一个新的验证码。"""
    session.pop("captcha_challenge", None)


def _check_captcha(user_input):
    """验证码只能使用一次，且五分钟后自动失效。"""
    challenge = session.pop("captcha_challenge", None) or {}
    if float(challenge.get("expires_at", 0)) < time.time():
        return False
    supplied = str(user_input or "").strip().upper()
    actual = _captcha_digest(challenge.get("nonce", ""), supplied)
    return bool(supplied) and hmac.compare_digest(actual, challenge.get("digest", ""))


def _normalize_email(value):
    email = str(value or "").strip().lower()
    if len(email) > 254 or not re.fullmatch(
        r"[^@\s]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+",
        email,
    ):
        return ""
    return email


def _validate_group_username(value):
    raw_value = str(value or "")
    group_username = raw_value.strip()
    if not group_username:
        return "", "请填写群内用户名"
    if any(character in raw_value for character in ("\r", "\n", "\t")):
        return "", "群内用户名不能包含换行或制表符"
    if len(group_username) > 40:
        return "", "群内用户名最多 40 个字符"
    return group_username, ""


def _parse_school_status(value):
    normalized = str(value or "").strip().lower()
    if normalized in {"1", "yes", "true"}:
        return 1
    if normalized in {"0", "no", "false"}:
        return 0
    return None


def _profile_completion_required(user):
    school_status = user["is_bashizhong_student"]
    if school_status is None:
        return True
    return bool(school_status) and not str(user["group_username"] or "").strip()


def _email_code_digest(nonce, email, code):
    key = str(app.secret_key or Config.SECRET_KEY).encode("utf-8")
    value = f"{nonce}:{email}:{code}".encode("utf-8")
    return hmac.new(key, value, hashlib.sha256).hexdigest()


def _send_registration_email(email, code):
    if not Config.SMTP_USERNAME or not Config.SMTP_PASSWORD:
        raise RuntimeError("SMTP 未配置")
    message = EmailMessage()
    message["Subject"] = "80GOTV 注册验证码"
    message["From"] = f"{Config.SMTP_FROM_NAME} <{Config.SMTP_USERNAME}>"
    message["To"] = email
    message.set_content(
        f"你的 80GOTV 注册验证码是：{code}\n\n验证码 10 分钟内有效。若不是你本人操作，请忽略此邮件。"
    )
    message.add_alternative(
        f"""<!doctype html><html><body style="font-family:Arial,sans-serif;color:#202832">
        <h2 style="margin-bottom:16px">80GOTV 注册验证</h2>
        <p>你的注册验证码是：</p>
        <p style="font-size:30px;font-weight:700;letter-spacing:6px;color:#3f698f">{code}</p>
        <p>验证码 10 分钟内有效。若不是你本人操作，请忽略此邮件。</p>
        </body></html>""",
        subtype="html",
    )
    with smtplib.SMTP_SSL(Config.SMTP_HOST, Config.SMTP_PORT, timeout=15) as smtp:
        smtp.login(Config.SMTP_USERNAME, Config.SMTP_PASSWORD)
        smtp.send_message(message)


def _get_verified_registration_email():
    verified = session.get("registration_email_verified") or {}
    if time.time() - float(verified.get("verified_at", 0)) > EMAIL_VERIFICATION_MAX_AGE:
        session.pop("registration_email_verified", None)
        return ""
    return _normalize_email(verified.get("email", ""))


# ============ 用户路由 ============


@app.route("/auth/csrf-token")
def current_csrf_token():
    """供长时间打开的登录/注册页刷新当前会话的安全令牌。"""
    response = jsonify({"success": True, "csrf_token": session["csrf_token"]})
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


@app.route("/captcha/reload")
def reload_captcha():
    _generate_captcha()
    return "", 204


@app.route("/captcha/image")
def captcha_image():
    code = "".join(secrets.choice(CAPTCHA_CHARS) for _ in range(5))
    nonce = secrets.token_hex(16)
    session["captcha_challenge"] = {
        "nonce": nonce,
        "digest": _captcha_digest(nonce, code),
        "expires_at": time.time() + CAPTCHA_MAX_AGE,
    }

    image = Image.new("RGB", (150, 48), (244, 247, 250))
    draw = ImageDraw.Draw(image)
    for _ in range(5):
        color = tuple(150 + secrets.randbelow(70) for _ in range(3))
        draw.line(
            (
                secrets.randbelow(150),
                secrets.randbelow(48),
                secrets.randbelow(150),
                secrets.randbelow(48),
            ),
            fill=color,
            width=1,
        )
    font_path = os.path.join(app.root_path, "resources", "fonts", "TestTiemposText-Regular.otf")
    angles = (-24, -18, -12, 12, 18, 24)
    colors = (
        (32, 92, 160, 255),
        (155, 48, 66, 255),
        (35, 118, 91, 255),
        (116, 69, 159, 255),
        (177, 92, 28, 255),
        (41, 116, 133, 255),
    )
    for index, char in enumerate(code):
        char_layer = Image.new("RGBA", (40, 48), (0, 0, 0, 0))
        char_draw = ImageDraw.Draw(char_layer)
        font_size = 14 + secrets.randbelow(17)
        try:
            char_font = ImageFont.truetype(font_path, font_size)
        except OSError:
            char_font = ImageFont.load_default()
        bounds = char_draw.textbbox((0, 0), char, font=char_font)
        text_width = bounds[2] - bounds[0]
        text_height = bounds[3] - bounds[1]
        text_x = (40 - text_width) // 2 - bounds[0]
        text_y = (48 - text_height) // 2 - bounds[1] + secrets.randbelow(5) - 2
        char_draw.text(
            (text_x, text_y),
            char,
            font=char_font,
            fill=secrets.choice(colors),
        )
        char_layer = char_layer.rotate(
            secrets.choice(angles),
            resample=Image.Resampling.BICUBIC,
            expand=False,
        )
        image.paste(char_layer, (5 + index * 28, 0), char_layer)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    response = Response(output.getvalue(), mimetype="image/png")
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


@app.route("/auth/email/send-code", methods=["POST"])
@csrf_required
def send_registration_email_code():
    email = _normalize_email(request.form.get("email", ""))
    if not email:
        return jsonify({"success": False, "error": "请输入有效的邮箱地址"}), 400

    last_sent = float(session.get("register_email_last_sent", 0) or 0)
    remaining = 60 - int(time.time() - last_sent)
    if remaining > 0:
        return jsonify({"success": False, "error": f"请等待 {remaining} 秒后再发送"}), 429
    if not rate_limit(f"register_email:{email}", 3, 3600, by_ip=True) or not rate_limit(
        "register_email_ip", 10, 3600, by_ip=True
    ):
        return jsonify({"success": False, "error": "发送次数过多，请一小时后再试"}), 429

    conn = get_db()
    existing = conn.execute("SELECT id FROM users WHERE LOWER(email)=LOWER(?)", (email,)).fetchone()
    conn.close()
    if existing:
        return jsonify({"success": False, "error": "该邮箱已经注册"}), 409

    code = f"{100000 + secrets.randbelow(900000):06d}"
    nonce = secrets.token_hex(16)
    try:
        _send_registration_email(email, code)
    except Exception:
        logger.exception("注册验证码邮件发送失败")
        return jsonify({"success": False, "error": "邮件发送失败，请稍后再试"}), 503

    session["register_email_challenge"] = {
        "email": email,
        "nonce": nonce,
        "digest": _email_code_digest(nonce, email, code),
        "expires_at": time.time() + EMAIL_CODE_MAX_AGE,
        "attempts": 0,
    }
    session["register_email"] = email
    session["register_email_last_sent"] = time.time()
    if _get_verified_registration_email() != email:
        session.pop("registration_email_verified", None)
    return jsonify({"success": True, "message": "验证码已发送，请检查收件箱"})


@app.route("/auth/email/verify-code", methods=["POST"])
@csrf_required
def verify_registration_email_code():
    email = _normalize_email(request.form.get("email", ""))
    code = request.form.get("code", "").strip()
    challenge = session.get("register_email_challenge") or {}
    if not email or not re.fullmatch(r"\d{6}", code):
        return jsonify({"success": False, "error": "请输入邮箱和六位验证码"}), 400
    if float(challenge.get("expires_at", 0)) < time.time():
        session.pop("register_email_challenge", None)
        return jsonify({"success": False, "error": "验证码已过期，请重新发送"}), 400
    if not hmac.compare_digest(email, str(challenge.get("email", ""))):
        return jsonify({"success": False, "error": "邮箱与验证码不匹配"}), 400

    attempts = int(challenge.get("attempts", 0)) + 1
    challenge["attempts"] = attempts
    session["register_email_challenge"] = challenge
    expected = _email_code_digest(challenge.get("nonce", ""), email, code)
    if not hmac.compare_digest(expected, challenge.get("digest", "")):
        if attempts >= 5:
            session.pop("register_email_challenge", None)
            return jsonify({"success": False, "error": "错误次数过多，请重新发送验证码"}), 400
        return jsonify({"success": False, "error": "邮箱验证码错误"}), 400

    session.pop("register_email_challenge", None)
    session["registration_email_verified"] = {"email": email, "verified_at": time.time()}
    session["register_email"] = email
    return jsonify({"success": True, "message": "邮箱验证成功"})


STEAM_OPENID_URL = "https://steamcommunity.com/openid/login"
STEAM_OPENID_NS = "http://specs.openid.net/auth/2.0"
STEAM_OPENID_IDENTIFIER = f"{STEAM_OPENID_NS}/identifier_select"
STEAM_AUTH_MAX_AGE = 10 * 60
STEAM_VERIFY_ATTEMPTS = 4


def _get_verified_steam_id(purpose):
    """返回本次 Steam 验证结果；过期或用途不符时返回空。"""
    verified = session.get("steam_verified") or {}
    if verified.get("purpose") != purpose:
        return ""
    if time.time() - float(verified.get("verified_at", 0)) > STEAM_AUTH_MAX_AGE:
        session.pop("steam_verified", None)
        return ""
    steam_id64 = str(verified.get("steam_id64", ""))
    return steam_id64 if steam_id64.isdigit() and len(steam_id64) == 17 else ""


def _is_local_host(host):
    """判断主机名是否属于本机或局域网。"""
    host = (host or "").lower().rstrip(".")
    if (
        host == "localhost"
        or host.endswith((".localhost", ".local"))
        or ("." not in host and ":" not in host)
    ):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


def _is_local_base_url(value):
    """判断地址是否指向本机或局域网。"""
    return _is_local_host(urllib.parse.urlsplit(value or "").hostname)


def _normalize_base_url(value):
    """整理并检查 Steam 要返回的网站根地址。"""
    parsed = urllib.parse.urlsplit((value or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("PUBLIC_BASE_URL 必须是完整的 http 或 https 地址")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("PUBLIC_BASE_URL 不能包含账号、查询参数或片段")
    if parsed.path not in ("", "/"):
        raise ValueError("PUBLIC_BASE_URL 不能包含子路径")

    scheme = parsed.scheme
    if not _is_local_host(parsed.hostname):
        scheme = "https"
    return urllib.parse.urlunsplit((scheme, parsed.netloc, "", "", "")).rstrip("/")


def _steam_base_url():
    """
    固定公网地址优先使用配置值；auto 或本机地址则跟随当前访问地址。
    启用 TRUST_PROXY 后，ProxyFix 会先把 Cloudflare 的外部地址还原到请求中。
    """
    configured = (Config.PUBLIC_BASE_URL or "").strip()
    use_current = not configured or configured.lower() == "auto" or _is_local_base_url(configured)
    return _normalize_base_url(request.host_url if use_current else configured)


def _steam_result_endpoint(purpose):
    """Steam 操作完成后回到用户刚才所在的页面。"""
    return "user_register" if purpose == "register" else "change_password"


def _redirect_after_steam(purpose, message, category="error"):
    flash(message, category)
    endpoint = (
        _steam_result_endpoint(purpose) if purpose in ("register", "recovery") else "user_login"
    )
    return redirect(url_for(endpoint))


def _safe_next_target(default_endpoint="index"):
    """登录后只允许跳回本站内部路径。"""
    target = (request.form.get("next") or request.args.get("next") or "").strip()
    if not target:
        return url_for(default_endpoint)
    parsed = urllib.parse.urlsplit(target)
    if parsed.scheme or parsed.netloc or not target.startswith("/"):
        return url_for(default_endpoint)
    return urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, parsed.fragment))


def _start_login_session(user=None, admin=None):
    """写入当前登录身份；同一个账号可同时拥有选手身份和管理员权限。"""
    session.clear()
    session.permanent = True
    session["csrf_token"] = uuid.uuid4().hex
    if user:
        session["user_id"] = user["id"]
        session["user_username"] = user["username"]
        if _profile_completion_required(user):
            session["profile_completion_required"] = True
    if admin:
        session["admin_id"] = admin["id"]
        session["admin_username"] = admin["username"]


def _login_destination(next_target):
    return next_target


def _verify_steam_openid(verify_params):
    """向 Steam 复核 OpenID 回包；国内网络偶发断连时自动重试。"""
    body = urllib.parse.urlencode(verify_params).encode("utf-8")
    last_error = None
    for attempt in range(1, STEAM_VERIFY_ATTEMPTS + 1):
        try:
            req = urllib.request.Request(STEAM_OPENID_URL, data=body, method="POST")
            req.add_header("User-Agent", "80GOTV/1.0")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            with urllib.request.urlopen(req, timeout=20) as response:
                return response.read().decode("utf-8", errors="replace")
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Steam OpenID 校验连接失败（第 %s/%s 次）：%s",
                attempt,
                STEAM_VERIFY_ATTEMPTS,
                type(exc).__name__,
            )
            if attempt < STEAM_VERIFY_ATTEMPTS:
                time.sleep(0.6 * attempt)
    raise last_error


@app.route("/auth/steam/start")
def steam_auth_start():
    """跳转到 Steam，由 Steam 确认当前用户身份。"""
    purpose = request.args.get("purpose", "")
    if purpose not in ("register", "recovery"):
        return "无效的 Steam 验证用途", 400
    nonce = uuid.uuid4().hex
    try:
        base_url = _steam_base_url()
    except ValueError:
        logger.exception("Steam 返回地址配置无效")
        return _redirect_after_steam(purpose, "Steam 验证地址配置有误，请联系管理员")

    callback_query = urllib.parse.urlencode({"nonce": nonce, "purpose": purpose})
    return_to = f"{base_url}/auth/steam/callback?{callback_query}"
    session["steam_auth"] = {
        "purpose": purpose,
        "nonce": nonce,
        "started_at": time.time(),
        "return_to": return_to,
    }
    params = {
        "openid.ns": STEAM_OPENID_NS,
        "openid.mode": "checkid_setup",
        "openid.return_to": return_to,
        "openid.realm": base_url,
        "openid.identity": STEAM_OPENID_IDENTIFIER,
        "openid.claimed_id": STEAM_OPENID_IDENTIFIER,
    }
    return redirect(f"{STEAM_OPENID_URL}?{urllib.parse.urlencode(params)}")


@app.route("/auth/steam/callback")
def steam_auth_callback():
    """校验 Steam 回传，并把已确认的 SteamID 暂存到当前浏览器 session。"""
    pending = session.get("steam_auth") or {}
    purpose = pending.get("purpose") or request.args.get("purpose", "")
    nonce = request.args.get("nonce", "")
    if not pending or nonce != pending.get("nonce"):
        return _redirect_after_steam(purpose, "Steam 验证已失效，请重新操作")
    if time.time() - float(pending.get("started_at", 0)) > STEAM_AUTH_MAX_AGE:
        session.pop("steam_auth", None)
        return _redirect_after_steam(purpose, "Steam 验证已超时，请重新操作")

    if request.args.get("openid.mode") == "cancel":
        session.pop("steam_auth", None)
        return _redirect_after_steam(purpose, "已取消 Steam 验证")

    verify_params = {key: value for key, value in request.args.items() if key.startswith("openid.")}
    returned_to = verify_params.get("openid.return_to", "")
    if not returned_to or returned_to != pending.get("return_to"):
        session.pop("steam_auth", None)
        return _redirect_after_steam(purpose, "Steam 返回地址不一致，请重新操作")

    verify_params["openid.mode"] = "check_authentication"
    try:
        verification = _verify_steam_openid(verify_params)
    except Exception:
        logger.exception("Steam OpenID 校验请求多次重试后仍失败")
        return _redirect_after_steam(purpose, "暂时无法稳定连接 Steam，已自动重试，请稍后再试")

    claimed_id = verify_params.get("openid.claimed_id", "")
    identity = verify_params.get("openid.identity", "")
    match = re.fullmatch(r"https?://steamcommunity\.com/openid/id/(\d{17})", claimed_id)
    verification_values = {}
    for line in verification.splitlines():
        key, separator, value = line.partition(":")
        if separator:
            verification_values[key.strip()] = value.strip()
    valid_response = bool(match) and (
        verification_values.get("is_valid") == "true"
        and verify_params.get("openid.op_endpoint") == STEAM_OPENID_URL
        and identity == claimed_id
    )
    if not valid_response or match is None:
        session.pop("steam_auth", None)
        return _redirect_after_steam(purpose, "Steam 身份验证失败，请重新操作")

    session.pop("steam_auth", None)
    session["steam_verified"] = {
        "purpose": purpose,
        "steam_id64": match.group(1),
        "verified_at": time.time(),
    }
    return _redirect_after_steam(purpose, "Steam 身份验证成功", "success")


@app.route("/login", methods=["GET", "POST"])
@csrf_required
def user_login():
    """用户登录"""
    next_target = _safe_next_target()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        captcha_input = request.form.get("captcha", "").strip()

        if not rate_limit(f"user_login:{username.lower()}", 5, 300, by_ip=True):
            flash("登录尝试次数过多，请 5 分钟后再试", "error")
            _generate_captcha()
            return render_template("login.html", next_target=next_target)

        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        admin = conn.execute("SELECT * FROM admins WHERE username=?", (username,)).fetchone()

        if admin and check_password_hash(admin["password_hash"], password):
            _start_login_session(user=user, admin=admin)
            conn.close()
            flash("登录成功", "success")
            return redirect(_login_destination(next_target))

        if not _check_captcha(captcha_input):
            conn.close()
            flash("验证码错误", "error")
            _generate_captcha()
            return render_template("login.html", next_target=next_target)

        if user and check_password_hash(user["password_hash"], password):
            status = user["approval_status"] or "approved"
            if status == "pending":
                conn.close()
                flash("账号正在等待管理员审核，审核通过后才能登录", "error")
                _generate_captcha()
                return render_template("login.html", next_target=next_target)
            if status == "rejected":
                conn.close()
                flash("账号申请未通过，请联系管理员", "error")
                _generate_captcha()
                return render_template("login.html", next_target=next_target)
            if status != "approved":
                conn.close()
                flash("账号当前不可登录，请联系管理员", "error")
                _generate_captcha()
                return render_template("login.html", next_target=next_target)
            _start_login_session(user=user)
            conn.close()
            flash("登录成功", "success")
            return redirect(_login_destination(next_target))

        conn.close()
        flash("用户名或密码错误", "error")
        _generate_captcha()
    else:
        _generate_captcha()

    return render_template("login.html", next_target=next_target)


@app.route("/register", methods=["GET", "POST"])
@csrf_required
def user_register():
    """仅接受 Steam 选手申请，申请通过后台审核后才能登录。"""
    verified_steam_id = _get_verified_steam_id("register")
    verified_email = _get_verified_registration_email()

    def _render_register(reset_timer=False):
        if reset_timer:
            session["register_form_started_at"] = time.time()
        return render_template(
            "login.html",
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
        email = _normalize_email(request.form.get("email", ""))
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")
        steam_id64 = verified_steam_id
        captcha_input = request.form.get("captcha", "").strip()

        if request.form.get("website", "").strip():
            flash("注册申请未通过安全检查", "error")
            return _render_register()

        started_at = float(session.get("register_form_started_at", 0) or 0)
        if not started_at or time.time() - started_at < 2:
            flash("提交过快，请稍等两秒后再试", "error")
            return _render_register()

        if not rate_limit("register_hour", 5, 3600, by_ip=True) or not rate_limit(
            "register_day", 20, 86400, by_ip=True
        ):
            flash("注册尝试次数过多，请稍后再试", "error")
            _generate_captcha()
            return _render_register()

        if not _check_captcha(captcha_input):
            flash("验证码错误", "error")
            _generate_captcha()
            return _render_register()

        if not username or not password:
            flash("用户名和密码不能为空", "error")
            _generate_captcha()
            return _render_register()

        if school_status is None:
            flash("请选择你是否是或曾经是八十中学生", "error")
            _generate_captcha()
            return _render_register()

        if group_username_error:
            flash(group_username_error, "error")
            _generate_captcha()
            return _render_register()

        if not email:
            flash("请输入有效的邮箱地址", "error")
            _generate_captcha()
            return _render_register()

        if not verified_email or not hmac.compare_digest(email, verified_email):
            flash("请先完成邮箱验证码验证", "error")
            _generate_captcha()
            return _render_register()

        if len(username) < 2 or len(username) > 20:
            flash("用户名长度 2-20 个字符", "error")
            _generate_captcha()
            return _render_register()

        if not re.fullmatch(r"[A-Za-z0-9_\-\u4e00-\u9fff]+", username):
            flash("用户名只能包含中文、字母、数字、下划线或短横线", "error")
            _generate_captcha()
            return _render_register()

        if password != password2:
            flash("两次密码不一致", "error")
            _generate_captcha()
            return _render_register()

        if (
            len(password) < 10
            or not re.search(r"[A-Za-z]", password)
            or not re.search(r"\d", password)
        ):
            flash("密码至少 10 位，并且同时包含字母和数字", "error")
            _generate_captcha()
            return _render_register()

        if not steam_id64:
            flash("提交申请前请先通过 Steam 验证", "error")
            _generate_captcha()
            return _render_register()

        conn = get_db()
        existing_steam = None
        if steam_id64:
            existing_steam = conn.execute(
                "SELECT * FROM users WHERE steam_id64=?", (steam_id64,)
            ).fetchone()

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
            flash("用户名已存在", "error")
            _generate_captcha()
            return _render_register()

        if existing_email and (
            claimable_steam is None or existing_email["id"] != claimable_steam["id"]
        ):
            conn.close()
            flash("该邮箱已经注册", "error")
            _generate_captcha()
            return _render_register()

        if steam_id64:
            if existing_steam and claimable_steam is None:
                conn.close()
                flash("该 Steam 账号已注册，请使用忘记密码找回账号", "error")
                _generate_captcha()
                return _render_register()

            existing_nick = conn.execute(
                "SELECT id, steam_id FROM players WHERE nickname=?", (username,)
            ).fetchone()
            if existing_nick and str(existing_nick["steam_id"] or "") != steam_id64:
                conn.close()
                flash("该昵称已被选手使用，请更换用户名", "error")
                _generate_captcha()
                return _render_register()

        # 处理头像上传
        avatar_filename = None
        avatar_file = request.files.get("avatar")
        if avatar_file and avatar_file.filename:
            avatar_filename, _ = save_uploaded_avatar(avatar_file, app.root_path)
            if not avatar_filename:
                conn.close()
                flash("头像文件无效，请上传 png/jpg/jpeg/gif 图片", "error")
                _generate_captcha()
                return _render_register()

        password_hash = generate_password_hash(password)
        submitted_user_id = None
        if claimable_steam is not None:
            conn.execute(
                """UPDATE users SET username=?, password_hash=?, email=?,
                                    email_verified_at=CURRENT_TIMESTAMP,
                                    group_username=?,
                                    is_bashizhong_student=?,
                                    avatar=COALESCE(?, avatar),
                                    is_placeholder=0, approval_status='pending',
                                    approval_note=NULL, approved_at=NULL, approved_by=NULL
                    WHERE id=?""",
                (
                    username,
                    password_hash,
                    email,
                    group_username or None,
                    school_status,
                    avatar_filename,
                    claimable_steam["id"],
                ),
            )
            submitted_user_id = claimable_steam["id"]
            claimed_players = conn.execute(
                "SELECT id FROM players WHERE steam_id=?", (steam_id64,)
            ).fetchall()
            for claimed_player in claimed_players:
                update_player_nickname(conn, claimed_player["id"], username, "website")
            conn.execute(
                "UPDATE players SET avatar=COALESCE(?, avatar) WHERE steam_id=?",
                (avatar_filename, steam_id64),
            )
        else:
            cursor = conn.execute(
                """INSERT INTO users(
                       username, password_hash, email, email_verified_at,
                       group_username, is_bashizhong_student, steam_id64, avatar,
                       is_placeholder, approval_status
                   ) VALUES(?,?,?,CURRENT_TIMESTAMP,?,?,?,?,0,'pending')""",
                (
                    username,
                    password_hash,
                    email,
                    group_username or None,
                    school_status,
                    steam_id64 or None,
                    avatar_filename,
                ),
            )
            submitted_user_id = cursor.lastrowid

        conn.commit()
        logger.info(
            "Registration application submitted: user_id=%s placeholder_claim=%s",
            submitted_user_id,
            claimable_steam is not None,
        )
        conn.close()
        session.pop("steam_verified", None)
        session.pop("registration_email_verified", None)
        session.pop("register_email", None)
        session.pop("register_email_last_sent", None)

        flash("申请已提交，等待管理员审核；审核通过后才能登录", "success")
        return redirect(url_for("user_login"))

    _generate_captcha()
    return _render_register(reset_timer=True)


@app.route("/account/complete-profile", methods=["POST"])
@csrf_required
@user_required
def complete_account_profile():
    """老账号登录后用不可关闭的弹窗补齐校内身份和必要的群昵称。"""
    school_status = _parse_school_status(request.form.get("is_bashizhong_student"))
    next_target = _safe_next_target()
    if school_status is None:
        flash("请选择你是否是或曾经是八十中学生", "error")
        return redirect(next_target)

    group_username = ""
    if school_status == 1:
        group_username, error = _validate_group_username(request.form.get("group_username", ""))
        if error:
            flash(error, "error")
            return redirect(next_target)

    conn = get_db()
    user = conn.execute(
        "SELECT id, steam_id64 FROM users WHERE id=?", (session["user_id"],)
    ).fetchone()
    if not user:
        conn.close()
        session.clear()
        return redirect(url_for("user_login"))

    if school_status == 1:
        conn.execute(
            """UPDATE users
               SET is_bashizhong_student=1, group_username=?
               WHERE id=?""",
            (group_username, user["id"]),
        )
    else:
        conn.execute(
            "UPDATE users SET is_bashizhong_student=0 WHERE id=?",
            (user["id"],),
        )

    if user["steam_id64"]:
        conn.execute(
            """UPDATE players
               SET is_bashizhong_student=?,
                   group_username_override=CASE
                       WHEN ?=1 THEN ?
                       ELSE group_username_override
                   END
               WHERE steam_id=?""",
            (
                school_status,
                school_status,
                group_username or None,
                user["steam_id64"],
            ),
        )
    conn.commit()
    conn.close()
    session.pop("profile_completion_required", None)
    session.pop("group_username_required", None)
    flash("资料已保存", "success")
    return redirect(next_target)


@app.route("/logout")
def user_logout():
    """前台登出：退出当前浏览器里的全部前台/管理员身份。"""
    for key in (
        "user_id",
        "user_username",
        "admin_id",
        "admin_username",
        "group_username_required",
        "profile_completion_required",
    ):
        session.pop(key, None)
    flash("已退出登录", "success")
    return redirect(url_for("index"))


@app.route("/profile", methods=["GET", "POST"])
@csrf_required
@user_required
def user_profile():
    """个人主页：查看/编辑资料"""
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()

    # 查找关联的选手（通过 steam_id 匹配）
    player = None
    if user["steam_id64"]:
        player = conn.execute(
            "SELECT p.*, t.name AS team_name FROM players p LEFT JOIN teams t ON p.team_id=t.id WHERE p.steam_id=?",
            (user["steam_id64"],),
        ).fetchone()

    if request.method == "POST":
        action = request.form.get("action", "")

        if _profile_completion_required(user) and action != "group_username":
            conn.close()
            flash("请先完成账号资料设置", "error")
            return redirect(url_for("user_profile"))

        if action == "nickname":
            new_nick = request.form.get("nickname", "").strip()
            if not new_nick or len(new_nick) < 2 or len(new_nick) > 20:
                flash("昵称长度 2-20 个字符", "error")
            else:
                existing = conn.execute(
                    "SELECT id FROM users WHERE username=? AND id!=?", (new_nick, user["id"])
                ).fetchone()
                if existing:
                    flash("该昵称已被使用", "error")
                else:
                    conn.execute("UPDATE users SET username=? WHERE id=?", (new_nick, user["id"]))
                    if player:
                        update_player_nickname(conn, player["id"], new_nick, "website")
                    conn.commit()
                    session["user_username"] = new_nick
                    flash("昵称已更新", "success")

        elif action == "group_username":
            if user["is_bashizhong_student"] != 1:
                conn.close()
                flash("外校选手不需要填写群内用户名", "error")
                return redirect(url_for("user_profile"))
            group_username, group_username_error = _validate_group_username(
                request.form.get("group_username", "")
            )
            if group_username_error:
                flash(group_username_error, "error")
            else:
                conn.execute(
                    "UPDATE users SET group_username=? WHERE id=?",
                    (group_username, user["id"]),
                )
                conn.commit()
                if user["steam_id64"]:
                    conn.execute(
                        """UPDATE players SET group_username_override=?
                           WHERE steam_id=?""",
                        (group_username, user["steam_id64"]),
                    )
                    conn.commit()
                session.pop("profile_completion_required", None)
                session.pop("group_username_required", None)
                flash("群内用户名已更新", "success")

        elif action == "password":
            old_pw = request.form.get("old_password", "")
            new_pw = request.form.get("new_password", "")
            new_pw2 = request.form.get("new_password2", "")
            if not check_password_hash(user["password_hash"], old_pw):
                flash("当前密码错误", "error")
            elif len(new_pw) < 8:
                flash("新密码至少 8 位", "error")
            elif new_pw != new_pw2:
                flash("两次新密码不一致", "error")
            else:
                conn.execute(
                    "UPDATE users SET password_hash=? WHERE id=?",
                    (generate_password_hash(new_pw), user["id"]),
                )
                conn.commit()
                flash("密码已更新", "success")

        elif action == "avatar":
            f = request.files.get("avatar")
            if not f or not f.filename:
                flash("请选择图片", "error")
            else:
                old_avatar = user["avatar"]
                filename, _ = save_uploaded_avatar(f, app.root_path, old_avatar=old_avatar)
                if not filename:
                    flash("文件内容无效，请上传 png/jpg/jpeg/gif 图片", "error")
                else:
                    # 用户和关联选手始终使用同一个头像文件。
                    conn.execute("UPDATE users SET avatar=? WHERE id=?", (filename, user["id"]))
                    if player:
                        conn.execute(
                            "UPDATE players SET avatar=? WHERE id=?", (filename, player["id"])
                        )
                    conn.commit()
                    flash("头像已更新", "success")

        conn.close()
        return redirect(url_for("user_profile"))

    # 查询关联选手参加过的赛事
    events_participated = []
    if player:
        events_participated = conn.execute(
            """
            SELECT DISTINCT e.*,
                   COUNT(DISTINCT m.id) as match_count,
                   SUM(CASE WHEN e.status IN ('ongoing','upcoming') THEN 1 ELSE 0 END) > 0 as is_active
            FROM events e
            JOIN matches m ON m.event_id = e.id
            JOIN match_stats ms ON ms.match_id = m.id
            WHERE ms.player_id = ?
            GROUP BY e.id
            ORDER BY e.start_date DESC
        """,
            (player["id"],),
        ).fetchall()

    conn.close()
    return render_template(
        "user_profile.html", user=user, player=player, events_participated=events_participated
    )


@app.route("/change-password", methods=["GET", "POST"])
@csrf_required
def change_password():
    """通过 Steam OpenID 验证后修改密码。"""
    steam_id64 = _get_verified_steam_id("recovery")
    if request.method == "POST":
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")

        if not steam_id64:
            flash("请先通过 Steam 验证身份", "error")
            return redirect(url_for("change_password"))

        if len(password) < 8:
            flash("密码至少 8 位", "error")
            return render_template("change_password.html", steam_verified_id=steam_id64)

        if password != password2:
            flash("两次密码不一致", "error")
            return render_template("change_password.html", steam_verified_id=steam_id64)

        conn = get_db()
        user = conn.execute(
            "SELECT id, username FROM users WHERE steam_id64=?", (steam_id64,)
        ).fetchone()

        if not user:
            conn.close()
            flash("未找到该 Steam ID 对应的账号", "error")
            session.pop("steam_verified", None)
            return redirect(url_for("change_password"))

        conn.execute(
            """UPDATE users
               SET password_hash=?, is_placeholder=0, approval_status='pending'
               WHERE id=?""",
            (generate_password_hash(password), user["id"]),
        )
        conn.commit()
        conn.close()
        session.pop("steam_verified", None)

        flash("密码修改成功，账号等待管理员审核", "success")
        return redirect(url_for("user_login"))

    return render_template("change_password.html", steam_verified_id=steam_id64)
