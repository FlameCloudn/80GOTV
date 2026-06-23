"""用户登录、注册和 Steam 身份验证。"""

import ipaddress
import random
import re
import time
import urllib.parse
import urllib.request
import uuid

from flask import flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from config import Config
from models import get_db
from services.player_service import record_player_nickname, update_player_nickname
from utils.db_helpers import save_uploaded_avatar
from utils.rate_limiter import rate_limit
from utils.web_helpers import csrf_required, user_required
from web_app import app, logger

# ============ CAPTCHA ============


def _generate_captcha():
    """生成数学验证码，答案存入 session"""
    a = random.randint(1, 20)
    b = random.randint(1, 20)
    op = random.choice(["+", "-", "x"])
    if op == "+":
        ans = a + b
    elif op == "-":
        ans = a - b
    else:
        ans = a * b
    session["captcha_answer"] = str(ans)
    session["captcha_text"] = f"{a} {op} {b} = ?"


def _check_captcha(user_input):
    """校验验证码，校验后清除答案防止复用"""
    answer = session.pop("captcha_answer", None)
    if answer is None:
        return False
    if str(user_input).strip() == answer:
        session.pop("captcha_text", None)  # 校验成功才清除文本
        return True
    session.pop("captcha_text", None)
    return False


# ============ 用户路由 ============


@app.route("/captcha/reload")
def reload_captcha():
    _generate_captcha()
    return session.get("captcha_text", "")


STEAM_OPENID_URL = "https://steamcommunity.com/openid/login"
STEAM_OPENID_NS = "http://specs.openid.net/auth/2.0"
STEAM_OPENID_IDENTIFIER = f"{STEAM_OPENID_NS}/identifier_select"
STEAM_AUTH_MAX_AGE = 10 * 60


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
    session["csrf_token"] = uuid.uuid4().hex
    if user:
        session["user_id"] = user["id"]
        session["user_username"] = user["username"]
    if admin:
        session["admin_id"] = admin["id"]
        session["admin_username"] = admin["username"]


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
        body = urllib.parse.urlencode(verify_params).encode("utf-8")
        req = urllib.request.Request(STEAM_OPENID_URL, data=body, method="POST")
        req.add_header("User-Agent", "80GOTV/1.0")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=15) as response:
            verification = response.read().decode("utf-8", errors="replace")
    except Exception:
        logger.exception("Steam OpenID 校验请求失败")
        return _redirect_after_steam(purpose, "暂时无法连接 Steam，请稍后重试")

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
            return redirect(next_target)

        if not _check_captcha(captcha_input):
            conn.close()
            flash("验证码错误", "error")
            _generate_captcha()
            return render_template("login.html", next_target=next_target)

        if user and check_password_hash(user["password_hash"], password):
            _start_login_session(user=user)
            conn.close()
            flash("登录成功", "success")
            return redirect(next_target)

        conn.close()
        flash("用户名或密码错误", "error")
        _generate_captcha()
    else:
        _generate_captcha()

    return render_template("login.html", next_target=next_target)


@app.route("/register", methods=["GET", "POST"])
@csrf_required
def user_register():
    """用户注册"""
    verified_steam_id = _get_verified_steam_id("register")

    def _render_register():
        return render_template("login.html", tab="register", steam_verified_id=verified_steam_id)

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")
        reg_type = request.form.get("reg_type", "player")
        steam_id64 = verified_steam_id if reg_type == "player" else ""
        captcha_input = request.form.get("captcha", "").strip()

        if not _check_captcha(captcha_input):
            flash("验证码错误", "error")
            _generate_captcha()
            return _render_register()

        if not rate_limit("register", 10, 3600, by_ip=True):
            flash("注册尝试次数过多，请稍后再试", "error")
            _generate_captcha()
            return _render_register()

        if not username or not password:
            flash("用户名和密码不能为空", "error")
            _generate_captcha()
            return _render_register()

        if len(username) < 2 or len(username) > 20:
            flash("用户名长度 2-20 个字符", "error")
            _generate_captcha()
            return _render_register()

        if password != password2:
            flash("两次密码不一致", "error")
            _generate_captcha()
            return _render_register()

        if len(password) < 8:
            flash("密码至少 8 位", "error")
            _generate_captcha()
            return _render_register()

        if reg_type == "player":
            if not steam_id64:
                flash("选手注册前请先通过 Steam 验证", "error")
                _generate_captcha()
                return _render_register()
        elif reg_type != "guest":
            flash("注册类型无效", "error")
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
            "SELECT id FROM users WHERE username=?", (username,)
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
        if claimable_steam is not None:
            conn.execute(
                """UPDATE users SET username=?, password_hash=?, avatar=COALESCE(?, avatar),
                                    is_placeholder=0 WHERE id=?""",
                (username, password_hash, avatar_filename, claimable_steam["id"]),
            )
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
            conn.execute(
                "INSERT INTO users(username, password_hash, steam_id64, avatar, is_placeholder) VALUES(?,?,?,?,0)",
                (username, password_hash, steam_id64 or None, avatar_filename),
            )

        # 选手注册：自动创建选手档案（如果 SteamID 不存在）
        if reg_type == "player" and steam_id64:
            existing_player = conn.execute(
                "SELECT id FROM players WHERE steam_id=?", (steam_id64,)
            ).fetchone()
            if not existing_player:
                conn.execute(
                    "INSERT INTO players(nickname, steam_id, avatar) VALUES(?,?,?)",
                    (username, steam_id64, avatar_filename),
                )
                player_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                record_player_nickname(conn, player_id, username, "website")

        conn.commit()
        conn.close()
        session.pop("steam_verified", None)

        flash("注册成功，请登录", "success")
        return redirect(url_for("user_login"))

    _generate_captcha()
    return _render_register()


@app.route("/logout")
def user_logout():
    """前台登出：退出当前浏览器里的全部前台/管理员身份。"""
    session.pop("user_id", None)
    session.pop("user_username", None)
    session.pop("admin_id", None)
    session.pop("admin_username", None)
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
            "UPDATE users SET password_hash=?, is_placeholder=0 WHERE id=?",
            (generate_password_hash(password), user["id"]),
        )
        conn.commit()
        conn.close()
        session.pop("steam_verified", None)

        flash("密码修改成功，请使用新密码登录", "success")
        return redirect(url_for("user_login"))

    return render_template("change_password.html", steam_verified_id=steam_id64)
