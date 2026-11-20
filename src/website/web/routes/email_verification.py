"""注册邮箱验证码的 HTTP 限流、邮件投递和浏览器凭据。"""

import logging
import re
import secrets
import smtplib
import time

from flask import current_app, jsonify, request, session

from config import Config
from src.website.domains.identity import email_challenges
from src.website.runtime.database import db
from src.website.runtime.mail import send_registration_email
from src.website.runtime.rate_limiter import rate_limit
from src.website.web.access import csrf_required
from src.website.web.routing import site_routes

logger = logging.getLogger("80gotv")


def _get_verified_registration_email():
    challenge_id = (session.get("registration_email_verified") or {}).get("challenge_id")
    if isinstance(challenge_id, str) and challenge_id:
        with db() as conn:
            email = email_challenges.verified_email(conn, challenge_id)
        if email:
            return email
    session.pop("registration_email_verified", None)
    return ""


def _consume_verified_registration_email(conn, email):
    challenge_id = (session.get("registration_email_verified") or {}).get("challenge_id")
    return email_challenges.consume(conn, challenge_id, email)


@site_routes.route("/auth/email/send-code", methods=["POST"])
@csrf_required
def send_registration_email_code():
    email = email_challenges.normalize_email(request.form.get("email", ""))
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
    if not rate_limit(f"register_email_cooldown:{email}", 1, 60, by_ip=True):
        return jsonify({"success": False, "error": "请等待 60 秒后再发送"}), 429

    with db() as conn:
        if email_challenges.email_registered(conn, email):
            return jsonify({"success": False, "error": "该邮箱已经注册"}), 409

    code = f"{100000 + secrets.randbelow(900000):06d}"
    challenge_id = secrets.token_urlsafe(32)
    try:
        send_registration_email(email, code)
    except (OSError, smtplib.SMTPException, RuntimeError):
        logger.exception("注册验证码邮件发送失败")
        return jsonify({"success": False, "error": "邮件发送失败，请稍后再试"}), 503

    with db() as conn:
        email_challenges.issue(
            conn, challenge_id, email, code, current_app.secret_key or Config.SECRET_KEY
        )
    session["register_email_challenge"] = {"id": challenge_id}
    session["register_email"] = email
    session["register_email_last_sent"] = time.time()
    if _get_verified_registration_email() != email:
        session.pop("registration_email_verified", None)
    return jsonify({"success": True, "message": "验证码已发送，请检查收件箱"})


@site_routes.route("/auth/email/verify-code", methods=["POST"])
@csrf_required
def verify_registration_email_code():
    email = email_challenges.normalize_email(request.form.get("email", ""))
    code = request.form.get("code", "").strip()
    challenge = session.get("register_email_challenge") or {}
    if not email or not re.fullmatch(r"\d{6}", code):
        return jsonify({"success": False, "error": "请输入邮箱和六位验证码"}), 400
    challenge_id = challenge.get("id")
    with db() as conn:
        error, discard = email_challenges.verify(
            conn, challenge_id, email, code, current_app.secret_key or Config.SECRET_KEY
        )
    if discard:
        session.pop("register_email_challenge", None)
    if error:
        return jsonify({"success": False, "error": error}), 400
    session["registration_email_verified"] = {"email": email, "challenge_id": challenge_id}
    session["register_email"] = email
    return jsonify({"success": True, "message": "邮箱验证成功"})
