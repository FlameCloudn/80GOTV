"""
比赛相关业务逻辑：临时队伍补全、赛事状态计算、预测计分
"""

from datetime import datetime


def supplement_temp_teams(match_row, conn=None):
    """为临时选手队伍填充 team_name 和 short_name，确保前端渲染不崩溃。
    conn 参数已废弃，保留仅为兼容旧调用。"""
    m = dict(match_row)
    if (not m.get("team1_id") or m.get("team1_id") == -1) and m.get("team1_players"):
        m["team1_name"] = "TEAM 1"
        m["t1s"] = "T1"
    if (not m.get("team2_id") or m.get("team2_id") == -2) and m.get("team2_players"):
        m["team2_name"] = "TEAM 2"
        m["t2s"] = "T2"
    # 为注册队伍补充空 short_name
    if not m.get("t1s"):
        m["t1s"] = (m.get("team1_name") or "T1")[:2]
    if not m.get("t2s"):
        m["t2s"] = (m.get("team2_name") or "T2")[:2]
    # 兜底队伍名
    if not m.get("team1_name"):
        m["team1_name"] = "TEAM 1"
    if not m.get("team2_name"):
        m["team2_name"] = "TEAM 2"
    # 补充 effective_status（若 SQL 未计算）
    if "effective_status" not in m:
        mt = m.get("match_time", "")
        if m.get("status") == "cancelled":
            m["effective_status"] = "cancelled"
            return m
        if m.get("status") == "completed":
            m["effective_status"] = "completed"
            return m
        try:
            if mt:
                mt_dt = datetime.fromisoformat(mt.replace("Z", "+00:00").replace("T", " ")[:19])
                if mt_dt > datetime.now():
                    m["effective_status"] = "upcoming"
                else:
                    m["effective_status"] = "live"
            else:
                m["effective_status"] = "upcoming"
        except (ValueError, TypeError):
            m["effective_status"] = "upcoming"
    return m


def add_effective_event_status(event_row, now=None):
    """根据日期计算赛事有效状态"""
    if now is None:
        now = datetime.now()
    event = dict(event_row)
    try:
        end_dt = datetime.fromisoformat(
            event["end_date"].replace("Z", "+00:00").replace("T", " ")[:19]
        )
        start_dt = datetime.fromisoformat(
            event["start_date"].replace("Z", "+00:00").replace("T", " ")[:19]
        )
    except (ValueError, TypeError):
        end_dt = start_dt = None
    if end_dt and end_dt < now:
        event["effective_event_status"] = "completed"
    elif start_dt and start_dt > now:
        event["effective_event_status"] = "upcoming"
    else:
        event["effective_event_status"] = "ongoing"
    return event


def score_predictions(conn):
    """对已完成但未计分的比赛投票进行计分。
    正确猜中胜者: +3 分
    正确猜中精确比分: 额外 +5 分
    """
    unscored = conn.execute("""
        SELECT v.id, v.match_id, v.voted_for, v.score1_guess, v.score2_guess,
               m.team1_score, m.team2_score
        FROM match_votes v
        JOIN matches m ON v.match_id = m.id
        WHERE v.scored = 0
          AND m.team1_score IS NOT NULL
          AND m.team2_score IS NOT NULL
          AND m.team1_score != m.team2_score
    """).fetchall()

    for v in unscored:
        winner = "t1" if v["team1_score"] > v["team2_score"] else "t2"
        points = 0
        if v["voted_for"] == winner:
            points += 3
            # 精确比分加分
            if (
                v["score1_guess"] is not None
                and v["score2_guess"] is not None
                and v["score1_guess"] == v["team1_score"]
                and v["score2_guess"] == v["team2_score"]
            ):
                points += 5
        conn.execute(
            "UPDATE match_votes SET points_earned=?, scored=1 WHERE id=?", (points, v["id"])
        )
