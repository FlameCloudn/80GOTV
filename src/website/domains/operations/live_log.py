"""Long-term Game Log storage and admin live-status helpers."""

import json
from datetime import datetime, timezone

from src.website.domains.operations.projection import live_schema_ready
from src.website.runtime.host import is_managed_match


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
        ("round", state.get("overtime_history", [])),
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
                event_key = f"round-{stored_event['map_name']}-{round_num}"
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


def uses_run_timeline(conn, match_id):
    return is_managed_match(conn, match_id) and live_schema_ready(conn)


def load_run_timeline(conn, match_id, run_id=None):
    """Project only a playing attempt or the attempt retained by the official result."""
    rows = conn.execute(
        """SELECT e.map_run_id,e.event_key,e.event_type,e.round_number,e.payload,s.map_name
           FROM scheduled_maps s JOIN map_runs r USING(scheduled_map_id)
           JOIN live_run_events e USING(map_run_id)
           LEFT JOIN official_map_results o ON o.scheduled_map_id=s.scheduled_map_id
                AND o.map_run_id=r.map_run_id AND o.is_current=1
           WHERE s.match_id=? AND s.is_enabled=1 AND (? IS NULL OR r.map_run_id=?)
             AND (r.status='active' OR (r.status='closed' AND o.map_run_id IS NOT NULL))
           ORDER BY s.map_order,e.round_number,(e.event_type='round'),
                    COALESCE(json_extract(e.payload,'$.captured_at_epoch'),
                             unixepoch(json_extract(e.payload,'$.captured_at'))),e.rowid""",
        (match_id, run_id, run_id),
    )
    timeline = []
    for row in rows:
        event = json.loads(row["payload"])
        event.setdefault("id", row["event_key"])
        event.update(
            type=row["event_type"],
            map_run_id=row["map_run_id"],
            round=row["round_number"],
            round_number=row["round_number"],
            created_at=event.get("captured_at"),
        )
        event.setdefault("map_name", row["map_name"])
        if event["type"] == "death":
            # The report can display a victim without attributing a kill.
            event.update(
                victim=event.get("name"),
                victim_side=event.get("side"),
                victim_steamid=event.get("steamid"),
            )
        timeline.append(event)
    return timeline


def load_match_timeline(conn, match_id):
    if uses_run_timeline(conn, match_id):
        return load_run_timeline(conn, match_id)
    return load_legacy_timeline(conn, match_id)


def load_legacy_timeline(conn, match_id):
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
