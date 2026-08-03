"""
网站基础设置。
这里只放所有页面都要用到的东西：Flask 应用、请求钩子、安全策略和
共享工具。具体页面放在 routes/ 目录。
"""

import logging
import os
import uuid

from flask import (
    Flask,
    abort,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from models import get_db
from services.player_remark_service import (
    private_name_for_player,
    private_name_for_user,
    private_remark_for_player,
    private_remark_for_user,
)
from utils.db_helpers import avatar_static_filename
from utils.helpers import event_path, news_path, normalize_map_key

logger = logging.getLogger("80gotv")

app = Flask(__name__)
app.jinja_env.auto_reload = True
app.config.from_object(Config)
app.config["PROPAGATE_EXCEPTIONS"] = False
if Config.TRUST_PROXY:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

DEMOS_DIR = os.path.join(app.root_path, "static", "demos")
_IMAGE_FORM_LIMIT = 6 * 1024 * 1024
_JSON_BODY_LIMIT = 2 * 1024 * 1024


# ── 注册模板过滤器 ──────────────────────────────────────────
from utils.filters import (  # noqa: E402
    bilibili_embed_filter,
    cn_time_filter,
    compact_date_display_filter,
    date_display_filter,
    datetime_display_filter,
    json_loads_filter,
    map_background_filter,
    map_display_cn_filter,
    map_display_filter,
    map_image_filter,
    rating_class_filter,
    registration_team_abbr_filter,
    relative_date_display_filter,
    time_display_filter,
)

app.template_filter("json_loads")(json_loads_filter)
app.template_filter("cn_time")(cn_time_filter)
app.template_filter("compact_date_display")(compact_date_display_filter)
app.template_filter("date_display")(date_display_filter)
app.template_filter("datetime_display")(datetime_display_filter)
app.template_filter("relative_date_display")(relative_date_display_filter)
app.template_filter("time_display")(time_display_filter)
app.template_filter("map_image")(map_image_filter)
app.template_filter("map_background")(map_background_filter)
app.template_filter("map_display")(map_display_filter)
app.template_filter("map_display_cn")(map_display_cn_filter)
app.template_filter("rating_class")(rating_class_filter)
app.template_filter("registration_team_abbr")(registration_team_abbr_filter)
app.template_filter("bilibili_embed")(bilibili_embed_filter)
app.jinja_env.globals["event_path"] = event_path
app.jinja_env.globals["news_path"] = news_path
app.jinja_env.globals["private_name_for_player"] = private_name_for_player
app.jinja_env.globals["private_name_for_user"] = private_name_for_user
app.jinja_env.globals["private_remark_for_player"] = private_remark_for_player
app.jinja_env.globals["private_remark_for_user"] = private_remark_for_user


# ── 请求钩子 ────────────────────────────────────────────────


@app.before_request
def _start_timer():
    """记录请求开始时间"""
    import time as _time

    request._start_time = _time.time()
    g.request_id = uuid.uuid4().hex


@app.before_request
def _enforce_public_https():
    """公网启用安全 Cookie 时，将 Cloudflare 的 HTTP 访问强制转到 HTTPS。"""
    forwarded_proto = request.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip()
    cloudflare_visitor = request.headers.get("CF-Visitor", "").replace(" ", "").lower()
    external_http = forwarded_proto == "http" or '"scheme":"http"' in cloudflare_visitor
    if app.config.get("SESSION_COOKIE_SECURE") and external_http:
        secure_url = request.url.replace("http://", "https://", 1)
        return redirect(secure_url, code=308)


_PUBLIC_PATHS = {
    "/login",
    "/register",
    "/change-password",
    "/captcha/image",
    "/captcha/reload",
    "/auth/email/send-code",
    "/auth/email/verify-code",
    "/healthz",
    "/robots.txt",
    "/admin/login",
}
_PUBLIC_PREFIXES = ("/static/", "/resources/", "/auth/steam/")
_INGEST_PATHS = {"/api/gsi/receive", "/api/gotv/stats"}


def _is_ingest_path(path):
    if path in _INGEST_PATHS:
        return True
    parts = path.strip("/").split("/")
    return (
        len(parts) == 5
        and parts[:3] == ["api", "broadcast", "matches"]
        and parts[3].isdigit()
        and parts[4] in {"live", "map-result"}
    )


@app.before_request
def _reject_cross_site_writes():
    """Block browser form posts arriving from an unrelated website."""
    if request.method in ("GET", "HEAD", "OPTIONS") or _is_ingest_path(request.path):
        return None
    if request.headers.get("Sec-Fetch-Site", "").lower() != "cross-site":
        return None
    if request.path.startswith("/api/") or request.is_json:
        return jsonify({"success": False, "error": "已拒绝跨站请求"}), 403
    abort(403)


def _clear_user_session():
    for key in (
        "user_id",
        "user_username",
        "group_username_required",
        "profile_completion_required",
    ):
        session.pop(key, None)


@app.before_request
def _require_site_login():
    """访客可只读浏览；任何会修改数据的操作仍要求已审核账号。"""
    path = request.path
    if path in _PUBLIC_PATHS or _is_ingest_path(path) or path.startswith(_PUBLIC_PREFIXES):
        return None
    if "user_id" in session:
        conn = None
        try:
            conn = get_db()
            user = conn.execute(
                """SELECT id, approval_status, group_username,
                          is_bashizhong_student, is_cheater
                   FROM users WHERE id=?""",
                (session["user_id"],),
            ).fetchone()
        except Exception:
            logger.exception("检查账号审核状态失败")
            # 数据库短暂繁忙时不要把有效登录直接清掉；下一次请求会重新检查。
            return None
        finally:
            if conn is not None:
                conn.close()
        if user and (user["approval_status"] or "approved") == "approved":
            g.current_user_row = user
            needs_completion = user["is_bashizhong_student"] is None or (
                bool(user["is_bashizhong_student"])
                and not str(user["group_username"] or "").strip()
            )
            if not needs_completion:
                session.pop("profile_completion_required", None)
                session.pop("group_username_required", None)
            return None
        _clear_user_session()

    if "admin_id" in session:
        return None

    if request.method in ("GET", "HEAD", "OPTIONS"):
        return None
    if path.startswith("/api/") or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": False, "error": "请先登录"}), 401
    if path.startswith("/admin"):
        return redirect(url_for("admin.admin_login"))
    next_target = request.full_path.rstrip("?")
    return redirect(url_for("user_login", next=next_target))


@app.after_request
def _add_no_cache_headers(response):
    """页面不缓存 + 慢查询记录"""
    import logging as _logging
    import time as _time

    start = getattr(request, "_start_time", None)
    if start:
        elapsed = _time.time() - start
        if elapsed > 0.5:
            _logging.getLogger("80gotv").warning(
                "慢查询: %s %s (%.2fs)", request.method, request.path, elapsed
            )
    request_id = getattr(g, "request_id", None)
    if request_id:
        response.headers["X-Request-ID"] = request_id
    """页面不缓存；带版本号的静态资源长期缓存，减少重复下载。"""
    if request.path.startswith(("/static/", "/resources/")):
        # Versioned assets are safe to keep for a year. A changed file gets a
        # new URL, so repeat page loads no longer re-download the same CSS/JS.
        if request.args.get("v"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif request.path.endswith((".css", ".js")):
            response.headers["Cache-Control"] = "no-cache"
        else:
            response.headers["Cache-Control"] = "public, max-age=604800"
    elif request.path.startswith("/map-quiz/image/"):
        # 题图需要登录，但同一道题无需在每次提交后重新下载。
        response.headers["Cache-Control"] = "private, max-age=86400"
    else:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
    response.headers["Cross-Origin-Resource-Policy"] = "same-site"
    response.headers["Origin-Agent-Cluster"] = "?1"
    production = bool(app.config.get("IS_PRODUCTION"))
    script_sources = ["'self'", "'unsafe-inline'"]
    connect_sources = ["'self'"]
    frame_sources = ["'self'", "https://player.bilibili.com", "https://live.bilibili.com"]
    worker_sources = ["'self'", "blob:"]
    if not production:
        script_sources.extend(("http://127.0.0.1:5173", "http://localhost:5173"))
        connect_sources.extend(
            (
                "http://127.0.0.1:5173",
                "http://localhost:5173",
                "ws://127.0.0.1:5173",
                "ws://localhost:5173",
            )
        )
        frame_sources.extend(("http://127.0.0.1:5173", "http://localhost:5173"))
        worker_sources.extend(("http://127.0.0.1:5173", "http://localhost:5173"))
    csp_parts = [
        "default-src 'self'",
        "img-src 'self' data: https:",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://www.w3schools.com",
        f"script-src {' '.join(script_sources)}",
        f"connect-src {' '.join(connect_sources)}",
        f"frame-src {' '.join(frame_sources)}",
        f"worker-src {' '.join(worker_sources)}",
        "font-src 'self' data: https://fonts.gstatic.com",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self' https://steamcommunity.com",
        "frame-ancestors 'self'",
    ]
    if production:
        csp_parts.append("upgrade-insecure-requests")
    response.headers["Content-Security-Policy"] = "; ".join(csp_parts)
    response.headers["X-DNS-Prefetch-Control"] = "off"
    response.headers["X-Download-Options"] = "noopen"
    if app.config.get("SESSION_COOKIE_SECURE"):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.before_request
def _csrf_before_request():
    content_length = request.content_length
    if content_length is not None:
        if _is_ingest_path(request.path) and content_length > _JSON_BODY_LIMIT:
            abort(413)
        image_form = request.path in (
            "/register",
            "/profile",
            "/admin/upload/image",
            "/admin/players/add",
        ) or request.path.startswith("/admin/players/edit/")
        image_form = image_form or request.endpoint in {
            "event_registration_upload_logo",
            "event_register",
        }
        if request.method == "POST" and image_form and content_length > _IMAGE_FORM_LIMIT:
            abort(413)
    if "csrf_token" not in session:
        session["csrf_token"] = uuid.uuid4().hex


@app.before_request
def _require_profile_completion_before_request():
    if not session.get("profile_completion_required"):
        return None
    if session.get("admin_id") and request.path.startswith("/admin"):
        return None
    if request.endpoint in {
        "complete_account_profile",
        "user_profile",
        "user_logout",
        "current_csrf_token",
        "healthz",
        "static",
    }:
        return None
    if request.method in ("GET", "HEAD", "OPTIONS") and not request.path.startswith("/api/"):
        return None
    if (
        request.path.startswith("/api/")
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
    ):
        return (
            jsonify(
                {
                    "success": False,
                    "error": "请先完成账号资料设置",
                    "requires_profile_completion": True,
                }
            ),
            409,
        )
    return redirect(request.referrer or url_for("index"))


# ── 模板全局工具 ────────────────────────────────────────────


@app.template_global()
def versioned_url(path):
    """给静态文件加版本号防缓存。用法: {{ versioned_url('css/style.css') }}"""
    import os as _os

    if not path.startswith(("/", "http")):
        path = "/" + path
    if path.startswith("/static/") or path.startswith("/resources/"):
        full = _os.path.join(app.root_path, path.lstrip("/"))
        if _os.path.exists(full):
            ts = int(_os.path.getmtime(full))
            return f"{path}?v={ts}"
    return path


@app.template_global()
def avatar_thumbnail_url(filename):
    """列表优先使用小头像；没有小图时自动退回原头像。"""
    static_filename = avatar_static_filename(app.root_path, filename, thumbnail=True)
    return url_for("static", filename=static_filename) if static_filename else ""


@app.context_processor
def _csrf_context():
    unread = 0
    current_user_is_cheater = False
    current_user_group_username = ""
    current_user_saved_group_username = ""
    current_user_school_status = None
    if "user_id" in session:
        conn = None
        try:
            conn = get_db()
            unread = conn.execute(
                "SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0",
                (session["user_id"],),
            ).fetchone()[0]
            user_row = getattr(g, "current_user_row", None)
            if user_row is None:
                user_row = conn.execute(
                    """SELECT is_cheater, group_username, is_bashizhong_student
                       FROM users WHERE id=?""",
                    (session["user_id"],),
                ).fetchone()
            current_user_is_cheater = bool(user_row and user_row["is_cheater"])
            current_user_school_status = user_row["is_bashizhong_student"] if user_row else None
            current_user_saved_group_username = (
                (user_row["group_username"] or "") if user_row else ""
            )
            if current_user_school_status != 0:
                current_user_group_username = current_user_saved_group_username
        except Exception:
            pass
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
    return {
        "csrf_token": session.get("csrf_token", ""),
        "unread_count": unread,
        "current_user_is_cheater": current_user_is_cheater,
        "current_user_group_username": current_user_group_username,
        "current_user_saved_group_username": current_user_saved_group_username,
        "current_user_school_status": current_user_school_status,
        "profile_completion_required": bool(session.get("profile_completion_required")),
    }


# ── 错误处理 ────────────────────────────────────────────────


@app.route("/healthz")
def healthz():
    """供公网更新脚本确认网站和数据库都能正常工作。"""
    conn = None
    try:
        conn = get_db()
        conn.execute("SELECT 1").fetchone()
        return jsonify({"ok": True})
    except Exception:
        logger.exception("健康检查失败")
        return jsonify({"ok": False}), 503
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


@app.route("/robots.txt")
def robots_txt():
    return "User-agent: *\nDisallow: /\n", 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.errorhandler(Exception)
def _handle_exception(e):
    """统一错误处理：页面隐藏细节，日志保留完整异常信息。"""
    code = e.code if isinstance(e, HTTPException) else 500
    if code >= 500:
        logger.exception(
            "未处理的服务器错误 request_id=%s path=%s",
            getattr(g, "request_id", "-"),
            request.path,
        )
    error = str(e) if code < 500 else "服务器内部错误，请稍后重试"
    return render_template("error.html", error=error, code=code, debug_info=None), code


# ── 静态资源路由 ────────────────────────────────────────────


@app.route("/resources/maps/<path:filename>")
def serve_map_resource(filename):
    maps_dir = os.path.join(app.root_path, "resources", "maps")
    try:
        return send_from_directory(maps_dir, filename)
    except HTTPException as e:
        if e.code != 404:
            raise
    fallback = f"{normalize_map_key(os.path.splitext(os.path.basename(filename))[0])}.png"
    return send_from_directory(os.path.join(app.root_path, "resources", "map_landscapes"), fallback)


@app.route("/resources/fonts/<path:filename>")
def serve_font_resource(filename):
    return send_from_directory(os.path.join(app.root_path, "resources", "fonts"), filename)


@app.route("/resources/<path:filename>")
def serve_resource(filename):
    return send_from_directory(os.path.join(app.root_path, "resources"), filename)
