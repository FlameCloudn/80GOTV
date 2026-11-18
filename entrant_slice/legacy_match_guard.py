"""只读旧比赛证据：不能用新报名命令更改已锁定或已经开打的阵容。"""

import sqlite3

from .storage import SliceError


def require_pre_series(conn: sqlite3.Connection, event_id: int, registration_group_id: int) -> None:
    from utils.match_utils import get_sql_effective_status

    club = conn.execute(
        "SELECT club_id FROM registration_group WHERE registration_group_id=?",
        (registration_group_id,),
    ).fetchone()[0]

    def clearly_other(group: int | None, team: int | None) -> bool:
        if club is not None and club == team:
            return False
        if group is not None:
            return group != registration_group_id
        return club is not None and team is not None and team > 0 and team != club

    # 旧导播可落图分而不改变计划状态；未知的旧两侧也不能当作无关队。
    scores = " OR ".join(f"m.map{slot}_t{side}>0" for slot in range(1, 6) for side in (1, 2))
    rows = conn.execute(
        f"""SELECT m.team1_registration_id,m.team2_registration_id,m.team1_id,m.team2_id,
        m.roster_snapshot,m.bp_state,m.bp_process,{get_sql_effective_status()},
        (m.status='ongoing' OR m.team1_score>0 OR m.team2_score>0 OR {scores} OR EXISTS (
            SELECT 1 FROM match_stats s WHERE s.match_id=m.id AND COALESCE(s.data_status,'final')='final')) AS started_evidence
        FROM matches m WHERE m.event_id=? AND COALESCE(m.status,'')!='cancelled'""",
        (event_id,),
    )
    for row in rows:
        if all(
            clearly_other(row[f"team{side}_registration_id"], row[f"team{side}_id"])
            for side in (1, 2)
        ):
            continue
        if (
            row["effective_status"] in ("completed", "live")
            or row["started_evidence"]
            or any(
                row[k] not in (None, "", "{}", "[]")
                for k in ("roster_snapshot", "bp_state", "bp_process")
            )
        ):
            raise SliceError("相关比赛已锁名单、已开始 BP 或开打；本切片不办理赛中或历史阵容变更")
