"""Reconcile prediction scores against valid series settlements."""

from src.website.domains.predictions.votes import _LEGACY_EVENT
from src.website.runtime.host import has_event_schema

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
