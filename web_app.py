"""
网站基础设置。
这里只放所有页面都要用到的东西：Flask 应用、请求钩子、安全策略和
共享工具。具体页面放在 routes/ 目录。
"""

import logging
import os
import uuid

from flask import Flask, abort, jsonify, render_template, request, send_from_directory, session
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from models import get_db
from utils.helpers import normalize_map_key

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
    date_display_filter,
    datetime_display_filter,
    json_loads_filter,
    map_background_filter,
    map_display_cn_filter,
    map_display_filter,
    map_image_filter,
    rating_class_filter,
    time_display_filter,
)

app.template_filter("json_loads")(json_loads_filter)
app.template_filter("cn_time")(cn_time_filter)
app.template_filter("date_display")(date_display_filter)
app.template_filter("datetime_display")(datetime_display_filter)
app.template_filter("time_display")(time_display_filter)
app.template_filter("map_image")(map_image_filter)
app.template_filter("map_background")(map_background_filter)
app.template_filter("map_display")(map_display_filter)
app.template_filter("map_display_cn")(map_display_cn_filter)
app.template_filter("rating_class")(rating_class_filter)
app.template_filter("bilibili_embed")(bilibili_embed_filter)


# ── 请求钩子 ────────────────────────────────────────────────


@app.before_request
def _start_timer():
    """记录请求开始时间"""
    import time as _time

    request._start_time = _time.time()


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
    """页面不缓存；图片、字体和样式缓存一天，减少重复下载。"""
    if request.path.startswith(("/static/", "/resources/")):
        # 图片和字体缓存一天；CSS/JS 不缓存，方便开发调试
        if request.path.endswith((".css", ".js")):
            response.headers["Cache-Control"] = "no-cache"
        else:
            response.headers["Cache-Control"] = "public, max-age=86400"
    else:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data: https:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://www.w3schools.com; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval' https://cdn.jsdelivr.net http://127.0.0.1:5173 http://localhost:5173; "
        "connect-src 'self' http://127.0.0.1:5173 http://localhost:5173 ws://127.0.0.1:5173 ws://localhost:5173; "
        "frame-src 'self' https://player.bilibili.com https://live.bilibili.com http://127.0.0.1:5173 http://localhost:5173; "
        "worker-src 'self' blob: http://127.0.0.1:5173 http://localhost:5173; "
        "font-src 'self' data: https://fonts.gstatic.com; "
        "object-src 'none'; base-uri 'self'; form-action 'self' https://steamcommunity.com; "
        "frame-ancestors 'self'"
    )
    if app.config.get("SESSION_COOKIE_SECURE"):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.before_request
def _csrf_before_request():
    content_length = request.content_length
    if content_length is not None:
        if (
            request.path in ("/api/gsi/receive", "/api/gotv/stats")
            and content_length > _JSON_BODY_LIMIT
        ):
            abort(413)
        image_form = request.path in (
            "/register",
            "/profile",
            "/admin/upload/image",
            "/admin/players/add",
        ) or request.path.startswith("/admin/players/edit/")
        if request.method == "POST" and image_form and content_length > _IMAGE_FORM_LIMIT:
            abort(413)
    if "csrf_token" not in session:
        session["csrf_token"] = uuid.uuid4().hex


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


@app.context_processor
def _csrf_context():
    unread = 0
    if "user_id" in session:
        try:
            conn = get_db()
            unread = conn.execute(
                "SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0",
                (session["user_id"],),
            ).fetchone()[0]
            conn.close()
        except Exception:
            pass
    return {"csrf_token": session.get("csrf_token", ""), "unread_count": unread}


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


@app.errorhandler(Exception)
def _handle_exception(e):
    """统一错误处理。开发模式显示 traceback，生产模式隐藏细节。"""
    import traceback

    code = e.code if isinstance(e, HTTPException) else 500
    if code >= 500:
        logger.exception("未处理的服务器错误")
    error = str(e) if code < 500 else "服务器内部错误，请稍后重试"
    # 开发模式下把错误详情传给模板，方便调试
    debug_info = None
    if app.debug and code >= 500:
        debug_info = traceback.format_exc()
    return render_template("error.html", error=error, code=code, debug_info=debug_info), code


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
