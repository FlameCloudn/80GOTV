"""Expose own private player nicknames while rendering the current request."""

from contextlib import closing

from flask import g, has_request_context, session

from src.website.domains.directory.player_remark_service import read_private_remarks
from src.website.runtime.database import get_db


def _load_request_remarks():
    if not has_request_context():
        return {"users": {}, "players": {}}
    cached = getattr(g, "private_player_remarks", None)
    if cached is not None:
        return cached

    owner_user_id = session.get("user_id")
    if owner_user_id:
        with closing(get_db()) as conn:
            remarks = read_private_remarks(conn, owner_user_id)
    else:
        remarks = {"users": {}, "players": {}}
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
