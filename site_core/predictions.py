"""比赛竞猜：收票、票数、积分榜和正式赛果结算。"""

from site_core.host import HostError, has_event_schema, is_managed_match
from utils.match_utils import get_sql_match_upcoming

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


_EXACT_POINTS = 8
_POINTS = f"""CASE WHEN voted_for=winner THEN
    CASE WHEN score1_guess=score1 AND score2_guess=score2 THEN {_EXACT_POINTS} ELSE 3 END
    ELSE 0 END"""


def _legacy_votes(managed_schema, match_filter=""):
    """旧赛按当下有效的最终比分计算，不依赖上次写入的积分。"""
    return f"""WITH candidates AS (
        SELECT m.id,m.status,m.team1_score AS score1,m.team2_score AS score2,
               CASE UPPER(COALESCE(NULLIF(m.bo_format,''),'BO3'))
                   WHEN 'BO1' THEN 1 WHEN 'BO3' THEN 2 WHEN 'BO5' THEN 3
               END AS wins_needed
        FROM matches m WHERE {match_filter or "1=1"}
            {"AND " + _LEGACY_EVENT if managed_schema else ""}
    ), results AS (
        SELECT *,CASE WHEN status='completed' AND typeof(score1)='integer'
                       AND typeof(score2)='integer' AND score1>=0 AND score2>=0 THEN
                    CASE WHEN score1=wins_needed AND score2<wins_needed THEN 't1'
                         WHEN score2=wins_needed AND score1<wins_needed THEN 't2' END
                 END AS winner
        FROM candidates
    ), legacy_votes AS (
        SELECT v.id,v.user_id,v.scored,v.points_earned,winner IS NOT NULL AS new_scored,
               {_POINTS} AS new_points
        FROM match_votes v JOIN results r ON r.id=v.match_id
        WHERE r.status='completed' OR v.scored<>0 OR v.points_earned<>0
    )"""


def get_prediction_leaderboard(conn, limit=10):
    managed_schema = has_event_schema(conn)
    managed_votes = ""
    if managed_schema:
        # 新赛只认正式结算。管理员可能判胜或撤销，不能拿页面上的比分重新推算。
        managed_votes = """UNION ALL SELECT v.user_id,v.points_earned
            FROM match_votes v JOIN matches m ON m.id=v.match_id
            JOIN event_registration_control c ON c.event_id=m.event_id WHERE v.scored=1"""
    rows = conn.execute(
        f"""{_legacy_votes(managed_schema, "m.status='completed'")}, valid_votes AS (
                SELECT user_id,new_points AS points FROM legacy_votes WHERE new_scored=1
                {managed_votes}
            )
            SELECT u.id AS user_id,u.username,u.avatar,u.is_cheater,COUNT(*) AS total_votes,
                   SUM(CASE WHEN points>0 THEN 1 ELSE 0 END) AS correct_votes,
                   SUM(points) AS total_points,
                   MAX(CASE WHEN points>={_EXACT_POINTS} THEN 1 ELSE 0 END) AS has_perfect
            FROM valid_votes JOIN users u ON u.id=user_id GROUP BY u.id
            ORDER BY total_points DESC,correct_votes DESC,user_id ASC LIMIT ?""",
        (max(1, min(int(limit), 100)),),
    ).fetchall()
    return [dict(row) for row in rows]


def score_predictions(conn, match_id=None):
    projection = _legacy_votes(has_event_schema(conn), "m.id=?" if match_id is not None else "")
    changes = conn.execute(
        projection
        + """ SELECT new_points,new_scored,id FROM legacy_votes
                         WHERE points_earned IS NOT new_points OR scored IS NOT new_scored""",
        (match_id,) if match_id is not None else (),
    ).fetchall()
    for change in changes:
        conn.execute("UPDATE match_votes SET points_earned=?,scored=? WHERE id=?", change)


def revoke_legacy_points(conn, match_id):
    conn.execute("UPDATE match_votes SET scored=0,points_earned=0 WHERE match_id=?", (match_id,))


def settle_managed_predictions(conn, match_id, settlement_id, winner, score1, score2):
    """与赛果写在同一事务；每票记下改前和改后的值，改判不重复加分。"""
    scored = int(winner is not None)
    votes = conn.execute(
        f"""SELECT id,points_earned,scored,{_POINTS} AS new_points FROM match_votes
            CROSS JOIN (SELECT ? AS winner,? AS score1,? AS score2) WHERE match_id=?""",
        (winner, score1, score2, match_id),
    ).fetchall()
    for vote in votes:
        conn.execute(
            """INSERT INTO prediction_settlement_changes
               (settlement_id,vote_id,old_points,new_points,old_scored,new_scored)
               VALUES(?,?,?,?,?,?)""",
            (
                settlement_id,
                vote["id"],
                vote["points_earned"],
                vote["new_points"],
                vote["scored"],
                scored,
            ),
        )
        conn.execute(
            "UPDATE match_votes SET points_earned=?,scored=? WHERE id=?",
            (vote["new_points"], scored, vote["id"]),
        )
