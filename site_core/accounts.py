"""登录账号的 Steam 归属、审核状态和校内资料。事务由调用方提交。"""


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
    password_hash: str,
    email: str | None,
    school_status: int,
    group_username: str,
    avatar: str | None,
):
    """管理员显式建号；与新增选手同一事务，不替换已有普通账号。"""
    claimable = _claimable_account(conn, steam_id)
    values = (
        username,
        password_hash,
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
