"""托管比赛的正式图裁定与系列结算。写入口共用宿主已取得的 SQLite 写事务。"""

import json

from src.website.domains.events.registration import require_admin
from src.website.domains.matches.managed_bracket import apply_bracket_outcome
from src.website.domains.matches.series import get_series_result
from src.website.domains.predictions.scoring import settle_managed_predictions
from src.website.domains.statistics.statistics import refresh_map
from src.website.runtime.host import HostError


def _match(conn, match_id):
    row = conn.execute(
        """SELECT m.id,m.status,m.bo_format,c.archived_at FROM matches m
           JOIN event_registration_control c USING(event_id) WHERE m.id=?""",
        (match_id,),
    ).fetchone()
    if not row:
        raise HostError("找不到该托管比赛", 404)
    return row


def _write_match(conn, match_id, actor, source="admin"):
    if not conn.in_transaction:
        raise HostError("请在宿主写事务中办理裁定")
    if source == "admin":
        if type(actor) is not int:
            raise HostError("需要已验证的管理员", 403)
        require_admin(conn, actor)
    elif source != "director" or actor != "director":
        raise HostError("未授权的裁定来源", 403)
    match = _match(conn, match_id)
    if match["archived_at"] is not None or match["status"] == "cancelled":
        raise HostError("已归档或取消的比赛不能办理裁定")
    return match


def _baseline(expected, current):
    if expected is not None:
        if type(expected) is not int or expected < 0:
            raise HostError("版本号必须是非负整数", 400)
        if expected != current:
            raise HostError("裁定已更新，请重新核对版本")


def _reason(value, *, required):
    if not isinstance(value, str) or (required and not value.strip()):
        raise HostError("请填写改判或重开的理由", 400)
    return value.strip()


def _require_retention_review(state, expected_series_revision, reason):
    if expected_series_revision is None:
        raise HostError("保留下游须提交此次核对的系列版本", 400)
    _baseline(expected_series_revision, state["revision"])
    _reason(reason, required=True)
    if not state["series"] or state["series"]["state"] != "settled":
        raise HostError("只有更改当前正式结算时才能裁定保留下游")


def map_score_finished(score1: int, score2: int) -> bool:
    """常规每半 12 回合；12:12 后每轮加时从同分起，先取四回合。"""
    low, high = sorted((score1, score2))
    if high == 13:
        return 0 <= low <= 11
    return high >= 16 and (high - 16) % 3 == 0 and high - 4 <= low <= high - 2


def _state(conn, match):
    mid = match["id"]
    maps = [
        dict(row)
        for row in conn.execute(
            """SELECT sm.scheduled_map_id,sm.map_order,sm.legacy_slot,sm.map_name,sm.is_enabled,
                  r.map_run_id,r.status AS run_status,o.official_map_result_id,o.score1,o.score2,
                  o.actor,o.source,o.reason,o.recorded_at,o.terminal_receipt,
                  CASE WHEN o.score1>o.score2 THEN 'home' WHEN o.score1<o.score2 THEN 'away' END AS winner_side,
                  EXISTS(SELECT 1 FROM map_runs h WHERE h.scheduled_map_id=sm.scheduled_map_id) AS has_started,
                  COALESCE((SELECT MAX(h.revision+(h.revoked_at IS NOT NULL))
                       FROM official_map_results h WHERE h.scheduled_map_id=sm.scheduled_map_id),0) AS revision
           FROM scheduled_maps sm LEFT JOIN map_runs r
             ON r.scheduled_map_id=sm.scheduled_map_id AND r.status<>'void'
           LEFT JOIN official_map_results o ON o.scheduled_map_id=sm.scheduled_map_id AND o.is_current=1
           WHERE sm.match_id=? ORDER BY sm.map_order""",
            (mid,),
        )
    ]
    latest = conn.execute(
        """SELECT s.*,home.event_entrant_id AS home_entrant_id,away.event_entrant_id AS away_entrant_id
           FROM series_settlements s JOIN match_participants home ON home.match_participant_id=s.home_participant_id
           JOIN match_participants away ON away.match_participant_id=s.away_participant_id
           WHERE s.match_id=? ORDER BY s.revision DESC LIMIT 1""",
        (mid,),
    ).fetchone()
    settled = dict(latest) if latest else None
    if settled:
        settled["map_result_ids"] = json.loads(settled["map_result_ids"])
        side = None
        if settled["state"] == "settled":
            side = "home" if settled["score1"] > settled["score2"] else "away"
        settled["winner_side"] = side
        settled["winner_event_entrant_id"] = settled[f"{side}_entrant_id"] if side else None
    # 每次图版本变更、撤图和系列办理各推进一次；管理员预览后换了依据也要失效。
    revision = sum(m["revision"] for m in maps)
    revision += conn.execute(
        "SELECT count(*) FROM series_settlements WHERE match_id=?", (mid,)
    ).fetchone()[0]
    scores = [m for m in maps if m["is_enabled"] and m["official_map_result_id"] is not None]
    wins = sum(m["score1"] > m["score2"] for m in scores)
    return {
        "match_id": mid,
        "status": match["status"],
        "bo_format": match["bo_format"],
        "score1": wins,
        "score2": len(scores) - wins,
        "revision": revision,
        "series": settled,
        "maps": maps,
    }


def read_results(conn, match_id):
    """每图 revision 用于单图操作；顶层 revision 用于完赛与系列重开。读取不写库。"""
    return _state(conn, _match(conn, match_id))


def _fixed_participants(conn, match_id):
    rows = {
        r["side_key"]: r
        for r in conn.execute("SELECT * FROM match_participants WHERE match_id=?", (match_id,))
    }
    if (
        set(rows) != {"home", "away"}
        or rows["home"]["event_entrant_id"] == rows["away"]["event_entrant_id"]
    ):
        raise HostError("正式赛果需要两支不同的本届参赛队")
    return rows


def _validate_progress(state, *, changed_map=None, winner_side=None):
    needed = {"BO1": 1, "BO3": 2, "BO5": 3}.get(state["bo_format"])
    if needed is None:
        raise HostError("正式赛果只支持 BO1、BO3、BO5")
    wins = [0, 0]
    missing = False
    for m in state["maps"]:
        if not m["is_enabled"]:
            continue
        if max(wins) >= needed and m["has_started"]:
            raise HostError("此前已经决胜，不能保留决胜后开打的赛图")
        if m["official_map_result_id"] is None:
            missing = True
            continue
        if missing:
            raise HostError("不能跳过未裁定的前序赛图")
        side = winner_side if m["scheduled_map_id"] == changed_map else m["winner_side"]
        wins[int(side == "away")] += 1
    return wins


def map_change_options(state):
    """只读：用正式结算的赛程顺序和判胜规则预览已有图分的改判。"""
    series = state["series"]
    options = {}
    if not series or series["state"] != "settled":
        return options
    for slot in state["maps"]:
        if slot["official_map_result_id"] is None:
            continue
        mid = slot["scheduled_map_id"]
        options[mid] = {}
        for side in ("home", "away"):
            try:
                score = _validate_progress(state, changed_map=mid, winner_side=side)
            except HostError as exc:
                options[mid][side] = {"error": exc.message}
                continue
            winner, loser = get_series_result(state["bo_format"], *score)
            entrants: dict[str | None, int | None] = {
                "t1": series["home_entrant_id"],
                "t2": series["away_entrant_id"],
            }
            options[mid][side] = {"winner": entrants.get(winner), "loser": entrants.get(loser)}
    return options


def _target(state, scheduled_map_id, map_run_id):
    for m in state["maps"]:
        if m["scheduled_map_id"] == scheduled_map_id and m["is_enabled"]:
            if m["map_run_id"] != map_run_id or map_run_id is None:
                raise HostError("开局不属于该赛图或旧局已作废")
            return m
    raise HostError("排定赛图不属于本场或未启用")


def _write_settlement(conn, state, *, settle, actor, reason, retain_downstream=None):
    mid, score1, score2 = state["match_id"], state["score1"], state["score2"]
    fixed = _fixed_participants(conn, mid)
    winner, _ = get_series_result(state["bo_format"], score1, score2)
    if settle and winner is None:
        raise HostError("正式图胜场尚未满足该赛制，不能完赛")
    if not settle:
        winner = None
    decision = conn.execute(
        """INSERT INTO series_settlements(match_id,revision,previous_revision,state,score1,score2,
           home_participant_id,away_participant_id,map_result_ids,actor,reason)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            mid,
            state["revision"] + 1,
            state["revision"],
            "settled" if settle else "reopened",
            score1,
            score2,
            fixed["home"]["match_participant_id"],
            fixed["away"]["match_participant_id"],
            json.dumps(
                [m["official_map_result_id"] for m in state["maps"] if m["official_map_result_id"]]
            ),
            actor,
            reason,
        ),
    ).lastrowid
    winner_id = loser_id = None
    if winner:
        winning_side, losing_side = ("home", "away") if winner == "t1" else ("away", "home")
        winner_id = fixed[winning_side]["event_entrant_id"]
        loser_id = fixed[losing_side]["event_entrant_id"]
    apply_bracket_outcome(
        conn, mid, decision, winner_id, loser_id, retain_downstream=retain_downstream
    )
    settle_managed_predictions(conn, mid, decision, winner, score1, score2)
    conn.execute(
        "UPDATE matches SET status=?,team1_score=?,team2_score=? WHERE id=?",
        ("completed" if settle else "live", score1, score2, mid),
    )


def _after_map_change(conn, match, slot, scores, *, actor, reason, retain_downstream=None):
    state = _state(conn, match)
    _validate_progress(state)
    refresh_map(conn, slot["scheduled_map_id"])
    # 旧页面的列只作显示副本，计算系列胜场从不读回这些列。
    legacy = slot["legacy_slot"]
    conn.execute(
        f"UPDATE matches SET map{legacy}_t1=?,map{legacy}_t2=?,team1_score=?,team2_score=? WHERE id=?",
        (*scores, state["score1"], state["score2"], match["id"]),
    )
    if state["series"] and state["series"]["state"] == "settled":
        winner, _ = get_series_result(state["bo_format"], state["score1"], state["score2"])
        _write_settlement(
            conn,
            state,
            settle=winner is not None,
            actor=actor,
            reason=reason,
            retain_downstream=retain_downstream,
        )


def confirm_map(
    conn,
    match_id,
    scheduled_map_id,
    map_run_id,
    score1,
    score2,
    *,
    actor,
    source,
    reason="",
    expected_revision=None,
    terminal_receipt=None,
    retain_downstream=None,
    expected_series_revision=None,
):
    match = _write_match(conn, match_id, actor, source)
    if retain_downstream is not None and source != "admin":
        raise HostError("只有管理员可以明确裁定保留下游", 403)
    if any(type(s) is not int or not 0 <= s <= 100 for s in (score1, score2)) or score1 == score2:
        raise HostError("正式图分须为 0 至 100 的整数，且不能平分", 400)
    normal_finish = map_score_finished(score1, score2)
    if source == "director":
        if not isinstance(terminal_receipt, str) or not 1 <= len(terminal_receipt.strip()) <= 120:
            raise HostError("导播裁定必须关联经验证的显式终图回执", 400)
        terminal_receipt = terminal_receipt.strip()
        if not normal_finish:
            raise HostError("导播比分不是合法终分，请核对常规或加时赛果", 400)
    elif terminal_receipt is not None:
        raise HostError("人工裁定不使用导播回执身份", 400)
    state = _state(conn, match)
    slot = _target(state, scheduled_map_id, map_run_id)
    prior = slot["official_map_result_id"]
    if retain_downstream is not None:
        _require_retention_review(state, expected_series_revision, reason)
        if expected_revision is None:
            raise HostError("保留下游须提交此次核对的赛图版本", 400)
        if not prior or (score1, score2) == (slot["score1"], slot["score2"]):
            raise HostError("没有旧图分变更，不能附带下游裁定")
    elif expected_series_revision is not None:
        _baseline(expected_series_revision, state["revision"])
    if prior and (score1, score2) == (slot["score1"], slot["score2"]):
        return {
            **slot,
            "match_id": match_id,
            "applied": False,
            "duplicate": True,
            "series_revision": state["revision"],
        }
    if source == "director" and (prior or match["status"] == "completed"):
        raise HostError("导播不能覆盖正式裁定或更改完赛结果")
    _baseline(expected_revision, slot["revision"])
    reason = _reason(reason, required=bool(prior) or not normal_finish)
    _fixed_participants(conn, match_id)
    if not prior and slot["run_status"] != "active":
        raise HostError("新裁定必须引用实际开打且未关闭的开局")
    if prior:
        conn.execute(
            "UPDATE official_map_results SET is_current=0 WHERE official_map_result_id=?", (prior,)
        )
    revision = slot["revision"] + 1
    conn.execute(
        """INSERT INTO official_map_results(scheduled_map_id,map_run_id,score1,score2,revision,
           is_current,actor,source,reason,terminal_receipt) VALUES(?,?,?,?,?,1,?,?,?,?)""",
        (
            scheduled_map_id,
            map_run_id,
            score1,
            score2,
            revision,
            actor,
            source,
            reason,
            terminal_receipt,
        ),
    )
    if not prior:
        conn.execute("UPDATE map_runs SET status='closed' WHERE map_run_id=?", (map_run_id,))
    _after_map_change(
        conn,
        match,
        slot,
        (score1, score2),
        actor=actor,
        reason=reason,
        retain_downstream=retain_downstream,
    )
    updated = read_results(conn, match_id)
    return {
        **_target(updated, scheduled_map_id, map_run_id),
        "match_id": match_id,
        "applied": True,
        "duplicate": False,
        "series_revision": updated["revision"],
    }


def settle_series(conn, match_id, *, actor, reason="", expected_revision=None):
    state = _state(conn, _write_match(conn, match_id, actor))
    previous = state["series"]
    if previous and previous["state"] == "settled":
        if expected_revision != previous["previous_revision"]:
            _baseline(expected_revision, state["revision"])
        return {**state, "applied": False}
    _baseline(expected_revision, state["revision"])
    _validate_progress(state)
    _write_settlement(conn, state, settle=True, actor=actor, reason=_reason(reason, required=False))
    return {**read_results(conn, match_id), "applied": True}


def reopen_series(conn, match_id, *, actor, reason, expected_revision=None, retain_downstream=None):
    state = _state(conn, _write_match(conn, match_id, actor))
    reason = _reason(reason, required=True)
    previous = state["series"]
    if retain_downstream is not None:
        _require_retention_review(state, expected_revision, reason)
    if not previous:
        raise HostError("本场尚未正式结算")
    if previous["state"] == "reopened":
        if expected_revision != previous["previous_revision"]:
            _baseline(expected_revision, state["revision"])
        return {**state, "applied": False}
    _baseline(expected_revision, state["revision"])
    _write_settlement(
        conn, state, settle=False, actor=actor, reason=reason, retain_downstream=retain_downstream
    )
    return {**read_results(conn, match_id), "applied": True}


def revoke_for_replay(
    conn,
    match_id,
    scheduled_map_id,
    map_run_id,
    *,
    actor,
    reason,
    retain_downstream=None,
    expected_revision=None,
    expected_series_revision=None,
):
    """技术替补已核准；先撤裁定及结算，再由同一事务作废旧局。新局须等实际开打。"""
    match = _write_match(conn, match_id, actor)
    reason = _reason(reason, required=True)
    state = _state(conn, match)
    slot = _target(state, scheduled_map_id, map_run_id)
    if retain_downstream is not None:
        _require_retention_review(state, expected_series_revision, reason)
        if expected_revision is None:
            raise HostError("保留下游须提交此次核对的赛图版本", 400)
        if slot["official_map_result_id"] is None:
            raise HostError("该开局没有正式图分，不能附带下游裁定")
    elif expected_series_revision is not None:
        _baseline(expected_series_revision, state["revision"])
    _baseline(expected_revision, slot["revision"])
    if conn.execute(
        """SELECT 1 FROM scheduled_maps s JOIN map_runs r USING(scheduled_map_id)
           WHERE s.match_id=? AND s.map_order>? LIMIT 1""",
        (match_id, slot["map_order"]),
    ).fetchone():
        raise HostError("后续赛图已开打，不能倒放赛程办理重赛")
    result_id = slot["official_map_result_id"]
    if result_id is not None:
        conn.execute(
            """UPDATE official_map_results SET is_current=0,revoked_by=?,revoke_reason=?,
               revoked_at=CURRENT_TIMESTAMP WHERE official_map_result_id=?""",
            (actor, reason, result_id),
        )
        _after_map_change(
            conn,
            match,
            slot,
            (0, 0),
            actor=actor,
            reason=reason,
            retain_downstream=retain_downstream,
        )
    return {
        "match_id": match_id,
        "scheduled_map_id": scheduled_map_id,
        "map_run_id": map_run_id,
        "revoked_result_id": result_id,
        "applied": result_id is not None,
    }
