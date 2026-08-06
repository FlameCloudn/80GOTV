"""
比赛相关业务逻辑：临时队伍补全、赛事状态计算、预测计分
"""

import json
import sqlite3
from datetime import datetime


def _has_temp_players(value):
    """Return whether a temporary match side contains an actual roster."""
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    try:
        return bool(json.loads(text))
    except (TypeError, ValueError, json.JSONDecodeError):
        return True


def _single_temp_player_name(value, conn):
    if conn is None:
        return None
    try:
        player_ids = json.loads(value) if value else []
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(player_ids, list) or len(player_ids) != 1:
        return None
    try:
        player_id = int(player_ids[0])
    except (TypeError, ValueError):
        return None
    row = conn.execute("SELECT nickname FROM players WHERE id=?", (player_id,)).fetchone()
    return str(row["nickname"] or "").strip() if row else None


def _event_registration_logo(conn, event_id, team_name):
    """Return a registration logo in the same relative format as team logos."""
    if conn is None or not event_id or not team_name or team_name == "TBD":
        return ""
    try:
        row = conn.execute(
            """
            SELECT team_logo
            FROM event_registrations
            WHERE event_id=?
              AND lower(trim(team_name))=lower(trim(?))
              AND trim(COALESCE(team_logo, '')) != ''
            ORDER BY id DESC
            LIMIT 1
            """,
            (event_id, team_name),
        ).fetchone()
    except (sqlite3.Error, TypeError):
        return ""
    if not row:
        return ""
    value = str(row["team_logo"] or "").strip().replace("\\", "/").lstrip("/")
    if value.startswith("static/uploads/"):
        value = value[len("static/uploads/") :]
    elif value.startswith("uploads/"):
        value = value[len("uploads/") :]
    if value.startswith(("http://", "https://")):
        return ""
    if "/" not in value:
        value = f"team_logos/{value}"
    return value


def supplement_temp_teams(match_row, conn=None):
    """补齐比赛两侧的临时名称、简称和报名队标。"""
    m = dict(match_row)
    if (not m.get("team1_id") or m.get("team1_id") == -1) and _has_temp_players(
        m.get("team1_players")
    ):
        name = _single_temp_player_name(m.get("team1_players"), conn)
        m["team1_name"] = name or "TEAM 1"
        m["t1s"] = name or "T1"
    if (not m.get("team2_id") or m.get("team2_id") == -2) and _has_temp_players(
        m.get("team2_players")
    ):
        name = _single_temp_player_name(m.get("team2_players"), conn)
        m["team2_name"] = name or "TEAM 2"
        m["t2s"] = name or "T2"
    # 尚未由真实赛果分配的对阵必须在所有页面显示 TBD。
    if not m.get("team1_name"):
        m["team1_name"] = "TBD"
    if not m.get("team2_name"):
        m["team2_name"] = "TBD"
    # 为注册队伍补充空 short_name。
    if not m.get("t1s"):
        m["t1s"] = "TBD" if m["team1_name"] == "TBD" else m["team1_name"][:2]
    if not m.get("t2s"):
        m["t2s"] = "TBD" if m["team2_name"] == "TBD" else m["team2_name"][:2]
    # A registered event team is the source of truth for that event. Prefer its
    # uploaded logo everywhere so a newer event logo cannot be hidden by an old
    # permanent team logo.
    for side in (1, 2):
        logo = _event_registration_logo(conn, m.get("event_id"), m.get(f"team{side}_name"))
        if not logo:
            continue
        for key in (f"team{side}_logo", f"t{side}_logo"):
            m[key] = logo
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
