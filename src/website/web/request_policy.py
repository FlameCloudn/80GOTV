"""请求、认证、缓存和响应策略。"""

import logging
import os
import posixpath
import uuid

from flask import abort, current_app, g, jsonify, redirect, request, session, url_for

from src.website.domains.identity.accounts import approval_status, profile_completion_required
from src.website.runtime.database import get_db
from src.website.runtime.uploads import MAX_TEAM_LOGO_UPLOAD_BYTES
from src.website.web.access import safe_redirect_target, validate_admin_session

logger = logging.getLogger("80gotv")


_IMAGE_FORM_LIMIT = 6 * 1024 * 1024


_TEAM_LOGO_FORM_LIMIT = MAX_TEAM_LOGO_UPLOAD_BYTES + 1024 * 1024


_JSON_BODY_LIMIT = 2 * 1024 * 1024


def _start_timer():
    """记录请求开始时间"""
    import time as _time

    g._start_time = _time.time()
    g.request_id = uuid.uuid4().hex


def _limit_request_body():
    """Apply limits before parsing, including streamed bodies without Content-Length."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return None
    image_form = request.path in (
        "/register",
        "/profile",
        "/admin/upload/image",
        "/admin/players/add",
    ) or request.path.startswith("/admin/players/edit/")
    team_logo_form = (
        request.path == "/admin/teams/add" or request.path.startswith("/admin/teams/edit/")
    ) or request.endpoint in {
        "event_registration_upload_logo",
        "event_register",
    }
    if _is_ingest_path(request.path) or request.is_json:
        limit = _JSON_BODY_LIMIT
    elif team_logo_form:
        limit = _TEAM_LOGO_FORM_LIMIT
    elif image_form:
        limit = _IMAGE_FORM_LIMIT
    elif request.path in _PUBLIC_FORM_PATHS:
        limit = _PUBLIC_FORM_LIMIT
    else:
        return None
    request.max_content_length = min(limit, current_app.config["MAX_CONTENT_LENGTH"] or limit)
    if request.content_length is not None and request.content_length > request.max_content_length:
        abort(413)


def _enforce_public_https():
    """公网启用安全 Cookie 时，将 Cloudflare 的 HTTP 访问强制转到 HTTPS。"""
    forwarded_proto = request.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip()
    cloudflare_visitor = request.headers.get("CF-Visitor", "").replace(" ", "").lower()
    external_http = forwarded_proto == "http" or '"scheme":"http"' in cloudflare_visitor
    if current_app.config.get("SESSION_COOKIE_SECURE") and external_http:
        secure_url = request.url.replace("http://", "https://", 1)
        return redirect(secure_url, code=308)


_PUBLIC_PATHS = {
    "/preferences/language",
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


_PUBLIC_PREFIXES = ("/static/", "/resources/", "/assets/build/", "/auth/steam/")


_NON_CONTENT_PREFIXES = (
    "/preferences/",
    "/admin",
    "/account/",
    "/auth/",
    "/captcha/",
    "/login",
    "/logout",
    "/register",
    "/change-password",
    "/profile",
    "/notifications",
    "/api/front/notifications",
    "/static/demos/",
)


_PUBLIC_READ_ENDPOINTS = {
    "index",
    "news_list",
    "news_detail",
    "matches_list",
    "match_detail",
    "match_detailed_stats",
    "match_live",
    "results_list",
    "events_list",
    "event_detail",
    "event_stats",
    "event_mvp_poster",
    "event_award_poster",
    "players_list",
    "player_detail",
    "player_compare",
    "player_stats_detail",
    "stats_page",
    "stats_overview_detail",
    "predictions_page",
    "awards_page",
    "teams_list",
    "team_detail",
    "dashboard",
    "forum_index",
    "forum_thread",
    "games_page",
    "search",
    "api_search",
    "sitemap",
    "match_poster",
    "match_report",
    "api_live_match",
    "api_broadcast_matches",
    "api_broadcast_events",
    "api_broadcast_event",
    "api_broadcast_current",
    "api_broadcast_match",
    "api_front_home",
    "api_front_matches",
    "api_front_features",
    "api_front_news",
    "api_front_news_detail",
    "api_front_results",
    "api_front_match_detail",
    "api_front_events",
    "api_front_event_detail",
    "api_front_players",
    "api_front_player_detail",
    "api_front_teams",
    "api_front_stats_overview",
    "api_front_dashboard",
    "api_front_predictions",
    "api_front_forum",
    "current_csrf_token",
    "user_logout",
    "admin.admin_logout",
}


_INGEST_PATHS = {"/api/gsi/receive", "/api/gotv/stats"}


_PUBLIC_FORM_PATHS = frozenset(
    {
        "/preferences/language",
        "/login",
        "/register",
        "/change-password",
        "/admin/login",
        "/auth/email/send-code",
        "/auth/email/verify-code",
    }
)


_PUBLIC_FORM_LIMIT = 256 * 1024


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


def _reject_cross_site_writes():
    """Block browser form posts arriving from an unrelated website."""
    if request.method in ("GET", "HEAD", "OPTIONS") or _is_ingest_path(request.path):
        return None
    if request.headers.get("Sec-Fetch-Site", "").lower() != "cross-site":
        return None
    if request.path.startswith("/api/") or request.is_json:
        return jsonify({"success": False, "error": "已拒绝跨站请求"}), 403
    abort(403)


def _block_public_demo_static():
    """旧公开地址继续返回 404；原件只允许通过比赛的下载入口读取。"""
    filename = (request.view_args or {}).get("filename", "")
    parts = str(filename).replace("\\", "/").split("/")
    if os.name == "nt":
        parts = [part if part in {".", ".."} else part.rstrip(" .") for part in parts]
    normalized = posixpath.normpath("/".join(parts))
    if request.endpoint == "static" and normalized.split("/", 1)[0].casefold() == "demos":
        abort(404)


def _clear_user_session():
    for key in (
        "user_id",
        "user_username",
        "group_username_required",
        "profile_completion_required",
    ):
        session.pop(key, None)


def _require_site_login():
    """访客可只读浏览；任何会修改数据的操作仍要求已审核账号。"""
    path = request.path
    if path in _PUBLIC_PATHS or _is_ingest_path(path) or path.startswith(_PUBLIC_PREFIXES):
        return None
    if "admin_id" in session:
        try:
            validate_admin_session()
        except Exception:
            logger.exception("检查管理员权限失败")
            response = jsonify(
                {
                    "ok": False,
                    "success": False,
                    "error": "暂时无法确认管理员权限，请稍后重试",
                }
            )
            response.status_code = 503
            response.headers["Retry-After"] = "5"
            return response
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
            # 保留登录，但无法确认审核结果时不能继续受限操作。
            if (
                request.method in ("GET", "HEAD", "OPTIONS")
                and request.endpoint in _PUBLIC_READ_ENDPOINTS
            ):
                return None
            error = "暂时无法确认账号权限，请稍后重试"
            if (
                path.startswith("/api/")
                or request.is_json
                or request.headers.get("X-Requested-With") == "XMLHttpRequest"
            ):
                response = jsonify({"ok": False, "success": False, "error": error})
            else:
                response = current_app.make_response(error)
            response.status_code = 503
            response.headers["Retry-After"] = "5"
            return response
        finally:
            if conn is not None:
                conn.close()
        if user and approval_status(user) == "approved":
            g.current_user_row = user
            if profile_completion_required(user):
                session["profile_completion_required"] = True
            else:
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


def _add_no_cache_headers(response):
    """页面不缓存 + 慢查询记录"""
    import logging as _logging
    import time as _time

    start = getattr(g, "_start_time", None) or getattr(request, "_start_time", None)
    if start:
        elapsed = _time.time() - start
        if elapsed > 0.5:
            _logging.getLogger("80gotv").warning(
                "慢查询: %s %s (%.2fs)", request.method, request.path, elapsed
            )
    request_id = getattr(g, "request_id", None)
    if request_id:
        response.headers["X-Request-ID"] = request_id
    if request.endpoint == "frontend_asset" and response.status_code in (200, 206, 304):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif request.path.startswith(("/static/", "/resources/")) and response.status_code in (
        200,
        206,
        304,
    ):
        if request.path.endswith((".css", ".js")):
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
    if (
        response.status_code >= 400
        or request.path.startswith(_NON_CONTENT_PREFIXES)
        or request.endpoint == "download_demo"
    ):
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
    response.headers["Cross-Origin-Resource-Policy"] = "same-site"
    response.headers["Origin-Agent-Cluster"] = "?1"
    production = bool(current_app.config.get("IS_PRODUCTION"))
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
    if current_app.config.get("SESSION_COOKIE_SECURE"):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


def _csrf_before_request():
    if "csrf_token" not in session:
        session["csrf_token"] = uuid.uuid4().hex


def _require_profile_completion_before_request():
    if not session.get("profile_completion_required"):
        return None
    if session.get("admin_id") and request.path.startswith("/admin"):
        return None
    if request.endpoint in {
        "complete_account_profile",
        "set_site_language",
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
    return redirect(safe_redirect_target(url_for("index")))
