"""
比赛相关业务逻辑：临时队伍补全、赛事状态计算、预测计分、BP 记录拆分
"""

import json
import re
import sqlite3
from datetime import datetime

from services.match_roster_service import frozen_match_teams, match_registration
from services.team_logo_service import logo_relative_path
from utils.helpers import normalize_map_key, row_get, team_abbr


def match_stat_belongs_to_side(row, expected_side, expected_team_id):
    """Use the recorded match side; only fall back to real team IDs for old rows."""
    stored_side = str(row_get(row, "match_team_side", "") or "").strip().lower()
    if stored_side in {"t1", "t2"}:
        return stored_side == expected_side
    return expected_team_id is not None and row_get(row, "team_id") == expected_team_id


def get_series_result(bo_format, score1, score2):
    """Return the two match sides only for a valid, decided BO1/BO3/BO5 result."""
    wins_needed = {"BO1": 1, "BO3": 2, "BO5": 3}.get(str(bo_format or "BO3").upper())
    if wins_needed is None:
        return None, None
    scores = []
    for value in (score1, score2):
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            return None, None
        text = str(value).strip()
        if not text.isascii() or not text.isdigit():
            return None, None
        scores.append(int(text))
    if max(scores) != wins_needed or min(scores) >= wins_needed:
        return None, None
    return ("t1", "t2") if scores[0] > scores[1] else ("t2", "t1")


def completed_match_result_error(match):
    """Validate the explicit finish action without requiring map or Demo details."""
    match = dict(match)
    if match.get("status") == "cancelled":
        return "比赛已取消，不能直接结束比赛"
    winner, _ = get_series_result(
        match.get("bo_format"), match.get("team1_score"), match.get("team2_score")
    )
    if winner is None:
        return "比分尚未达到该赛制的获胜条件，或比分无效，不能结束比赛"
    for side in (1, 2):
        if not match.get(f"team{side}_id") and not _has_temp_players(
            match.get(f"team{side}_players")
        ):
            return "请先确认双方参赛队伍，再结束比赛"
    if match.get("team1_id") and match.get("team1_id") == match.get("team2_id"):
        return "两支参赛队伍不能相同"
    return None


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
    if not isinstance(player_ids, list):
        return None
    player_ids = [player_id for player_id in player_ids if player_id is not None]
    if len(player_ids) != 1:
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
    value = logo_relative_path(row["team_logo"])
    if value.startswith(("http://", "https://", "/")):
        return ""
    return value


def supplement_temp_teams(match_row, conn=None):
    """补齐比赛两侧的临时名称、简称和报名队标。"""
    m = dict(match_row)
    frozen = frozen_match_teams(m)
    if frozen:
        for side in (1, 2):
            info = frozen[str(side)]
            m[f"team{side}_name"] = info.get("name") or "TBD"
            m[f"t{side}s"] = info.get("short_name") or team_abbr(m[f"team{side}_name"])
            for key in (f"team{side}_logo", f"t{side}_logo"):
                m[key] = info.get("logo") or ""
    elif conn is not None:
        for side in (1, 2):
            if m.get(f"team{side}_registration_id"):
                registration = match_registration(conn, m, side)
                if registration:
                    m[f"team{side}_name"] = registration["team_name"]
    missing_short_ids = [
        m[f"team{side}_id"]
        for side in (1, 2)
        if m.get(f"team{side}_id", 0) and m[f"team{side}_id"] > 0 and not m.get(f"t{side}s")
    ]
    if conn is not None and missing_short_ids:
        placeholders = ",".join("?" for _ in missing_short_ids)
        shorts = {
            row["id"]: row["short_name"]
            for row in conn.execute(
                f"SELECT id, short_name FROM teams WHERE id IN ({placeholders})", missing_short_ids
            )
        }
        for side in (1, 2):
            if not m.get(f"t{side}s"):
                m[f"t{side}s"] = shorts.get(m.get(f"team{side}_id"))
    for side in (1, 2):
        if frozen:
            continue
        if (m.get(f"team{side}_id") and m.get(f"team{side}_id") != -side) or not _has_temp_players(
            m.get(f"team{side}_players")
        ):
            continue
        registration = match_registration(conn, m, side) if conn is not None else None
        single_name = _single_temp_player_name(m.get(f"team{side}_players"), conn)
        name = (
            (registration["team_name"] if registration else None)
            or single_name
            or m.get(f"team{side}_name")
        )
        m[f"team{side}_name"] = name or "TBD"
        m[f"t{side}s"] = m.get(f"t{side}s") or (single_name or team_abbr(name) if name else "TBD")
    # 尚未由真实赛果分配的对阵必须在所有页面显示 TBD。
    if not m.get("team1_name"):
        m["team1_name"] = "TBD"
    if not m.get("team2_name"):
        m["team2_name"] = "TBD"
    # 为注册队伍补充空 short_name（和队标占位缩写同一套规则）。
    if not m.get("t1s"):
        m["t1s"] = "TBD" if m["team1_name"] == "TBD" else team_abbr(m["team1_name"])
    if not m.get("t2s"):
        m["t2s"] = "TBD" if m["team2_name"] == "TBD" else team_abbr(m["team2_name"])
    # A registered event team is the source of truth for that event. Prefer its
    # uploaded logo everywhere so a newer event logo cannot be hidden by an old
    # permanent team logo.
    for side in (1, 2):
        if frozen:
            continue
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
        if m.get("status") == "live":
            m["effective_status"] = "live"
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
        end_val = event.get("end_date")
        start_val = event.get("start_date")
        end_dt = (
            datetime.fromisoformat(str(end_val).replace("Z", "+00:00").replace("T", " ")[:19])
            if end_val
            else None
        )
        start_dt = (
            datetime.fromisoformat(str(start_val).replace("Z", "+00:00").replace("T", " ")[:19])
            if start_val
            else None
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


def get_prediction_upcoming_matches(conn):
    """Share the existing HTML upcoming-match selection with the JSON API."""
    rows = conn.execute(
        """SELECT m.id,m.slug,m.match_time,m.bo_format,m.event_id,
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
           WHERE COALESCE(m.status,'')='upcoming'
             AND (m.match_time IS NULL OR datetime(m.match_time)>datetime('now','localtime'))
           GROUP BY m.id ORDER BY vote_count DESC,m.match_time ASC LIMIT 10"""
    ).fetchall()
    return [supplement_temp_teams(row, conn) for row in rows]


def get_prediction_leaderboard(conn, limit=10):
    """Read current prediction scores without updating votes, matches or caches."""
    rows = conn.execute(
        """WITH predictions AS (
               SELECT v.user_id,v.voted_for,v.score1_guess,v.score2_guess,
                      u.username,u.avatar,u.is_cheater,m.team1_score,m.team2_score,
                      CASE UPPER(COALESCE(NULLIF(m.bo_format,''),'BO3'))
                          WHEN 'BO1' THEN 1 WHEN 'BO3' THEN 2 WHEN 'BO5' THEN 3
                      END AS wins_needed
               FROM match_votes v
               JOIN matches m ON m.id=v.match_id
               JOIN users u ON u.id=v.user_id
               WHERE m.status='completed'
                 AND typeof(m.team1_score)='integer' AND typeof(m.team2_score)='integer'
                 AND m.team1_score>=0 AND m.team2_score>=0
           ), valid_votes AS (
               SELECT *,CASE
                   WHEN (team1_score>team2_score AND voted_for='t1')
                     OR (team2_score>team1_score AND voted_for='t2')
                   THEN 3+CASE WHEN score1_guess=team1_score AND score2_guess=team2_score THEN 5 ELSE 0 END
                   ELSE 0 END AS current_points
               FROM predictions
               WHERE (team1_score=wins_needed AND team2_score<wins_needed)
                  OR (team2_score=wins_needed AND team1_score<wins_needed)
           )
           SELECT user_id,username,avatar,is_cheater,COUNT(*) AS total_votes,
                  SUM(CASE WHEN current_points>0 THEN 1 ELSE 0 END) AS correct_votes,
                  SUM(current_points) AS total_points,
                  MAX(CASE WHEN current_points>=8 THEN 1 ELSE 0 END) AS has_perfect
           FROM valid_votes GROUP BY user_id
           ORDER BY total_points DESC,correct_votes DESC,user_id ASC LIMIT ?""",
        (max(1, min(int(limit), 100)),),
    ).fetchall()
    return [dict(row) for row in rows]


def score_predictions(conn, match_id=None):
    """Reconcile prediction points with the current valid completed result.
    正确猜中胜者: +3 分
    正确猜中精确比分: 额外 +5 分
    """
    query = """
        SELECT v.id, v.match_id, v.voted_for, v.score1_guess, v.score2_guess,
               v.scored, v.points_earned, m.status, m.bo_format, m.team1_score, m.team2_score
        FROM match_votes v
        JOIN matches m ON v.match_id = m.id
        WHERE (m.status='completed' OR COALESCE(v.scored,0)<>0 OR COALESCE(v.points_earned,0)<>0)
    """
    params = ()
    if match_id is not None:
        query += " AND m.id=?"
        params = (match_id,)
    votes = conn.execute(query, params).fetchall()

    for v in votes:
        winner, _ = (
            get_series_result(v["bo_format"], v["team1_score"], v["team2_score"])
            if v["status"] == "completed"
            else (None, None)
        )
        points = 0
        scored = 1 if winner else 0
        if winner and v["voted_for"] == winner:
            points += 3
            # 精确比分加分
            if (
                v["score1_guess"] is not None
                and v["score2_guess"] is not None
                and v["score1_guess"] == v["team1_score"]
                and v["score2_guess"] == v["team2_score"]
            ):
                points += 5
        if v["points_earned"] != points or v["scored"] != scored:
            conn.execute(
                "UPDATE match_votes SET points_earned=?, scored=? WHERE id=?",
                (points, scored, v["id"]),
            )


# ── BP 记录拆分（比赛页把文字记录画成步骤列表） ─────────────────
# 支持两种写法：系统生成的“1. T1 Ban Inferno / 7. Dust2 剩余 / 选边: Dust2 → CT 方”，
# 以及管理员手写的“T3 BAN OP / LEFT NUKE”。认不出的行放进 notes 原样显示。
_BP_ROLL = re.compile(
    r"^roll[:：]\s*(?P<a>[^=]+?)=(?P<ra>[^,，]+?)\s*[,，]\s*(?P<b>[^=]+?)=(?P<rb>\S+?)"
    r"(?:\s*→\s*(?P<win>.+?)\s*胜出)?$",
    re.I,
)
_BP_ORDER = re.compile(r"^(?P<team>.+?)\s*选择(?P<order>先手|后手)$")
_BP_STEP = re.compile(
    r"^(?:(?P<num>\d+)[.、)]\s*)?(?P<team>.+?)\s+(?P<act>ban|pick)\s+(?P<map>.+)$", re.I
)
_BP_LEFT = re.compile(
    r"^(?:(?P<num>\d+)[.、)]\s*)?(?:(?P<map>.+?)\s*剩余|(?:left|decider)\s+(?P<map2>.+))$", re.I
)
_BP_SIDE = re.compile(
    r"^选边[:：]\s*(?:(?P<team>.+?)\s+为\s+(?P<map>.+?)\s+选择\s*|(?P<map2>.+?)\s*→\s*)(?P<side>CT|T)\s*方?$",
    re.I,
)


def _bp_team_side(label, team_labels):
    """BP 记录里的队名 → 't1' / 't2'；认不出返回 None（页面直接显示原文）。"""
    key = (label or "").strip().casefold()
    for side, labels in team_labels.items():
        if key in labels:
            return side
    return None


def _bp_add_step(result, num, team_label, action, map_name, team_labels):
    """记一步禁图 / 选图 / 决胜图；没写序号的按顺序补上。"""
    result["steps"].append(
        {
            "num": int(num) if num else len(result["steps"]) + 1,
            "team": _bp_team_side(team_label, team_labels),
            "label": (team_label or "").strip(),
            "action": action,
            "map": map_name.strip(),
        }
    )


def _bp_parse_line(line, result, team_labels):
    """拆一行 BP 记录，写进 result；这一行认不出来返回 False。"""
    if m := _BP_ROLL.match(line):
        rolls = {
            _bp_team_side(m["a"], team_labels) or "t1": m["ra"],
            _bp_team_side(m["b"], team_labels) or "t2": m["rb"],
        }
        result["roll"] = {
            "t1": rolls.get("t1", "?"),
            "t2": rolls.get("t2", "?"),
            "winner": _bp_team_side(m["win"], team_labels),
        }
    elif m := _BP_ORDER.match(line):
        result["order"] = {
            "team": _bp_team_side(m["team"], team_labels),
            "label": m["team"].strip(),
            "order": m["order"],
        }
    elif m := _BP_SIDE.match(line):
        result["sides"].append(
            {
                "team": _bp_team_side(m["team"], team_labels),
                "label": (m["team"] or "").strip(),
                "map": (m["map"] or m["map2"]).strip(),
                "side": m["side"].upper(),
            }
        )
    elif m := _BP_STEP.match(line):
        _bp_add_step(result, m["num"], m["team"], m["act"].lower(), m["map"], team_labels)
    elif m := _BP_LEFT.match(line):
        _bp_add_step(result, m["num"], "", "left", m["map"] or m["map2"], team_labels)
    else:
        return False
    return True


def _bp_fill_side_teams(result):
    """旧记录的“选边”没写是谁选的：选图的对手选边；BO1 的剩余图由没做最后一次禁图的队伍选。"""
    other = {"t1": "t2", "t2": "t1"}
    pickers = {
        normalize_map_key(st["map"]): st["team"] for st in result["steps"] if st["action"] == "pick"
    }
    bans = [st["team"] for st in result["steps"] if st["action"] == "ban"]
    for side in result["sides"]:
        if side["team"] or side["label"]:
            continue
        key = normalize_map_key(side["map"])
        if key in pickers and pickers[key]:
            side["team"] = other[pickers[key]]
        elif not pickers and bans and bans[-1]:
            side["team"] = other[bans[-1]]


def parse_bp_log(text, team1_labels, team2_labels):
    """把比赛的 BP 记录文字拆成 roll / 先后手 / 步骤 / 选边；一步都认不出时返回 None（页面原样显示文字）。

    team1_labels / team2_labels：记录里可能出现的两队叫法，比如 ["T1", 队名, 简称]。
    """
    team_labels = {
        "t1": {str(x).strip().casefold() for x in team1_labels if x},
        "t2": {str(x).strip().casefold() for x in team2_labels if x},
    }
    result = {"roll": None, "order": None, "steps": [], "sides": [], "notes": []}
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if line and not _bp_parse_line(line, result, team_labels):
            result["notes"].append(line)
    if not result["steps"]:
        return None
    _bp_fill_side_teams(result)
    return result
