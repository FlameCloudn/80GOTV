"""Shared binding and compatibility projection for hosted live feeds."""

import json

from site_core.events.registration import require_admin
from site_core.host import PREMATCH_ONLY, HostError
from site_core.matches import operations
from utils.demo_parser import normalize_map_name


def live_schema_ready(conn):
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='live_director_receipts'"
        ).fetchone()
        is not None
    )


def start_projection(conn, match_id):
    if not live_schema_ready(conn):
        return {
            "eligible": False,
            "authorized": False,
            "ready_for_start": False,
            "reason": PREMATCH_ONLY,
        }
    return operations.start_state(conn, match_id)


def require_start_authorization(conn, match_id):
    state = start_projection(conn, match_id)
    if not state["ready_for_start"]:
        reason = state["reason"]
        if state["eligible"] and not state["authorized"]:
            reason = f"本场仍在赛前准备：{reason}"
        raise HostError(reason)


def resolve_schedule(conn, match_id, map_name, slot=None):
    plans = conn.execute(
        """SELECT * FROM scheduled_maps WHERE match_id=? AND is_enabled=1
           AND (? IS NULL OR legacy_slot=?)""",
        (match_id, slot, slot),
    )
    key = normalize_map_name(map_name)
    matching = [
        plan for plan in plans if plan["map_name"] and normalize_map_name(plan["map_name"]) == key
    ]
    if not matching:
        raise HostError("推送地图不在该比赛指定赛程槽位中")
    if len(matching) != 1:
        raise HostError("同名地图存在多个槽位，请明确指定地图槽位")
    return matching[0]


def parse_session_id(value, match_id, *, required=False):
    if value is None and not required:
        return ""
    if not isinstance(value, str) or len(value.strip()) > 120 or (required and not value.strip()):
        raise HostError("导播会话编号格式错误", 400)
    value = value.strip()
    if value.startswith("80gotv:") and value.split(":", 2)[1] != str(match_id):
        raise HostError("导播会话属于另一场比赛，请重新同步")
    return value


def _bound_run(conn, scheduled_map_id, session_id):
    return conn.execute(
        """SELECT map_run_id FROM live_director_sessions
           WHERE scheduled_map_id=? AND session_id=?""",
        (scheduled_map_id, session_id),
    ).fetchone()


def register_director_session(conn, scheduled_map_id, run_id, session_id, *, actor=None, reason):
    return (
        conn.execute(
            """INSERT INTO live_director_sessions(scheduled_map_id,session_id,map_run_id,actor,reason)
           VALUES(?,?,?,?,?) ON CONFLICT(scheduled_map_id,session_id) DO NOTHING""",
            (scheduled_map_id, session_id, run_id, actor, reason),
        ).rowcount
        == 1
    )


def bind_director_session(conn, match_id, run_id, session_id, *, actor, reason):
    """Associate a verified independent director session inside the caller's write transaction."""
    require_admin(conn, actor)
    session_id = parse_session_id(session_id, match_id, required=True)
    if not isinstance(reason, str) or not reason.strip():
        raise HostError("请说明如何核对新导播会话和实际开局", 400)
    run = operations.match_run(conn, match_id, run_id)
    scheduled_map_id = run["scheduled_map_id"]
    bound = _bound_run(conn, scheduled_map_id, session_id)
    if bound and bound["map_run_id"] != run_id:
        raise HostError("同一赛图的导播会话已经绑定另一局，不能改绑")
    if run["status"] != "active":
        raise HostError("仅能绑定仍在进行的实际开局")
    require_start_authorization(conn, match_id)
    inserted = register_director_session(
        conn,
        scheduled_map_id,
        run_id,
        session_id,
        actor=actor,
        reason=reason.strip(),
    )
    return {
        "scheduled_map_id": scheduled_map_id,
        "map_run_id": run_id,
        "session_id": session_id,
        "duplicate": not inserted,
    }


def director_receipts_for_run(conn, match_id, run_id):
    """For the authorized operations reader; never expose receipt evidence in public metadata."""
    operations.match_run(conn, match_id, run_id)
    return [
        {
            **json.loads(row["response"]),
            "session_id": row["session_id"],
            "frame_seq": row["frame_seq"],
            "received_at": row["received_at"],
            "players_candidate": json.loads(row["players_candidate"] or "[]"),
        }
        for row in conn.execute(
            """SELECT response,players_candidate,received_at,session_id,frame_seq FROM live_director_receipts
               WHERE match_id=? AND map_run_id=? ORDER BY received_at,result_id""",
            (match_id, run_id),
        )
    ]


def resolve_run(conn, scheduled_map_id, expected_run_id, *, session_id=""):
    run = operations.current_run(conn, scheduled_map_id)
    bound = _bound_run(conn, scheduled_map_id, session_id) if session_id else None
    if bound and (not run or bound["map_run_id"] != run["map_run_id"]):
        raise HostError("导播会话属于本图的旧开局，不能用于重赛")
    if expected_run_id is not None:
        if not run or run["map_run_id"] != expected_run_id:
            raise HostError("上报的开局编号与当前开局不一致，请核对后重发")
    if (
        not bound
        and (session_id or expected_run_id is None)
        and conn.execute(
            "SELECT 1 FROM map_runs WHERE scheduled_map_id=? AND status='void' LIMIT 1",
            (scheduled_map_id,),
        ).fetchone()
    ):
        raise HostError("本图正在或曾经重赛，无法确认报文属于哪一局，请核对并绑定新导播会话")
    return run


def run_lineup(conn, run_id):
    return {
        row["steam_id"]: row
        for row in conn.execute(
            """SELECT l.*,p.side_key,pl.nickname AS name FROM map_run_lineups l
               JOIN match_participants p USING(match_participant_id)
               JOIN players pl ON pl.id=l.player_id WHERE l.map_run_id=?""",
            (run_id,),
        )
    }


def load_snapshot(conn, match_id):
    row = conn.execute(
        "SELECT live_state FROM live_match_data WHERE match_id=?", (match_id,)
    ).fetchone()
    try:
        state = json.loads(row["live_state"] or "{}") if row else {}
    except json.JSONDecodeError:
        return {}
    return state if isinstance(state, dict) else {}


def snapshot_for_run(state, plan, run_id):
    if state.get("map_run_id") == run_id:
        return state
    return {
        **({"a2s": state["a2s"]} if "a2s" in state else {}),
        "scheduled_map_id": plan["scheduled_map_id"],
        "map_run_id": run_id,
    }


def save_snapshot(conn, match_id, state):
    conn.execute(
        """INSERT INTO live_match_data(match_id,live_state) VALUES(?,?)
           ON CONFLICT(match_id) DO UPDATE
           SET live_state=excluded.live_state,updated_at=CURRENT_TIMESTAMP""",
        (match_id, json.dumps(state, ensure_ascii=False)),
    )


def project_director_match(conn, match_id, maps, roster, snapshot):
    """Keep the old map/roster fields, but read results and attempts by scheduled identity."""
    plans = conn.execute(
        """SELECT s.scheduled_map_id,s.legacy_slot,r.map_run_id,r.status,
                  o.official_map_result_id,o.score1,o.score2
           FROM scheduled_maps s
           LEFT JOIN map_runs r ON r.scheduled_map_id=s.scheduled_map_id AND r.status<>'void'
           LEFT JOIN official_map_results o
                ON o.scheduled_map_id=s.scheduled_map_id AND o.is_current=1
           WHERE s.match_id=? AND s.is_enabled=1 ORDER BY s.map_order""",
        (match_id,),
    ).fetchall()
    by_slot = {plan["legacy_slot"]: plan for plan in plans}
    for item in maps:
        plan = by_slot[item["slot"]]
        final = plan["official_map_result_id"] is not None
        item.update(
            scheduled_map_id=plan["scheduled_map_id"],
            map_run_id=plan["map_run_id"],
            map_finished=final,
        )
        if final:
            item.update(team1_score=plan["score1"], team2_score=plan["score2"])
        elif plan["status"] == "active" and plan["map_run_id"] == snapshot.get("map_run_id"):
            scores = snapshot.get("observed_score")
            if scores:
                item.update(team1_score=scores[0], team2_score=scores[1])

    if roster["locked"] and plans:
        current = next(
            (plan for plan in plans if plan["official_map_result_id"] is None), plans[-1]
        )
        lineup = operations.effective_roster(conn, match_id, current["scheduled_map_id"])
        original = {
            (side, player["slot"]): player
            for side, players in roster["players"].items()
            for player in players
        }
        for member in lineup:
            side = 1 if member["side_key"] == "home" else 2
            slot = member["roster_slot"]
            player = original[side, slot]
            if player["id"] == member["player_id"]:
                continue
            replacement = conn.execute(
                """SELECT id,nickname,avatar,group_username_override,is_bashizhong_student
                   FROM players WHERE id=?""",
                (member["player_id"],),
            ).fetchone()
            player.update(dict(replacement), steam_id=member["steam_id"], is_substitute=True)
        roster["steam_ids"] = [
            player["steam_id"] for players in roster["players"].values() for player in players
        ]
