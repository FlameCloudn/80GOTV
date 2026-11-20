"""Read historical or managed entries without exposing private account fields."""

from src.website.domains.events import reads as event_reads
from src.website.domains.events.status import add_effective_event_status
from src.website.runtime.host import is_managed_event


def registration_user(conn, user_id):
    if not user_id:
        return None
    return conn.execute(
        "SELECT id, username, group_username, steam_id64 FROM users WHERE id=?", (user_id,)
    ).fetchone()


def registration_panel(conn, event_id, user_id):
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    event = add_effective_event_status(event_reads.public_event(conn, event)) if event else None
    current_user = registration_user(conn, user_id)
    current_id = current_user["id"] if current_user else None
    individual = _load_individual_registrations(conn, event_id, current_id) if event else None
    return {
        "event": event,
        "current_user": current_user,
        "registrations": _load_event_registrations(conn, event_id) if event else [],
        "individual_registration": individual,
        "substitute_registration_open": bool(
            event and event["effective_event_status"] != "completed"
        ),
        **(_managed_registration_flags(conn, event, individual) if event else {}),
    }


def _load_event_registrations(conn, event_id):
    if is_managed_event(conn, event_id):
        return event_reads.registration_groups(conn, event_id)
    regs = conn.execute(
        """
        SELECT r.*, u.username AS creator_name,
               CASE WHEN COALESCE(u.is_bashizhong_student, 1)<>0
                    THEN u.group_username END
                   AS creator_group_username
        FROM event_registrations r
        LEFT JOIN users u ON r.creator_user_id=u.id
        WHERE r.event_id=? AND r.status='pending'
        ORDER BY r.created_at DESC
        """,
        (event_id,),
    ).fetchall()
    if not regs:
        return []
    registration_ids = [reg["id"] for reg in regs]
    placeholders = ",".join("?" for _ in registration_ids)
    slot_rows = conn.execute(
        f"""
        SELECT s.*, u.username AS user_username,
               CASE WHEN COALESCE(u.is_bashizhong_student, 1)<>0
                    THEN u.group_username END
                   AS group_username
        FROM event_registration_slots s
        LEFT JOIN users u ON u.id=s.user_id
        WHERE s.registration_id IN ({placeholders})
        ORDER BY s.registration_id, s.slot_index
        """,
        tuple(registration_ids),
    ).fetchall()
    slots_by_registration = {registration_id: [] for registration_id in registration_ids}
    for slot in slot_rows:
        slots_by_registration[slot["registration_id"]].append(dict(slot))
    return [
        {
            "info": dict(registration),
            "slots": slots_by_registration[registration["id"]],
        }
        for registration in regs
    ]


def _load_individual_registrations(conn, event_id, current_user_id=None):
    if is_managed_event(conn, event_id):
        return event_reads.individual_registrations(conn, event_id, current_user_id)
    rows = conn.execute(
        """
        SELECT ir.*,
               preferred.team_name AS preferred_team_name,
               COALESCE(NULLIF(u.username, ''), ir.player_name) AS website_name,
               COALESCE(
                   CASE WHEN COALESCE(u.is_bashizhong_student, 1)<>0
                        THEN NULLIF(TRIM(u.group_username), '') END,
                   NULLIF((
                       SELECT TRIM(p.group_username_override) FROM players p
                       WHERE p.steam_id=ir.steam_id
                         AND COALESCE(p.is_bashizhong_student, 1)<>0
                       ORDER BY p.id LIMIT 1
                   ), ''),
                   ''
               ) AS group_username,
               COALESCE(
                   NULLIF(u.avatar, ''),
                   NULLIF((
                       SELECT p.avatar FROM players p
                       WHERE p.steam_id=ir.steam_id
                       ORDER BY p.id LIMIT 1
                   ), '')
               ) AS avatar,
               EXISTS(
                   SELECT 1
                   FROM event_registration_slots ers
                   JOIN event_registrations er ON er.id=ers.registration_id
                   WHERE er.event_id=ir.event_id
                     AND er.status='pending'
                     AND ers.user_id=ir.user_id
               ) AS is_formal_member
        FROM event_individual_registrations ir
        LEFT JOIN users u ON u.id=ir.user_id
        LEFT JOIN event_registrations preferred
          ON preferred.id=ir.preferred_registration_id
         AND preferred.event_id=ir.event_id
         AND preferred.status='pending'
        WHERE ir.event_id=?
        ORDER BY
            CASE ir.assignment_status
                WHEN 'assigned' THEN 0
                WHEN 'reserve' THEN 1
                ELSE 2
            END,
            COALESCE(ir.team_number, 999),
            ir.created_at,
            ir.id
        """,
        (event_id,),
    ).fetchall()
    entries = [dict(row) for row in rows]
    teams = {}
    reserves = []
    pending = []
    formal_members = []
    current_entry = None
    for entry in entries:
        if current_user_id and entry["user_id"] == current_user_id:
            current_entry = entry
        if entry["is_formal_member"]:
            formal_members.append(entry)
            continue
        if entry["assignment_status"] == "assigned" and entry["team_number"]:
            teams.setdefault(entry["team_number"], []).append(entry)
        elif entry["assignment_status"] == "reserve":
            reserves.append(entry)
        else:
            pending.append(entry)
    return {
        "entries": entries,
        "teams": [
            {"number": team_number, "players": players}
            for team_number, players in sorted(teams.items())
        ],
        "reserves": reserves,
        "pending": pending,
        "formal_members": formal_members,
        "current_entry": current_entry,
        "has_assignment": any(entry["assignment_status"] != "pending" for entry in entries),
        "has_formal_members": bool(formal_members),
        "can_randomize": not formal_members,
        "count": len(entries),
        "individual_count": len(entries) - len(reserves),
        "substitute_count": len(reserves),
    }


def _managed_registration_flags(conn, event, individual):
    if not is_managed_event(conn, event["id"]):
        return {}
    closed = event["effective_event_status"] == "completed" or bool(
        conn.execute(
            "SELECT archived_at IS NOT NULL FROM event_registration_control WHERE event_id=?",
            (event["id"],),
        ).fetchone()[0]
    )
    if closed:
        event["registration_open"] = 0
    if event["registration_open"]:
        individual["has_assignment"] = any(
            e["assignment_status"] == "assigned" for e in individual["entries"]
        )
    return dict(
        entrant_slice_event=True,
        entrant_registration_closed=closed,
        entrant_reserve_signup_open=not closed,
        entrant_reserve_only=not closed
        and not event["registration_open"]
        and event["effective_event_status"] != "upcoming",
    )
