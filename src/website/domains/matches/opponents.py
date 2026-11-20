"""还原某场比赛真正参赛的两方：锁定名单、临时队伍、永久队伍与队标。"""

import json
import sqlite3
from datetime import datetime

from src.website.domains.directory.team_logo_service import logo_relative_path
from src.website.domains.directory.team_names import team_abbr
from src.website.domains.matches.maps import project_legacy_map_fields
from src.website.domains.matches.match_roster_service import (
    frozen_match_teams,
    managed_match_teams,
    match_registration,
)


def has_temp_players(value):
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
    managed = managed_match_teams(conn, m) if conn is not None else None
    if managed is not None:
        m = project_legacy_map_fields(conn, m)
        for side in (1, 2):
            info = managed.get(str(side), {})
            m[f"team{side}_id"] = info.get("team_id")
            m[f"team{side}_registration_id"] = info.get("registration_id")
            m[f"team{side}_name"] = info.get("name") or "TBD"
            m[f"t{side}s"] = info.get("short_name") or team_abbr(m[f"team{side}_name"])
            m[f"t{side}_logo"] = m[f"team{side}_logo"] = info.get("logo") or ""
            m[f"team{side}_players"] = json.dumps([p["id"] for p in info.get("players", [])])
            if info:
                m[f"_team{side}_identity"] = ("entrant", info["event_entrant_id"])
        # 日程到了不等于已真实开打。本批次只准备比赛。
        m["effective_status"] = m.get("status") or "upcoming"
        return m
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
        if (m.get(f"team{side}_id") and m.get(f"team{side}_id") != -side) or not has_temp_players(
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


def read_opponents(conn, match_id):
    row = conn.execute(
        """SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
                  t1.short_name AS t1s, t2.short_name AS t2s, t1.logo AS t1_logo, t2.logo AS t2_logo,
                  e.name AS event_name, e.status AS event_status
           FROM matches m LEFT JOIN teams t1 ON t1.id=m.team1_id
           LEFT JOIN teams t2 ON t2.id=m.team2_id LEFT JOIN events e ON e.id=m.event_id
           WHERE m.id=?""",
        (match_id,),
    ).fetchone()
    return supplement_temp_teams(row, conn) if row is not None else None
