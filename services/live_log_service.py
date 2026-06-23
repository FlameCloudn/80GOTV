"""Long-term Game Log storage and admin live-status helpers."""

import json
from datetime import datetime, timezone


def _json_text(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def persist_live_match_events(conn, match_id, state):
    """Copy volatile GSI Game Log entries into the long-term timeline table."""
    saved = 0
    map_name = str((((state.get("gsi") or {}).get("map") or {}).get("name")) or "")
    groups = (
        ("kill", state.get("kill_events", [])),
        ("plant", state.get("bomb_events", [])),
        ("round", state.get("round_history", [])),
    )
    for event_type, events in groups:
        if not isinstance(events, list):
            continue
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                continue
            round_num = int(event.get("round", 0) or 0)
            stored_event = dict(event)
            stored_event.setdefault("map_name", map_name)
            if event_type == "round":
                event_key = f"round-{map_name}-{round_num}"
            else:
                event_key = str(event.get("id") or f"{event_type}-{round_num}-{index}")
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO live_match_events(
                    match_id, event_key, event_type, round_num, payload
                ) VALUES(?,?,?,?,?)
            """,
                (match_id, event_key, event_type, round_num, _json_text(stored_event)),
            )
            if cursor.rowcount and cursor.rowcount > 0:
                saved += 1
    return saved


def load_match_timeline(conn, match_id):
    """Return saved Game Log entries in the order they arrived."""
    rows = conn.execute(
        """
        SELECT event_type, round_num, payload, created_at
        FROM live_match_events
        WHERE match_id=?
        ORDER BY id
    """,
        (match_id,),
    ).fetchall()
    timeline = []
    for row in rows:
        try:
            payload = json.loads(row["payload"] or "{}")
        except (TypeError, ValueError):
            payload = {}
        payload["type"] = row["event_type"]
        payload["round"] = row["round_num"]
        payload["created_at"] = row["created_at"]
        timeline.append(payload)
    return timeline


def record_ingest_status(conn, source, status, message="", match_id=None, map_name=""):
    """Store the latest receiver result for the admin status page."""
    conn.execute(
        """
        INSERT INTO live_ingest_status(source, status, message, match_id, map_name, received_at)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(source) DO UPDATE SET
            status=excluded.status,
            message=excluded.message,
            match_id=excluded.match_id,
            map_name=excluded.map_name,
            received_at=excluded.received_at
    """,
        (
            str(source or ""),
            str(status or ""),
            str(message or ""),
            match_id,
            str(map_name or ""),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
