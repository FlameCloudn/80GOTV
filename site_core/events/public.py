"""一届比赛的正式分队、确认和赛前调整；所有写操作共用调用方的写事务。"""

import json
import sqlite3
import time
from collections import defaultdict
from datetime import datetime, timezone

from site_core.host import HostError, has_event_schema, write

from .legacy_matches import has_active_play, has_unfinished_binding
from .registration import active_event, create_formed_group, eligible_player, require_admin


def keeps_initial_majority(initial_player_ids, proposed_player_ids):
    initial, proposed = set(initial_player_ids), set(proposed_player_ids)
    return (
        len(initial_player_ids) == len(initial) == 5
        and len(proposed_player_ids) == len(proposed) == 5
        and len(initial & proposed) >= 3
    )


def _summary(conn, event_id):
    row = conn.execute(
        "SELECT * FROM event_formation_batches WHERE event_id=?", (event_id,)
    ).fetchone()
    if not row:
        raise HostError("这届赛事尚未完成分队", status=409)
    return {
        **dict(row),
        "entrant_ids": [
            r[0]
            for r in conn.execute(
                "SELECT event_entrant_id FROM event_entrants WHERE event_id=? ORDER BY event_entrant_id",
                (event_id,),
            )
        ],
    }


def _admin_event(conn, event_id, admin_id, now):
    require_admin(conn, admin_id)
    active_event(conn, event_id, now)
    return _summary(conn, event_id)


def verify_registered_players(conn, event_id, player_ids):
    for p in player_ids:
        row = conn.execute(
            "SELECT account_id FROM event_signup_entries WHERE event_id=? AND player_id=?",
            (event_id, p),
        ).fetchone()
        if not row or eligible_player(conn, row["account_id"])[0] != p:
            raise HostError("本届报名时的选手身份与当前已核实账号不一致")


def _version(batch, expected_revision):
    if type(expected_revision) is not int or batch["formation_revision"] != expected_revision:
        raise HostError("名单已改变，请重新查看再操作")


def _finish(conn, event_id):
    conn.execute(
        "UPDATE event_formation_batches SET formation_revision=formation_revision+1 WHERE event_id=?",
        (event_id,),
    )
    return _summary(conn, event_id)


def _audit(conn, entrant_id, kind, admin_id, now, reason, before, after):
    if not isinstance(reason, str) or not reason.strip():
        raise HostError("请记录实际协商或变更原因", status=400)
    conn.execute(
        """INSERT INTO event_formation_actions
        (event_entrant_id,action_kind,admin_id,changed_at,reason,before_json,after_json) VALUES(?,?,?,?,?,?,?)""",
        (
            entrant_id,
            kind,
            admin_id,
            now,
            reason.strip(),
            json.dumps(before, ensure_ascii=False),
            json.dumps(after, ensure_ascii=False),
        ),
    )


def form_due_event(conn: sqlite3.Connection, event_id: int, *, now: int):
    if conn.execute(
        "SELECT 1 FROM event_formation_batches WHERE event_id=?", (event_id,)
    ).fetchone():
        return _summary(conn, event_id)
    event = active_event(conn, event_id, now)
    if now < event["registration_deadline"]:
        raise HostError("普通报名尚未截止")
    if conn.execute(
        """SELECT 1 FROM event_signup_reservations s JOIN event_registration_groups g
                    USING(registration_id) WHERE g.event_id=? LIMIT 1""",
        (event_id,),
    ).fetchone():
        raise HostError("有未核实的预留位，不能把预留人当作实际队员或空位")

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
    from services.steam_playtime_service import attach_latest_playtime

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
        raise HostError("个人报名人数不足，无法补齐已报队伍，原报名保留")
    # 原函数不接受没有待分配队的输入。此时完整组照常成队，余数不丢失。
    if fixed or len(candidates) >= 5:
        from services.steam_playtime_service import build_balanced_roster_plan

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
            raise HostError("正式队必须有五个已认领的位置")
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


def record_late_reserve(conn, event_id, player_id):
    conn.execute(
        """INSERT INTO event_reserve_candidates(event_id,player_id)
        SELECT e.event_id,e.player_id FROM event_signup_entries e JOIN event_formation_batches b USING(event_id)
        WHERE e.event_id=? AND e.player_id=? AND (e.registration_origin='independent_reserve' OR
            EXISTS (SELECT 1 FROM event_reserve_candidates c WHERE c.event_id=e.event_id AND c.player_id=e.player_id))
          AND NOT EXISTS (SELECT 1 FROM event_current_members m WHERE m.event_id=e.event_id AND m.player_id=e.player_id)
        ON CONFLICT(event_id,player_id) DO UPDATE SET withdrawn_at=NULL""",
        (event_id, player_id),
    )


def roster(conn, event_id, entrant_id):
    head = conn.execute(
        """SELECT e.event_id,e.event_entrant_id,e.registration_id,b.formation_revision,
        i.confirmed_by,i.confirmed_at,i.confirmed_revision,g.archived_at AS team_archived_at
        FROM event_entrants e JOIN event_formation_batches b USING(event_id) JOIN event_registration_groups g USING(event_id,registration_id)
        LEFT JOIN event_initial_rosters i USING(event_entrant_id) WHERE e.event_entrant_id=? AND e.event_id=?""",
        (entrant_id, event_id),
    ).fetchone()
    if head is None:
        raise HostError("本届参赛方不存在", status=404)
    initial = conn.execute(
        "SELECT player_id FROM event_initial_members WHERE event_entrant_id=? ORDER BY roster_slot",
        (entrant_id,),
    ).fetchall()
    current = conn.execute(
        "SELECT player_id FROM event_current_members WHERE event_entrant_id=? ORDER BY roster_slot",
        (entrant_id,),
    ).fetchall()
    changes = [
        {
            "admin_id": r["admin_id"],
            "reason": r["reason"],
            "changed_at": r["changed_at"],
            "outgoing_player_id": json.loads(r["before_json"])["player_id"],
            "incoming_player_id": json.loads(r["after_json"])["player_id"],
        }
        for r in conn.execute(
            "SELECT * FROM event_formation_actions WHERE event_entrant_id=? AND action_kind='replace' ORDER BY formation_action_id",
            (entrant_id,),
        )
    ]
    return {
        **dict(head),
        "is_frozen": head["confirmed_at"] is not None,
        "initial_player_ids": [r[0] for r in initial],
        "current_player_ids": [r[0] for r in current],
        "changes": changes,
    }


def confirm_initial_rosters(conn, event_id, entrant_ids, *, expected_revision, admin_id, now):
    batch = _admin_event(conn, event_id, admin_id, now)
    if not entrant_ids or len(set(entrant_ids)) != len(entrant_ids):
        raise HostError("请选择不同的本届参赛方", status=400)
    rosters = [roster(conn, event_id, e) for e in entrant_ids]
    if all(r["is_frozen"] for r in rosters):
        # 旧确认可以重试，但不能替另一个管理员确认他没看到的分组。
        if (
            type(expected_revision) is not int
            or not max(r["confirmed_revision"] for r in rosters)
            <= expected_revision
            <= batch["formation_revision"]
        ):
            raise HostError("确认时的名单版本不同，请重新查看已冻结的五人")
        return batch
    _version(batch, expected_revision)
    for r in rosters:
        if r["is_frozen"]:
            continue
        require_pre_series(conn, event_id, r["registration_id"])
        if len(set(r["current_player_ids"])) != 5:
            raise HostError("不能确认未满五人的阵容")
        verify_registered_players(conn, event_id, r["current_player_ids"])
        entrant = r["event_entrant_id"]
        conn.execute(
            "INSERT INTO event_initial_rosters VALUES(?,?,?,?)",
            (entrant, admin_id, now, expected_revision),
        )
        conn.execute(
            """INSERT INTO event_initial_members(event_entrant_id,player_id,roster_slot)
            SELECT event_entrant_id,player_id,roster_slot FROM event_current_members
            WHERE event_entrant_id=? ORDER BY roster_slot""",
            (entrant,),
        )
    return _finish(conn, event_id)


def adjust_formation(conn, event_id, assignments, *, expected_revision, admin_id, reason, now):
    batch = _admin_event(conn, event_id, admin_id, now)
    _version(batch, expected_revision)
    if not assignments:
        raise HostError("未选择要调整的队伍", status=400)
    prior = {e: roster(conn, event_id, e) for e in assignments}
    if any(r["is_frozen"] for r in prior.values()):
        raise HostError("初始名单已冻结，请走赛前换人办理")
    for r in prior.values():
        require_pre_series(conn, event_id, r["registration_id"])
    before = {p for r in prior.values() for p in r["current_player_ids"]}
    players = [p for members in assignments.values() for p in members]
    if any(len(members) != 5 for members in assignments.values()) or len(set(players)) != len(
        players
    ):
        raise HostError("每队必须是互不重占的五名选手")
    verify_registered_players(conn, event_id, players)
    incoming = set(players) - before
    for p in incoming:
        if not conn.execute(
            """SELECT 1 FROM event_reserve_candidates c JOIN event_signup_entries e USING(event_id,player_id)
            WHERE c.event_id=? AND c.player_id=? AND c.assigned_entrant_id IS NULL AND c.withdrawn_at IS NULL
            AND e.registration_origin IN ('group','individual')""",
            (event_id, p),
        ).fetchone():
            raise HostError("不可使用其他队的队员或未报名首发的候补")
    if all(prior[e]["current_player_ids"] == list(members) for e, members in assignments.items()):
        return batch
    for e in assignments:
        conn.execute("DELETE FROM event_current_members WHERE event_entrant_id=?", (e,))
    for e, members in assignments.items():
        conn.executemany(
            "INSERT INTO event_current_members VALUES(?,?,?,?)",
            [(e, event_id, p, n) for n, p in enumerate(members)],
        )
        _audit(
            conn, e, "adjust", admin_id, now, reason, prior[e]["current_player_ids"], list(members)
        )
    conn.executemany(
        "DELETE FROM event_reserve_candidates WHERE event_id=? AND player_id=?",
        [(event_id, p) for p in incoming],
    )
    conn.executemany(
        "INSERT INTO event_reserve_candidates(event_id,player_id) VALUES(?,?)",
        [(event_id, p) for p in before - set(players)],
    )
    return _finish(conn, event_id)


def assign_reserve(
    conn,
    event_id,
    entrant_id,
    player_id,
    *,
    expected_revision,
    admin_id,
    reason,
    now,
    excluded_candidates=None,
):
    batch = _admin_event(conn, event_id, admin_id, now)
    current_roster = roster(conn, event_id, entrant_id)
    options = {
        r["player_id"]: r
        for r in conn.execute(
            """SELECT c.player_id,c.assigned_entrant_id,e.registration_origin
        FROM event_reserve_candidates c JOIN event_signup_entries e USING(event_id,player_id)
        WHERE c.event_id=? AND c.withdrawn_at IS NULL""",
            (event_id,),
        )
    }
    if player_id not in options:
        raise HostError("该选手不是本届候补")
    chosen = options[player_id]
    if chosen["assigned_entrant_id"] == entrant_id:
        return batch
    _version(batch, expected_revision)
    require_pre_series(conn, event_id, current_roster["registration_id"])
    if chosen["assigned_entrant_id"] is not None:
        raise HostError("该候补已有其他队的席位")
    verify_registered_players(conn, event_id, [player_id])
    excluded = excluded_candidates or {}
    if not isinstance(excluded, dict) or any(
        k not in options
        or k == player_id
        or options[k]["assigned_entrant_id"] is not None
        or not isinstance(v, str)
        or not v.strip()
        for k, v in excluded.items()
    ):
        raise HostError("排除原因必须逐一对应未授席候补，不能排除本次入选者", status=400)
    if chosen["registration_origin"] != "independent_reserve":
        if any(
            r["registration_origin"] == "independent_reserve"
            and r["assigned_entrant_id"] is None
            and p not in excluded
            for p, r in options.items()
        ):
            raise HostError("独立入口候补优先；若不适合或不愿意，请逐人记录协商原因")
    _audit(
        conn,
        entrant_id,
        "assign_reserve",
        admin_id,
        now,
        reason,
        None,
        {"player_id": player_id, "excluded_candidates": excluded},
    )
    conn.execute(
        "UPDATE event_reserve_candidates SET assigned_entrant_id=? WHERE event_id=? AND player_id=?",
        (entrant_id, event_id, player_id),
    )
    return _finish(conn, event_id)


def replace_before_series(
    conn,
    event_id,
    entrant_id,
    outgoing_player_id,
    incoming_player_id,
    *,
    expected_revision,
    admin_id,
    reason,
    now,
):
    batch = _admin_event(conn, event_id, admin_id, now)
    _version(batch, expected_revision)
    current_roster = roster(conn, event_id, entrant_id)
    require_pre_series(conn, event_id, current_roster["registration_id"])
    if (
        not current_roster["is_frozen"]
        or outgoing_player_id not in current_roster["current_player_ids"]
    ):
        raise HostError("仅可更换已冻结阵容中的现有队员")
    if not conn.execute(
        """SELECT 1 FROM event_reserve_candidates WHERE event_id=? AND player_id=? AND assigned_entrant_id=?
                        AND withdrawn_at IS NULL""",
        (event_id, incoming_player_id, entrant_id),
    ).fetchone():
        raise HostError("换入者须已获本队替补席位")
    proposed = [
        incoming_player_id if p == outgoing_player_id else p
        for p in current_roster["current_player_ids"]
    ]
    if not keeps_initial_majority(current_roster["initial_player_ids"], proposed):
        raise HostError("新阵容必须至少保留最初五人中的三人")
    verify_registered_players(conn, event_id, proposed)
    _audit(
        conn,
        entrant_id,
        "replace",
        admin_id,
        now,
        reason,
        {"player_id": outgoing_player_id},
        {"player_id": incoming_player_id},
    )
    conn.execute(
        "UPDATE event_current_members SET player_id=? WHERE event_entrant_id=? AND player_id=?",
        (incoming_player_id, entrant_id, outgoing_player_id),
    )
    conn.execute(
        "DELETE FROM event_reserve_candidates WHERE event_id=? AND player_id=?",
        (event_id, incoming_player_id),
    )
    return _finish(conn, event_id)


def require_pre_series(conn, event_id, registration_id):
    if conn.execute(
        "SELECT 1 FROM event_registration_groups WHERE event_id=? AND registration_id=? AND archived_at IS NOT NULL",
        (event_id, registration_id),
    ).fetchone():
        raise HostError("本队已经归档，不能变更名单或增补候补")
    if has_active_play(conn, event_id, registration_id):
        raise HostError("相关系列已有实战记录，不能按普通赛前流程更换队员")


def archive_team(conn, event_id, registration_id, *, admin_id, now, reason):
    batch = _admin_event(conn, event_id, admin_id, now)
    row = conn.execute(
        """SELECT e.event_entrant_id,g.archived_at FROM event_entrants e
        JOIN event_registration_groups g USING(event_id,registration_id) WHERE e.event_id=? AND e.registration_id=?""",
        (event_id, registration_id),
    ).fetchone()
    if row is None:
        raise HostError("本届没有该正式参赛队", 404)
    if row["archived_at"] is not None:
        return batch
    if not isinstance(reason, str) or not reason.strip():
        raise HostError("请填写本队归档原因", 400)
    if has_unfinished_binding(conn, event_id, registration_id, row["event_entrant_id"]):
        raise HostError("本队仍有已绑定且未结束的比赛，请先处理原场次")
    conn.execute(
        "UPDATE event_registration_groups SET archived_at=?,archived_by=?,archive_reason=? WHERE registration_id=?",
        (now, admin_id, reason.strip(), registration_id),
    )
    return _finish(conn, event_id)


def process_due_event(conn, event_id, *, now=None, admin_id=None):
    """Cutoff command shared by the scheduler and both manual retry endpoints."""
    from services.steam_playtime_service import refresh_player_playtimes

    if not has_event_schema(conn):
        raise HostError("此数据库未开放赛前托管")
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
        raise HostError("普通报名尚未截止")
    unresolved = conn.execute(
        """SELECT 1 FROM event_signup_reservations s JOIN event_registration_groups g
                           USING(registration_id) WHERE g.event_id=? LIMIT 1""",
        (event_id,),
    ).fetchone()
    if unresolved:
        raise HostError("有未核实的预留位，须先核实再分队")
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
