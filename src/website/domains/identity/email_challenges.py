"""邮箱凭据属于账号：验证时占用一次尝试，注册事务成功后才消费凭据。"""

import hashlib
import hmac
import re
import time

from src.website.runtime.database import write_transaction

CODE_MAX_AGE = 10 * 60
VERIFIED_MAX_AGE = 30 * 60


def normalize_email(value):
    email = str(value or "").strip().lower()
    if len(email) > 254 or not re.fullmatch(
        r"[^@\s]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+",
        email,
    ):
        return ""
    return email


def _challenge_key(challenge_id):
    return hashlib.sha256(str(challenge_id or "").encode()).hexdigest()


def _digest(secret, challenge_id, email, code):
    value = f"{challenge_id}:{email}:{code}".encode()
    return hmac.new(str(secret).encode(), value, hashlib.sha256).hexdigest()


def email_registered(conn, email):
    return (
        conn.execute("SELECT 1 FROM users WHERE LOWER(email)=LOWER(?)", (email,)).fetchone()
        is not None
    )


def issue(conn, challenge_id, email, code, secret):
    now = time.time()
    conn.execute(
        "UPDATE email_verification_challenges SET consumed_at=? "
        "WHERE email=? AND verified_at IS NULL AND consumed_at IS NULL",
        (now, email),
    )
    conn.execute(
        "INSERT INTO email_verification_challenges(id,email,digest,expires_at) VALUES(?,?,?,?)",
        (
            _challenge_key(challenge_id),
            email,
            _digest(secret, challenge_id, email, code),
            now + CODE_MAX_AGE,
        ),
    )


def verify(conn, challenge_id, email, code, secret):
    """Return (error, discard_browser_challenge); a rejected attempt must still be recorded."""
    with write_transaction(conn):
        row = conn.execute(
            "SELECT email,digest,attempts,expires_at,consumed_at,verified_at FROM email_verification_challenges WHERE id=?",
            (_challenge_key(challenge_id),),
        ).fetchone()
        now = time.time()
        if (
            not row
            or row["expires_at"] < now
            or row["consumed_at"] is not None
            or row["verified_at"] is not None
            or row["attempts"] >= 5
        ):
            return "验证码已失效，请重新发送", True
        if not hmac.compare_digest(email, row["email"]):
            return "邮箱与验证码不匹配", False
        attempts = row["attempts"] + 1
        correct = hmac.compare_digest(_digest(secret, challenge_id, email, code), row["digest"])
        exhausted = not correct and attempts >= 5
        conn.execute(
            "UPDATE email_verification_challenges SET attempts=?,verified_at=?,consumed_at=? WHERE id=?",
            (
                attempts,
                now if correct else None,
                now if exhausted else None,
                _challenge_key(challenge_id),
            ),
        )
    if correct:
        return None, True
    return ("错误次数过多，请重新发送验证码", True) if exhausted else ("邮箱验证码错误", False)


def verified_email(conn, challenge_id):
    if not isinstance(challenge_id, str) or not challenge_id:
        return ""
    row = conn.execute(
        """SELECT email FROM email_verification_challenges
           WHERE id=? AND verified_at>=? AND consumed_at IS NULL""",
        (_challenge_key(challenge_id), time.time() - VERIFIED_MAX_AGE),
    ).fetchone()
    return normalize_email(row["email"]) if row else ""


def consume(conn, challenge_id, email):
    if not isinstance(challenge_id, str) or not challenge_id:
        return False
    now = time.time()
    cursor = conn.execute(
        """UPDATE email_verification_challenges SET consumed_at=?
           WHERE id=? AND email=? AND verified_at>=? AND consumed_at IS NULL""",
        (now, _challenge_key(challenge_id), email, now - VERIFIED_MAX_AGE),
    )
    return cursor.rowcount == 1
