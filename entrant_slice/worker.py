"""Process overdue events even when no one visits the website."""

import sqlite3
import time
from contextlib import closing

from .formation import form_due_event
from .sandbox import connect
from .storage import SliceError, write


def process_due(workspace, *, clock=time.time):
    with closing(connect(workspace)) as conn:
        due = [
            r[0]
            for r in conn.execute(
                """SELECT ee.event_id FROM entrant_event ee
            JOIN events e ON ee.event_id=e.id LEFT JOIN formation_batch b ON b.event_id=ee.event_id
            WHERE b.event_id IS NULL AND ee.archived_at IS NULL AND COALESCE(e.status,'')<>'completed'
              AND ee.registration_deadline<=? ORDER BY ee.registration_deadline,ee.event_id""",
                (int(clock()),),
            )
        ]
    formed, blocked = [], {}
    for event_id in due:
        try:
            with closing(connect(workspace)) as conn, write(conn):
                batch = form_due_event(conn, event_id, now=int(clock()))
            formed.append(batch)
        except SliceError as exc:
            blocked[event_id] = str(exc)
        except sqlite3.OperationalError as exc:
            if getattr(exc, "sqlite_errorcode", 0) & 0xFF not in (
                sqlite3.SQLITE_BUSY,
                sqlite3.SQLITE_LOCKED,
            ):
                raise
            blocked[event_id] = "隔离库正被另一项操作写入，留待下次到期检查"
    return formed, blocked
