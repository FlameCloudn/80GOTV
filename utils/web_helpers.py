"""
共享网页请求辅助函数：登录检查和表单安全检查。
"""

import hmac
import logging
from functools import wraps
from urllib.parse import urlsplit, urlunsplit

from flask import flash, jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

logger = logging.getLogger("80gotv")


def safe_redirect_target(default):
    """只允许跳回本站路径，避免被外部地址带走。"""
    target = request.referrer
    if not target:
        return default
    parsed = urlsplit(target)
    if parsed.netloc and parsed.netloc != urlsplit(request.host_url).netloc:
        return default
    if parsed.scheme and parsed.scheme not in ("http", "https"):
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


def admin_required(f):
    """要求管理员已登录。"""

    @wraps(f)
    def decorated(*args, **kwargs):
        if "admin_id" not in session:
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
        if request.method in ("POST", "PUT", "DELETE"):
            token = request.form.get("csrf_token", "") or request.headers.get("X-CSRF-Token", "")
            expected = session.get("csrf_token", "")
            if not token or not expected or not hmac.compare_digest(str(token), str(expected)):
                logger.debug(
                    "[CSRF FAIL] route=%s form_keys=%s referrer=%s",
                    request.path,
                    list(request.form.keys()),
                    request.referrer,
                )
                if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return jsonify(
                        {"success": False, "error": "CSRF token 无效，请刷新页面后重试"}
                    ), 403
                flash("CSRF token 无效，请刷新页面后重试", "error")
                return redirect(safe_redirect_target(url_for("index")))
        return f(*args, **kwargs)

    return decorated
