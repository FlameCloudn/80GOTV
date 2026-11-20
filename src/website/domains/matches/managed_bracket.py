"""Managed bracket scheduling, dependency protection and advancement."""

from src.website.domains.events.registration import require_admin
from src.website.domains.matches.bracket_service import _normalise_match_time
from src.website.domains.matches.maps import match_has_started, sync_scheduled_maps
from src.website.domains.matches.match_references import update_match_slug
from src.website.domains.matches.participants import check_duplicate, select_entrant
from src.website.runtime.host import HostError, is_managed_event


def _managed_bracket_admin(conn, event_id, actor):
    if not conn.in_transaction:
        raise HostError("请在宿主写事务中配置签表")
    if type(actor) is not int:
        raise HostError("只有管理员可以配置签表", 403)
    require_admin(conn, actor)
    if (
        not is_managed_event(conn, event_id)
        or not conn.execute(
            "SELECT 1 FROM event_registration_control WHERE event_id=? AND archived_at IS NULL",
            (event_id,),
        ).fetchone()
    ):
        raise HostError("只能配置未归档的托管赛事签表")


def create_bracket_match(conn, event_id, *, bo_format, stage, actor, match_time=None):
    """在调用者事务中建真实赛程和空签位，不创建假的参赛方。"""
    _managed_bracket_admin(conn, event_id, actor)
    if bo_format not in ("BO1", "BO3", "BO5") or not isinstance(stage, str) or not stage.strip():
        raise HostError("请填写轮次和有效赛制", 400)
    try:
        match_time = _normalise_match_time(match_time)
    except ValueError as exc:
        raise HostError(str(exc), 400) from exc
    match_id = conn.execute(
        """INSERT INTO matches(event_id,status,bo_format,stage,match_time)
           VALUES(?,'upcoming',?,?,?)""",
        (event_id, bo_format, stage.strip(), match_time),
    ).lastrowid
    update_match_slug(conn, match_id)
    sync_scheduled_maps(conn, match_id)
    return {"match_id": match_id, "event_id": event_id}


def _slot_protection(conn, target, side):
    mid = target["id"]
    if target["status"] not in ("upcoming", "live", "ongoing", "completed"):
        raise HostError(f"下游比赛 {mid} 已取消或状态无效，不能调整签位")
    if (
        target["status"] != "upcoming"
        or target["bp_state"]
        or target["bp_process"]
        or target["roster_snapshot"]
        or match_has_started(conn, target)
        or conn.execute(
            """SELECT 1 FROM match_participants p JOIN match_rosters r USING(match_participant_id)
                   WHERE p.match_id=:m AND p.side_key=:s
                   UNION ALL SELECT 1 FROM match_bp_resets WHERE match_id=:m
                   UNION ALL SELECT 1 FROM match_start_authorizations WHERE match_id=:m
                   UNION ALL SELECT 1 FROM scheduled_maps sm JOIN map_runs r USING(scheduled_map_id)
                     WHERE sm.match_id=:m
                   UNION ALL SELECT 1 FROM scheduled_maps WHERE match_id=:m
                     AND (picked_by_match_participant_id IS NOT NULL
                          OR side_choice_match_participant_id IS NOT NULL) LIMIT 1""",
            {"m": mid, "s": side},
        ).fetchone()
    ):
        return f"下游比赛 {mid} 已锁定相关名单、已 BP 或已开赛，不能调整签位"
    if conn.execute("SELECT 1 FROM match_votes WHERE match_id=? LIMIT 1", (mid,)).fetchone():
        return f"下游比赛 {mid} 已有竞猜，不能自动调整签位"
    return None


def get_bracket_links(conn, event_id):
    return [
        dict(row)
        for row in conn.execute(
            """SELECT l.*,p.event_entrant_id,p.match_participant_id,
                  d.settlement_id IS NOT NULL AS detached,d.settlement_id AS detached_settlement_id
           FROM managed_bracket_links l LEFT JOIN bracket_retention_decisions d USING(source_match_id,outcome)
           LEFT JOIN match_participants p
             ON p.match_id=l.target_match_id AND p.side_key=l.target_side
           WHERE l.event_id=? ORDER BY l.source_match_id,l.outcome""",
            (event_id,),
        )
    ]


def configure_bracket_link(conn, source_match_id, outcome, target_match_id, target_side, *, actor):
    """把同届比赛的胜方或败方指向空签位。已生效的线路不能由配置覆盖。"""
    if outcome not in ("winner", "loser") or target_side not in ("home", "away"):
        raise HostError("签表来源或目标边无效", 400)
    source = conn.execute("SELECT * FROM matches WHERE id=?", (source_match_id,)).fetchone()
    target = conn.execute("SELECT * FROM matches WHERE id=?", (target_match_id,)).fetchone()
    if not source or not target or source["event_id"] != target["event_id"]:
        raise HostError("签表的两场比赛必须属于同一赛事", 400)
    _managed_bracket_admin(conn, source["event_id"], actor)
    links = conn.execute(
        """SELECT * FROM managed_bracket_links WHERE (source_match_id=? AND outcome=?)
           OR (target_match_id=? AND target_side=?)""",
        (source_match_id, outcome, target_match_id, target_side),
    ).fetchall()
    if links:
        if (
            len(links) == 1
            and links[0]["source_match_id"] == source_match_id
            and links[0]["outcome"] == outcome
            and links[0]["target_match_id"] == target_match_id
            and links[0]["target_side"] == target_side
        ):
            if conn.execute(
                "SELECT 1 FROM bracket_retention_decisions WHERE source_match_id=? AND outcome=?",
                (source_match_id, outcome),
            ).fetchone():
                raise HostError("此线路已经人工裁定脱离自动晋级，不可重新启用")
            return dict(links[0])
        raise HostError("签表来源或目标席位已有其他线路")
    if source["status"] in ("completed", "cancelled"):
        raise HostError("不能在完赛或取消后增设晋级线路")
    if conn.execute(
        """WITH RECURSIVE downstream(id) AS (SELECT ? UNION SELECT l.target_match_id
             FROM managed_bracket_links l JOIN downstream d ON d.id=l.source_match_id)
           SELECT 1 FROM downstream WHERE id=?""",
        (target_match_id, source_match_id),
    ).fetchone():
        raise HostError("签表线路不能循环")
    protection = _slot_protection(conn, target, target_side)
    if protection:
        raise HostError(protection)
    if conn.execute(
        "SELECT 1 FROM match_participants WHERE match_id=? AND side_key=?",
        (target_match_id, target_side),
    ).fetchone():
        raise HostError("目标签位已有固定参赛方，不是空位")
    row = conn.execute(
        """INSERT INTO managed_bracket_links(event_id,source_match_id,outcome,target_match_id,
           target_side,configured_by) VALUES(?,?,?,?,?,?) RETURNING *""",
        (source["event_id"], source_match_id, outcome, target_match_id, target_side, actor),
    ).fetchone()
    return dict(row)


def _retained_slots(entries):
    if not isinstance(entries, list) or not entries:
        raise HostError("保留下游裁定必须明确列出受保护的签位", 400)
    claims = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "target_match_id",
            "target_side",
            "retained_entrant_id",
            "proposed_entrant_id",
        }:
            raise HostError("每项裁定须填写目标场、侧、保留参赛方及原应晋级参赛方", 400)
        mid, side = entry["target_match_id"], entry["target_side"]
        retained, proposed = entry["retained_entrant_id"], entry["proposed_entrant_id"]
        if (
            type(mid) is not int
            or mid <= 0
            or side not in ("home", "away")
            or type(retained) is not int
            or retained <= 0
            or (proposed is not None and (type(proposed) is not int or proposed <= 0))
        ):
            raise HostError("签位编号、侧或本届参赛方编号无效", 400)
        if (mid, side) in claims:
            raise HostError("同一目标签位不能重复裁定", 400)
        claims[mid, side] = (retained, proposed)
    return claims


def apply_bracket_outcome(
    conn, match_id, settlement_id, winner_id, loser_id, *, retain_downstream=None
):
    """只传播正式结算给出的本届队号；同一参赛方保持原绑定和下游数据。"""
    outcomes = {"winner": winner_id, "loser": loser_id}
    claims = _retained_slots(retain_downstream) if retain_downstream is not None else {}
    decisions = []
    changes = {}
    for link in conn.execute(
        """SELECT l.* FROM managed_bracket_links l WHERE source_match_id=? AND NOT EXISTS
           (SELECT 1 FROM bracket_retention_decisions d
            WHERE d.source_match_id=l.source_match_id AND d.outcome=l.outcome)""",
        (match_id,),
    ):
        mid, side = link["target_match_id"], link["target_side"]
        old = conn.execute(
            "SELECT * FROM match_participants WHERE match_id=? AND side_key=?", (mid, side)
        ).fetchone()
        previous = conn.execute(
            """SELECT new_participant_id FROM bracket_settlement_changes
               WHERE target_match_id=? AND target_side=? ORDER BY settlement_id DESC LIMIT 1""",
            (mid, side),
        ).fetchone()
        old_id = old["match_participant_id"] if old else None
        if old_id != (previous[0] if previous else None):
            raise HostError("下游签位与上次正式落位不一致，不能覆盖")
        desired = outcomes[link["outcome"]]
        retained = old["event_entrant_id"] if old else None
        if retained == desired:
            continue
        target = conn.execute("SELECT * FROM matches WHERE id=?", (mid,)).fetchone()
        protection = _slot_protection(conn, target, side)
        if protection:
            if retained is None or claims.pop((mid, side), None) != (retained, desired):
                raise HostError(f"{protection}；未收到与该侧现状及拟晋级方一致的保留裁定")
            decisions.append(
                (settlement_id, match_id, link["outcome"], mid, side, old_id, retained, desired)
            )
        else:
            changes.setdefault(mid, {})[side] = (old, desired)
    if claims:
        raise HostError("保留清单包含不受本次改判影响、可正常调整或已脱离的签位")
    conn.executemany(
        """INSERT INTO bracket_retention_decisions(settlement_id,source_match_id,outcome,target_match_id,
           target_side,retained_participant_id,retained_entrant_id,proposed_entrant_id) VALUES(?,?,?,?,?,?,?,?)""",
        decisions,
    )
    for mid, slots in changes.items():
        target = conn.execute("SELECT * FROM matches WHERE id=?", (mid,)).fetchone()
        sides = dict(
            conn.execute(
                "SELECT side_key,event_entrant_id FROM match_participants WHERE match_id=?", (mid,)
            )
        )
        for side, (_, desired) in slots.items():
            if desired is not None:
                select_entrant(conn, target["event_id"], entrant_id=desired)
            sides[side] = desired
        if sides.get("home") is not None and sides.get("away") is not None:
            if sides["home"] == sides["away"]:
                raise HostError("晋级将使同队对阵自己，未更改签位")
            if target["match_time"]:
                check_duplicate(
                    conn,
                    target["event_id"],
                    target["match_time"],
                    (sides["home"], sides["away"]),
                    exclude_id=mid,
                )
        # 两条线路也可能落到同一场。先清两侧旧绑定，再分配全新的比赛方编号。
        for old, _ in slots.values():
            if old:
                conn.execute(
                    "DELETE FROM match_participants WHERE match_participant_id=?",
                    (old["match_participant_id"],),
                )
        for side, (old, desired) in slots.items():
            new_id = None
            if desired is not None:
                new_id = conn.execute(
                    """INSERT INTO match_participants(match_id,event_id,event_entrant_id,side_key)
                       VALUES(?,?,?,?)""",
                    (mid, target["event_id"], desired, side),
                ).lastrowid
            conn.execute(
                """INSERT INTO bracket_settlement_changes(settlement_id,target_match_id,target_side,
                   old_entrant_id,new_entrant_id,old_participant_id,new_participant_id)
                   VALUES(?,?,?,?,?,?,?)""",
                (
                    settlement_id,
                    mid,
                    side,
                    old["event_entrant_id"] if old else None,
                    desired,
                    old["match_participant_id"] if old else None,
                    new_id,
                ),
            )
