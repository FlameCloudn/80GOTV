"""登录账号的 Steam 归属、审核状态和校内资料。事务由调用方提交。"""

import re
from dataclasses import dataclass, field
from typing import Literal

from werkzeug.security import check_password_hash, generate_password_hash

from src.website.domains.directory.player_service import (
    player_linked_by_steam,
    update_player_nickname,
)


def steam_account_source(steam_reference: str, *, registered_only: bool = False) -> str:
    """共享 Steam 账号选择规则；引用只能是调用方写死的列名或 SQL 占位符。"""
    registered = " AND COALESCE(a.is_placeholder,0)=0" if registered_only else ""
    return (
        f"FROM users a WHERE a.steam_id64={steam_reference} AND a.steam_id64<>''{registered} "
        "ORDER BY COALESCE(a.is_placeholder,0)<>0, a.id DESC LIMIT 1"
    )


REGISTERED_PLAYER_ACCOUNT_JOIN = f"LEFT JOIN users u ON u.id=(SELECT a.id {steam_account_source('p.steam_id', registered_only=True)})"

# 后台编辑保留已存昵称，公开页则按校内身份决定是否显示。
MANAGED_PLAYER_IDENTITY_FIELDS = """
    COALESCE(u.is_bashizhong_student, p.is_bashizhong_student) AS managed_is_bashizhong_student,
    COALESCE(NULLIF(TRIM(u.group_username), ''), NULLIF(TRIM(p.group_username_override), ''), '')
        AS managed_group_username
"""


def steam_account(conn, steam_id: str):
    return conn.execute(
        f"SELECT a.id, a.is_placeholder {steam_account_source('?')}",
        (steam_id,),
    ).fetchone()


def approval_status(user) -> str:
    return user["approval_status"] or "approved"


def profile_completion_required(user) -> bool:
    school_status = user["is_bashizhong_student"]
    return school_status is None or (
        bool(school_status) and not str(user["group_username"] or "").strip()
    )


def profile_account(conn, user_id: int):
    return conn.execute(
        """SELECT id, username, steam_id64, avatar, group_username,
                  is_bashizhong_student, is_cheater, created_at FROM users WHERE id=?""",
        (user_id,),
    ).fetchone()


def change_profile_nickname(conn, user, nickname: str) -> Literal["length", "taken"] | None:
    if not 2 <= len(nickname) <= 20:
        return "length"
    if conn.execute(
        "SELECT id FROM users WHERE username=? AND id!=?", (nickname, user["id"])
    ).fetchone():
        return "taken"

    conn.execute("UPDATE users SET username=? WHERE id=?", (nickname, user["id"]))
    player = player_linked_by_steam(conn, user["steam_id64"])
    if player:
        update_player_nickname(conn, player["id"], nickname, "website")
    return None


def set_profile_avatar(conn, user, filename: str):
    conn.execute("UPDATE users SET avatar=? WHERE id=?", (filename, user["id"]))
    player = player_linked_by_steam(conn, user["steam_id64"])
    if player:
        conn.execute("UPDATE players SET avatar=? WHERE id=?", (filename, player["id"]))


def save_school_identity(conn, user, school_status: int, group_username: str):
    nickname = group_username if school_status == 1 else None
    conn.execute(
        """UPDATE users SET is_bashizhong_student=?, group_username=COALESCE(?, group_username)
           WHERE id=?""",
        (school_status, nickname, user["id"]),
    )
    if user["steam_id64"]:
        conn.execute(
            """UPDATE players SET is_bashizhong_student=?,
                       group_username_override=COALESCE(?, group_username_override)
               WHERE steam_id=?""",
            (school_status, nickname, user["steam_id64"]),
        )


def sync_registered_account_identity(conn, steam_id: str, school_status: int, group_username: str):
    if steam_id:
        conn.execute(
            f"""UPDATE users SET is_bashizhong_student=?, group_username=COALESCE(?, group_username)
                WHERE id=(SELECT a.id {steam_account_source("?", registered_only=True)})""",
            (school_status, (group_username or None) if school_status == 1 else None, steam_id),
        )


class SteamAccountInUse(ValueError):
    """这个 Steam 身份已对应一个非占位账号。"""


def _claimable_account(conn, steam_id: str):
    existing = steam_account(conn, steam_id)
    if existing and not existing["is_placeholder"]:
        raise SteamAccountInUse
    return existing


@dataclass(frozen=True)
class InitialPlayerAccount:
    email: str
    password: str = field(repr=False)
    confirmation: str = field(repr=False)


def initial_player_account_error(conn, steam_id: str, nickname: str, account: InitialPlayerAccount):
    if not steam_id:
        return "同时创建登录账号时必须填写 Steam ID"
    if not 8 <= len(account.password) <= 128:
        return "初始密码必须为 8-128 个字符"
    if account.password != account.confirmation:
        return "两次输入的初始密码不一致"
    if account.email and (
        len(account.email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", account.email)
    ):
        return "邮箱格式不正确"

    try:
        placeholder = _claimable_account(conn, steam_id)
    except SteamAccountInUse:
        return "该 Steam ID 已关联其他网站账号"
    placeholder_id = placeholder["id"] if placeholder else None
    duplicate_user = conn.execute(
        "SELECT id FROM users WHERE LOWER(username)=LOWER(?)", (nickname,)
    ).fetchone()
    if duplicate_user and duplicate_user["id"] != placeholder_id:
        return "该昵称已被网站账号使用"
    if account.email:
        duplicate_email = conn.execute(
            "SELECT id FROM users WHERE LOWER(email)=LOWER(?)", (account.email,)
        ).fetchone()
        if duplicate_email and duplicate_email["id"] != placeholder_id:
            return "该邮箱已被其他网站账号使用"
    return None


def submit_verified_registration(
    conn,
    *,
    steam_id: str,
    username: str,
    password_hash: str,
    email: str,
    school_status: int,
    group_username: str,
    avatar: str | None,
) -> tuple[int, bool]:
    """邮箱验证消费与此写入同属一笔事务；注册永远进入审核。"""
    claimable = _claimable_account(conn, steam_id)
    if claimable:
        conn.execute(
            """UPDATE users SET username=?, password_hash=?, email=?, email_verified_at=CURRENT_TIMESTAMP,
                       group_username=?, is_bashizhong_student=?, avatar=COALESCE(?, avatar),
                       is_placeholder=0, approval_status='pending', approval_note=NULL,
                       approved_at=NULL, approved_by=NULL
               WHERE id=?""",
            (
                username,
                password_hash,
                email,
                group_username or None,
                school_status,
                avatar,
                claimable["id"],
            ),
        )
        return claimable["id"], True
    cursor = conn.execute(
        """INSERT INTO users(username, password_hash, email, email_verified_at, group_username,
                             is_bashizhong_student, steam_id64, avatar, is_placeholder, approval_status)
           VALUES(?,?,?,CURRENT_TIMESTAMP,?,?,?,?,0,'pending')""",
        (username, password_hash, email, group_username or None, school_status, steam_id, avatar),
    )
    return cursor.lastrowid, False


def create_approved_player_account(
    conn,
    *,
    steam_id: str,
    username: str,
    password: str,
    email: str | None,
    school_status: int,
    group_username: str,
    avatar: str | None,
):
    """管理员显式建号；与新增选手同一事务，不替换已有普通账号。"""
    claimable = _claimable_account(conn, steam_id)
    values = (
        username,
        generate_password_hash(password),
        email,
        steam_id,
        group_username if school_status == 1 else None,
        school_status,
        avatar,
    )
    if claimable:
        conn.execute(
            """UPDATE users SET username=?, password_hash=?, email=?, steam_id64=?,
                       group_username=?, is_bashizhong_student=?, avatar=COALESCE(?, avatar),
                       is_placeholder=0, approval_status='approved', approval_note=NULL,
                       approved_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (*values, claimable["id"]),
        )
    else:
        conn.execute(
            """INSERT INTO users(username, password_hash, email, steam_id64, group_username,
                                 is_bashizhong_student, avatar, is_placeholder, approval_status, approved_at)
               VALUES(?,?,?,?,?,?,?,0,'approved',CURRENT_TIMESTAMP)""",
            values,
        )


def registered_account_for_player(conn, player_id: int):
    return conn.execute(
        f"""SELECT p.id AS player_id, p.nickname, p.steam_id, u.id AS user_id, u.username
            FROM players p {REGISTERED_PLAYER_ACCOUNT_JOIN} WHERE p.id=?""",
        (player_id,),
    ).fetchone()


def _set_password(conn, user_id: int, password: str):
    conn.execute(
        "UPDATE users SET password_hash=? WHERE id=?",
        (generate_password_hash(password), user_id),
    )


def change_profile_password(
    conn, user_id: int, current_password: str, password: str, confirmation: str
) -> Literal["wrong_password", "too_short", "mismatch"] | None:
    user = conn.execute("SELECT password_hash FROM users WHERE id=?", (user_id,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], current_password):
        return "wrong_password"
    if len(password) < 8:
        return "too_short"
    if password != confirmation:
        return "mismatch"
    _set_password(conn, user_id, password)
    return None


def reset_registered_player_password(
    conn, user_id: int, password: str, confirmation: str
) -> Literal["too_short", "too_long", "mismatch"] | None:
    if len(password) < 8:
        return "too_short"
    if len(password) > 128:
        return "too_long"
    if password != confirmation:
        return "mismatch"
    _set_password(conn, user_id, password)
    return None


def recover_password(conn, steam_id: str, password_hash: str) -> bool:
    """只处理 Steam 验证已通过的请求，修改后保持待审核。"""
    return (
        conn.execute(
            f"""UPDATE users SET password_hash=?, is_placeholder=0, approval_status='pending'
            WHERE id=(SELECT a.id {steam_account_source("?")})""",
            (password_hash, steam_id),
        ).rowcount
        == 1
    )
