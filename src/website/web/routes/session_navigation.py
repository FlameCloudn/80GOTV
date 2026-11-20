"""登录后会话与站内返回地址。"""

import unicodedata
import urllib.parse
import urllib.request
import uuid

from flask import request, session, url_for

from src.website.domains.identity import accounts


def _safe_next_target(default_endpoint="index"):
    """登录后只允许跳回本站内部路径。"""
    target = request.form.get("next") or request.args.get("next") or ""
    fallback = url_for(default_endpoint)
    if not target:
        return fallback
    if not isinstance(target, str) or target != target.strip():
        return fallback

    # Check each decoding layer. Browsers treat backslashes as path separators,
    # and encoded separators or controls can hide a protocol-relative target.
    probe = target
    try:
        while True:
            if any(unicodedata.category(character) == "Cc" for character in probe):
                return fallback
            if "\\" in probe or not probe.startswith("/") or probe.startswith("//"):
                return fallback
            parsed = urllib.parse.urlsplit(probe)
            if parsed.scheme or parsed.netloc or not parsed.path.startswith("/"):
                return fallback

            decoded_path = urllib.parse.unquote(parsed.path, errors="strict")
            decoded_target = urllib.parse.unquote(probe, errors="strict")
            decoded_parts = urllib.parse.urlsplit(decoded_target)
            if (
                decoded_path.count("/") != parsed.path.count("/")
                or decoded_parts.path != decoded_path
            ):
                return fallback
            if decoded_target == probe:
                break
            probe = decoded_target
    except (UnicodeDecodeError, ValueError):
        return fallback

    parsed = urllib.parse.urlsplit(target)
    return urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, parsed.fragment))


def _start_login_session(user=None, admin=None):
    """写入当前登录身份；同一个账号可同时拥有选手身份和管理员权限。"""
    session.clear()
    session.permanent = True
    session["csrf_token"] = uuid.uuid4().hex
    if user:
        session["user_id"] = user["id"]
        session["user_username"] = user["username"]
        if accounts.profile_completion_required(user):
            session["profile_completion_required"] = True
    if admin:
        session["admin_id"] = admin["id"]
        session["admin_username"] = admin["username"]


def _login_destination(next_target):
    return next_target
