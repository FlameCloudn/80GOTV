"""The caller owns one SQLite transaction for each registration or roster command."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager


class SliceError(ValueError):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


@contextmanager
def write(conn: sqlite3.Connection) -> Iterator[None]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def require_admin(conn: sqlite3.Connection, admin_id: int | None) -> None:
    if (
        admin_id is None
        or not conn.execute("SELECT 1 FROM admins WHERE id=?", (admin_id,)).fetchone()
    ):
        raise SliceError("需要有权限的赛事管理员", 403)
