"""Per-viewer private player nicknames."""

import sqlite3

MAX_PLAYER_REMARK_LENGTH = 40


def validate_player_remark(value):
    remark = str(value or "").strip()
    if not remark:
        return "", ""
    if len(remark) > MAX_PLAYER_REMARK_LENGTH:
        return "", "note_too_long"
    if any(ord(character) < 32 or ord(character) == 127 for character in remark):
        return "", "note_invalid_characters"
    return remark, ""


def read_private_remarks(conn, owner_user_id):
    remarks = {"users": {}, "players": {}}
    try:
        rows = conn.execute(
            """
            SELECT r.target_user_id, r.remark, p.id AS target_player_id
            FROM player_private_remarks r
            LEFT JOIN users u ON u.id=r.target_user_id
            LEFT JOIN players p ON p.steam_id=u.steam_id64
            WHERE r.owner_user_id=?
            """,
            (owner_user_id,),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc).lower():
            raise
        rows = []
    for row in rows:
        remark = str(row["remark"] or "").strip()
        if not remark:
            continue
        remarks["users"][int(row["target_user_id"])] = remark
        if row["target_player_id"] is not None:
            remarks["players"][int(row["target_player_id"])] = remark
    return remarks


def remark_target(conn, player_id):
    return conn.execute(
        """
        SELECT p.id AS player_id, p.nickname, u.id AS user_id, u.username
        FROM players p
        JOIN users u ON u.steam_id64=p.steam_id
        WHERE p.id=?
        ORDER BY COALESCE(u.is_placeholder, 0), u.id DESC
        LIMIT 1
        """,
        (player_id,),
    ).fetchone()


def change_private_remark(conn, owner_user_id, target_user_id, remark):
    if not remark:
        conn.execute(
            "DELETE FROM player_private_remarks WHERE owner_user_id=? AND target_user_id=?",
            (owner_user_id, target_user_id),
        )
        return
    conn.execute(
        """
        INSERT INTO player_private_remarks(
            owner_user_id, target_user_id, remark, updated_at
        ) VALUES(?,?,?,CURRENT_TIMESTAMP)
        ON CONFLICT(owner_user_id, target_user_id) DO UPDATE SET
            remark=excluded.remark,
            updated_at=CURRENT_TIMESTAMP
        """,
        (owner_user_id, target_user_id, remark),
    )
