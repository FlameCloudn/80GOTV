"""Per-viewer private player nicknames."""

import sqlite3

from flask import g, has_request_context, session

from models import get_db

MAX_PLAYER_REMARK_LENGTH = 40


def validate_player_remark(value):
    remark = str(value or "").strip()
    if not remark:
        return "", ""
    if len(remark) > MAX_PLAYER_REMARK_LENGTH:
        return "", f"备注最多 {MAX_PLAYER_REMARK_LENGTH} 个字符"
    if any(ord(character) < 32 or ord(character) == 127 for character in remark):
        return "", "备注不能包含换行或控制字符"
    return remark, ""


def _load_request_remarks():
    if not has_request_context():
        return {"users": {}, "players": {}}
    cached = getattr(g, "private_player_remarks", None)
    if cached is not None:
        return cached

    remarks = {"users": {}, "players": {}}
    owner_user_id = session.get("user_id")
    if owner_user_id:
        conn = get_db()
        try:
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
        finally:
            conn.close()
        for row in rows:
            remark = str(row["remark"] or "").strip()
            if not remark:
                continue
            remarks["users"][int(row["target_user_id"])] = remark
            if row["target_player_id"] is not None:
                remarks["players"][int(row["target_player_id"])] = remark

    g.private_player_remarks = remarks
    return remarks


def private_remark_for_user(target_user_id):
    if target_user_id is None:
        return ""
    try:
        target_user_id = int(target_user_id)
    except (TypeError, ValueError):
        return ""
    return _load_request_remarks()["users"].get(target_user_id, "")


def private_remark_for_player(target_player_id):
    if target_player_id is None:
        return ""
    try:
        target_player_id = int(target_player_id)
    except (TypeError, ValueError):
        return ""
    return _load_request_remarks()["players"].get(target_player_id, "")


def private_name_for_user(target_user_id, fallback):
    return private_remark_for_user(target_user_id) or str(fallback or "")


def private_name_for_player(target_player_id, fallback):
    return private_remark_for_player(target_player_id) or str(fallback or "")


def private_user_identity(target_user_id, username, group_username=""):
    remark = private_remark_for_user(target_user_id)
    if remark:
        return remark, ""
    return str(username or ""), str(group_username or "")


def private_player_identity(target_player_id, nickname, group_username=""):
    remark = private_remark_for_player(target_player_id)
    if remark:
        return remark, ""
    return str(nickname or ""), str(group_username or "")
