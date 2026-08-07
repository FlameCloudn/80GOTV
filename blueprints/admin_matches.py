"""Admin match editor, stats editor and demo import pages."""

import json
import logging
import os
import re
import shutil
import tempfile

from flask import flash, redirect, render_template, request, url_for

from blueprints.admin import admin_bp
from config import BASE_DIR
from models import get_db
from services.bracket_service import refresh_bracket_for_match
from services.demo_service import analyze_demo, import_demo_data
from services.live_log_service import persist_live_match_events
from services.match_service import score_predictions, supplement_temp_teams
from services.performance_service import refresh_player_performance
from utils.demo_naming import build_demo_filename
from utils.helpers import ensure_unique_match_slug, make_match_slug, normalize_http_url, row_get
from utils.match_utils import get_demo_upload_slot_count, get_sql_effective_status
from utils.stats_calc import calculate_rating
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
    f["server_address"] = request.form.get("server_address", "").strip() or None
    f["server_password"] = None
    if f["server_address"]:
        m = re.match(r"password\s+(\S+);connect\s+(\S+)", f["server_address"])
        if m:
            f["server_password"] = m.group(1)
            f["server_address"] = m.group(2)
    return f


def _preserve_managed_match_fields(values, existing):
    """Keep live scores and locked setup data out of ordinary admin edits."""
    for field in LIVE_SCORE_FIELDS:
        values[field] = existing[field]

    current_status = existing["status"] or "upcoming"
    if current_status == "ongoing":
        current_status = "live"
    if current_status != "upcoming":
        for field in LOCKED_AFTER_START_FIELDS:
            values[field] = existing[field]
        for slot in range(1, 6):
            values[f"map{slot}_pb"] = existing[f"map{slot}_picked_by"]

    if current_status != "completed":
        values["bp_process"] = existing["bp_process"]

    if request.form.get("clear_bp_password") == "1":
        values["bp_password"] = None
    elif not values["bp_password"]:
        values["bp_password"] = existing["bp_password"]

    if values["server_address"] and not values["server_password"]:
        values["server_password"] = existing["server_password"]
    return values


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
    team_id = row_get(match, f"team{side}_id")
    try:
        team_id = int(team_id) if team_id else None
    except (TypeError, ValueError):
        team_id = None
    current_ids = _match_player_ids(match, f"team{side}_players")
    team_ids = []
    if team_id:
        team_ids = [
            row["id"]
            for row in conn.execute(
                "SELECT id FROM players WHERE team_id=? ORDER BY nickname COLLATE NOCASE",
                (team_id,),
            ).fetchall()
        ]
    reserve_ids = _event_reserve_player_ids(conn, row_get(match, "event_id"))
    candidate_ids = list(dict.fromkeys(current_ids + team_ids + reserve_ids))
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
            "is_substitute": row["id"] in reserve_set
            or bool(team_id and row["team_id"] != team_id),
        }
        for row in ordered
    ]


def _match_roster_selected(conn, match, side):
    """Return the current five slots, falling back to the team's roster."""
    selected = _match_player_ids(match, f"team{side}_players")
    if selected:
        return selected[:5]
    team_id = row_get(match, f"team{side}_id")
    if not team_id:
        return []
    return [
        row["id"]
        for row in conn.execute(
            "SELECT id FROM players WHERE team_id=? ORDER BY nickname COLLATE NOCASE LIMIT 5",
            (team_id,),
        ).fetchall()
    ]


def _parse_match_roster(conn, match, side):
    """Read an edited five-player roster, if the form included the controls."""
    fields = [f"match_team{side}_p{index}" for index in range(5)]
    if not any(field in request.form for field in fields):
        return None, None
    values = [request.form.get(field, "").strip() for field in fields]
    values = [value for value in values if value]
    if len(values) != 5:
        return None, f"队伍{side} 必须选择 5 名本场选手"
    if len(set(values)) != 5:
        return None, f"队伍{side} 不能重复选择同一名选手"
    allowed = {str(option["id"]) for option in _match_roster_options(conn, match, side)}
    if any(value not in allowed for value in values):
        return None, f"队伍{side} 只能选择本队选手或已报名替补"
    selected_options = {
        str(option["id"]): option for option in _match_roster_options(conn, match, side)
    }
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
    conn.close()
    # sqlite3.Row does not expose dict.get(); accept both a database row and
    # the submitted-form dict used when re-rendering validation errors.
    is_new_match = not match or ("_is_new_form" in match.keys() and bool(match["_is_new_form"]))
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
    ), status


def _match_form_state(
    current_match, values=None, team1_id=None, team2_id=None, team1_players=None, team2_players=None
):
    """Keep the submitted values when a match form needs to be shown again.

    Previously validation failures rendered the database row again, so a user
    could click save, lose all their edits, and see no useful explanation.
    """
    state = dict(current_match) if current_match else {}
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
        player_ids = [request.form.get(f"{prefix}_p{i}", "").strip() for i in range(5)]
        player_ids = [player_id for player_id in player_ids if player_id]
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
        return None, json.dumps(player_ids), None
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
    if values["decider_knife_winner"] not in (None, "t1", "t2"):
        return "决胜图拼刀胜者无效"
    if values["decider_start_side"] not in (None, "CT", "T"):
        return "决胜图起始阵营无效"
    if bool(values["decider_knife_winner"]) != bool(values["decider_start_side"]):
        return "决胜图拼刀胜者和起始阵营必须一起填写"
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
                frozenset(str(value) for value in _match_player_ids(row, "team1_players")),
                frozenset(str(value) for value in _match_player_ids(row, "team2_players")),
            }
            submitted_sides = {
                frozenset(json.loads(team1_players)),
                frozenset(json.loads(team2_players)),
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
        conn.execute(
            "INSERT OR IGNORE INTO match_slug_aliases(slug,match_id) VALUES(?,?)",
            (match["old_slug"], match_id),
        )
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
    matches = conn.execute(f"""SELECT m.*, t1.name AS team1_name, t2.name AS team2_name, e.name AS event_name,
        {get_sql_effective_status()} FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id ORDER BY m.match_time DESC""").fetchall()
    matches = [supplement_temp_teams(m, conn) for m in matches]
    conn.close()
    return render_template("admin/matches.html", matches=matches)


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
            if set(json.loads(team1_players)) & set(json.loads(team2_players)):
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
        f = _preserve_managed_match_fields(f, current_match)
        error = _match_validation_error(conn, f)
        if error:
            flash(error, "error")
            return _match_form_response(conn, _match_form_state(current_match, f), 400)
        existing = current_match
        team1_id = existing["team1_id"] if existing else None
        team2_id = existing["team2_id"] if existing else None
        team1_players = existing["team1_players"] if existing else None
        team2_players = existing["team2_players"] if existing else None
        if (existing["status"] or "upcoming") == "upcoming":
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
        f["is_test_mode"] = int(existing["is_test_mode"] or 0) if existing else 0
        if team1_id and team2_id and team1_id > 0 and team1_id == team2_id:
            flash("两支队伍不能相同", "error")
            return _match_form_response(
                conn,
                _match_form_state(
                    current_match, f, team1_id, team2_id, team1_players, team2_players
                ),
                400,
            )
        if team1_players and team2_players:
            if set(json.loads(team1_players)) & set(json.loads(team2_players)):
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
        if "map_halves" not in request.form:
            existing_halves = conn.execute(
                "SELECT map_halves FROM matches WHERE id=?", (match_id,)
            ).fetchone()
            f["map_halves"] = existing_halves["map_halves"] if existing_halves else None
        try:
            conn.execute(
                """UPDATE matches SET event_id=?, team1_id=?, team2_id=?, team1_score=?, team2_score=?, match_time=?, bo_format=?, stage=?, status=?,
                map1=?, map1_t1=?, map1_t2=?, map2=?, map2_t1=?, map2_t2=?, map3=?, map3_t1=?, map3_t2=?, has_map3=?,
                map4=?, map4_t1=?, map4_t2=?, map5=?, map5_t1=?, map5_t2=?, has_map4=?, has_map5=?,
                map1_picked_by=?, map2_picked_by=?, map3_picked_by=?, map4_picked_by=?, map5_picked_by=?,
                bp_process=?, bp_password=?, stream_url=?, map_halves=?, team1_players=?, team2_players=?, watch_urls=?,
                server_address=?, server_password=?, is_test_mode=?, decider_knife_winner=?, decider_start_side=?
                WHERE id=?""",
                _match_values(f, team1_id, team2_id, team1_players, team2_players)
                + (f["decider_knife_winner"], f["decider_start_side"], match_id),
            )
            _generate_match_slug(conn, match_id)
            refresh_bracket_for_match(conn, match_id)
            conn.commit()
        except Exception as exc:
            conn.rollback()
            logger.exception("更新比赛失败 match_id=%s", match_id)
            flash(f"比赛保存失败：{exc}", "error")
            return _match_form_response(
                conn,
                _match_form_state(
                    current_match, f, team1_id, team2_id, team1_players, team2_players
                ),
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
        match = conn.execute("SELECT id FROM matches WHERE id=?", (match_id,)).fetchone()
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
    match = conn.execute("SELECT id FROM matches WHERE id=?", (match_id,)).fetchone()
    if not match:
        conn.close()
        flash("比赛不存在", "error")
        return redirect(url_for("admin.admin_matches"))
    saved = 0
    if request.form.get("save_game_log") == "1":
        row = conn.execute(
            "SELECT live_state FROM live_match_data WHERE match_id=?", (match_id,)
        ).fetchone()
        if row and row["live_state"]:
            try:
                saved = persist_live_match_events(conn, match_id, json.loads(row["live_state"]))
            except (TypeError, ValueError):
                pass
    conn.execute("UPDATE matches SET status='completed' WHERE id=?", (match_id,))
    refresh_bracket_for_match(conn, match_id)
    score_predictions(conn)
    conn.commit()
    conn.close()
    flash(f"比赛已结束，新增保存 {saved} 条 Game Log", "success")
    return redirect(url_for("admin.admin_matches"))


@admin_bp.route("/matches/<int:match_id>/reopen", methods=["POST"])
@csrf_required
@login_required
def admin_match_reopen(match_id):
    """Reopen a mistakenly completed match; time decides live/upcoming."""
    conn = get_db()
    changed = conn.execute(
        "UPDATE matches SET status='live' WHERE id=? AND status='completed'", (match_id,)
    ).rowcount
    if changed:
        refresh_bracket_for_match(conn, match_id)
    conn.commit()
    conn.close()
    flash("比赛已重新开启" if changed else "比赛未发生变化", "success")
    return redirect(url_for("admin.admin_matches"))


@admin_bp.route("/matches/<int:match_id>/stats", methods=["GET", "POST"])
@csrf_required
@login_required
def admin_match_stats(match_id):
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

    # 队伍选手
    def _get_players(players_json, team_id):
        if players_json:
            pids = json.loads(players_json)
            ph = ",".join("?" * len(pids))
            return conn.execute(f"SELECT * FROM players WHERE id IN ({ph})", pids).fetchall()
        return conn.execute("SELECT * FROM players WHERE team_id=?", (team_id,)).fetchall()

    team1_players = _get_players(match["team1_players"], match["team1_id"])
    team2_players = _get_players(match["team2_players"], match["team2_id"])

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

    if request.method == "POST":
        if match["status"] == "completed":
            flash("已结束比赛的 Demo 数据不可修改", "error")
            conn.close()
            return redirect(url_for("admin.admin_match_stats", match_id=match_id))
        map_name = request.form.get("map_name", "")
        conn.execute("BEGIN TRANSACTION")
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
            previous_version = conn.execute(
                """SELECT COALESCE(MAX(data_version), 0) AS version
                   FROM match_stats WHERE match_id=? AND map_name=?""",
                (match_id, map_name),
            ).fetchone()["version"]
            conn.execute(
                """UPDATE match_stats SET data_status='superseded'
                   WHERE match_id=? AND map_name=?
                     AND COALESCE(data_status, 'final') <> 'superseded'""",
                (match_id, map_name),
            )
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
            team1_player_ids = {p["id"] for p in team1_players}
            for p in list(team1_players) + list(team2_players):
                pid = p["id"]
                kills = int(request.form.get(f"kills_{pid}", 0) or 0)
                deaths = int(request.form.get(f"deaths_{pid}", 0) or 0)
                assists = int(request.form.get(f"assists_{pid}", 0) or 0)
                adr = float(request.form.get(f"adr_{pid}", 0) or 0)
                kast = float(request.form.get(f"kast_{pid}", 0) or 0)
                hs = float(request.form.get(f"hs_{pid}", 0) or 0)
                impact = float(request.form.get(f"impact_{pid}", 0) or 0)
                team_id = int(request.form.get(f"team_id_{pid}", 0) or 0)
                stored_team_id = team_id if team_id > 0 else None
                match_team_side = "t1" if pid in team1_player_ids else "t2"
                rating, kpr, dpr = calculate_rating(
                    kills=kills,
                    deaths=deaths,
                    rounds_played=rounds,
                    adr=adr,
                    kast=kast,
                    impact=impact if impact else 0,
                )
                conn.execute(
                    """INSERT INTO match_stats(
                           match_id, player_id, team_id, match_team_side,
                           kills, deaths, assists,
                           adr, kpr, dpr, rating, impact, kast,
                           headshot_percentage, rounds_played, map_name,
                           data_source, data_status, data_version
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        match_id,
                        pid,
                        stored_team_id,
                        match_team_side,
                        kills,
                        deaths,
                        assists,
                        adr,
                        kpr,
                        dpr,
                        rating,
                        impact,
                        kast,
                        hs,
                        rounds,
                        map_name,
                        "manual_review",
                        "final",
                        int(previous_version or 0) + 1,
                    ),
                )
                affected_player_ids.add(pid)
            refresh_player_performance(conn, affected_player_ids)
            conn.commit()
            flash(f"{map_name} 数据已保存", "success")
        except Exception as e:
            conn.rollback()
            flash(f"数据保存失败：{str(e)}", "error")
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
    )


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
                    previews.append(pv)
                    os.makedirs(DEMOS_DIR, exist_ok=True)
                    map_slot = int(pv.get("map_slot", i))
                    if not 0 <= map_slot < demo_slot_count:
                        raise ValueError(f"地图编号超出当前比赛范围：{map_slot + 1}")
                    map_name = row_get(match, f"map{map_slot + 1}", "") or pv.get("map_name", "")
                    demo_filename = build_demo_filename(
                        match_id, map_slot, match["event_short_name"], map_name
                    )
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
                except Exception as e:
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
                    imported_count = 0
                    for pv in all_demo_data:
                        result, msg = import_demo_data(
                            conn, match_id, match, pv.get("demo_data", "{}"), pv.get("map_slot", 0)
                        )
                        if result is not None:
                            imported_count += 1
                        flash(msg, "info")
                    conn.commit()
                    flash(f"批量导入完成：{imported_count} 个 Demo 已导入", "success")
            except Exception as e:
                conn.rollback()
                flash(f"导入失败：{str(e)}", "error")
            conn.close()
            return redirect(url_for("admin.admin_match_stats", match_id=match_id))
    conn.close()
    return _render_import_demo(match)
