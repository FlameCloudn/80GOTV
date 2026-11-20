"""Accept predictions and read the current eligible matches and votes."""

from src.website.domains.matches.match_utils import get_sql_match_upcoming
from src.website.domains.matches.opponents import supplement_temp_teams
from src.website.runtime.host import HostError, has_event_schema, is_managed_match

_SCHEDULE_OPEN = """m.status='upcoming'
    AND (m.match_time IS NULL OR datetime(m.match_time)>datetime('now','localtime'))"""


_MANAGED_READY = """EXISTS (SELECT 1 FROM event_registration_control c
                            WHERE c.event_id=m.event_id AND c.archived_at IS NULL)
    AND (SELECT count(*) FROM match_participants p WHERE p.match_id=m.id)=2
    AND NOT EXISTS (SELECT 1 FROM match_start_authorizations a WHERE a.match_id=m.id)
    AND NOT EXISTS (SELECT 1 FROM scheduled_maps sm JOIN map_runs r USING(scheduled_map_id)
                    WHERE sm.match_id=m.id)"""


_LEGACY_EVENT = """NOT EXISTS (SELECT 1 FROM event_registration_control c
                               WHERE c.event_id=m.event_id)"""


def managed_vote_open(conn, match_id):
    return (
        conn.execute(
            f"SELECT 1 FROM matches m WHERE m.id=? AND {_SCHEDULE_OPEN} AND {_MANAGED_READY}",
            (match_id,),
        ).fetchone()
        is not None
    )


def vote_summary(conn, match_id, user_id):
    if not user_id:
        return {"t1_count": 0, "t2_count": 0, "total": 0, "user_voted": None}
    row = conn.execute(
        """SELECT COUNT(CASE WHEN voted_for='t1' THEN 1 END) AS t1_count,
                  COUNT(CASE WHEN voted_for='t2' THEN 1 END) AS t2_count,
                  MAX(CASE WHEN user_id=? THEN voted_for END) AS user_voted
           FROM match_votes WHERE match_id=?""",
        (user_id, match_id),
    ).fetchone()
    return {**dict(row), "total": row["t1_count"] + row["t2_count"]}


def cast_vote(
    conn,
    match_id: int,
    user_id: int,
    voted_for: str,
    score1_guess: int | None,
    score2_guess: int | None,
):
    """使用入口已校验的选择与比分；调用方负责提交或回滚。"""
    if is_managed_match(conn, match_id):
        # 与开赛操作共用写锁，取得后再判断双方是否确定、是否已经停止收票。
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        if not managed_vote_open(conn, match_id):
            raise HostError("本场对阵未确定或已停止接受竞猜", 409)
    elif not conn.execute(
        f"SELECT 1 FROM matches m WHERE m.id=? AND {get_sql_match_upcoming()}", (match_id,)
    ).fetchone():
        raise HostError("比赛已经开始或不存在，无法继续投票", 200)
    if conn.execute(
        "SELECT 1 FROM match_votes WHERE match_id=? AND user_id=?", (match_id, user_id)
    ).fetchone():
        raise HostError("您已投过票", 200)
    conn.execute(
        """INSERT INTO match_votes(match_id,user_id,voted_for,score1_guess,score2_guess)
           VALUES(?,?,?,?,?)""",
        (match_id, user_id, voted_for, score1_guess, score2_guess),
    )
    return vote_summary(conn, match_id, user_id)


def upcoming_match_rows(conn):
    managed_filter = (
        f" AND ({_LEGACY_EVENT} OR ({_MANAGED_READY}))" if has_event_schema(conn) else ""
    )
    return conn.execute(
        f"""SELECT m.id,m.slug,m.match_time,m.bo_format,m.event_id,
                  m.team1_id,m.team2_id,m.team1_players,m.team2_players,
                  m.roster_snapshot,m.team1_registration_id,m.team2_registration_id,
                  t1.short_name AS t1s,t2.short_name AS t2s,
                  COALESCE(t1.name,'TBD') AS team1_name,
                  COALESCE(t2.name,'TBD') AS team2_name,e.name AS event_name,
                  COUNT(v.id) AS vote_count,
                  SUM(CASE WHEN v.voted_for='t1' THEN 1 ELSE 0 END) AS t1_votes,
                  SUM(CASE WHEN v.voted_for='t2' THEN 1 ELSE 0 END) AS t2_votes
           FROM matches m
           LEFT JOIN match_votes v ON m.id=v.match_id
           LEFT JOIN teams t1 ON m.team1_id=t1.id
           LEFT JOIN teams t2 ON m.team2_id=t2.id
           LEFT JOIN events e ON m.event_id=e.id
           WHERE {_SCHEDULE_OPEN} {managed_filter}
           GROUP BY m.id ORDER BY vote_count DESC,m.match_time ASC LIMIT 10"""
    ).fetchall()


def get_prediction_upcoming_matches(conn):
    """兼容页面的展示格式：在竞猜候选行上补齐参赛队名与队标。"""
    return [supplement_temp_teams(row, conn) for row in upcoming_match_rows(conn)]
