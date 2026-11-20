"""Form teams at the signup deadline through the worker or the same admin action."""

import sqlite3
import time
from collections import defaultdict
from datetime import datetime, timezone

from src.website.domains.events.roster_management import _summary, verify_registered_players
from src.website.runtime.host import HostError, has_event_schema, write

from .registration import active_event, create_formed_group, require_admin


def form_due_event(conn: sqlite3.Connection, event_id: int, *, now: int):
    if conn.execute(
        "SELECT 1 FROM event_formation_batches WHERE event_id=?", (event_id,)
    ).fetchone():
        return _summary(conn, event_id)
    event = active_event(conn, event_id, now)
    if now < event["registration_deadline"]:
        raise HostError("普通报名尚未截止", code="deadline_not_reached")
    if conn.execute(
        """SELECT 1 FROM event_signup_reservations s JOIN event_registration_groups g
                    USING(registration_id) WHERE g.event_id=? LIMIT 1""",
        (event_id,),
    ).fetchone():
        raise HostError(
            "有未核实的预留位，不能把预留人当作实际队员或空位", code="unverified_reservations"
        )

    groups = conn.execute(
        """SELECT g.registration_id,r.team_name AS display_name FROM event_registration_groups g
        JOIN event_registrations r ON r.id=g.registration_id WHERE g.event_id=? AND g.group_origin='registered'
        ORDER BY r.created_at DESC,g.registration_id""",
        (event_id,),
    ).fetchall()
    entries = [
        dict(row)
        for row in conn.execute(
            """SELECT e.registration_entry_id AS id,e.player_id,e.created_at,
        e.account_id,e.registration_origin,e.registration_id,e.roster_slot,p.steam_id
        FROM event_signup_entries e JOIN players p ON p.id=e.player_id WHERE e.event_id=?
        ORDER BY e.created_at,e.registration_entry_id""",
            (event_id,),
        )
    ]
    from src.website.domains.events.steam_playtime_service import attach_latest_playtime

    entries = attach_latest_playtime(conn, entries, "steam_id")
    members = defaultdict(dict)
    candidates = []
    reserves = []
    for entry in entries:
        origin = entry["registration_origin"]
        if origin == "group":
            members[entry["registration_id"]][entry["roster_slot"]] = entry
        elif origin == "independent_reserve":
            reserves.append(entry["player_id"])
        else:
            candidates.append(entry)
    fixed = [
        {
            "registration_id": g["registration_id"],
            "players": list(members[g["registration_id"]].values()),
        }
        for g in groups
        if len(members[g["registration_id"]]) < 5
    ]
    if sum(5 - len(team["players"]) for team in fixed) > len(candidates):
        raise HostError(
            "个人报名人数不足，无法补齐已报队伍，原报名保留", code="not_enough_to_fill_managed"
        )
    # 原函数不接受没有待分配队的输入。此时完整组照常成队，余数不丢失。
    if fixed or len(candidates) >= 5:
        from src.website.domains.events.steam_playtime_service import build_balanced_roster_plan

        draw = build_balanced_roster_plan(candidates, fixed_teams=fixed, team_size=5)
        individual = {entry["id"]: entry for entry in candidates}
        reserves.extend(individual[k]["player_id"] for k in draw["reserves"])
        used_names = {str(g["display_name"]).casefold() for g in groups}
        number = 1
        for team in draw["teams"]:
            group_id = team["registration_id"]
            added = [individual[k] for k in team["candidate_ids"]]
            if group_id is None:
                while f"个人报名队 {number}".casefold() in used_names:
                    number += 1
                label = f"个人报名队 {number}"
                used_names.add(label.casefold())
                captain = min(added, key=lambda e: (e["created_at"], e["id"]))
                added = [captain, *(entry for entry in added if entry != captain)]
                group_id = create_formed_group(
                    conn, event_id, label, captain_account_id=captain["account_id"], now=now
                )
            roster = members[group_id]
            for slot, entry in zip([n for n in range(5) if n not in roster], added, strict=True):
                roster[slot] = entry
    else:
        reserves.extend(entry["player_id"] for entry in candidates)

    conn.execute("INSERT INTO event_formation_batches VALUES(?,?,1)", (event_id, now))
    conn.executemany(
        "INSERT INTO event_formation_inputs(event_id,player_id,minutes,playtime_status,checked_at) VALUES(?,?,?,?,?)",
        [
            (
                event_id,
                e["player_id"],
                e["cs2_playtime_minutes"],
                e["playtime_status"],
                e["playtime_checked_at"],
            )
            for e in entries
            if e["registration_origin"] != "independent_reserve"
        ],
    )
    for group_id, roster in members.items():
        if set(roster) != set(range(5)):
            raise HostError("正式队必须有五个已认领的位置", code="lineup_requires_five")
        verify_registered_players(conn, event_id, [entry["player_id"] for entry in roster.values()])
        entrant_id = conn.execute(
            "INSERT INTO event_entrants(event_id,registration_id) VALUES(?,?)",
            (event_id, group_id),
        ).lastrowid
        conn.executemany(
            "INSERT INTO event_current_members VALUES(?,?,?,?)",
            [
                (entrant_id, event_id, entry["player_id"], slot)
                for slot, entry in sorted(roster.items())
            ],
        )
    conn.executemany(
        "INSERT INTO event_reserve_candidates(event_id,player_id) VALUES(?,?)",
        [(event_id, p) for p in reserves],
    )
    conn.execute("UPDATE events SET registration_open=0 WHERE id=?", (event_id,))
    return _summary(conn, event_id)


def process_due_event(conn, event_id, *, now=None, admin_id=None):
    """Cutoff command shared by the scheduler and both manual retry endpoints."""
    from src.website.domains.events.steam_playtime_service import refresh_player_playtimes

    if not has_event_schema(conn):
        raise HostError("此数据库未开放赛前托管", code="managed_unavailable")
    if conn.in_transaction:
        raise RuntimeError("截止命令需要未持有写锁的连接")
    if admin_id is not None:
        require_admin(conn, admin_id)
    if conn.execute(
        "SELECT 1 FROM event_formation_batches WHERE event_id=?", (event_id,)
    ).fetchone():
        return _summary(conn, event_id)
    at = int(time.time()) if now is None else now
    event = active_event(conn, event_id, at)
    if at < event["registration_deadline"]:
        raise HostError("普通报名尚未截止", code="deadline_not_reached")
    unresolved = conn.execute(
        """SELECT 1 FROM event_signup_reservations s JOIN event_registration_groups g
                           USING(registration_id) WHERE g.event_id=? LIMIT 1""",
        (event_id,),
    ).fetchone()
    if unresolved:
        raise HostError("有未核实的预留位，须先核实再分队", code="unverified_reservations")
    rows = conn.execute(
        """SELECT p.id,p.steam_id,p.cs2_playtime_minutes,p.playtime_checked_at,p.playtime_status,
                   e.registration_id FROM event_signup_entries e JOIN players p ON p.id=e.player_id
                   WHERE e.event_id=? AND e.registration_origin!='independent_reserve'""",
        (event_id,),
    ).fetchall()
    group_sizes = defaultdict(int)
    for row in rows:
        group_sizes[row["registration_id"]] += 1
    individual = group_sizes.pop(None, 0)
    vacancies = sum(5 - size for size in group_sizes.values())
    if individual >= vacancies and (vacancies or individual >= 5):
        participating = [
            r for r in rows if r["registration_id"] is None or group_sizes[r["registration_id"]] < 5
        ]
        # This existing helper finishes all HTTP before its first UPDATE. The player cache
        # is independent of the immutable input snapshot and remains valid even if formation fails.
        try:
            refresh_player_playtimes(
                conn, participating, now=datetime.fromtimestamp(at, timezone.utc)
            )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    with write(conn):
        if admin_id is not None:
            require_admin(conn, admin_id)
        return form_due_event(conn, event_id, now=int(time.time()) if now is None else now)


def run_due_events_once(conn, *, now=None):
    """Each due event owns its transaction; a blocked one cannot undo another event."""

    if not has_event_schema(conn):
        return [], {}
    limit = int(time.time()) if now is None else now
    due = conn.execute(
        """SELECT c.event_id FROM event_registration_control c JOIN events e ON e.id=c.event_id
                LEFT JOIN event_formation_batches b ON b.event_id=c.event_id WHERE b.event_id IS NULL
                AND c.archived_at IS NULL AND COALESCE(e.status,'')!='completed' AND c.registration_deadline<=?
                ORDER BY c.registration_deadline,c.event_id""",
        (limit,),
    ).fetchall()
    formed, blocked = [], {}
    for (event_id,) in due:
        try:
            formed.append(process_due_event(conn, event_id, now=now))
        except HostError as exc:
            blocked[event_id] = str(exc)
        except sqlite3.OperationalError as exc:
            if getattr(exc, "sqlite_errorcode", 0) & 255 not in (
                sqlite3.SQLITE_BUSY,
                sqlite3.SQLITE_LOCKED,
            ):
                raise
            blocked[event_id] = "数据库忙，等待下一次办理"
    return formed, blocked
