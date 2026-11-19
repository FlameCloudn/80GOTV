"""Admin match editor, stats editor and demo import pages."""

import json
import logging
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from time import time

from flask import flash, redirect, render_template, request, session, url_for

from blueprints.admin import admin_bp
from config import BASE_DIR
from models import get_db
from services.bracket_service import (
    match_is_bound_to_bracket,
    refresh_bracket_for_match,
    refresh_event_bracket,
)
from services.demo_service import analyze_demo, import_demo_data
from services.live_log_service import persist_live_match_events
from services.manual_stats_service import (
    FORM_FIELDS,
    StatsRevisionConflict,
    manual_map_revision,
    save_manual_map_stats,
    stats_editor_players,
)
from services.match_roster_service import (
    freeze_match_roster,
    managed_match_teams,
    match_player_slots,
    registration_player_slots,
)
from services.match_service import (
    completed_match_result_error,
    supplement_temp_teams,
    update_match_slug,
)
from services.performance_service import refresh_player_performance
from site_core.community import delete_target_comments
from site_core.events import public as event_rosters
from site_core.events.registration import active_event
from site_core.host import (
    PREMATCH_ONLY,
    HostError,
    has_event_schema,
    is_managed_event,
    is_managed_match,
    write,
)
from site_core.matches import participants
from site_core.matches.maps import match_has_started
from site_core.predictions import revoke_legacy_points, score_predictions
from utils.demo_naming import build_demo_filename
from utils.helpers import (
    normalize_http_url,
    normalize_map_key,
    row_get,
)
from utils.match_utils import get_demo_upload_slot_count, get_sql_effective_status
from utils.web_helpers import admin_required as login_required
from utils.web_helpers import csrf_required, hash_bp_password

DEMOS_DIR = os.path.join(BASE_DIR, "static", "demos")
logger = logging.getLogger("80gotv.admin.matches")

LIVE_SCORE_FIELDS = (
    "team1_score",
    "team2_score",
    "map1_t1",
    "map1_t2",
    "map2_t1",
    "map2_t2",
    "map3_t1",
    "map3_t2",
    "map4_t1",
    "map4_t2",
    "map5_t1",
    "map5_t2",
    "has_map3",
    "has_map4",
    "has_map5",
    "map_halves",
)

LOCKED_AFTER_START_FIELDS = (
    "event_id",
    "match_time",
    "bo_format",
    "stage",
    "map1",
    "map2",
    "map3",
    "map4",
    "map5",
)


def _render_import_demo(match, **context):
    return render_template(
        "admin/import_demo.html",
        match=match,
        demo_slot_count=get_demo_upload_slot_count(match),
        **context,
    )


def _invalid_demo_upload_fields(files, slot_count):
    invalid = []
    for field, file in files.items():
        if not field.startswith("demo_file_") or not file or not file.filename:
            continue
        match = re.fullmatch(r"demo_file_(\d+)", field)
        if not match or int(match.group(1)) >= slot_count:
            invalid.append(field)
    return invalid


def _int_form(name, default=0):
    try:
        return int(request.form.get(name, default) or default)
    except (TypeError, ValueError):
        return default


def _parse_match_form(request, include_results=False):
    f = {}
    for i in range(1, 6):
        f[f"map{i}"] = request.form.get(f"map{i}", "")
        f[f"map{i}_t1"] = _int_form(f"map{i}_t1") if include_results else 0
        f[f"map{i}_t2"] = _int_form(f"map{i}_t2") if include_results else 0
        f[f"map{i}_pb"] = (
            request.form.get(f"map{i}_picked_by", "") or None if include_results else None
        )
    f["event_id"] = request.form.get("event_id")
    f["match_time"] = request.form.get("match_time")
    f["bo_format"] = request.form.get("bo_format", "BO3")
    f["stage"] = request.form.get("stage", "").strip() or None
    f["is_test_mode"] = 1 if request.form.get("is_test_mode") == "1" else 0
    f["team1_score"] = _int_form("team1_score") if include_results else 0
    f["team2_score"] = _int_form("team2_score") if include_results else 0
    f["has_map3"] = 0 if include_results and request.form.get("no_map3") == "1" else 1
    f["has_map4"] = 0 if include_results and request.form.get("no_map4") == "1" else 1
    f["has_map5"] = 0 if include_results and request.form.get("no_map5") == "1" else 1
    f["bp_password"] = hash_bp_password(request.form.get("bp_password", "").strip())
    f["bp_process"] = request.form.get("bp_process", "") if include_results else ""
    f["decider_knife_winner"] = (
        request.form.get("decider_knife_winner", "").strip() or None if include_results else None
    )
    f["decider_start_side"] = (
        request.form.get("decider_start_side", "").strip().upper() or None
        if include_results
        else None
    )
    f["stream_url"] = request.form.get("stream_url", "").strip() or None
    f["map_halves"] = request.form.get("map_halves", "").strip() or None
    watch_urls = []
    idx = 0
    while True:
        name = request.form.get(f"watch_name_{idx}", "").strip()
        url = normalize_http_url(request.form.get(f"watch_url_{idx}", ""))
        if name and url:
            watch_urls.append({"name": name, "url": url})
            idx += 1
        elif (
            request.form.get(f"watch_name_{idx}") is not None
            or request.form.get(f"watch_url_{idx}") is not None
        ):
            idx += 1
        else:
            break
    f["watch_urls"] = json.dumps(watch_urls, ensure_ascii=False) if watch_urls else None
    f["status"] = request.form.get("status", "upcoming") if include_results else "upcoming"
    if f["status"] == "ongoing":
        f["status"] = "live"
    if f["status"] not in ("upcoming", "live", "completed", "cancelled"):
        f["status"] = "upcoming"
    f["server_address"], f["server_password"] = _parse_server_connect(
        request.form.get("server_address", "").strip()
    )
    return f


_CONNECT_PART = re.compile(r"^connect\s+(\S+)$", re.IGNORECASE)
_PASSWORD_PART = re.compile(r"^password\s+(\S+)$", re.IGNORECASE)


def _parse_server_connect(raw):
    """把粘贴的进服串拆成（地址, 密码）。

    支持原来的 “password 密码;connect IP:端口”，也支持 “connect IP:端口; password 密码”
    和只有 “connect IP:端口”（以前这两种会把 “connect ” 一起存进地址，复制出来变成
    “connect connect …”，直播轮询也解析不了地址）。认不出的写法仍原样当地址保存。
    """
    if not raw:
        return None, None
    address, password = None, None
    for part in (piece.strip() for piece in raw.split(";")):
        connect = _CONNECT_PART.match(part)
        secret = _PASSWORD_PART.match(part)
        if connect:
            address = connect.group(1)
        elif secret:
            password = secret.group(1)
    if address is None:
        return raw, None
    return address, password


def _preserve_managed_match_fields(values, existing):
    """Keep live scores and locked setup data out of ordinary admin edits."""
    for field in LIVE_SCORE_FIELDS:
        values[field] = existing[field]

    current_status = existing["status"] or "upcoming"
    if current_status == "ongoing":
        current_status = "live"
    if current_status != "upcoming" or row_get(existing, "bp_state"):
        for field in LOCKED_AFTER_START_FIELDS:
            values[field] = existing[field]
        for slot in range(1, 6):
            values[f"map{slot}_pb"] = existing[f"map{slot}_picked_by"]

    if current_status == "completed":
        values["server_address"] = existing["server_address"]
        values["server_password"] = existing["server_password"]
        values["bp_password"] = existing["bp_password"]
    else:
        if request.form.get("clear_bp_password") == "1":
            values["bp_password"] = None
        elif not values["bp_password"]:
            values["bp_password"] = existing["bp_password"]

        if values["server_address"] and not values["server_password"]:
            values["server_password"] = existing["server_password"]
    if not values.get("decider_knife_winner"):
        values["decider_knife_winner"] = existing["decider_knife_winner"]
    if not values.get("decider_start_side"):
        values["decider_start_side"] = existing["decider_start_side"]
    return values


def _match_setup_editable(match):
    status = row_get(match, "status") or "upcoming"
    if str(status).lower() == "ongoing":
        status = "live"
    return status == "upcoming" and not row_get(match, "bp_state")


def _started_bp_setup_change(values, existing):
    if not row_get(existing, "bp_state"):
        return False
    for field in LOCKED_AFTER_START_FIELDS:
        if field not in request.form:
            continue
        submitted = values.get(field)
        current = row_get(existing, field)
        if field == "event_id":
            submitted = str(submitted or "").strip()
            current = str(current or "").strip()
        elif field == "match_time":
            submitted = str(submitted or "").strip()[:16]
            current = str(current or "").strip()[:16]
        elif field == "bo_format":
            submitted = str(submitted or "").strip().upper()
            current = str(current or "").strip().upper()
        else:
            submitted = str(submitted or "").strip()
            current = str(current or "").strip()
        if submitted != current:
            return True
    return False


def _get_form_dropdowns(conn):
    return (
        conn.execute("SELECT * FROM events ORDER BY start_date DESC").fetchall(),
        conn.execute("SELECT * FROM teams ORDER BY name").fetchall(),
        conn.execute(
            "SELECT p.*, t.name AS team_name FROM players p LEFT JOIN teams t ON p.team_id=t.id ORDER BY p.nickname"
        ).fetchall(),
    )


def _get_match_form_row(conn, match_id):
    match = conn.execute(
        """SELECT m.*, t1.name AS team1_name, t2.name AS team2_name FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id LEFT JOIN teams t2 ON m.team2_id=t2.id
        WHERE m.id=?""",
        (match_id,),
    ).fetchone()
    if match and is_managed_event(conn, match["event_id"]):
        from site_core.matches.maps import project_legacy_map_fields

        return project_legacy_map_fields(conn, match)
    return match


def _match_player_ids(match, key):
    if not match or not match[key]:
        return []
    try:
        return json.loads(match[key])
    except (TypeError, json.JSONDecodeError):
        return []


def _event_reserve_player_ids(conn, event_id):
    """Return database player ids for registered substitutes in an event."""
    if not event_id:
        return []
    rows = conn.execute(
        """
        SELECT DISTINCT p.id
        FROM event_individual_registrations ir
        JOIN players p ON p.steam_id=ir.steam_id
        WHERE ir.event_id=? AND ir.assignment_status='reserve'
        ORDER BY p.nickname COLLATE NOCASE
        """,
        (event_id,),
    ).fetchall()
    return [row["id"] for row in rows]


def _match_roster_options(conn, match, side):
    """Build the small player list an admin can use for a match substitution."""
    current_ids = [
        player["id"] for player in match_player_slots(conn, match, side) if player.get("id")
    ]
    registered_ids = [
        player["id"] for player in registration_player_slots(conn, match, side) if player.get("id")
    ]
    managed = managed_match_teams(conn, match)
    reserve_ids = (
        [
            player["id"]
            for player in managed.get(str(side), {}).get("players", [])
            if player["is_substitute"]
        ]
        if managed is not None
        else _event_reserve_player_ids(conn, row_get(match, "event_id"))
    )
    candidate_ids = list(dict.fromkeys(current_ids + registered_ids + reserve_ids))
    if not candidate_ids:
        return []
    placeholders = ",".join("?" for _ in candidate_ids)
    rows = conn.execute(
        f"""
        SELECT p.id, p.nickname, p.team_id, p.steam_id, t.name AS team_name
        FROM players p
        LEFT JOIN teams t ON t.id=p.team_id
        WHERE p.id IN ({placeholders})
        ORDER BY p.nickname COLLATE NOCASE
        """,
        candidate_ids,
    ).fetchall()
    reserve_set = set(reserve_ids)
    by_id = {row["id"]: row for row in rows}
    ordered = [by_id[player_id] for player_id in candidate_ids if player_id in by_id]
    return [
        {
            "id": row["id"],
            "nickname": row["nickname"] or "",
            "team_name": row["team_name"] or "",
            "has_steam_id": bool(str(row["steam_id"] or "").strip()),
            "is_substitute": row["id"] in reserve_set,
        }
        for row in ordered
    ]


def _match_roster_selected(conn, match, side):
    """Keep the exact slots supplied by the administrator or registration."""
    slots = {player["slot"]: player.get("id") for player in match_player_slots(conn, match, side)}
    if not slots:
        return []
    return [slots.get(slot) for slot in range(1, max(slots) + 1)]


def _match_roster_form_values(side):
    fields = [f"match_team{side}_p{index}" for index in range(5)]
    if not any(field in request.form for field in fields):
        return None
    return [request.form.get(field, "").strip() for field in fields]


def _match_roster_is_unchanged(conn, match, side, values):
    if values is None:
        return True
    previous = [
        str(player_id) if player_id is not None else ""
        for player_id in _match_roster_selected(conn, match, side)
    ]
    previous.extend([""] * (5 - len(previous)))
    return values == previous


def _parse_match_roster(conn, match, side, *, team_id=None):
    """Read an edited five-player roster, if the form included the controls."""
    values = _match_roster_form_values(side)
    if values is None:
        return None, None
    values = [value for value in values if value]
    if len(values) != 5:
        return None, f"队伍{side} 必须选择 5 名本场选手"
    if len(set(values)) != 5:
        return None, f"队伍{side} 不能重复选择同一名选手"
    roster_match = match
    if team_id is not None and str(team_id) != str(row_get(match, f"team{side}_id")):
        roster_match = dict(match)
        roster_match[f"team{side}_id"] = team_id
        roster_match[f"team{side}_players"] = None
        roster_match[f"team{side}_registration_id"] = None
        roster_match["roster_snapshot"] = None
        other_side = 2 if side == 1 else 1
        if str(team_id) == str(row_get(match, f"team{other_side}_id")):
            roster_match[f"team{side}_players"] = json.dumps(
                _match_roster_selected(conn, match, other_side)
            )
            roster_match[f"team{side}_registration_id"] = row_get(
                match, f"team{other_side}_registration_id"
            )
    roster_options = _match_roster_options(conn, roster_match, side)
    allowed = {str(option["id"]) for option in roster_options}
    if any(value not in allowed for value in values):
        return None, f"队伍{side} 只能选择本队选手或已报名替补"
    selected_options = {str(option["id"]): option for option in roster_options}
    if any(not selected_options.get(value, {}).get("has_steam_id") for value in values):
        return None, f"队伍{side} 有选手未绑定 Steam ID，不能锁定本场名单"
    return json.dumps([int(value) for value in values]), None


_UTC8 = timezone(timedelta(hours=8))


def _utc_text_to_iso(raw):
    if not raw:
        return ""
    text = str(raw).strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_UTC8).isoformat()
    except ValueError:
        return text


def _epoch_to_iso(ts):
    if ts is None:
        return ""
    return datetime.fromtimestamp(int(ts), _UTC8).isoformat()


def annotate_managed_matches(conn, matches):
    """Attach read-only is_managed / rosters_frozen flags to match dicts."""
    if not matches:
        return matches
    if not has_event_schema(conn):
        for m in matches:
            m["is_managed"] = False
            m["rosters_frozen"] = False
        return matches
    managed_events = {
        r[0] for r in conn.execute("SELECT event_id FROM event_registration_control").fetchall()
    }
    managed_ids = [m["id"] for m in matches if m.get("event_id") in managed_events]
    frozen_counts = {}
    if managed_ids:
        placeholders = ",".join("?" for _ in managed_ids)
        for row in conn.execute(
            f"""SELECT p.match_id, COUNT(*) AS cnt
                FROM match_participants p
                JOIN match_roster_members r ON r.match_participant_id=p.match_participant_id
                WHERE p.match_id IN ({placeholders})
                GROUP BY p.match_id""",
            managed_ids,
        ):
            frozen_counts[row["match_id"]] = row["cnt"]
    for m in matches:
        managed = m.get("event_id") in managed_events
        m["is_managed"] = managed
        m["rosters_frozen"] = bool(managed and frozen_counts.get(m["id"], 0) == 10)
    return matches


def _managed_events_for_match_add(conn):
    if not has_event_schema(conn):
        return {}
    controls = conn.execute(
        """SELECT c.event_id, c.archived_at, b.formed_at
           FROM event_registration_control c
           LEFT JOIN event_formation_batches b USING(event_id)"""
    ).fetchall()
    if not controls:
        return {}
    entrants_rows = conn.execute(
        """SELECT e.event_id, e.event_entrant_id, e.registration_id,
                  g.club_id, g.group_origin, g.archived_at AS team_archived_at,
                  r.team_name, r.status AS reg_status,
                  t.name AS club_name,
                  i.confirmed_at
           FROM event_entrants e
           JOIN event_registration_groups g ON g.event_id=e.event_id AND g.registration_id=e.registration_id
           JOIN event_registrations r ON r.id=e.registration_id AND r.event_id=e.event_id
           LEFT JOIN teams t ON t.id=g.club_id
           LEFT JOIN event_initial_rosters i ON i.event_entrant_id=e.event_entrant_id
           ORDER BY e.event_id, e.event_entrant_id"""
    ).fetchall()
    initial_by_entrant = {}
    for row in conn.execute("SELECT event_entrant_id, player_id FROM event_initial_members"):
        initial_by_entrant.setdefault(row["event_entrant_id"], set()).add(row["player_id"])
    current_by_entrant = {}
    for row in conn.execute(
        """SELECT cm.event_entrant_id, cm.player_id, p.nickname
           FROM event_current_members cm
           JOIN players p ON p.id=cm.player_id
           ORDER BY cm.event_entrant_id, cm.roster_slot"""
    ):
        current_by_entrant.setdefault(row["event_entrant_id"], []).append(
            {"id": row["player_id"], "nickname": row["nickname"] or f"#{row['player_id']}"}
        )

    entrants_by_event = {}
    for row in entrants_rows:
        eid = row["event_entrant_id"]
        confirmed = row["confirmed_at"] is not None
        members = current_by_entrant.get(eid, [])
        initial_set = initial_by_entrant.get(eid, set())
        players = [
            {**m, "is_added_sub": bool(confirmed and m["id"] not in initial_set)} for m in members
        ]
        not_ready_reason = ""
        if row["team_archived_at"] is not None:
            not_ready_reason = "已归档"
        elif row["reg_status"] != "pending":
            not_ready_reason = "报名状态无效"
        elif not confirmed:
            not_ready_reason = "首五待确认"
        elif len(players) != 5:
            not_ready_reason = f"当前仅 {len(players)} 人"
        entrants_by_event.setdefault(row["event_id"], []).append(
            {
                "event_entrant_id": eid,
                "name": row["team_name"] or f"参赛队 #{eid}",
                "club_name": row["club_name"] or "",
                "origin_label": "自动分队" if row["group_origin"] == "formed" else "报名队",
                "ready": not not_ready_reason,
                "not_ready_reason": not_ready_reason,
                "players": players,
            }
        )

    result = {}
    for ctrl in controls:
        ev_id = ctrl["event_id"]
        result[str(ev_id)] = {
            "event_id": ev_id,
            "archived": ctrl["archived_at"] is not None,
            "formed": ctrl["formed_at"] is not None,
            "roster_url": url_for("admin.admin_event_roster", event_id=ev_id),
            "entrants": entrants_by_event.get(ev_id, []),
        }
    return result


def _managed_match_edit_info(conn, match):
    match_id = match["id"]
    event_id = match["event_id"]
    fixed = participants.sides(conn, match_id)
    rosters_frozen = participants.rosters_frozen(conn, match_id)
    bp_started = bool(row_get(match, "bp_state"))
    has_started = match_has_started(conn, match)
    ctrl = conn.execute(
        "SELECT archived_at FROM event_registration_control WHERE event_id=?", (event_id,)
    ).fetchone()
    event_archived = bool(ctrl and ctrl["archived_at"] is not None) or (
        match.get("status") == "completed"
    )
    admins_map = {
        r["id"]: r["username"] for r in conn.execute("SELECT id, username FROM admins").fetchall()
    }
    club_names = {
        r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM teams").fetchall()
    }

    approved_by_side = {}
    all_player_ids = set()
    for side_num, side_info in fixed.items():
        approved = event_rosters.roster(conn, event_id, side_info["event_entrant_id"])
        approved_by_side[side_num] = approved
        all_player_ids.update(approved["initial_player_ids"])
        all_player_ids.update(approved["current_player_ids"])
        all_player_ids.update(p["id"] for p in side_info["players"])

    players_map = {}
    if all_player_ids:
        placeholders = ",".join("?" for _ in all_player_ids)
        for p in conn.execute(
            f"SELECT id, nickname, steam_id FROM players WHERE id IN ({placeholders})",
            tuple(all_player_ids),
        ):
            players_map[p["id"]] = dict(p)

    sides_out = {}
    freeze_blockers = []
    if bp_started or has_started:
        freeze_blockers.append("比赛已开始或已有 BP / 赛果记录，不能新建固定双方或重新冻结名单")
    if event_archived:
        freeze_blockers.append("本届赛事已归档，不能冻结新比赛名单")
    if len(fixed) != 2:
        freeze_blockers.append("请先确认本场的两支参赛队伍")
    elif any(s["frozen_at"] for s in fixed.values()) and not rosters_frozen:
        freeze_blockers.append("本场只有一侧已冻结，请核对原名单")

    seen_player_ids = set()
    seen_steam_ids = set()
    for side_num in (1, 2):
        side_info = fixed.get(side_num)
        if not side_info:
            sides_out[side_num] = None
            continue
        approved = approved_by_side[side_num]
        initial_ids = approved["initial_player_ids"]
        current_ids = approved["current_player_ids"]
        initial_set = set(initial_ids)
        initial_players = [
            {
                "id": pid,
                "nickname": (players_map.get(pid) or {}).get("nickname") or f"#{pid}",
                "swapped_out": pid not in set(current_ids),
            }
            for pid in initial_ids
        ]
        current_players = [
            {
                "id": pid,
                "nickname": (players_map.get(pid) or {}).get("nickname") or f"#{pid}",
                "is_added_sub": bool(approved["is_frozen"] and pid not in initial_set),
                "steam_id": str((players_map.get(pid) or {}).get("steam_id") or "").strip(),
            }
            for pid in current_ids
        ]
        kept_initial = len(initial_set & set(current_ids)) if approved["is_frozen"] else None

        frozen_meta = None
        frozen_players = []
        if side_info["frozen_at"]:
            mr = conn.execute(
                "SELECT frozen_by, frozen_at, team_name FROM match_rosters WHERE match_participant_id=?",
                (side_info["match_participant_id"],),
            ).fetchone()
            frozen_meta = {
                "frozen_at_iso": _utc_text_to_iso(mr["frozen_at"] if mr else side_info["frozen_at"]),
                "frozen_by_name": admins_map.get(mr["frozen_by"], "") if mr else "",
                "frozen_team_name": mr["team_name"] if mr else side_info["name"],
            }
            frozen_players = [
                {
                    "slot": p["slot"],
                    "id": p["id"],
                    "nickname": p["nickname"] or f"#{p['id']}",
                    "is_substitute": bool(p["is_substitute"]),
                }
                for p in side_info["players"]
            ]

        team_archived = bool(
            side_info["group_status"] != "pending" or approved["team_archived_at"] is not None
        )
        if not rosters_frozen and not (bp_started or has_started or event_archived):
            if team_archived:
                freeze_blockers.append(f"{side_info['name']} 已归档，不能冻结新比赛名单")
            if not approved["is_frozen"]:
                freeze_blockers.append(f"{side_info['name']} 尚未在「报名与阵容」页确认初始五人")
            elif len(current_ids) != 5:
                freeze_blockers.append(f"{side_info['name']} 当前阵容不足 5 人")
            elif not event_rosters.keeps_initial_majority(initial_ids, current_ids):
                freeze_blockers.append(f"{side_info['name']} 当前阵容保留初始成员不足 3 名")
            if current_ids:
                try:
                    event_rosters.verify_registered_players(conn, event_id, current_ids)
                except HostError as exc:
                    freeze_blockers.append(f"{side_info['name']}：{exc.message}")
            steams = [p["steam_id"] for p in current_players]
            if len(current_ids) == 5 and (
                not all(steams)
                or len(set(steams)) != 5
                or (set(steams) & seen_steam_ids)
                or (set(current_ids) & seen_player_ids)
            ):
                freeze_blockers.append("本场十名选手须具备有效且互不重复的选手编号及 Steam ID")
            seen_player_ids.update(current_ids)
            seen_steam_ids.update(s for s in steams if s)

        sides_out[side_num] = {
            "event_entrant_id": side_info["event_entrant_id"],
            "registration_id": side_info["registration_id"],
            "name": side_info["name"],
            "short_name": side_info["short_name"],
            "club_name": club_names.get(side_info["team_id"], "") if side_info["team_id"] else "",
            "team_archived": team_archived,
            "initial_confirmed": bool(approved["is_frozen"]),
            "initial_confirmed_at_iso": _epoch_to_iso(approved["confirmed_at"]),
            "initial_players": initial_players,
            "current_players": current_players,
            "kept_initial_count": kept_initial,
            "frozen": bool(side_info["frozen_at"]),
            "frozen_at_iso": frozen_meta["frozen_at_iso"] if frozen_meta else "",
            "frozen_by_name": frozen_meta["frozen_by_name"] if frozen_meta else "",
            "frozen_team_name": frozen_meta["frozen_team_name"] if frozen_meta else "",
            "frozen_players": frozen_players,
        }

    # Deduplicate blocker messages while preserving order
    unique_blockers = list(dict.fromkeys(freeze_blockers))
    return {
        "is_managed": True,
        "rosters_frozen": rosters_frozen,
        "bp_started": bp_started,
        "has_started": has_started,
        "event_archived": event_archived,
        "roster_url": url_for("admin.admin_event_roster", event_id=event_id),
        "bp_url": f"/bp/{match_id}",
        "can_freeze": not rosters_frozen and not unique_blockers,
        "freeze_blockers": unique_blockers,
        "sides": sides_out,
    }


def _match_form_response(conn, match=None, status=200):
    events, teams, all_players = _get_form_dropdowns(conn)
    team1_player_ids = _match_player_ids(match, "team1_players")
    team2_player_ids = _match_player_ids(match, "team2_players")
    match_roster_options = {}
    match_roster_selected = {}
    if match and not ("_is_new_form" in match.keys() and bool(match["_is_new_form"])):
        match_roster_options = {
            1: _match_roster_options(conn, match, 1),
            2: _match_roster_options(conn, match, 2),
        }
        match_roster_selected = {
            1: _match_roster_selected(conn, match, 1),
            2: _match_roster_selected(conn, match, 2),
        }
    # sqlite3.Row does not expose dict.get(); accept both a database row and
    # the submitted-form dict used when re-rendering validation errors.
    is_new_match = not match or ("_is_new_form" in match.keys() and bool(match["_is_new_form"]))
    managed_events_data = _managed_events_for_match_add(conn) if is_new_match else {}
    selected_sides = {}
    if is_new_match and request.method == "POST":
        selected_sides = {
            "1": {
                "type": request.form.get("side1_type", ""),
                "id": request.form.get("side1_id", ""),
            },
            "2": {
                "type": request.form.get("side2_type", ""),
                "id": request.form.get("side2_id", ""),
            },
        }
    managed_match_info = None
    if not is_new_match and match and is_managed_event(conn, match["event_id"]):
        managed_match_info = _managed_match_edit_info(conn, dict(match))
    if match and "_setup_editable" in match.keys():
        match_setup_editable = bool(match["_setup_editable"])
    elif match:
        match_setup_editable = _match_setup_editable(match)
    else:
        match_setup_editable = False
    custom_side_labels = {}
    if match:
        match = dict(match)
        managed = managed_match_teams(conn, match)
        team_names = {team["id"]: team["name"] for team in teams}
        for side in (1, 2):
            team_id = match.get(f"team{side}_id")
            match[f"team{side}_id"] = int(team_id) if team_id is not None else None
            match[f"team{side}_name"] = team_names.get(match[f"team{side}_id"])
        match = supplement_temp_teams(match, conn)
        for side in (1, 2):
            selected = match_roster_selected.get(side, [])
            if managed is not None:
                match[f"team{side}_id"] = managed.get(str(side), {}).get("team_id")
            if (managed is not None or not match_setup_editable) and not is_new_match:
                if side == 1:
                    team1_player_ids = selected
                else:
                    team2_player_ids = selected
            if (
                match[f"team{side}_name"] == "TBD"
                and not team_names.get(match[f"team{side}_id"])
                and any(selected)
            ):
                custom_side_labels[side] = "自选阵容 A" if side == 1 else "自选阵容 B"
    conn.close()
    return render_template(
        "admin/matches_form.html",
        match=match,
        is_new_match=is_new_match,
        events=events,
        teams=teams,
        all_players=all_players,
        team1_player_ids=team1_player_ids,
        team2_player_ids=team2_player_ids,
        match_roster_options=match_roster_options,
        match_roster_selected=match_roster_selected,
        match_setup_editable=match_setup_editable,
        custom_side_labels=custom_side_labels,
        managed_events_data=managed_events_data,
        selected_sides=selected_sides,
        managed_match_info=managed_match_info,
    ), status


def _match_form_state(
    current_match, values=None, team1_id=None, team2_id=None, team1_players=None, team2_players=None
):
    """Keep the submitted values when a match form needs to be shown again.

    Previously validation failures rendered the database row again, so a user
    could click save, lose all their edits, and see no useful explanation.
    """
    state = dict(current_match) if current_match else {}
    state["_setup_editable"] = bool(current_match and _match_setup_editable(current_match))
    for key, value in (values or {}).items():
        if key.endswith("_pb"):
            state[key[:-3] + "_picked_by"] = value
        else:
            state[key] = value
    if team1_id is not None:
        state["team1_id"] = team1_id
    if team2_id is not None:
        state["team2_id"] = team2_id
    if team1_players is not None:
        state["team1_players"] = team1_players
    if team2_players is not None:
        state["team2_players"] = team2_players
    # The add form has no database row yet, but the renderer still reads these
    # fields to decide whether to show the player selectors.
    state.setdefault("team1_players", None)
    state.setdefault("team2_players", None)
    if not current_match:
        state["_is_new_form"] = True
    return state


def _parse_side(conn, prefix, *, allow_partial=False, allow_empty=False):
    side_type = request.form.get(f"{prefix}_type", "team")
    if side_type == "players":
        player_slots = [request.form.get(f"{prefix}_p{i}", "").strip() for i in range(5)]
        player_ids = [player_id for player_id in player_slots if player_id]
        if not player_ids and allow_empty:
            return None, None, None
        if not allow_partial and len(player_ids) != 5:
            return None, None, f"{prefix} 请选择 5 名选手"
        if len(set(player_ids)) != len(player_ids):
            return None, None, f"{prefix} 不能重复选择同一名选手"
        placeholders = ",".join("?" * len(player_ids))
        count = conn.execute(
            f"SELECT COUNT(*) FROM players WHERE id IN ({placeholders})", player_ids
        ).fetchone()[0]
        if count != len(player_ids):
            return None, None, f"{prefix} 包含不存在的选手"
        selected = [player_id or None for player_id in player_slots]
        while selected and selected[-1] is None:
            selected.pop()
        return None, json.dumps(selected), None
    if side_type != "team":
        return None, None, f"{prefix} 的参赛方类型无效"
    team_id = request.form.get(f"{prefix}_id", "").strip()
    if not team_id and allow_empty:
        return None, None, None
    if not team_id:
        return None, None, f"{prefix} 请选择队伍"
    if (
        not team_id.isdigit()
        or not conn.execute("SELECT id FROM teams WHERE id=?", (team_id,)).fetchone()
    ):
        return None, None, f"{prefix} 所选队伍不存在"
    return team_id, None, None


def _match_validation_error(conn, values):
    if not values["event_id"]:
        return "请选择赛事"
    if (
        not str(values["event_id"]).isdigit()
        or not conn.execute("SELECT id FROM events WHERE id=?", (values["event_id"],)).fetchone()
    ):
        return "所选赛事不存在"
    if not values["match_time"]:
        return "比赛时间不能为空"
    if values["bo_format"] not in ("BO1", "BO3", "BO5"):
        return "BO 格式无效"
    if values.get("decider_knife_winner") not in ("t1", "t2") or values.get(
        "decider_start_side"
    ) not in ("CT", "T"):
        values["decider_knife_winner"] = None
        values["decider_start_side"] = None
    return None


def _duplicate_match(
    conn,
    values,
    team1_id,
    team2_id,
    team1_players,
    team2_players,
    exclude_id=None,
):
    sql = (
        "SELECT id, team1_id, team2_id, team1_players, team2_players, is_test_mode "
        "FROM matches WHERE event_id=? AND match_time=?"
    )
    params = [values["event_id"], values["match_time"]]
    if exclude_id is not None:
        sql += " AND id<>?"
        params.append(exclude_id)
    for row in conn.execute(sql, params).fetchall():
        if values["is_test_mode"] and row["is_test_mode"]:
            return True
        if team1_id and team2_id:
            if {str(row["team1_id"]), str(row["team2_id"])} == {
                str(team1_id),
                str(team2_id),
            }:
                return True
        elif team1_players and team2_players:
            current_sides = {
                frozenset(
                    str(value)
                    for value in _match_player_ids(row, "team1_players")
                    if value is not None
                ),
                frozenset(
                    str(value)
                    for value in _match_player_ids(row, "team2_players")
                    if value is not None
                ),
            }
            submitted_sides = {
                frozenset(value for value in json.loads(team1_players) if value is not None),
                frozenset(value for value in json.loads(team2_players) if value is not None),
            }
            if current_sides == submitted_sides:
                return True
    return False


MATCH_COLS = (
    "event_id, team1_id, team2_id, team1_score, team2_score, match_time, bo_format, stage, status,"
    " map1, map1_t1, map1_t2, map2, map2_t1, map2_t2, map3, map3_t1, map3_t2, has_map3,"
    " map4, map4_t1, map4_t2, map5, map5_t1, map5_t2, has_map4, has_map5,"
    " map1_picked_by, map2_picked_by, map3_picked_by, map4_picked_by, map5_picked_by,"
    " bp_process, bp_password, stream_url, map_halves, team1_players, team2_players,"
    " watch_urls, server_address, server_password, is_test_mode"
)
MATCH_PLACEHOLDERS = "(" + ",".join("?" * 42) + ")"


def _match_values(f, team1_id, team2_id, team1_players, team2_players):
    return (
        f["event_id"],
        team1_id,
        team2_id,
        f["team1_score"],
        f["team2_score"],
        f["match_time"],
        f["bo_format"],
        f["stage"],
        f["status"],
        f["map1"],
        f["map1_t1"],
        f["map1_t2"],
        f["map2"],
        f["map2_t1"],
        f["map2_t2"],
        f["map3"],
        f["map3_t1"],
        f["map3_t2"],
        f["has_map3"],
        f["map4"],
        f["map4_t1"],
        f["map4_t2"],
        f["map5"],
        f["map5_t1"],
        f["map5_t2"],
        f["has_map4"],
        f["has_map5"],
        f["map1_pb"],
        f["map2_pb"],
        f["map3_pb"],
        f["map4_pb"],
        f["map5_pb"],
        f["bp_process"],
        f["bp_password"],
        f["stream_url"],
        f["map_halves"],
        team1_players,
        team2_players,
        f["watch_urls"],
        f["server_address"],
        f["server_password"],
        f["is_test_mode"],
    )


_PREMATCH_FIELDS = (
    "event_id",
    "match_time",
    "bo_format",
    "stage",
    "bp_password",
    "stream_url",
    "watch_urls",
    "server_address",
    "server_password",
)
_PREMATCH_MAPS = tuple(f"map{index}" for index in range(1, 6))


def _entrant_from_match_form(conn, event_id, side):
    prefix = f"side{side}"
    if request.form.get(f"{prefix}_type") == "entrant":
        choice = request.form.get(f"{prefix}_id", "").strip()
        if not (choice.isascii() and choice.isdigit() and 0 < len(choice) < 20):
            raise HostError(f"请选择第 {side} 方的本届参赛队伍", 400)
        # Bind through the current event, never through the old registration integer.
        return participants.select_entrant(conn, event_id, entrant_id=choice)
    club, players, error = _parse_side(conn, prefix)
    if error:
        raise HostError(error, 400)
    if club:
        return participants.select_entrant(conn, event_id, club_id=club)
    if not players:
        raise HostError("请选择已确认的本届队伍或完整五人名单", 400)
    return participants.select_entrant(conn, event_id, player_ids=json.loads(players))


def _sync_prematch_maps(conn, match_id, values):
    from site_core.matches.maps import sync_scheduled_maps

    setup = {key: values[key] for key in ("bo_format", *_PREMATCH_MAPS)}
    setup.update({f"{key}_picked_by": values[f"{key}_pb"] for key in _PREMATCH_MAPS})
    setup.update({f"has_map{slot}": values[f"has_map{slot}"] for slot in (3, 4, 5)})
    sync_scheduled_maps(conn, match_id, setup=setup)


def _unsupported_prematch_submission(match=None):
    raw_status = request.form.get("status")
    if raw_status not in (None, "upcoming"):
        return True
    fields = (
        *(field for field in LIVE_SCORE_FIELDS if not field.startswith("has_map")),
        "bp_process",
        "decider_knife_winner",
        "decider_start_side",
    )
    for field in fields:
        if field in request.form:
            submitted = request.form.get(field, "").strip()
            current = str(row_get(match, field) or "").strip()
            accepted = {"", current}
            if field.endswith(("score", "_t1", "_t2")):
                accepted.add("0")
            if submitted not in accepted:
                return True
    return False


def _create_prematch(conn, values):
    if _unsupported_prematch_submission():
        raise HostError(PREMATCH_ONLY)
    if values["is_test_mode"]:
        raise HostError("托管赛事必须选择两支已确认的参赛队伍，测试空位请使用原流程", 400)
    with write(conn):
        entrant_ids = [_entrant_from_match_form(conn, values["event_id"], side) for side in (1, 2)]
        conn.execute(
            f"INSERT INTO matches({','.join(_PREMATCH_FIELDS)},status) VALUES (?,?,?,?,?,?,?,?,?,'upcoming')",
            tuple(values[field] for field in _PREMATCH_FIELDS),
        )
        match_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        participants.bind(conn, match_id, *entrant_ids)
        update_match_slug(conn, match_id)
        _sync_prematch_maps(conn, match_id, values)


def _edit_prematch(conn, current_match):
    match_id = current_match["id"]
    with write(conn):
        match = _get_match_form_row(conn, match_id)
        if not match or not is_managed_event(conn, match["event_id"]):
            raise HostError("比赛已变化，请刷新页面")
        active_event(conn, match["event_id"], int(time()))
        if match["status"] != "upcoming" or _unsupported_prematch_submission(match):
            raise HostError(PREMATCH_ONLY)
        values = _parse_match_form(request, include_results=True)
        if "event_id" in request.form and str(values["event_id"]) != str(match["event_id"]):
            raise HostError("托管比赛不能更换所属赛事")
        for field in ("event_id", "match_time", "bo_format", "stage", *_PREMATCH_MAPS):
            if field not in request.form:
                values[field] = match[field]
        for field in _PREMATCH_MAPS:
            if f"{field}_picked_by" not in request.form:
                values[f"{field}_pb"] = match[f"{field}_picked_by"]
        for slot in (3, 4, 5):
            if f"no_map{slot}" not in request.form:
                values[f"has_map{slot}"] = (
                    match[f"has_map{slot}"]
                    if values["bo_format"] == match["bo_format"]
                    else int(slot <= {"BO1": 1, "BO3": 3, "BO5": 5}.get(values["bo_format"], 0))
                )
        if error := _match_validation_error(conn, values):
            raise HostError(error, 400)
        maps_changed = (
            values["bo_format"] != match["bo_format"]
            or any(
                (values[key] or None) != match[key]
                or values[f"{key}_pb"] != match[f"{key}_picked_by"]
                for key in _PREMATCH_MAPS
            )
            or any(values[f"has_{key}"] != match[f"has_{key}"] for key in _PREMATCH_MAPS[2:])
        )
        if _started_bp_setup_change(values, match) or (match["bp_state"] and maps_changed):
            raise HostError("BP 已开始，不能更改赛制或地图等比赛设置")
        fixed = participants.sides(conn, match_id)
        if len(fixed) != 2:
            raise HostError("托管比赛缺少固定双方，请核对比赛资料")
        for side, team in fixed.items():
            current_ids = [str(player["id"]) for player in team["players"]]
            if f"side{side}_type" in request.form:
                if request.form.get(f"side{side}_type") == "players" and team["frozen_at"]:
                    submitted = [request.form.get(f"side{side}_p{i}", "").strip() for i in range(5)]
                    same = len(current_ids) == 5 and sorted(submitted) == sorted(current_ids)
                else:
                    same = (
                        _entrant_from_match_form(conn, match["event_id"], side)
                        == team["event_entrant_id"]
                    )
                if not same:
                    raise HostError("比赛双方已绑定，不能互换或改绑")
            roster_values = _match_roster_form_values(side)
            if roster_values is not None and roster_values != current_ids:
                raise HostError("本场名单须从已批准阵容冻结；请先办理赛前换人，再确认本场名单")
        participants.check_duplicate(
            conn,
            match["event_id"],
            values["match_time"],
            [team["event_entrant_id"] for team in fixed.values()],
            exclude_id=match_id,
        )
        # These controls keep the existing form's password and server connection behavior.
        if request.form.get("clear_bp_password") == "1":
            values["bp_password"] = None
        elif not values["bp_password"]:
            values["bp_password"] = match["bp_password"]
        if "server_address" not in request.form:
            values["server_address"] = match["server_address"]
        if values["server_address"] and not values["server_password"]:
            values["server_password"] = match["server_password"]
        if "stream_url" not in request.form:
            values["stream_url"] = match["stream_url"]
        if "watch_name_0" not in request.form and "watch_url_0" not in request.form:
            values["watch_urls"] = match["watch_urls"]
        conn.execute(
            "UPDATE matches SET "
            + ",".join(f"{field}=?" for field in _PREMATCH_FIELDS)
            + " WHERE id=?",
            (*[values[field] for field in _PREMATCH_FIELDS], match_id),
        )
        if maps_changed:
            _sync_prematch_maps(conn, match_id, values)
        if request.form.get("freeze_rosters") == "1":
            participants.freeze_rosters(conn, match_id, session["admin_id"])
        update_match_slug(conn, match_id)


# ---- 比赛管理 ----
@admin_bp.route("/matches")
@login_required
def admin_matches():
    conn = get_db()
    event_filter = request.args.get("event", "").strip()
    status_filter = request.args.get("status", "").strip()
    search_query = request.args.get("q", "").strip()

    events = conn.execute(
        "SELECT id, name, short_name FROM events ORDER BY start_date DESC, id DESC"
    ).fetchall()

    sql_effective_status = get_sql_effective_status()

    query = f"""SELECT m.*, t1.name AS team1_name, t2.name AS team2_name, e.name AS event_name,
        {sql_effective_status} FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id"""

    params = []
    if event_filter:
        query += " WHERE m.event_id=?"
        params.append(event_filter)

    query += " ORDER BY m.match_time DESC, m.id DESC"

    raw_matches = conn.execute(query, params).fetchall()
    matches = annotate_managed_matches(conn, [supplement_temp_teams(m, conn) for m in raw_matches])

    if search_query:
        q_lower = search_query.lower()
        matches = [
            m
            for m in matches
            if q_lower in (m.get("team1_name") or "").lower()
            or q_lower in (m.get("team2_name") or "").lower()
            or q_lower in (m.get("event_name") or "").lower()
            or str(m.get("id")) == search_query
        ]

    counts = {"all": len(matches), "live": 0, "upcoming": 0, "completed": 0, "cancelled": 0}
    for m in matches:
        st = m.get("effective_status")
        if st in counts:
            counts[st] += 1

    if status_filter and status_filter != "all":
        matches = [m for m in matches if m.get("effective_status") == status_filter]

    conn.close()
    return render_template(
        "admin/matches.html",
        matches=matches,
        events=events,
        current_event=event_filter,
        current_status=status_filter or "all",
        search_query=search_query,
        counts=counts,
    )


@admin_bp.route("/matches/add", methods=["GET", "POST"])
@csrf_required
@login_required
def admin_matches_add():
    conn = get_db()
    if request.method == "POST":
        f = _parse_match_form(request)
        error = _match_validation_error(conn, f)
        if error:
            flash(error, "error")
            return _match_form_response(conn, _match_form_state(None, f), 400)

        if is_managed_event(conn, f["event_id"]):
            try:
                _create_prematch(conn, f)
            except HostError as exc:
                flash(exc.message, "error")
                return _match_form_response(conn, _match_form_state(None, f), exc.status)
            conn.close()
            flash("比赛添加成功，请确认本场名单后进行 BP", "success")
            return redirect(url_for("admin.admin_matches"))

        team1_id = team2_id = None
        team1_players = team2_players = None
        team1_id, team1_players, err = _parse_side(
            conn,
            "side1",
            allow_partial=bool(f["is_test_mode"]),
            allow_empty=bool(f["is_test_mode"]),
        )
        if not err:
            team2_id, team2_players, err = _parse_side(
                conn,
                "side2",
                allow_partial=bool(f["is_test_mode"]),
                allow_empty=bool(f["is_test_mode"]),
            )
        if err:
            flash(err, "error")
            return _match_form_response(
                conn,
                _match_form_state(None, f, team1_id, team2_id, team1_players, team2_players),
                400,
            )
        if team1_id and team2_id and team1_id == team2_id:
            flash("两支队伍不能相同", "error")
            return _match_form_response(
                conn,
                _match_form_state(None, f, team1_id, team2_id, team1_players, team2_players),
                400,
            )
        if team1_players and team2_players:
            if {value for value in json.loads(team1_players) if value is not None} & {
                value for value in json.loads(team2_players) if value is not None
            }:
                flash("两边不能选择同一名选手", "error")
                return _match_form_response(
                    conn,
                    _match_form_state(None, f, team1_id, team2_id, team1_players, team2_players),
                    400,
                )
        if _duplicate_match(conn, f, team1_id, team2_id, team1_players, team2_players):
            flash("相同赛事、时间和参赛方的比赛已存在", "error")
            return _match_form_response(
                conn,
                _match_form_state(None, f, team1_id, team2_id, team1_players, team2_players),
                400,
            )
        try:
            conn.execute("BEGIN IMMEDIATE")
            if is_managed_event(conn, f["event_id"]):
                raise HostError("赛事的报名流程已切换，请刷新后再创建比赛")
            conn.execute(
                f"INSERT INTO matches({MATCH_COLS}) VALUES{MATCH_PLACEHOLDERS}",
                _match_values(f, team1_id, team2_id, team1_players, team2_players),
            )
            match_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            update_match_slug(conn, match_id)
            refresh_bracket_for_match(conn, match_id)
            conn.commit()
        except Exception as exc:
            conn.rollback()
            logger.exception("创建比赛失败 match_id=%s", locals().get("match_id"))
            flash(f"比赛保存失败：{exc}", "error")
            return _match_form_response(
                conn,
                _match_form_state(None, f, team1_id, team2_id, team1_players, team2_players),
                400,
            )
        conn.close()
        flash("比赛添加成功", "success")
        return redirect(url_for("admin.admin_matches"))
    return _match_form_response(conn)


@admin_bp.route("/matches/edit/<int:match_id>", methods=["GET", "POST"])
@csrf_required
@login_required
def admin_matches_edit(match_id):
    conn = get_db()
    current_match = _get_match_form_row(conn, match_id)
    if not current_match:
        conn.close()
        return "比赛不存在", 404
    if request.method == "POST":
        if is_managed_event(conn, current_match["event_id"]):
            try:
                _edit_prematch(conn, current_match)
            except HostError as exc:
                flash(exc.message, "error")
                return _match_form_response(conn, _match_form_state(current_match), exc.status)
            conn.close()
            flash("比赛更新成功", "success")
            return redirect(url_for("admin.admin_matches"))
        f = _parse_match_form(request, include_results=True)
        if is_managed_event(conn, f["event_id"]):
            flash("旧比赛不能移动到托管赛事", "error")
            return _match_form_response(conn, _match_form_state(current_match), 409)
        if _started_bp_setup_change(f, current_match):
            flash("BP 已开始，不能更改赛制或地图等比赛设置", "error")
            return _match_form_response(conn, _match_form_state(current_match), 400)
        f = _preserve_managed_match_fields(f, current_match)
        error = _match_validation_error(conn, f)
        if error:
            flash(error, "error")
            return _match_form_response(conn, _match_form_state(current_match, f), 400)
        existing = current_match
        # 是否测试比赛以数据库为准（创建时决定），和创建时用同一套“参赛方可留空”的规则
        f["is_test_mode"] = int(existing["is_test_mode"] or 0)
        is_test = bool(f["is_test_mode"])
        team1_id = existing["team1_id"]
        team2_id = existing["team2_id"]
        team1_players = existing["team1_players"]
        team2_players = existing["team2_players"]
        if (existing["status"] or "upcoming") == "upcoming":
            if "side1_type" in request.form:
                team1_id, team1_players, err = _parse_side(
                    conn, "side1", allow_partial=is_test, allow_empty=is_test
                )
                if not err and "side2_type" in request.form:
                    team2_id, team2_players, err = _parse_side(
                        conn, "side2", allow_partial=is_test, allow_empty=is_test
                    )
                if err:
                    flash(err, "error")
                    return _match_form_response(
                        conn,
                        _match_form_state(
                            current_match, f, team1_id, team2_id, team1_players, team2_players
                        ),
                        400,
                    )
                for side in (1, 2):
                    if request.form.get(f"side{side}_type") != "team":
                        continue
                    side_team_id = team1_id if side == 1 else team2_id
                    side_players_key = f"team{side}_players"
                    previous_team_id = existing[f"team{side}_id"]
                    same_team = bool(
                        side_team_id
                        and previous_team_id
                        and str(side_team_id) == str(previous_team_id)
                    )
                    roster_values = _match_roster_form_values(side)
                    if same_team and _match_roster_is_unchanged(
                        conn, existing, side, roster_values
                    ):
                        if side == 1:
                            team1_players = existing[side_players_key]
                        else:
                            team2_players = existing[side_players_key]
                        continue
                    if not side_team_id or roster_values is None:
                        if side == 1:
                            team1_players = None
                        else:
                            team2_players = None
                        continue
                    submitted_roster, roster_error = _parse_match_roster(
                        conn, existing, side, team_id=side_team_id
                    )
                    if roster_error:
                        flash(roster_error, "error")
                        return _match_form_response(
                            conn,
                            _match_form_state(
                                current_match, f, team1_id, team2_id, team1_players, team2_players
                            ),
                            400,
                        )
                    if submitted_roster is not None:
                        if side == 1:
                            team1_players = submitted_roster
                        else:
                            team2_players = submitted_roster
            else:
                submitted_team1_players, roster_error = _parse_match_roster(conn, existing, 1)
                if submitted_team1_players is not None:
                    team1_players = submitted_team1_players
                if not roster_error:
                    submitted_team2_players, roster_error = _parse_match_roster(conn, existing, 2)
                    if submitted_team2_players is not None:
                        team2_players = submitted_team2_players
                if roster_error:
                    flash(roster_error, "error")
                    return _match_form_response(
                        conn,
                        _match_form_state(
                            current_match, f, team1_id, team2_id, team1_players, team2_players
                        ),
                        400,
                    )
        if team1_id and team2_id and team1_id == team2_id:
            flash("两支队伍不能相同", "error")
            return _match_form_response(
                conn,
                _match_form_state(
                    current_match, f, team1_id, team2_id, team1_players, team2_players
                ),
                400,
            )
        if team1_players and team2_players:
            if {value for value in json.loads(team1_players) if value is not None} & {
                value for value in json.loads(team2_players) if value is not None
            }:
                flash("两边不能选择同一名选手", "error")
                return _match_form_response(
                    conn,
                    _match_form_state(
                        current_match, f, team1_id, team2_id, team1_players, team2_players
                    ),
                    400,
                )
        if _duplicate_match(conn, f, team1_id, team2_id, team1_players, team2_players, match_id):
            flash("相同赛事、时间和参赛方的比赛已存在", "error")
            return _match_form_response(
                conn,
                _match_form_state(
                    current_match, f, team1_id, team2_id, team1_players, team2_players
                ),
                400,
            )
        guard_status = existing["status"] or "upcoming"
        guard_event_id = existing["event_id"]
        roster_fields = ("team1_id", "team2_id", "team1_players", "team2_players")
        guard_roster = tuple(existing[field] for field in roster_fields)
        bp_setup_conflict = False
        try:
            conn.execute("BEGIN IMMEDIATE")
            # 表单校验期间 BP 可能开始；拿到写锁后必须按最新行再次检查。
            latest_match = _get_match_form_row(conn, match_id)
            if not latest_match:
                raise ValueError("比赛已不存在，请刷新页面后重试")
            if is_managed_event(conn, latest_match["event_id"]) or is_managed_event(
                conn, f["event_id"]
            ):
                raise ValueError("不能通过旧流程编辑托管赛事的比赛")
            if tuple(latest_match[field] for field in roster_fields) != guard_roster:
                raise ValueError("比赛阵容已更新，请刷新页面后再保存")
            if _started_bp_setup_change(f, latest_match):
                current_match = latest_match
                bp_setup_conflict = True
                raise ValueError("BP 已开始，不能更改赛制或地图等比赛设置")
            current_match = existing = latest_match
            f = _preserve_managed_match_fields(f, existing)
            error = _match_validation_error(conn, f)
            if error:
                raise ValueError(error)
            if str(f["event_id"]) != str(existing["event_id"]) and match_is_bound_to_bracket(
                conn, existing["event_id"], match_id
            ):
                raise ValueError("这场比赛已绑定原赛事的对阵图，请先解除绑定再更换赛事")
            columns = tuple(column.strip() for column in MATCH_COLS.split(",")) + (
                "decider_knife_winner",
                "decider_start_side",
            )
            values = _match_values(f, team1_id, team2_id, team1_players, team2_players) + (
                f["decider_knife_winner"],
                f["decider_start_side"],
            )
            # 直播管理的列不进入 UPDATE，不能把读取时的旧比分写回去。
            editable = {
                column: value
                for column, value in zip(columns, values)
                if column not in LIVE_SCORE_FIELDS
            }
            roster_changed = False
            for side, selected_id, selected_players in (
                (1, team1_id, team1_players),
                (2, team2_id, team2_players),
            ):
                if (
                    str(selected_id or "") != str(existing[f"team{side}_id"] or "")
                    or selected_players != existing[f"team{side}_players"]
                ):
                    editable[f"team{side}_registration_id"] = None
                    roster_changed = True
            if str(f["event_id"]) != str(existing["event_id"]):
                editable.update(team1_registration_id=None, team2_registration_id=None)
                if existing["status"] in {"live", "completed"} or existing["bp_state"]:
                    freeze_match_roster(conn, existing)
                else:
                    roster_changed = True
            if roster_changed:
                editable["roster_snapshot"] = None
            cursor = conn.execute(
                "UPDATE matches SET "
                + ",".join(f"{column}=?" for column in editable)
                + " WHERE id=? AND COALESCE(status,'upcoming')=? AND event_id IS ?",
                (
                    *editable.values(),
                    match_id,
                    guard_status,
                    guard_event_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("比赛状态或所属赛事已更新，请刷新页面后再保存")
            if f["status"] == "completed" and existing["status"] != "completed":
                result = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
                error = completed_match_result_error(result)
                if error:
                    raise ValueError(error)
            if existing["status"] == "completed" and f["status"] != "completed":
                revoke_legacy_points(conn, match_id)
            update_match_slug(conn, match_id)
            refresh_bracket_for_match(conn, match_id)
            if f["status"] == "completed":
                finished = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
                freeze_match_roster(conn, finished, confirmed=existing["status"] != "completed")
                score_predictions(conn, match_id)
            conn.commit()
        except Exception as exc:
            conn.rollback()
            if isinstance(exc, ValueError):
                flash(str(exc), "error")
            else:
                logger.exception("更新比赛失败 match_id=%s", match_id)
                flash("比赛保存失败，请稍后重试", "error")
            form_state = (
                _match_form_state(current_match)
                if bp_setup_conflict
                else _match_form_state(
                    current_match, f, team1_id, team2_id, team1_players, team2_players
                )
            )
            return _match_form_response(
                conn,
                form_state,
                400,
            )
        conn.close()
        flash("比赛更新成功", "success")
        return redirect(url_for("admin.admin_matches"))
    return _match_form_response(conn, current_match)


@admin_bp.route("/matches/delete/<int:match_id>", methods=["POST"])
@csrf_required
@login_required
def admin_matches_delete(match_id):
    conn = get_db()
    if is_managed_match(conn, match_id):
        conn.close()
        return PREMATCH_ONLY, 409
    try:
        match = conn.execute("SELECT id,event_id FROM matches WHERE id=?", (match_id,)).fetchone()
        if not match:
            flash("比赛不存在", "error")
            return redirect(url_for("admin.admin_matches"))
        affected_player_ids = {
            row["player_id"]
            for row in conn.execute(
                "SELECT DISTINCT player_id FROM match_stats WHERE match_id=?",
                (match_id,),
            ).fetchall()
            if row["player_id"]
        }
        delete_target_comments(conn, "match", match_id)
        for table in (
            "match_stats",
            "player_medals",
            "match_votes",
            "live_match_data",
            "live_match_events",
            "match_kill_events",
        ):
            conn.execute(f"DELETE FROM {table} WHERE match_id=?", (match_id,))
        conn.execute("UPDATE news SET related_match_id=NULL WHERE related_match_id=?", (match_id,))
        conn.execute("UPDATE live_ingest_status SET match_id=NULL WHERE match_id=?", (match_id,))
        conn.execute("DELETE FROM match_slug_aliases WHERE match_id=?", (match_id,))
        conn.execute("DELETE FROM matches WHERE id=?", (match_id,))
        if match["event_id"]:
            refresh_event_bracket(conn, match["event_id"])
        refresh_player_performance(conn, affected_player_ids)
        conn.commit()
        flash("比赛删除成功", "success")
    except Exception as e:
        conn.rollback()
        flash(f"删除失败：{str(e)}", "error")
    finally:
        conn.close()
    return redirect(url_for("admin.admin_matches"))


@admin_bp.route("/matches/<int:match_id>/freeze-rosters", methods=["POST"])
@csrf_required
@login_required
def admin_match_freeze_rosters(match_id):
    conn = get_db()
    try:
        with write(conn):
            participants.freeze_rosters(conn, match_id, session["admin_id"])
    except HostError as exc:
        return exc.message, exc.status
    finally:
        conn.close()
    flash("本场双方名单已冻结", "success")
    return redirect(url_for("admin.admin_matches_edit", match_id=match_id))


def _managed_series_form(conn, match_id, action):
    from blueprints.match_operations import _dispatch

    try:
        if request.is_json:
            body = request.get_json(silent=True)
            if not isinstance(body, dict):
                raise HostError("请提交 JSON 对象", 400)
        else:
            body = {"reason": request.form.get("reason", "")}
            revision = request.form.get("expected_revision")
            if revision is not None:
                try:
                    body["expected_revision"] = int(revision)
                except ValueError:
                    raise HostError("裁定版本号无效", 400) from None
        if action == "reopen" and (not body.get("reason") or "expected_revision" not in body):
            raise HostError("请在比赛运营中核对结算版本，并填写重开原因")
        with write(conn):
            result = _dispatch(conn, match_id, action, body, session["admin_id"])
        if request.is_json:
            return {"ok": True, **result}
        flash("比赛已正式完赛" if action == "settle" else "已撤销本次结算", "success")
        return redirect(url_for("admin.admin_matches"))
    except HostError as exc:
        return ({"ok": False, "error": exc.message} if request.is_json else exc.message), exc.status
    finally:
        conn.close()


@admin_bp.route("/matches/<int:match_id>/complete", methods=["POST"])
@csrf_required
@login_required
def admin_match_complete(match_id):
    """Explicitly finish a match and optionally snapshot its Game Log."""
    conn = get_db()
    if is_managed_match(conn, match_id):
        return _managed_series_form(conn, match_id, "settle")
    try:
        conn.execute("UPDATE matches SET status=status WHERE id=?", (match_id,))
        match = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
        if not match:
            raise ValueError("比赛不存在")
        error = completed_match_result_error(match)
        if error:
            raise ValueError(error)
        saved = 0
        if request.form.get("save_game_log") == "1":
            row = conn.execute(
                "SELECT live_state FROM live_match_data WHERE match_id=?", (match_id,)
            ).fetchone()
            if row and row["live_state"]:
                try:
                    live_state = json.loads(row["live_state"])
                except (TypeError, ValueError):
                    live_state = None
                if isinstance(live_state, dict):
                    saved = persist_live_match_events(conn, match_id, live_state)
        freeze_match_roster(conn, match, confirmed=True)
        conn.execute("UPDATE matches SET status='completed' WHERE id=?", (match_id,))
        refresh_bracket_for_match(conn, match_id)
        score_predictions(conn, match_id)
        conn.commit()
        flash(f"比赛已结束，新增保存 {saved} 条 Game Log", "success")
    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "error")
    except Exception as exc:
        conn.rollback()
        logger.error("结束比赛失败 match_id=%s 错误类型=%s", match_id, type(exc).__name__)
        flash("比赛结束失败，所有变更均未保存，请稍后重试", "error")
    finally:
        conn.close()
    return redirect(url_for("admin.admin_matches"))


@admin_bp.route("/matches/<int:match_id>/reopen", methods=["POST"])
@csrf_required
@login_required
def admin_match_reopen(match_id):
    """Reopen a mistakenly completed match; time decides live/upcoming."""
    conn = get_db()
    if is_managed_match(conn, match_id):
        return _managed_series_form(conn, match_id, "reopen")
    try:
        changed = conn.execute(
            "UPDATE matches SET status='live' WHERE id=? AND status='completed'", (match_id,)
        ).rowcount
        if changed:
            revoke_legacy_points(conn, match_id)
            refresh_bracket_for_match(conn, match_id)
        conn.commit()
        flash("比赛已重新开启" if changed else "比赛未发生变化", "success")
    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "error")
    except Exception as exc:
        conn.rollback()
        logger.error("重新开启比赛失败 match_id=%s 错误类型=%s", match_id, type(exc).__name__)
        flash("重新开启失败，所有变更均未保存，请稍后重试", "error")
    finally:
        conn.close()
    return redirect(url_for("admin.admin_matches"))


@admin_bp.route("/matches/<int:match_id>/stats", methods=["GET", "POST"])
@csrf_required
@login_required
def admin_match_stats(match_id):
    conn = get_db()
    if is_managed_match(conn, match_id):
        conn.close()
        if request.method == "POST":
            if request.is_json:
                from blueprints.match_operations import managed_operation

                return managed_operation(match_id, "stats")
            return "请在比赛运营中选择实际局、选手和统计版本，旧表单不能覆盖整场统计。", 409
        return redirect(url_for("admin.managed_match_operate", match_id=match_id) + "#stats")
    if request.method == "POST":
        # 取得写锁后再读取状态、阵容和统计，避免保存期间读到旧状态。
        conn.execute("BEGIN IMMEDIATE")
    match = conn.execute(
        """SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
        e.name AS event_name, e.short_name AS event_short_name
        FROM matches m LEFT JOIN teams t1 ON m.team1_id=t1.id LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id WHERE m.id=?""",
        (match_id,),
    ).fetchone()
    if not match:
        conn.close()
        return "比赛不存在", 404
    match = supplement_temp_teams(match, conn)

    team1_players = stats_editor_players(conn, match, 1)
    team2_players = stats_editor_players(conn, match, 2)
    sides = {1: team1_players, 2: team2_players}

    stats_by_map = {}
    for row in conn.execute(
        """SELECT * FROM match_stats
           WHERE match_id=? AND COALESCE(data_status, 'final') <> 'superseded'""",
        (match_id,),
    ):
        if key := normalize_map_key(row["map_name"]):
            stats_by_map.setdefault(key, []).append(row)
    total_played = (match["team1_score"] or 0) + (match["team2_score"] or 0)
    bo = match["bo_format"] or "BO3"
    bo_max = {"BO1": 1, "BO3": 3, "BO5": 5}.get(bo, 3)
    maps = []
    for slot in range(1, bo_max + 1):
        mn = match[f"map{slot}"]
        rounds = (match[f"map{slot}_t1"] or 0) + (match[f"map{slot}_t2"] or 0)
        if total_played > 0:
            is_active = slot <= total_played or rounds > 0
        else:
            is_active = slot <= 2 or match.get(f"has_map{slot}", 1)
        if not is_active:
            continue
        key = normalize_map_key(mn)
        existing_map = stats_by_map.get(key, [])
        map_stats = {s["player_id"]: s for s in existing_map}
        maps.append(
            {
                "name": mn,
                "disabled": not mn,
                "has_data": len(map_stats) > 0,
                "stats": map_stats,
                "index": slot - 1,
                "key": key,
                "rounds": rounds,
                "revision": manual_map_revision(match, mn, sides, existing_map),
            }
        )
    if not maps:
        maps.append({"name": None, "disabled": True, "has_data": False, "stats": {}, "index": 0})
    active_tab = next((i for i, m in enumerate(maps) if not m["disabled"]), 0)
    readonly = match["status"] == "completed"
    response_status = 200

    if request.method == "POST":
        if match["status"] == "completed":
            flash("已结束比赛的 Demo 数据不可修改", "error")
            conn.close()
            return redirect(url_for("admin.admin_match_stats", match_id=match_id))
        key = normalize_map_key(request.form.get("map_name", ""))
        selected = next((m for m in maps if not m["disabled"] and m["key"] == key), None)
        try:
            if selected is None:
                raise ValueError("请选择本场已有地图")
            if request.form.get("stats_revision") != selected["revision"]:
                raise StatsRevisionConflict("该地图的统计、比分或阵容已更新，请刷新页面核对后再保存")
            affected_player_ids = save_manual_map_stats(
                conn, match, selected["name"], selected["rounds"], sides,
                stats_by_map.get(key, []), request.form,
            )
            refresh_player_performance(conn, affected_player_ids)
            conn.commit()
            flash(f"{selected['name']} 数据已保存", "success")
        except Exception as e:
            conn.rollback()
            flash(f"数据保存失败：{str(e)}", "error")
            response_status = 409 if isinstance(e, StatsRevisionConflict) else 400
            # 只回填本次提交地图的可编辑数字，不能靠浏览器草稿来保住整张表。
            if selected is not None:
                active_tab = maps.index(selected)
                selected["server_rejected"] = True
                # 被拒的旧表单不能拿到新版本号后再次覆盖；刷新后才重新核对。
                selected["revision"] = request.form.get("stats_revision", "")
                for player in team1_players + team2_players:
                    player_id = player["id"]
                    saved = selected["stats"].get(player_id)
                    values = (
                        dict(saved)
                        if saved
                        else {
                            "kills": 0,
                            "deaths": 0,
                            "assists": 0,
                            "adr": 0,
                            "impact": 0,
                            "rating": 1.0,
                            "kast": 70,
                            "headshot_percentage": 50,
                        }
                    )
                    for field, (column, _, _) in FORM_FIELDS.items():
                        field_name = f"{field}_{player_id}"
                        if field_name in request.form:
                            values[column] = request.form[field_name]
                    selected["stats"][player_id] = values
        else:
            conn.close()
            return redirect(url_for("admin.admin_match_stats", match_id=match_id))
    conn.close()
    return render_template(
        "admin/match_stats.html",
        match=match,
        team1_players=team1_players,
        team2_players=team2_players,
        maps=maps,
        active_tab=active_tab,
        readonly=readonly,
    ), response_status


@admin_bp.route("/matches/<int:match_id>/import-demo", methods=["GET", "POST"])
@csrf_required
@login_required
def admin_import_demo(match_id):
    conn = get_db()
    if is_managed_match(conn, match_id):
        if request.method == "GET":
            conn.close()
            return redirect(url_for("admin.managed_match_operate", match_id=match_id) + "#demos")
        has_run = conn.execute("SELECT 1 FROM map_runs r JOIN scheduled_maps s USING(scheduled_map_id) WHERE s.match_id=? LIMIT 1", (match_id,)).fetchone()
        conn.close()
        if not has_run:
            return "本场尚没有可以关联录像的实际开局。", 409
        from blueprints.match_operation_demos import managed_import_post

        return managed_import_post(match_id)
    match = conn.execute(
        """SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
        e.name AS event_name, e.short_name AS event_short_name
        FROM matches m LEFT JOIN teams t1 ON m.team1_id=t1.id LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id WHERE m.id=?""",
        (match_id,),
    ).fetchone()
    if not match:
        conn.close()
        return "比赛不存在", 404
    match = supplement_temp_teams(match, conn)
    demo_slot_count = get_demo_upload_slot_count(match)
    if request.method == "POST":
        step = request.form.get("step", "analyze")
        if step == "analyze":
            invalid_fields = _invalid_demo_upload_fields(request.files, demo_slot_count)
            if invalid_fields:
                flash(f"当前比赛最多只能上传 {demo_slot_count} 个 Demo", "error")
                conn.close()
                return _render_import_demo(match)
            previews = []
            tmpdirs = []
            has_file = False
            for i in range(demo_slot_count):
                field = f"demo_file_{i}"
                if field not in request.files:
                    continue
                file = request.files[field]
                if not file or not file.filename or not file.filename.lower().endswith(".dem"):
                    continue
                has_file = True
                tmpdir = tempfile.mkdtemp(prefix=f"demo_import_{i}_")
                tmpdirs.append(tmpdir)
                demo_path = os.path.join(tmpdir, "upload.dem")
                file.save(demo_path)
                try:
                    pv = analyze_demo(conn, match, demo_path)
                    os.makedirs(DEMOS_DIR, exist_ok=True)
                    map_slot = int(pv.get("map_slot", i))
                    if not 0 <= map_slot < demo_slot_count:
                        raise ValueError(f"地图编号超出当前比赛范围：{map_slot + 1}")
                    map_name = row_get(match, f"map{map_slot + 1}", "") or pv.get("map_name", "")
                    demo_filename = build_demo_filename(
                        match_id, map_slot, match["event_short_name"], map_name
                    )
                    # Keep the previous file intact until the new reference is committed.
                    demo_stem, demo_ext = os.path.splitext(demo_filename)
                    demo_filename = f"{demo_stem}_{uuid.uuid4().hex}{demo_ext}"
                    shutil.copy2(demo_path, os.path.join(DEMOS_DIR, demo_filename))
                    existing_raw = row_get(match, "demo_file", "") or "[]"
                    demo_list = (
                        json.loads(existing_raw) if existing_raw and existing_raw != "[]" else []
                    )
                    while len(demo_list) <= map_slot:
                        demo_list.append(None)
                    demo_list[map_slot] = demo_filename
                    conn.execute(
                        "UPDATE matches SET demo_file=? WHERE id=?",
                        (json.dumps(demo_list, ensure_ascii=False), match_id),
                    )
                    conn.commit()
                    match["demo_file"] = json.dumps(demo_list, ensure_ascii=False)
                    previews.append(pv)
                except Exception as e:
                    conn.rollback()
                    flash(f"Demo #{i + 1} 分析失败：{str(e)}", "error")
            for d in tmpdirs:
                shutil.rmtree(d, ignore_errors=True)
            if not has_file:
                flash("请至少选择一个 .dem 文件", "error")
                conn.close()
                return _render_import_demo(match)
            if not previews:
                conn.close()
                return _render_import_demo(match)
            all_demo_data = json.dumps(previews, ensure_ascii=False)
            conn.close()
            return _render_import_demo(match, previews=previews, all_demo_data=all_demo_data)
        elif step in ("import_single", "import_all"):
            conn.execute("BEGIN TRANSACTION")
            try:
                if step == "import_single":
                    demo_data_str = request.form.get("demo_data", "{}")
                    map_slot = request.form.get("map_slot", 0)
                    result, msg = import_demo_data(conn, match_id, match, demo_data_str, map_slot)
                    if result is None:
                        conn.rollback()
                        flash(msg, "error")
                    else:
                        conn.commit()
                        flash(msg, "success")
                else:
                    all_demo_data = json.loads(request.form.get("all_demo_data", "[]"))
                    if not isinstance(all_demo_data, list) or not all_demo_data:
                        raise ValueError("请选择至少一个有效 Demo，未保存任何导入数据")
                    imported_count = 0
                    messages = []
                    for pv in all_demo_data:
                        if not isinstance(pv, dict):
                            raise ValueError("Demo 数据格式无效，整批导入未保存")
                        result, msg = import_demo_data(
                            conn, match_id, match, pv.get("demo_data", "{}"), pv.get("map_slot", 0)
                        )
                        if result is None or result <= 0:
                            raise ValueError(f"{msg}；整批导入未保存")
                        imported_count += 1
                        messages.append(msg)
                    conn.commit()
                    for msg in messages:
                        flash(msg, "info")
                    flash(f"批量导入完成：{imported_count} 个 Demo 已导入", "success")
            except Exception as e:
                conn.rollback()
                flash(f"导入失败：{str(e)}", "error")
            conn.close()
            return redirect(url_for("admin.admin_match_stats", match_id=match_id))
    conn.close()
    return _render_import_demo(match)
