"""Admin match editor, stats editor and demo import pages."""

import json
import logging
import os
import re
import shutil
import tempfile
import uuid

from flask import flash, redirect, render_template, request, url_for

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
    prepare_manual_map_rows,
    stats_editor_players,
    write_manual_map_revision,
)
from services.match_roster_service import (
    freeze_match_roster,
    match_player_slots,
    registration_player_slots,
)
from services.match_service import (
    completed_match_result_error,
    score_predictions,
    supplement_temp_teams,
)
from services.performance_service import refresh_player_performance
from utils.demo_naming import build_demo_filename
from utils.helpers import (
    ensure_unique_match_slug,
    make_match_slug,
    normalize_http_url,
    record_match_slug_alias,
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
    return conn.execute(
        """SELECT m.*, t1.name AS team1_name, t2.name AS team2_name FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id LEFT JOIN teams t2 ON m.team2_id=t2.id
        WHERE m.id=?""",
        (match_id,),
    ).fetchone()


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
    reserve_ids = _event_reserve_player_ids(conn, row_get(match, "event_id"))
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
    if match and "_setup_editable" in match.keys():
        match_setup_editable = bool(match["_setup_editable"])
    elif match:
        match_setup_editable = _match_setup_editable(match)
    else:
        match_setup_editable = False
    custom_side_labels = {}
    if match:
        match = dict(match)
        team_names = {team["id"]: team["name"] for team in teams}
        for side in (1, 2):
            team_id = match.get(f"team{side}_id")
            match[f"team{side}_id"] = int(team_id) if team_id is not None else None
            match[f"team{side}_name"] = team_names.get(match[f"team{side}_id"])
        match = supplement_temp_teams(match, conn)
        for side in (1, 2):
            selected = match_roster_selected.get(side, [])
            if not match_setup_editable and not is_new_match:
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


def _generate_match_slug(conn, match_id):
    """根据比赛的队伍、时间、赛事信息自动生成并保存唯一 slug"""
    match = conn.execute(
        """
        SELECT m.match_time, m.slug AS old_slug,
               COALESCE(t1.short_name, t1.name, 'team-1') AS t1n,
               COALESCE(t2.short_name, t2.name, 'team-2') AS t2n,
               COALESCE(e.slug, e.short_name, e.name) AS esn
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id
        WHERE m.id=?
    """,
        (match_id,),
    ).fetchone()
    if not match:
        return
    # 根据队伍、时间、赛事信息自动生成 slug（每次编辑都会更新）
    slug = make_match_slug(match["t1n"], match["t2n"], match["match_time"], match["esn"])
    slug = ensure_unique_match_slug(conn, match_id, slug)
    if match["old_slug"] and match["old_slug"] != slug:
        record_match_slug_alias(conn, match["old_slug"], match_id)
    conn.execute("UPDATE matches SET slug=? WHERE id=?", (slug, match_id))


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
    matches = [supplement_temp_teams(m, conn) for m in raw_matches]

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
            conn.execute(
                f"INSERT INTO matches({MATCH_COLS}) VALUES{MATCH_PLACEHOLDERS}",
                _match_values(f, team1_id, team2_id, team1_players, team2_players),
            )
            match_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            _generate_match_slug(conn, match_id)
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
        f = _parse_match_form(request, include_results=True)
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
                conn.execute(
                    "UPDATE match_votes SET scored=0,points_earned=0 WHERE match_id=?", (match_id,)
                )
            _generate_match_slug(conn, match_id)
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
        conn.execute(
            "DELETE FROM comment_likes WHERE comment_id IN "
            "(SELECT id FROM comments WHERE target_type='match' AND target_id=?)",
            (match_id,),
        )
        conn.execute("DELETE FROM comments WHERE target_type='match' AND target_id=?", (match_id,))
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


@admin_bp.route("/matches/<int:match_id>/complete", methods=["POST"])
@csrf_required
@login_required
def admin_match_complete(match_id):
    """Explicitly finish a match and optionally snapshot its Game Log."""
    conn = get_db()
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
    try:
        changed = conn.execute(
            "UPDATE matches SET status='live' WHERE id=? AND status='completed'", (match_id,)
        ).rowcount
        if changed:
            conn.execute(
                "UPDATE match_votes SET scored=0, points_earned=0 WHERE match_id=?", (match_id,)
            )
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

    existing_stats = conn.execute(
        """SELECT * FROM match_stats
           WHERE match_id=? AND COALESCE(data_status, 'final') <> 'superseded'""",
        (match_id,),
    ).fetchall()
    total_played = (match["team1_score"] or 0) + (match["team2_score"] or 0)
    bo = match["bo_format"] or "BO3"
    bo_max = {"BO1": 1, "BO3": 3, "BO5": 5}.get(bo, 3)
    map_names = [match["map1"], match["map2"], match["map3"], match["map4"], match["map5"]]
    map_score_sums = [
        (match["map1_t1"] or 0) + (match["map1_t2"] or 0),
        (match["map2_t1"] or 0) + (match["map2_t2"] or 0),
        (match["map3_t1"] or 0) + (match["map3_t2"] or 0),
        (match["map4_t1"] or 0) + (match["map4_t2"] or 0),
        (match["map5_t1"] or 0) + (match["map5_t2"] or 0),
    ]
    has_map_flag = [
        True,
        True,
        bool(match["has_map3"]),
        bool(row_get(match, "has_map4", 1)),
        bool(row_get(match, "has_map5", 1)),
    ]
    maps = []
    for i, mn in enumerate(map_names):
        if i >= bo_max:
            continue
        is_active = (
            (i < total_played or map_score_sums[i] > 0) if total_played > 0 else has_map_flag[i]
        )
        if not is_active:
            continue
        map_stats = {s["player_id"]: s for s in existing_stats if s["map_name"] == mn}
        maps.append(
            {
                "name": mn,
                "disabled": not mn,
                "has_data": len(map_stats) > 0,
                "stats": map_stats,
                "index": i,
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
        map_name = request.form.get("map_name", "")
        try:
            affected_player_ids = {
                row["player_id"]
                for row in conn.execute(
                    """SELECT DISTINCT player_id
                       FROM match_stats
                       WHERE match_id=? AND map_name=?""",
                    (match_id, map_name),
                ).fetchall()
                if row["player_id"]
            }
            if not map_name or map_name not in [name for name in map_names if name]:
                raise ValueError("请选择本场已有地图")
            rounds = 0
            for mn, t1, t2 in [
                (match["map1"], match["map1_t1"], match["map1_t2"]),
                (match["map2"], match["map2_t1"], match["map2_t2"]),
                (match["map3"], match["map3_t1"], match["map3_t2"]),
                (match["map4"], match["map4_t1"], match["map4_t2"]),
                (match["map5"], match["map5_t1"], match["map5_t2"]),
            ]:
                if map_name == mn:
                    rounds = (t1 or 0) + (t2 or 0)
                    break
            if rounds <= 0:
                raise ValueError("该地图比分尚未确认，不能按旧的 30 回合默认值保存")
            rows, changed = prepare_manual_map_rows(
                match,
                map_name,
                rounds,
                {1: team1_players, 2: team2_players},
                [row for row in existing_stats if row["map_name"] == map_name],
                request.form,
            )
            if changed:
                write_manual_map_revision(conn, match_id, map_name, rows)
            affected_player_ids.update(row["player_id"] for row in rows)
            refresh_player_performance(conn, affected_player_ids)
            conn.commit()
            flash(f"{map_name} 数据已保存", "success")
        except Exception as e:
            conn.rollback()
            flash(f"数据保存失败：{str(e)}", "error")
            response_status = 400
            # 只回填本次提交地图的可编辑数字，不能靠浏览器草稿来保住整张表。
            for tab_index, map_entry in enumerate(maps):
                if map_entry["name"] != map_name or map_entry["disabled"]:
                    continue
                active_tab = tab_index
                map_entry["server_rejected"] = True
                for player in list(team1_players) + list(team2_players):
                    player_id = player["id"]
                    saved = map_entry["stats"].get(player_id)
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
                    for field, column in (
                        ("kills", "kills"),
                        ("deaths", "deaths"),
                        ("assists", "assists"),
                        ("adr", "adr"),
                        ("impact", "impact"),
                        ("kast", "kast"),
                        ("hs", "headshot_percentage"),
                    ):
                        field_name = f"{field}_{player_id}"
                        if field_name in request.form:
                            values[column] = request.form[field_name]
                    map_entry["stats"][player_id] = values
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
