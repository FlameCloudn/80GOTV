"""托管场开赛、实际开局、出场与技术重赛；写入共用调用方事务。"""

import json

from site_core.events.public import keeps_initial_majority, verify_registered_players
from site_core.events.registration import require_admin
from site_core.host import HostError
from site_core.matches.participants import rosters_frozen
from utils.bp_manager import FORMAT_MAP_COUNTS


def start_state(conn, match_id):
    match = conn.execute(
        """SELECT m.status,m.bo_format,m.bp_state,c.archived_at,e.status AS event_status,
                  a.authorized_at FROM matches m JOIN event_registration_control c USING(event_id)
           JOIN events e ON e.id=m.event_id LEFT JOIN match_start_authorizations a ON a.match_id=m.id
           WHERE m.id=?""",
        (match_id,),
    ).fetchone()
    if not match:
        raise HostError("比赛不存在或仍使用往届流程", 404)
    authorized = match["authorized_at"] is not None
    reason = None
    if (
        match["archived_at"] is not None
        or match["event_status"] == "completed"
        or match["status"] not in {"upcoming", "live"}
    ):
        reason = "比赛或赛事已结束、取消或归档"
    elif not rosters_frozen(conn, match_id):
        reason = "请先冻结本场双方的五人名单"
    else:
        bp = json.loads(match["bp_state"]) if match["bp_state"] else None
        if not bp or bp.get("status") != "completed":
            reason = "本场 BP 尚未完成"
        else:
            planned = conn.execute(
                "SELECT count(*),count(nullif(trim(map_name),'')) FROM scheduled_maps "
                "WHERE match_id=? AND is_enabled=1",
                (match_id,),
            ).fetchone()
            size = FORMAT_MAP_COUNTS.get((match["bo_format"] or "BO3").upper())
            if not size or (planned[0], planned[1]) != (size, size):
                reason = "BP 排图不完整，请先核对本场赛图"
    return {
        "eligible": reason is None,
        "authorized": authorized,
        "ready_for_start": authorized and reason is None,
        "reason": reason or (None if authorized else "等待管理员授权开赛"),
    }


def authorize(conn, match_id, admin_id):
    require_admin(conn, admin_id)
    state = start_state(conn, match_id)
    if not state["eligible"]:
        raise HostError(state["reason"])
    if not state["authorized"]:
        conn.execute(
            "INSERT INTO match_start_authorizations(match_id,admin_id) VALUES(?,?)",
            (match_id, admin_id),
        )
    return {**state, "authorized": True, "ready_for_start": True, "reason": None}


def _schedule(conn, match_id, scheduled_map_id):
    plan = conn.execute(
        "SELECT * FROM scheduled_maps WHERE match_id=? AND scheduled_map_id=? AND is_enabled=1",
        (match_id, scheduled_map_id),
    ).fetchone()
    if not plan:
        raise HostError("本场没有这张启用的赛图", 404)
    return plan


def match_run(conn, match_id, run_id):
    run = conn.execute(
        """SELECT r.*,s.match_id,s.map_order FROM map_runs r JOIN scheduled_maps s USING(scheduled_map_id)
           WHERE r.map_run_id=? AND s.match_id=?""",
        (run_id, match_id),
    ).fetchone()
    if not run:
        raise HostError("本场没有这次开局", 404)
    return run


def current_run(conn, scheduled_map_id):
    return conn.execute(
        "SELECT * FROM map_runs WHERE scheduled_map_id=? AND status<>'void'", (scheduled_map_id,)
    ).fetchone()


def effective_roster(conn, match_id, scheduled_map_id):
    plan = _schedule(conn, match_id, scheduled_map_id)
    lineup = [
        dict(row)
        for row in conn.execute(
            """SELECT m.player_id,m.steam_id,m.match_participant_id,m.roster_slot,p.side_key,p.event_entrant_id
           FROM match_roster_members m JOIN match_participants p USING(match_participant_id)
           WHERE p.match_id=? ORDER BY p.side_key DESC,m.roster_slot""",
            (match_id,),
        )
    ]
    # 每次替换占原人的同一席位；后续换人仍接着使用该席，不倒填前图。
    slots = {(row["match_participant_id"], row["roster_slot"]): row for row in lineup}
    changes = conn.execute(
        """SELECT t.match_participant_id,l.roster_slot,t.incoming_player_id,t.incoming_steam_id
           FROM technical_replays t JOIN map_runs r USING(map_run_id) JOIN scheduled_maps s USING(scheduled_map_id)
           JOIN map_run_lineups l ON l.map_run_id=t.map_run_id AND l.player_id=t.outgoing_player_id
           WHERE s.match_id=? AND s.map_order<=? ORDER BY s.map_order,r.attempt_no""",
        (match_id, plan["map_order"]),
    )
    for change in changes:
        row = slots[change["match_participant_id"], change["roster_slot"]]
        row.update(player_id=change["incoming_player_id"], steam_id=change["incoming_steam_id"])
    return lineup


def observe_start(
    conn,
    match_id,
    scheduled_map_id,
    *,
    source,
    evidence,
    expected_run_id=None,
    previous_map_run_id=None,
):
    state = start_state(conn, match_id)
    if not state["ready_for_start"]:
        raise HostError(state["reason"])
    plan = _schedule(conn, match_id, scheduled_map_id)
    running = current_run(conn, scheduled_map_id)
    if expected_run_id is not None and (not running or running["map_run_id"] != expected_run_id):
        raise HostError("上报的开局与当前开局不一致")
    if running:
        if running["status"] != "active":
            raise HostError("该图已裁定，不能再次开局")
        if (
            source.startswith("admin:")
            and previous_map_run_id != running["previous_map_run_id"]
            and expected_run_id is None
        ):
            raise HostError("这不是同一次开局请求，请核对当前局号")
        return running["map_run_id"]
    outcomes = conn.execute(
        """SELECT s.map_order,o.score1,o.score2 FROM scheduled_maps s LEFT JOIN official_map_results o
           ON o.scheduled_map_id=s.scheduled_map_id AND o.is_current=1
           WHERE s.match_id=? AND s.is_enabled=1 ORDER BY s.map_order""",
        (match_id,),
    ).fetchall()
    needed = len(outcomes) // 2 + 1
    prior = [r for r in outcomes if r["map_order"] < plan["map_order"]]
    if any(r["score1"] is None for r in prior):
        raise HostError("上一张赛图尚未正式确认，不能跳图开赛")
    wins = sum(r["score1"] > r["score2"] for r in prior)
    if max(wins, len(prior) - wins) >= needed:
        raise HostError("系列赛已达到所需胜图，不再开剩余赛图")
    old = conn.execute(
        "SELECT map_run_id,attempt_no FROM map_runs WHERE scheduled_map_id=? "
        "ORDER BY attempt_no DESC LIMIT 1",
        (scheduled_map_id,),
    ).fetchone()
    if source.startswith("admin:") and previous_map_run_id != (old[0] if old else None):
        raise HostError("重打须明确指向刚获批准作废的原局，请核对 previous_map_run_id")
    if (
        old
        and not conn.execute(
            "SELECT 1 FROM technical_replays WHERE map_run_id=?", (old[0],)
        ).fetchone()
    ):
        raise HostError("没有本图的技术重赛批准记录")
    if not isinstance(evidence, str) or not evidence.strip():
        raise HostError("实际开局需要可核对的现场依据", 400)
    lineup = effective_roster(conn, match_id, scheduled_map_id)
    run_id = conn.execute(
        """INSERT INTO map_runs(scheduled_map_id,attempt_no,previous_map_run_id,status,source,start_evidence)
           VALUES(?,?,?,'active',?,?)""",
        (
            scheduled_map_id,
            old[1] + 1 if old else 1,
            old[0] if old else None,
            source,
            evidence.strip(),
        ),
    ).lastrowid
    conn.executemany(
        "INSERT INTO map_run_lineups(map_run_id,player_id,match_participant_id,roster_slot,steam_id) "
        "VALUES(?,?,?,?,?)",
        [
            (run_id, r["player_id"], r["match_participant_id"], r["roster_slot"], r["steam_id"])
            for r in lineup
        ],
    )
    conn.execute("UPDATE matches SET status='live' WHERE id=? AND status='upcoming'", (match_id,))
    return run_id


def record_round(conn, run_id, round_number, *, source, winner_side=None):
    if (
        type(round_number) is not int
        or not 1 <= round_number <= 1000
        or winner_side not in (None, "home", "away")
    ):
        raise HostError("回合号或回合胜方无效", 400)
    if not conn.execute(
        "SELECT 1 FROM map_runs WHERE map_run_id=? AND status<>'void'", (run_id,)
    ).fetchone():
        raise HostError("不能写入不存在或已作废的开局")
    conn.execute(
        """INSERT INTO map_run_rounds(map_run_id,round_number,winner_side,source) VALUES(?,?,?,?)
           ON CONFLICT(map_run_id,round_number) DO UPDATE SET winner_side=excluded.winner_side,source=excluded.source
           WHERE map_run_rounds.winner_side IS NULL AND excluded.winner_side IS NOT NULL""",
        (run_id, round_number, winner_side, source),
    )


def _audit_participation(conn, pid):
    conn.execute(
        """INSERT INTO participation_decisions(participation_id,revision,is_current,source,admin_id,reason)
                    SELECT participation_id,revision,is_current,source,confirmed_by,reason FROM run_participations
                    WHERE participation_id=?""",
        (pid,),
    )


def _refresh_adopted_run(conn, run_id):
    result = conn.execute(
        "SELECT scheduled_map_id FROM official_map_results WHERE map_run_id=? AND is_current=1",
        (run_id,),
    ).fetchone()
    if result:
        from site_core.matches.statistics import refresh_map

        refresh_map(conn, result[0])


def record_participation(
    conn,
    run_id,
    player_id,
    match_participant_id,
    *,
    source,
    round_number=None,
    side=None,
    actor=None,
    reason=None,
):
    allowed = conn.execute(
        """SELECT 1 FROM map_run_lineups l JOIN map_runs r USING(map_run_id)
           JOIN scheduled_maps s USING(scheduled_map_id) JOIN matches m ON m.id=s.match_id
           JOIN event_registration_control c ON c.event_id=m.event_id
           WHERE l.map_run_id=? AND l.player_id=? AND l.match_participant_id=? AND r.status<>'void'
           AND c.archived_at IS NULL AND m.status<>'cancelled'""",
        (run_id, player_id, match_participant_id),
    ).fetchone()
    if not allowed:
        raise HostError("不能为归档、取消、作废的开局或不在该方批准名单上的选手登记出场")
    if side not in (None, "CT", "T") or (side and round_number is None):
        raise HostError("CT/T 出场须对应实际回合", 400)
    row = conn.execute(
        "SELECT * FROM run_participations WHERE map_run_id=? AND player_id=?", (run_id, player_id)
    ).fetchone()
    admin = actor if type(actor) is int else None
    if row and not row["is_current"]:
        raise HostError("这条出场已被人工撤回，请管理员核对原决定")
    if row:
        pid = row["participation_id"]
        if admin is not None and row["confirmed_by"] is None:
            conn.execute(
                "UPDATE run_participations SET confirmed_by=?,source=?,reason=?,revision=revision+1 "
                "WHERE participation_id=?",
                (admin, source, reason, pid),
            )
            _audit_participation(conn, pid)
    else:
        pid = conn.execute(
            """INSERT INTO run_participations(map_run_id,player_id,match_participant_id,source,confirmed_by,reason)
                              VALUES(?,?,?,?,?,?)""",
            (run_id, player_id, match_participant_id, source, admin, reason),
        ).lastrowid
        _audit_participation(conn, pid)
    if round_number is not None:
        record_round(conn, run_id, round_number, source=source)
        conn.execute(
            """INSERT INTO run_round_participations(map_run_id,round_number,participation_id,side,source)
                        VALUES(?,?,?,?,?) ON CONFLICT(map_run_id,round_number,participation_id) DO UPDATE
                        SET side=excluded.side,source=excluded.source WHERE run_round_participations.side IS NULL
                        AND excluded.side IS NOT NULL""",
            (run_id, round_number, pid, side, source),
        )
    if not row:
        _refresh_adopted_run(conn, run_id)
    return pid


def review_participation(
    conn, match_id, participation_id, *, present, expected_revision, admin_id, reason
):
    row = conn.execute(
        """SELECT p.* FROM run_participations p JOIN map_runs r USING(map_run_id)
                          JOIN scheduled_maps s USING(scheduled_map_id) JOIN matches m ON m.id=s.match_id
                          JOIN event_registration_control c ON c.event_id=m.event_id WHERE s.match_id=? AND participation_id=?
                          AND r.status<>'void' AND c.archived_at IS NULL AND m.status<>'cancelled'""",
        (match_id, participation_id),
    ).fetchone()
    if not row:
        raise HostError("本场没有这条可核准的出场记录", 404)
    if expected_revision != row["revision"]:
        raise HostError("出场记录已修订，请重新核对")
    conn.execute(
        """UPDATE run_participations SET is_current=?,revision=revision+1,confirmed_by=?,reason=?,source='admin'
                    WHERE participation_id=?""",
        (int(present), admin_id, reason, participation_id),
    )
    _audit_participation(conn, participation_id)
    _refresh_adopted_run(conn, row["map_run_id"])
    return {
        "participation_id": participation_id,
        "revision": row["revision"] + 1,
        "present": present,
    }


def technical_replay(
    conn,
    match_id,
    run_id,
    *,
    admin_id,
    reason,
    outgoing_player_id=None,
    incoming_player_id=None,
    expected_revision=None,
    expected_series_revision=None,
    retain_downstream=None,
):
    from site_core.matches.results import revoke_for_replay

    require_admin(conn, admin_id)
    run = match_run(conn, match_id, run_id)
    if not isinstance(reason, str) or not reason.strip():
        raise HostError("请说明故障和无法原局继续的原因", 400)
    approval = conn.execute(
        "SELECT * FROM technical_replays WHERE map_run_id=?", (run_id,)
    ).fetchone()
    if approval:
        if retain_downstream is not None:
            raise HostError("该局已作废，不能为已办理的重赛追加下游裁定")
        if (approval["outgoing_player_id"], approval["incoming_player_id"], approval["reason"]) != (
            outgoing_player_id,
            incoming_player_id,
            reason.strip(),
        ):
            raise HostError("此次开局已有不同的技术重赛决定")
        return {"void_map_run_id": run_id, "duplicate": True}
    if (outgoing_player_id is None) != (incoming_player_id is None):
        raise HostError("换人须同时指明原选手和替补", 400)
    match = conn.execute(
        "SELECT m.status,m.event_id,c.archived_at FROM matches m JOIN event_registration_control c "
        "USING(event_id) WHERE m.id=?",
        (match_id,),
    ).fetchone()
    if (
        not match
        or match["archived_at"] is not None
        or match["status"] == "cancelled"
        or run["status"] == "void"
    ):
        raise HostError("不能为归档、取消或已作废的开局办理重赛")
    party = steam = None
    if incoming_player_id is not None:
        lineup = effective_roster(conn, match_id, run["scheduled_map_id"])
        outgoing = next((p for p in lineup if p["player_id"] == outgoing_player_id), None)
        if outgoing is None or any(p["player_id"] == incoming_player_id for p in lineup):
            raise HostError("原选手须在该局有效阵容内，替补不能已是本场在列选手")
        entrant, party = outgoing["event_entrant_id"], outgoing["match_participant_id"]
        reserve = conn.execute(
            """SELECT p.steam_id FROM event_reserve_candidates c JOIN players p ON p.id=c.player_id
                                 WHERE c.event_id=? AND c.player_id=? AND c.assigned_entrant_id=? AND c.withdrawn_at IS NULL
                                 AND NOT EXISTS (SELECT 1 FROM event_current_members m WHERE m.event_id=c.event_id AND m.player_id=c.player_id)""",
            (match["event_id"], incoming_player_id, entrant),
        ).fetchone()
        if not reserve:
            raise HostError("换入者须是本届已获本队席位的有效候补")
        verify_registered_players(conn, match["event_id"], [incoming_player_id])
        steam = str(reserve[0] or "").strip()
        if not steam or any(p["steam_id"] == steam for p in lineup):
            raise HostError("替补缺少唯一可识别的 Steam 身份")
        initial = [
            r[0]
            for r in conn.execute(
                "SELECT player_id FROM event_initial_members WHERE event_entrant_id=?", (entrant,)
            )
        ]
        revised = [
            incoming_player_id if p["player_id"] == outgoing_player_id else p["player_id"]
            for p in lineup
            if p["match_participant_id"] == party
        ]
        if not keeps_initial_majority(initial, revised):
            raise HostError("技术替补后仍须保留至少三名本届初始选手")
    revoke_for_replay(
        conn,
        match_id,
        run["scheduled_map_id"],
        run_id,
        actor=admin_id,
        reason=reason.strip(),
        expected_revision=expected_revision,
        expected_series_revision=expected_series_revision,
        retain_downstream=retain_downstream,
    )
    conn.execute(
        """INSERT INTO technical_replays(map_run_id,admin_id,reason,match_participant_id,
                    outgoing_player_id,incoming_player_id,incoming_steam_id) VALUES(?,?,?,?,?,?,?)""",
        (run_id, admin_id, reason.strip(), party, outgoing_player_id, incoming_player_id, steam),
    )
    conn.execute("UPDATE map_runs SET status='void' WHERE map_run_id=?", (run_id,))
    # 原观察可查，但站内直播面板不能继续把故障局的比分当作当前场面。
    conn.execute("DELETE FROM live_match_data WHERE match_id=?", (match_id,))
    return {"void_map_run_id": run_id, "duplicate": False}
