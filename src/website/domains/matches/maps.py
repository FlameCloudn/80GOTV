"""赛前排图及对旧槽位的只读输出，不接收开局或赛果。"""

from src.website.domains.matches.bp_manager import FORMAT_MAP_COUNTS
from src.website.runtime.host import HostError, is_managed_match

_OLD_SIDE = {"home": "t1", "away": "t2"}


def _format_size(bo_format):
    size = FORMAT_MAP_COUNTS.get(str(bo_format or "BO3").upper())
    if size is None:
        raise HostError("仅支持 BO1、BO3、BO5", 400)
    return size


def _fixed_sides(conn, match_id):
    return {
        _OLD_SIDE[row["side_key"]]: row["match_participant_id"]
        for row in conn.execute(
            "SELECT match_participant_id,side_key FROM match_participants WHERE match_id=?",
            (match_id,),
        )
    }


def match_has_started(conn, match):
    """旧列只作已有开打证据，不用比赛时间、排图或阵容冻结猜开局。"""
    if str(match["status"] or "").lower() in {"live", "ongoing", "completed", "cancelled"}:
        return True
    if any(
        match[name] not in (None, 0, "0", "")
        for name in (
            "team1_score",
            "team2_score",
            "decider_knife_winner",
            "decider_start_side",
            *(f"map{slot}_t{side}" for slot in range(1, 6) for side in (1, 2)),
        )
    ):
        return True
    return (
        conn.execute(
            """SELECT 1 FROM match_stats WHERE match_id=? AND COALESCE(data_status,'final')='final'
           UNION ALL SELECT 1 FROM live_match_events WHERE match_id=? LIMIT 1""",
            (match["id"], match["id"]),
        ).fetchone()
        is not None
    )


def bp_lock_reason(conn, match):
    """托管场的 BP 权限门槛，房间和导播用同一判断。"""
    from src.website.domains.matches.participants import rosters_frozen

    if not is_managed_match(conn, match["id"]):
        return None
    if conn.execute(
        """SELECT 1 FROM matches m JOIN event_registration_control c ON c.event_id=m.event_id
           WHERE m.id=? AND c.archived_at IS NOT NULL""",
        (match["id"],),
    ).fetchone():
        return "本届赛事已归档，BP 只读"
    if match_has_started(conn, match):
        return "比赛已开始或已有赛果记录，不能更改 BP"
    if conn.execute(
        "SELECT 1 FROM match_start_authorizations WHERE match_id=?", (match["id"],)
    ).fetchone():
        return "管理员已授权开赛，不能再更改 BP 排图"
    if not rosters_frozen(conn, match["id"]):
        return "请先由管理员冻结比赛双方名单，再办理 BP"
    return None


def _store_plan(conn, match_id, plan):
    # Positions created earlier keep their IDs, even when disabled or cleared during undo.
    conn.execute(
        """UPDATE scheduled_maps SET is_enabled=0,map_name=NULL,picked_by_match_participant_id=NULL,
           is_decider=0,side_choice_match_participant_id=NULL,starting_side=NULL
           WHERE match_id=? AND legacy_slot>?""",
        (match_id, len(plan)),
    )
    conn.executemany(
        """INSERT INTO scheduled_maps(match_id,map_order,legacy_slot,is_enabled,map_name,
               picked_by_match_participant_id,is_decider,side_choice_match_participant_id,starting_side)
           VALUES(?,?,?,?,?,?,?,?,?)
           ON CONFLICT(match_id,legacy_slot) DO UPDATE SET
               is_enabled=excluded.is_enabled,map_name=excluded.map_name,
               picked_by_match_participant_id=excluded.picked_by_match_participant_id,
               is_decider=excluded.is_decider,
               side_choice_match_participant_id=excluded.side_choice_match_participant_id,
               starting_side=excluded.starting_side""",
        [(match_id, slot, slot, *fields) for slot, fields in enumerate(plan, 1)],
    )


def sync_scheduled_maps(conn, match_id, *, setup=None):
    """Called inside the match setup transaction; never reads old map columns as input."""
    if not is_managed_match(conn, match_id):
        return
    match = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
    if (
        setup is None
        and conn.execute(
            "SELECT 1 FROM scheduled_maps WHERE match_id=? LIMIT 1", (match_id,)
        ).fetchone()
    ):
        return
    if match["bp_state"] or match_has_started(conn, match):
        raise HostError("BP 已开始或比赛已有开打记录，不能再次编辑排图")
    size = _format_size(match["bo_format"])
    if setup is None:
        _store_plan(conn, match_id, [(1, None, None, 0, None, None)] * size)
        return
    if _format_size(setup.get("bo_format", match["bo_format"])) != size:
        raise HostError("排图和比赛赛制不一致")
    fixed = _fixed_sides(conn, match_id)
    plan = []
    for slot in range(1, size + 1):
        enabled = slot < 3 or bool(setup.get(f"has_map{slot}", 1))
        name = (str(setup.get(f"map{slot}") or "").strip() or None) if enabled else None
        picked_by = setup.get(f"map{slot}_picked_by") if name else None
        if picked_by and picked_by != "decider" and picked_by not in fixed:
            raise HostError("选图者不属于本场固定双方", 400)
        plan.append(
            (
                int(enabled),
                name,
                fixed.get(picked_by) if picked_by else None,
                int(picked_by == "decider"),
                None,
                None,
            )
        )
    _store_plan(conn, match_id, plan)


def save_bp_plan(conn, match_id, bo_format, picks):
    """Publish the finished BP's ordered selections in the caller's single transaction."""
    match = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
    fixed = _fixed_sides(conn, match_id)
    if set(fixed) != {"t1", "t2"}:
        raise HostError("须先确定比赛双方，才能保存 BP 排图")
    if match_has_started(conn, match):
        raise HostError("比赛已开始或已有比分，不能保存 BP 排图")
    if len(picks) != _format_size(bo_format) or _format_size(match["bo_format"]) != len(picks):
        raise HostError("排图和比赛赛制不一致")

    plan = []
    for name, picker, chooser, side in picks:
        is_decider = picker == "remaining"
        if not name or (not is_decider and picker not in fixed):
            raise HostError("BP 排图或选图者无效", 400)
        if side is not None and (side not in {"CT", "T"} or chooser not in fixed):
            raise HostError("BP 选边资料无效", 400)
        if side is None and (not is_decider or len(picks) == 1):
            raise HostError("BP 选边尚未完成", 400)
        plan.append(
            (
                1,
                name,
                fixed.get(picker),
                int(is_decider),
                fixed.get(chooser) if side else None,
                side,
            )
        )
    _store_plan(conn, match_id, plan)


def clear_bp_plan(conn, match_id, bo_format):
    _store_plan(conn, match_id, [(1, None, None, 0, None, None)] * _format_size(bo_format))


def bp_revision_after_reset(conn, match_id):
    row = conn.execute(
        "SELECT minimum_revision FROM match_bp_resets WHERE match_id=?", (match_id,)
    ).fetchone()
    return row[0] if row else 0


def record_bp_reset(conn, match_id, revision):
    conn.execute(
        """INSERT INTO match_bp_resets(match_id,minimum_revision) VALUES(?,?)
           ON CONFLICT(match_id) DO UPDATE SET minimum_revision=MAX(minimum_revision,excluded.minimum_revision)""",
        (match_id, revision + 1),
    )


def list_scheduled_maps(conn, match_id):
    return conn.execute(
        """SELECT plan.*,picker.side_key AS picker_side,chooser.side_key AS chooser_side
           FROM scheduled_maps plan
           LEFT JOIN match_participants picker ON picker.match_participant_id=plan.picked_by_match_participant_id
           LEFT JOIN match_participants chooser ON chooser.match_participant_id=plan.side_choice_match_participant_id
           WHERE plan.match_id=? ORDER BY plan.map_order""",
        (match_id,),
    ).fetchall()


def _legacy_picker(plan):
    return "decider" if plan["is_decider"] else _OLD_SIDE.get(plan["picker_side"], "")


def project_legacy_map_fields(conn, match):
    """Overlay the old read shape without changing the match row or creating a plan."""
    result = dict(match)
    if not is_managed_match(conn, result.get("id")):
        return result
    by_slot = {plan["legacy_slot"]: plan for plan in list_scheduled_maps(conn, result["id"])}
    for slot in range(1, 6):
        plan = by_slot.get(slot)
        enabled = plan is not None and bool(plan["is_enabled"])
        result[f"map{slot}"] = plan["map_name"] if plan is not None and enabled else None
        result[f"map{slot}_picked_by"] = (_legacy_picker(plan) or None) if enabled else None
        if slot >= 3:
            result[f"has_map{slot}"] = int(enabled)
    return result


def broadcast_maps(conn, match_id):
    result = []
    for plan in list_scheduled_maps(conn, match_id):
        if not plan["is_enabled"]:
            continue
        opening_ct = ""
        if plan["starting_side"]:
            choice = _OLD_SIDE[plan["chooser_side"]]
            opening_ct = (
                choice if plan["starting_side"] == "CT" else ("t2" if choice == "t1" else "t1")
            )
        result.append(
            {
                "slot": plan["legacy_slot"],
                "name": plan["map_name"] or "",
                "picked_by": _legacy_picker(plan),
                "opening_ct_team": opening_ct,
                "opening_side_source": "website_bp" if opening_ct else "pending",
            }
        )
    return result
