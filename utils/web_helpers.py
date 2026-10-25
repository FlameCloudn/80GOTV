"""
共享网页请求辅助函数：登录检查和表单安全检查。
"""

import hmac
import logging
from functools import wraps
from urllib.parse import urlsplit, urlunsplit

from flask import current_app, flash, g, jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from models import get_db

logger = logging.getLogger("80gotv")
CSRF_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _expects_json_response():
    path = request.path
    return (
        request.is_json
        or path.startswith("/api/")
        or "/api/" in path
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
    )


def safe_redirect_target(default):
    """只允许跳回本站路径，避免被外部地址带走。"""
    target = request.referrer
    if not target:
        return default
    try:
        parsed = urlsplit(target)
        request_netloc = urlsplit(request.host_url).netloc
    except ValueError:
        return default
    if parsed.netloc and parsed.netloc != request_netloc:
        return default
    if (
        (parsed.scheme and parsed.scheme not in ("http", "https"))
        or parsed.path.startswith("//")
        or "\\" in target
    ):
        return default
    return urlunsplit(("", "", parsed.path or "/", parsed.query, parsed.fragment))


def hash_bp_password(password):
    """用不可逆方式保存 BP 密码。"""
    return generate_password_hash(password) if password else None


def is_hashed_bp_password(password):
    return bool(password and password.startswith(("scrypt:", "pbkdf2:")))


def check_bp_password(stored_password, provided_password):
    """兼容旧的明文 BP 密码，成功验证后可升级保存格式。"""
    if not stored_password or not provided_password:
        return False
    if is_hashed_bp_password(stored_password):
        return check_password_hash(stored_password, provided_password)
    return hmac.compare_digest(str(stored_password), str(provided_password))


def validate_admin_session():
    """确认会话中的管理员仍存在；同一请求内只查询一次。"""
    admin_id = session.get("admin_id")
    cached = getattr(g, "_admin_session_validation", None)
    if cached is not None and cached[0] == admin_id:
        return cached[1]

    if admin_id is None:
        session.pop("admin_username", None)
        g._admin_session_validation = (None, False)
        return False

    conn = get_db()
    try:
        admin = conn.execute("SELECT id FROM admins WHERE id=?", (admin_id,)).fetchone()
    finally:
        conn.close()

    valid = bool(admin)
    if not valid:
        session.pop("admin_id", None)
        session.pop("admin_username", None)
    g._admin_session_validation = (admin_id, valid)
    return valid


def admin_required(f):
    """要求当前会话对应的管理员账号仍存在。"""

    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            valid_admin = validate_admin_session()
        except Exception:
            logger.exception("检查管理员权限失败")
            response = current_app.make_response(
                jsonify({"success": False, "error": "暂时无法确认管理员权限，请稍后重试"})
                if _expects_json_response()
                else ("暂时无法确认管理员权限，请稍后重试", 503)
            )
            response.status_code = 503
            response.headers["Retry-After"] = "5"
            return response
        if not valid_admin:
            if _expects_json_response():
                return jsonify({"success": False, "error": "请先登录管理员账号"}), 401
            return redirect(url_for("admin.admin_login"))
        return f(*args, **kwargs)

    return decorated


def user_required(f):
    """要求普通用户已登录。"""

    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("请先登录", "error")
            return redirect(url_for("user_login"))
        return f(*args, **kwargs)

    return decorated


def csrf_required(f):
    """拒绝缺少页面安全令牌的修改请求。"""

    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method in CSRF_METHODS:
            token = request.form.get("csrf_token", "") or request.headers.get("X-CSRF-Token", "")
            expected = session.get("csrf_token", "")
            if not token or not expected or not hmac.compare_digest(str(token), str(expected)):
                logger.debug(
                    "[CSRF FAIL] route=%s form_keys=%s",
                    request.path,
                    list(request.form.keys()),
                )
                if _expects_json_response():
                    return jsonify(
                        {"success": False, "error": "CSRF token 无效，请刷新页面后重试"}
                    ), 403
                flash("CSRF token 无效，请刷新页面后重试", "error")
                return redirect(safe_redirect_target(url_for("index")))
        return f(*args, **kwargs)

    return decorated
