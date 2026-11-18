"""一届比赛的正式分队、确认和赛前调整；所有写操作共用调用方的写事务。"""

import json
import sqlite3
from collections import defaultdict

from .legacy_match_guard import require_pre_series
from .registration import active_event, create_formed_group, eligible_player
from .storage import SliceError, require_admin


def keeps_initial_majority(initial_player_ids, proposed_player_ids):
    initial, proposed = set(initial_player_ids), set(proposed_player_ids)
    return (
        len(initial_player_ids) == len(initial) == 5
        and len(proposed_player_ids) == len(proposed) == 5
        and len(initial & proposed) >= 3
    )


def _summary(conn, event_id):
    row = conn.execute("SELECT * FROM formation_batch WHERE event_id=?", (event_id,)).fetchone()
    if not row:
        raise SliceError("这届赛事尚未完成分队", status=409)
    return {
        **dict(row),
        "entrant_ids": [
            r[0]
            for r in conn.execute(
                "SELECT event_entrant_id FROM event_entrant WHERE event_id=? ORDER BY event_entrant_id",
                (event_id,),
            )
        ],
    }


def _admin_event(conn, event_id, admin_id, now):
    require_admin(conn, admin_id)
    active_event(conn, event_id, now)
    return _summary(conn, event_id)


def _check_players(conn, event_id, player_ids):
    for p in player_ids:
        row = conn.execute(
            "SELECT account_id FROM registration_entry WHERE event_id=? AND player_id=?",
            (event_id, p),
        ).fetchone()
        if not row or eligible_player(conn, row["account_id"])[0] != p:
            raise SliceError("本届报名时的选手身份与当前已核实账号不一致")


def _version(batch, expected_revision):
    if type(expected_revision) is not int or batch["formation_revision"] != expected_revision:
        raise SliceError("名单已改变，请重新查看再操作")


def _finish(conn, event_id):
    conn.execute(
        "UPDATE formation_batch SET formation_revision=formation_revision+1 WHERE event_id=?",
        (event_id,),
    )
    return _summary(conn, event_id)


def _audit(conn, entrant_id, kind, admin_id, now, reason, before, after):
    if not isinstance(reason, str) or not reason.strip():
        raise SliceError("请记录实际协商或变更原因", status=400)
    conn.execute(
        """INSERT INTO formation_action
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
    if conn.execute("SELECT 1 FROM formation_batch WHERE event_id=?", (event_id,)).fetchone():
        return _summary(conn, event_id)
    event = active_event(conn, event_id, now)
    if now < event["registration_deadline"]:
        raise SliceError("普通报名尚未截止")
    if conn.execute(
        """SELECT 1 FROM registration_reservation s JOIN registration_group g
                    USING(registration_group_id) WHERE g.event_id=? LIMIT 1""",
        (event_id,),
    ).fetchone():
        raise SliceError("有未核实的预留位，不能把预留人当作实际队员或空位")

    groups = conn.execute(
        """SELECT registration_group_id,display_name FROM registration_group
        WHERE event_id=? AND group_origin='registered' ORDER BY created_at DESC,registration_group_id""",
        (event_id,),
    ).fetchall()
    entries = [
        dict(row)
        for row in conn.execute(
            """SELECT e.registration_entry_id AS id,e.player_id,e.created_at,
        e.account_id,e.registration_origin,e.registration_group_id,e.roster_slot,p.cs2_playtime_minutes
        FROM registration_entry e JOIN players p ON p.id=e.player_id WHERE e.event_id=?
        ORDER BY e.created_at,e.registration_entry_id""",
            (event_id,),
        )
    ]
    members = defaultdict(dict)
    candidates = []
    reserves = []
    for entry in entries:
        origin = entry["registration_origin"]
        if origin == "group":
            members[entry["registration_group_id"]][entry["roster_slot"]] = entry
        elif origin == "independent_reserve":
            reserves.append(entry["player_id"])
        else:
            candidates.append(entry)
    fixed = [
        {
            "registration_id": g["registration_group_id"],
            "players": list(members[g["registration_group_id"]].values()),
        }
        for g in groups
        if len(members[g["registration_group_id"]]) < 5
    ]
    if sum(5 - len(team["players"]) for team in fixed) > len(candidates):
        raise SliceError("个人报名人数不足，无法补齐已报队伍，原报名保留")
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
                group_id = create_formed_group(
                    conn, event_id, label, captain_account_id=captain["account_id"], now=now
                )
            roster = members[group_id]
            for slot, entry in zip([n for n in range(5) if n not in roster], added, strict=True):
                roster[slot] = entry
    else:
        reserves.extend(entry["player_id"] for entry in candidates)

    conn.execute("INSERT INTO formation_batch VALUES(?,?,1)", (event_id, now))
    for group_id, roster in members.items():
        if set(roster) != set(range(5)):
            raise SliceError("正式队必须有五个已认领的位置")
        _check_players(conn, event_id, [entry["player_id"] for entry in roster.values()])
        entrant_id = conn.execute(
            "INSERT INTO event_entrant(event_id,registration_group_id) VALUES(?,?)",
            (event_id, group_id),
        ).lastrowid
        conn.executemany(
            "INSERT INTO entrant_member VALUES(?,?,?,?)",
            [
                (entrant_id, event_id, entry["player_id"], slot)
                for slot, entry in sorted(roster.items())
            ],
        )
    conn.executemany(
        "INSERT INTO reserve_candidate(event_id,player_id) VALUES(?,?)",
        [(event_id, p) for p in reserves],
    )
    conn.execute("UPDATE events SET registration_open=0 WHERE id=?", (event_id,))
    return _summary(conn, event_id)


def record_late_reserve(conn, event_id, player_id):
    conn.execute(
        """INSERT INTO reserve_candidate(event_id,player_id)
        SELECT e.event_id,e.player_id FROM registration_entry e JOIN formation_batch b USING(event_id)
        WHERE e.event_id=? AND e.player_id=? AND (e.registration_origin='independent_reserve' OR
            EXISTS (SELECT 1 FROM reserve_candidate c WHERE c.event_id=e.event_id AND c.player_id=e.player_id))
          AND NOT EXISTS (SELECT 1 FROM entrant_member m WHERE m.event_id=e.event_id AND m.player_id=e.player_id)
        ON CONFLICT(event_id,player_id) DO UPDATE SET withdrawn_at=NULL""",
        (event_id, player_id),
    )


def get_roster(conn, event_id, entrant_id):
    head = conn.execute(
        """SELECT e.event_id,e.event_entrant_id,e.registration_group_id,b.formation_revision,
        i.confirmed_by,i.confirmed_at,i.confirmed_revision FROM event_entrant e JOIN formation_batch b USING(event_id)
        LEFT JOIN initial_roster i USING(event_entrant_id) WHERE e.event_entrant_id=? AND e.event_id=?""",
        (entrant_id, event_id),
    ).fetchone()
    if head is None:
        raise SliceError("本届参赛方不存在", status=404)
    initial = conn.execute(
        "SELECT player_id FROM initial_roster_member WHERE event_entrant_id=? ORDER BY roster_slot",
        (entrant_id,),
    ).fetchall()
    current = conn.execute(
        "SELECT player_id FROM entrant_member WHERE event_entrant_id=? ORDER BY roster_slot",
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
            "SELECT * FROM formation_action WHERE event_entrant_id=? AND action_kind='replace' ORDER BY formation_action_id",
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
        raise SliceError("请选择不同的本届参赛方", status=400)
    rosters = [get_roster(conn, event_id, e) for e in entrant_ids]
    if all(r["is_frozen"] for r in rosters):
        # 旧确认可以重试，但不能替另一个管理员确认他没看到的分组。
        if (
            type(expected_revision) is not int
            or not max(r["confirmed_revision"] for r in rosters)
            <= expected_revision
            <= batch["formation_revision"]
        ):
            raise SliceError("确认时的名单版本不同，请重新查看已冻结的五人")
        return batch
    _version(batch, expected_revision)
    for r in rosters:
        if r["is_frozen"]:
            continue
        require_pre_series(conn, event_id, r["registration_group_id"])
        if len(set(r["current_player_ids"])) != 5:
            raise SliceError("不能确认未满五人的阵容")
        _check_players(conn, event_id, r["current_player_ids"])
        entrant = r["event_entrant_id"]
        conn.execute(
            "INSERT INTO initial_roster VALUES(?,?,?,?)",
            (entrant, admin_id, now, expected_revision),
        )
        conn.execute(
            """INSERT INTO initial_roster_member(event_entrant_id,player_id,roster_slot)
            SELECT event_entrant_id,player_id,roster_slot FROM entrant_member
            WHERE event_entrant_id=? ORDER BY roster_slot""",
            (entrant,),
        )
    return _finish(conn, event_id)


def adjust_formation(conn, event_id, assignments, *, expected_revision, admin_id, reason, now):
    batch = _admin_event(conn, event_id, admin_id, now)
    _version(batch, expected_revision)
    if not assignments:
        raise SliceError("未选择要调整的队伍", status=400)
    prior = {e: get_roster(conn, event_id, e) for e in assignments}
    if any(r["is_frozen"] for r in prior.values()):
        raise SliceError("初始名单已冻结，请走赛前换人办理")
    for r in prior.values():
        require_pre_series(conn, event_id, r["registration_group_id"])
    before = {p for r in prior.values() for p in r["current_player_ids"]}
    players = [p for members in assignments.values() for p in members]
    if any(len(members) != 5 for members in assignments.values()) or len(set(players)) != len(
        players
    ):
        raise SliceError("每队必须是互不重占的五名选手")
    _check_players(conn, event_id, players)
    incoming = set(players) - before
    for p in incoming:
        if not conn.execute(
            """SELECT 1 FROM reserve_candidate c JOIN registration_entry e USING(event_id,player_id)
            WHERE c.event_id=? AND c.player_id=? AND c.assigned_entrant_id IS NULL AND c.withdrawn_at IS NULL
            AND e.registration_origin IN ('group','individual')""",
            (event_id, p),
        ).fetchone():
            raise SliceError("不可使用其他队的队员或未报名首发的候补")
    if all(prior[e]["current_player_ids"] == list(members) for e, members in assignments.items()):
        return batch
    for e in assignments:
        conn.execute("DELETE FROM entrant_member WHERE event_entrant_id=?", (e,))
    for e, members in assignments.items():
        conn.executemany(
            "INSERT INTO entrant_member VALUES(?,?,?,?)",
            [(e, event_id, p, n) for n, p in enumerate(members)],
        )
        _audit(
            conn, e, "adjust", admin_id, now, reason, prior[e]["current_player_ids"], list(members)
        )
    conn.executemany(
        "DELETE FROM reserve_candidate WHERE event_id=? AND player_id=?",
        [(event_id, p) for p in incoming],
    )
    conn.executemany(
        "INSERT INTO reserve_candidate(event_id,player_id) VALUES(?,?)",
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
    roster = get_roster(conn, event_id, entrant_id)
    options = {
        r["player_id"]: r
        for r in conn.execute(
            """SELECT c.player_id,c.assigned_entrant_id,e.registration_origin
        FROM reserve_candidate c JOIN registration_entry e USING(event_id,player_id)
        WHERE c.event_id=? AND c.withdrawn_at IS NULL""",
            (event_id,),
        )
    }
    if player_id not in options:
        raise SliceError("该选手不是本届候补")
    chosen = options[player_id]
    if chosen["assigned_entrant_id"] == entrant_id:
        return batch
    _version(batch, expected_revision)
    require_pre_series(conn, event_id, roster["registration_group_id"])
    if chosen["assigned_entrant_id"] is not None:
        raise SliceError("该候补已有其他队的席位")
    _check_players(conn, event_id, [player_id])
    excluded = excluded_candidates or {}
    if not isinstance(excluded, dict) or any(
        k not in options
        or k == player_id
        or options[k]["assigned_entrant_id"] is not None
        or not isinstance(v, str)
        or not v.strip()
        for k, v in excluded.items()
    ):
        raise SliceError("排除原因必须逐一对应未授席候补，不能排除本次入选者", status=400)
    if chosen["registration_origin"] != "independent_reserve":
        if any(
            r["registration_origin"] == "independent_reserve"
            and r["assigned_entrant_id"] is None
            and p not in excluded
            for p, r in options.items()
        ):
            raise SliceError("独立入口候补优先；若不适合或不愿意，请逐人记录协商原因")
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
        "UPDATE reserve_candidate SET assigned_entrant_id=? WHERE event_id=? AND player_id=?",
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
    roster = get_roster(conn, event_id, entrant_id)
    require_pre_series(conn, event_id, roster["registration_group_id"])
    if not roster["is_frozen"] or outgoing_player_id not in roster["current_player_ids"]:
        raise SliceError("仅可更换已冻结阵容中的现有队员")
    if not conn.execute(
        """SELECT 1 FROM reserve_candidate WHERE event_id=? AND player_id=? AND assigned_entrant_id=?
                        AND withdrawn_at IS NULL""",
        (event_id, incoming_player_id, entrant_id),
    ).fetchone():
        raise SliceError("换入者须已获本队替补席位")
    proposed = [
        incoming_player_id if p == outgoing_player_id else p for p in roster["current_player_ids"]
    ]
    if not keeps_initial_majority(roster["initial_player_ids"], proposed):
        raise SliceError("新阵容必须至少保留最初五人中的三人")
    _check_players(conn, event_id, proposed)
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
        "UPDATE entrant_member SET player_id=? WHERE event_entrant_id=? AND player_id=?",
        (incoming_player_id, entrant_id, outgoing_player_id),
    )
    conn.execute(
        "DELETE FROM reserve_candidate WHERE event_id=? AND player_id=?",
        (event_id, incoming_player_id),
    )
    return _finish(conn, event_id)
