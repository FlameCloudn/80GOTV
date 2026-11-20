"""系统端点、错误响应与公开资源。"""

import logging
import os

from flask import current_app, g, jsonify, render_template, request, send_from_directory, url_for
from werkzeug.exceptions import HTTPException, SecurityError

from src.website.domains.matches.map_names import normalize_map_key
from src.website.runtime.database import get_db
from src.website.runtime.storage import site_paths
from src.website.web.presentation.seo import public_site_url
from src.website.web.request_policy import _NON_CONTENT_PREFIXES

logger = logging.getLogger("80gotv")


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


def robots_txt():
    rules = ["User-agent: *"]
    rules.extend(f"Disallow: {prefix}" for prefix in _NON_CONTENT_PREFIXES)
    rules += [
        "Disallow: /matches/*/download-demo",
        "Allow: /",
        f"Sitemap: {public_site_url(url_for('sitemap'))}",
    ]
    return "\n".join(rules) + "\n", 200, {"Content-Type": "text/plain; charset=utf-8"}


def _handle_exception(e):
    """统一错误处理：页面隐藏细节，日志保留完整异常信息。"""
    if isinstance(e, SecurityError):
        # 不受信任的 Host 没有可用的地址构建器，不能渲染含 url_for 的模板。
        return e.get_response()
    raw_code = getattr(e, "code", None)
    code = int(raw_code) if isinstance(e, HTTPException) and raw_code is not None else 500
    if code >= 500:
        logger.exception(
            "未处理的服务器错误 request_id=%s path=%s",
            getattr(g, "request_id", "-"),
            request.path,
        )
    error = str(e) if code < 500 else "服务器内部错误，请稍后重试"
    wants_json = (
        request.path.startswith("/api/")
        or "/api/" in request.path
        or request.is_json
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
    )
    if wants_json:
        response = jsonify(
            {
                "ok": False,
                "success": False,
                "error": error,
                "request_id": getattr(g, "request_id", None),
            }
        )
        response.status_code = code
        if isinstance(e, HTTPException):
            for name, value in e.get_headers():
                if name.lower() not in {"content-type", "content-length"}:
                    response.headers[name] = value
        return response
    return render_template("public/home/error.html", error=error, code=code, debug_info=None), code


def favicon():
    """浏览器标签页上的网站小图标（浏览器和后台页面默认都会来这个地址找）。"""
    return send_from_directory(
        os.path.join(current_app.root_path, "static"),
        "favicon.ico",
        mimetype="image/vnd.microsoft.icon",
    )


def public_avatar(filename):
    return send_from_directory(site_paths().avatars, filename)


def public_upload(filename):
    return send_from_directory(site_paths().uploads, filename)


def serve_map_resource(filename):
    maps_dir = os.path.join(current_app.root_path, "resources", "maps")
    try:
        return send_from_directory(maps_dir, filename)
    except HTTPException as e:
        if e.code != 404:
            raise
    fallback = f"{normalize_map_key(os.path.splitext(os.path.basename(filename))[0])}.png"
    return send_from_directory(
        os.path.join(current_app.root_path, "resources", "map_landscapes"), fallback
    )


def serve_font_resource(filename):
    return send_from_directory(os.path.join(current_app.root_path, "resources", "fonts"), filename)


def serve_resource(filename):
    return send_from_directory(os.path.join(current_app.root_path, "resources"), filename)
