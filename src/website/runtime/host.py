"""正常宿主共用的单届权属检查与 SQLite 写事务。"""

import sqlite3

from src.website.runtime.database import write_transaction


class HostError(ValueError):
    def __init__(self, message, status=409, *, code=None, params=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.params = params or {}


def has_event_schema(conn):
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='event_registration_control'"
        ).fetchone()
        is not None
    )


def is_managed_event(conn, event_id):
    return bool(
        event_id
        and has_event_schema(conn)
        and conn.execute(
            "SELECT 1 FROM event_registration_control WHERE event_id=?", (event_id,)
        ).fetchone()
    )


def is_managed_match(conn, match_id):
    return bool(
        match_id
        and has_event_schema(conn)
        and conn.execute(
            """SELECT 1 FROM matches m JOIN event_registration_control c ON c.event_id=m.event_id
           WHERE m.id=?""",
            (match_id,),
        ).fetchone()
    )


PREMATCH_ONLY = "该旧入口不能改写本届比赛数据，请使用本场比赛运营操作。"


def write(conn):
    """托管赛务只在已验证的 SQLite 驱动上开放。"""
    if not isinstance(conn, sqlite3.Connection):
        raise HostError("托管赛前操作仅支持已验证的本机 SQLite 数据库")
    return write_transaction(conn)
