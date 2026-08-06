"""赛事列表、详情、报名和赛事统计页面。"""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import (
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from config import BASE_DIR
from models import get_db
from services.award_service import (
    build_event_award_poster,
    find_event_award_player,
    list_event_award_players,
)
from services.match_service import add_effective_event_status, supplement_temp_teams
from services.steam_playtime_service import (
    attach_latest_playtime,
    build_balanced_assignments,
    build_balanced_roster_plan,
    refresh_registration_playtimes,
)
from utils.db_helpers import remove_uploaded_team_logo, save_uploaded_team_logo
from utils.helpers import event_path, resolve_event_ref
from utils.match_utils import get_sql_effective_status
from utils.rate_limiter import rate_limit
from utils.web_helpers import csrf_required
from web_app import app

_SQL_EFFECTIVE_STATUS = get_sql_effective_status()
_INDIVIDUAL_REGISTRATION_OPENS_AT = datetime(2026, 7, 20, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def _individual_registration_is_open():
    return datetime.now(ZoneInfo("Asia/Shanghai")) >= _INDIVIDUAL_REGISTRATION_OPENS_AT


def _individual_registration_open_label():
    return (
        f"{_INDIVIDUAL_REGISTRATION_OPENS_AT.month} 月 {_INDIVIDUAL_REGISTRATION_OPENS_AT.day} 日"
    )


def _bp_window_is_open(match):
    """BP is manually started and remains available until the match is closed."""
    return bool(match and match.get("effective_status") not in {"completed", "cancelled"})


def _load_event_registrations(conn, event_id):
    regs = conn.execute(
        """
        SELECT r.*, u.username AS creator_name,
               CASE WHEN COALESCE(u.is_bashizhong_student, 1)<>0
                    THEN u.group_username END
                   AS creator_group_username
        FROM event_registrations r
        LEFT JOIN users u ON r.creator_user_id=u.id
        WHERE r.event_id=? AND r.status='pending'
        ORDER BY r.created_at DESC
        """,
        (event_id,),
    ).fetchall()
    if not regs:
        return []
    registration_ids = [reg["id"] for reg in regs]
    placeholders = ",".join("?" for _ in registration_ids)
    slot_rows = conn.execute(
        f"""
        SELECT s.*, u.username AS user_username,
               CASE WHEN COALESCE(u.is_bashizhong_student, 1)<>0
                    THEN u.group_username END
                   AS group_username
        FROM event_registration_slots s
        LEFT JOIN users u ON u.id=s.user_id
        WHERE s.registration_id IN ({placeholders})
        ORDER BY s.registration_id, s.slot_index
        """,
        tuple(registration_ids),
    ).fetchall()
    slots_by_registration = {registration_id: [] for registration_id in registration_ids}
    for slot in slot_rows:
        slots_by_registration[slot["registration_id"]].append(dict(slot))
    return [
        {
            "info": dict(registration),
            "slots": slots_by_registration[registration["id"]],
        }
        for registration in regs
    ]


def _load_individual_registrations(conn, event_id, current_user_id=None):
    rows = conn.execute(
        """
        SELECT ir.*,
               preferred.team_name AS preferred_team_name,
               COALESCE(NULLIF(u.username, ''), ir.player_name) AS website_name,
               COALESCE(
                   CASE WHEN COALESCE(u.is_bashizhong_student, 1)<>0
                        THEN NULLIF(TRIM(u.group_username), '') END,
                   NULLIF((
                       SELECT TRIM(p.group_username_override) FROM players p
                       WHERE p.steam_id=ir.steam_id
                         AND COALESCE(p.is_bashizhong_student, 1)<>0
                       ORDER BY p.id LIMIT 1
                   ), ''),
                   ''
               ) AS group_username,
               COALESCE(
                   NULLIF(u.avatar, ''),
                   NULLIF((
                       SELECT p.avatar FROM players p
                       WHERE p.steam_id=ir.steam_id
                       ORDER BY p.id LIMIT 1
                   ), '')
               ) AS avatar,
               EXISTS(
                   SELECT 1
                   FROM event_registration_slots ers
                   JOIN event_registrations er ON er.id=ers.registration_id
                   WHERE er.event_id=ir.event_id
                     AND er.status='pending'
                     AND ers.user_id=ir.user_id
               ) AS is_formal_member
        FROM event_individual_registrations ir
        LEFT JOIN users u ON u.id=ir.user_id
        LEFT JOIN event_registrations preferred
          ON preferred.id=ir.preferred_registration_id
         AND preferred.event_id=ir.event_id
         AND preferred.status='pending'
        WHERE ir.event_id=?
        ORDER BY
            CASE ir.assignment_status
                WHEN 'assigned' THEN 0
                WHEN 'reserve' THEN 1
                ELSE 2
            END,
            COALESCE(ir.team_number, 999),
            ir.created_at,
            ir.id
        """,
        (event_id,),
    ).fetchall()
    entries = [dict(row) for row in rows]
    teams = {}
    reserves = []
    pending = []
    formal_members = []
    current_entry = None
    for entry in entries:
        if current_user_id and entry["user_id"] == current_user_id:
            current_entry = entry
        if entry["is_formal_member"]:
            formal_members.append(entry)
            continue
        if entry["assignment_status"] == "assigned" and entry["team_number"]:
            teams.setdefault(entry["team_number"], []).append(entry)
        elif entry["assignment_status"] == "reserve":
            reserves.append(entry)
        else:
            pending.append(entry)
    return {
        "entries": entries,
        "teams": [
            {"number": team_number, "players": players}
            for team_number, players in sorted(teams.items())
        ],
        "reserves": reserves,
        "pending": pending,
        "formal_members": formal_members,
        "current_entry": current_entry,
        "has_assignment": any(entry["assignment_status"] != "pending" for entry in entries),
        "has_formal_members": bool(formal_members),
        "can_randomize": not formal_members,
        "count": len(entries),
        "individual_count": len(entries) - len(reserves),
        "substitute_count": len(reserves),
    }


def _get_registration_user(conn):
    user_id = session.get("user_id")
    if not user_id:
        return None
    return conn.execute(
        "SELECT id, username, group_username, steam_id64 FROM users WHERE id=?",
        (user_id,),
    ).fetchone()


def _registration_wants_json():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _registration_failure(event_id, message, status=400):
    if _registration_wants_json():
        return jsonify({"success": False, "error": message}), status
    flash(message, "error")
    return redirect(url_for("event_detail", event_id=event_id))


def _registration_success(event_id, message):
    if not _registration_wants_json():
        flash(message, "success")
        return redirect(url_for("event_detail", event_id=event_id))

    conn = get_db()
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    event = add_effective_event_status(event) if event else None
    current_user = _get_registration_user(conn)
    current_user_id = current_user["id"] if current_user else None
    registrations = _load_event_registrations(conn, event_id) if event else []
    individual_registration = (
        _load_individual_registrations(conn, event_id, current_user_id) if event else None
    )
    conn.close()
    html = render_template(
        "_event_registration_list.html",
        event=event,
        registrations=registrations,
        individual_registration=individual_registration,
        individual_registration_open=_individual_registration_is_open(),
        substitute_registration_open=bool(event and event["effective_event_status"] != "completed"),
        current_user=current_user,
    )
    return jsonify({"success": True, "message": message, "html": html})


def _registration_for_management(conn, event_id, reg_id):
    return conn.execute(
        """
        SELECT r.*, e.registration_open
        FROM event_registrations r
        JOIN events e ON e.id=r.event_id
        WHERE r.id=? AND r.event_id=? AND r.status='pending'
        """,
        (reg_id, event_id),
    ).fetchone()


def _can_manage_registration(registration):
    return bool(
        registration
        and (session.get("admin_id") or session.get("user_id") == registration["creator_user_id"])
    )


def _registration_slot_is_open(slot):
    """Only use truly empty slots; never overwrite a captain's reserved player."""
    return bool(
        not slot.get("user_id")
        and not str(slot.get("steam_id") or "").strip()
        and not int(slot.get("filled_by_creator") or 0)
    )


def _move_individual_registration_to_reserve(conn, event_id, user_id):
    if not user_id:
        return
    conn.execute(
        """
        UPDATE event_individual_registrations
        SET assignment_status='reserve', team_number=NULL,
            assigned_at=CURRENT_TIMESTAMP
        WHERE event_id=? AND user_id=? AND assignment_status='assigned'
        """,
        (event_id, user_id),
    )


@app.route("/events")
def events_list():
    """赛事列表"""
    status_filter = request.args.get("status", "")
    view_mode = request.args.get("view", "")  # calendar

    conn = get_db()
    events = conn.execute("""
        SELECT e.*,
               COUNT(DISTINCT CASE
                   WHEN COALESCE(m.status, '') != 'cancelled' THEN m.id
               END) AS match_count,
               (SELECT COUNT(DISTINCT team_id) FROM (
                   SELECT team1_id AS team_id FROM matches
                   WHERE event_id = e.id AND COALESCE(status, '') != 'cancelled'
                   UNION
                   SELECT team2_id FROM matches
                   WHERE event_id = e.id AND COALESCE(status, '') != 'cancelled'
               )) AS team_count
        FROM events e
        LEFT JOIN matches m ON e.id=m.event_id
        GROUP BY e.id
        ORDER BY e.start_date DESC
    """).fetchall()
    events = [add_effective_event_status(e) for e in events]

    # 状态筛选
    if status_filter in ("ongoing", "completed", "upcoming"):
        events = [e for e in events if e["effective_event_status"] == status_filter]

    conn.close()

    return render_template(
        "events.html", events=events, status_filter=status_filter, view_mode=view_mode
    )


@app.route("/events/<event_id>")
def event_detail(event_id):
    """赛事详情"""
    conn = get_db()
    event_ref = str(event_id)
    event = resolve_event_ref(conn, event_ref)

    if not event:
        conn.close()
        return "赛事不存在", 404
    if event["slug"] and event_ref != event["slug"]:
        conn.close()
        return redirect(event_path(event), code=301)
    event_id = event["id"]

    event = add_effective_event_status(event)

    matches = conn.execute(
        f"""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s,
               t1.logo AS t1_logo, t2.logo AS t2_logo,
               {_SQL_EFFECTIVE_STATUS}
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        WHERE m.event_id=? AND COALESCE(m.status, '') != 'cancelled'
        ORDER BY m.match_time
    """,
        (event_id,),
    ).fetchall()
    matches = [supplement_temp_teams(m, conn) for m in matches]
    for match in matches:
        match["bp_window_open"] = _bp_window_is_open(match)

    # 赛事报名名单是这项赛事的实际阵容，应优先于选手当前所属队伍。
    registrations = _load_event_registrations(conn, event_id)
    registration_rosters = {}
    registration_logos = {}
    registration_steam_ids = {
        str(slot.get("steam_id") or "").strip()
        for registration in registrations
        for slot in registration["slots"]
        if str(slot.get("steam_id") or "").strip()
    }
    registration_player_by_steam = {}
    if registration_steam_ids:
        placeholders = ",".join("?" * len(registration_steam_ids))
        rows = conn.execute(
            f"""
            SELECT id, nickname, avatar, steam_id
            FROM players
            WHERE steam_id IN ({placeholders})
            """,
            tuple(sorted(registration_steam_ids)),
        ).fetchall()
        registration_player_by_steam = {str(row["steam_id"]): dict(row) for row in rows}

    for registration in registrations:
        info = registration["info"]
        team_key = str(info.get("team_name") or "").strip().casefold()
        if not team_key:
            continue
        roster = []
        for slot in registration["slots"]:
            steam_id = str(slot.get("steam_id") or "").strip()
            player = registration_player_by_steam.get(steam_id)
            if player:
                roster.append(dict(player))
            elif str(slot.get("player_name") or "").strip():
                roster.append(
                    {
                        "id": 0,
                        "nickname": str(slot["player_name"]).strip(),
                        "avatar": "",
                        "steam_id": steam_id,
                    }
                )
        registration_rosters[team_key] = roster
        registration_logo = str(info.get("team_logo") or "").strip()
        if registration_logo:
            registration_logos[team_key] = f"team_logos/{registration_logo}"

    # 从比赛列表自动提取参赛队伍（含临时队伍）
    import json as _json

    team_map = {}  # key: team_id or "temp_<side>_<player_ids>"
    all_player_ids = set()
    for m in matches:
        for side, tid_key, pkey in [
            ("side1", "team1_id", "team1_players"),
            ("side2", "team2_id", "team2_players"),
        ]:
            tid = m.get(tid_key)
            pids_str = m.get(pkey)
            if tid and tid > 0:
                key = ("team", tid)
                if key not in team_map:
                    team_map[key] = {
                        "id": tid,
                        "name": m.get("team1_name" if side == "side1" else "team2_name", ""),
                        "short_name": m.get("t1s" if side == "side1" else "t2s", ""),
                        "logo": m.get("t1_logo" if side == "side1" else "t2_logo", ""),
                        "is_temp": False,
                        "player_ids": [],
                    }
            elif pids_str:
                try:
                    pids = _json.loads(pids_str) if isinstance(pids_str, str) else pids_str
                    pids = [int(p) for p in pids] if isinstance(pids, list) else []
                except (TypeError, ValueError):
                    pids = []
                if pids:
                    key = ("temp", side, tuple(pids))
                    if key not in team_map:
                        team_map[key] = {
                            "id": None,
                            "name": m.get("team1_name" if side == "side1" else "team2_name", ""),
                            "short_name": m.get("t1s" if side == "side1" else "t2s", "") or "TMP",
                            "logo": "",
                            "is_temp": True,
                            "player_ids": pids,
                        }
                    all_player_ids.update(pids)

    # 批量查询选手信息
    player_info = {}
    if all_player_ids:
        placeholders = ",".join("?" * len(all_player_ids))
        rows = conn.execute(
            f"SELECT id, nickname, avatar FROM players WHERE id IN ({placeholders})",
            tuple(all_player_ids),
        ).fetchall()
        player_info = {r["id"]: r for r in rows}

    # Bracket hover cards use the current event statistics. The old query only
    # loaded names and avatars, so every rating rendered as a dash even when
    # the match had already produced stats.
    event_ratings = conn.execute(
        """
        SELECT ms.player_id,
               SUM(ms.rating * COALESCE(NULLIF(ms.rounds_played, 0), 1)) /
                 NULLIF(SUM(COALESCE(NULLIF(ms.rounds_played, 0), 1)), 0) AS rating
        FROM match_stats ms
        JOIN matches m ON m.id=ms.match_id
        WHERE m.event_id=? AND ms.player_id IS NOT NULL
          AND COALESCE(ms.data_status, 'final') <> 'superseded'
        GROUP BY ms.player_id
        """,
        (event_id,),
    ).fetchall()
    rating_by_player = {
        int(row["player_id"]): round(float(row["rating"]), 2)
        for row in event_ratings
        if row["player_id"] and row["rating"] is not None
    }
    for player_id, player in list(player_info.items()):
        if player_id in rating_by_player:
            player_info[player_id] = {**dict(player), "rating": rating_by_player[player_id]}
    for team_key, roster in list(registration_rosters.items()):
        registration_rosters[team_key] = [
            {
                **player,
                **(
                    {"rating": rating_by_player[int(player["id"])]}
                    if str(player.get("id", "")).isdigit() and int(player["id"]) in rating_by_player
                    else {}
                ),
            }
            for player in roster
        ]

    # 为注册队伍查选手
    reg_team_ids = [v["id"] for k, v in team_map.items() if k[0] == "team"]
    if reg_team_ids:
        ph = ",".join("?" * len(reg_team_ids))
        rows = conn.execute(
            f"SELECT id, nickname, avatar, team_id FROM players WHERE team_id IN ({ph})",
            tuple(reg_team_ids),
        ).fetchall()
        for r in rows:
            key = ("team", r["team_id"])
            if key in team_map:
                team_map[key].setdefault("player_ids", []).append(r["id"])
                player_info[r["id"]] = r
    for player_id, player in list(player_info.items()):
        if player_id in rating_by_player:
            player_info[player_id] = {**dict(player), "rating": rating_by_player[player_id]}

    # 组装最终 teams 列表
    teams = []
    for key, t in team_map.items():
        players = []
        for pid in t["player_ids"]:
            if pid in player_info:
                players.append(dict(player_info[pid]))
        team_key = str(t["name"] or "").strip().casefold()
        if team_key in registration_rosters:
            players = registration_rosters[team_key]
        teams.append(
            {
                "id": t["id"],
                "name": t["name"],
                "short_name": t["short_name"],
                "logo": registration_logos.get(team_key) or t.get("logo") or "",
                "is_temp": t["is_temp"],
                "players": players,
            }
        )
    teams.sort(key=lambda t: (t["is_temp"], t["name"]))

    # 构建 team_id → players 映射（供对阵图卡片悬停用）
    team_players_map = {}
    for t in teams:
        if t["id"] is not None:
            team_players_map[str(t["id"])] = t["players"]
        if t["is_temp"]:
            team_players_map[t["name"]] = t["players"]
            team_players_map[t["name"].lower()] = t["players"]

    # 赛事图池从比赛配置汇总；不再让详情页写死一套地图。
    event_map_pool = []
    seen_map_names = set()
    for match in matches:
        try:
            configured_pool = json.loads(match["map_pool"] or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            configured_pool = []
        if not isinstance(configured_pool, list):
            continue
        for map_name in configured_pool:
            display_name = str(map_name or "").strip()
            key = display_name.casefold()
            if display_name and key not in seen_map_names:
                seen_map_names.add(key)
                event_map_pool.append(display_name)
    if not event_map_pool:
        from utils.bp_manager import ALL_MAPS

        event_map_pool = list(ALL_MAPS)

    # 报名关闭后也保留名单和分队结果，方便参赛者查看。
    award_players = list_event_award_players(conn, event_id)
    current_user = _get_registration_user(conn)
    individual_registration = _load_individual_registrations(
        conn,
        event_id,
        current_user["id"] if current_user else None,
    )
    conn.close()

    return render_template(
        "event_detail.html",
        event=event,
        matches=matches,
        teams=teams,
        team_players_map=team_players_map,
        event_map_pool=event_map_pool,
        registrations=registrations,
        individual_registration=individual_registration,
        individual_registration_open=_individual_registration_is_open(),
        substitute_registration_open=event["effective_event_status"] != "completed",
        award_players=award_players,
        current_user=current_user,
    )


@app.route("/events/<int:event_id>/mvp-poster.png")
def event_mvp_poster(event_id):
    """Public MVP card shown at the bottom of the event page."""
    conn = get_db()
    mvp_player = find_event_award_player(conn, event_id)
    if not mvp_player:
        conn.close()
        return "该赛事还没有设置 MVP", 404
    buffer = build_event_award_poster(conn, BASE_DIR, event_id, mvp_player["id"], "MVP")
    conn.close()
    if not buffer:
        return "赛事或选手不存在", 404
    return send_file(buffer, mimetype="image/png", max_age=0)


@app.route("/events/<int:event_id>/award-poster/<award_type>/<int:player_id>.png")
def event_award_poster(event_id, award_type, player_id):
    """Public MVP / EVP cards shown together at the bottom of the event page."""
    award_type = award_type.upper()
    if award_type not in ("MVP", "EVP"):
        return "荣誉类型不存在", 404
    conn = get_db()
    medal = conn.execute(
        """
        SELECT 1 FROM player_medals
        WHERE event_id=? AND player_id=? AND type=?
    """,
        (event_id, player_id, award_type),
    ).fetchone()
    if not medal:
        conn.close()
        return "该赛事没有这张数据图", 404
    buffer = build_event_award_poster(conn, BASE_DIR, event_id, player_id, award_type)
    conn.close()
    if not buffer:
        return "赛事或选手不存在", 404
    return send_file(buffer, mimetype="image/png", max_age=0)


@app.route("/events/<int:event_id>/register", methods=["POST"])
@csrf_required
def event_register(event_id):
    """选手报名：创建队伍 + 选择队友/位置"""
    if "user_id" not in session:
        flash("请先登录后再报名", "error")
        return redirect(url_for("user_login", next=url_for("event_detail", event_id=event_id)))
    if not rate_limit("event_register", 10, 3600, by_ip=True):
        flash("报名操作过于频繁，请稍后再试", "error")
        return redirect(url_for("event_detail", event_id=event_id))

    conn = get_db()
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not event or not event["registration_open"]:
        conn.close()
        flash("该赛事未开放报名", "error")
        return redirect(url_for("event_detail", event_id=event_id))
    user = conn.execute(
        "SELECT username, steam_id64 FROM users WHERE id=?", (session["user_id"],)
    ).fetchone()
    if not user or not user["steam_id64"]:
        conn.close()
        flash("报名赛事前请先绑定 Steam 账号", "error")
        return redirect(url_for("user_profile"))

    team_name = request.form.get("team_name", "").strip()
    try:
        my_slot = int(request.form.get("my_slot", 0) or 0)
    except (TypeError, ValueError):
        my_slot = -1
    if not team_name:
        conn.close()
        flash("请输入队伍名", "error")
        return redirect(url_for("event_detail", event_id=event_id))
    if my_slot not in range(5):
        conn.close()
        flash("请选择有效的位置", "error")
        return redirect(url_for("event_detail", event_id=event_id))
    already_joined = conn.execute(
        """
        SELECT 1 FROM event_registration_slots s
        JOIN event_registrations r ON r.id=s.registration_id
        WHERE r.event_id=? AND r.status='pending' AND s.user_id=?
    """,
        (event_id, session["user_id"]),
    ).fetchone()
    if already_joined:
        conn.close()
        flash("你已经加入该赛事的一支报名队伍", "error")
        return redirect(url_for("event_detail", event_id=event_id))
    individual_entry = conn.execute(
        "SELECT 1 FROM event_individual_registrations WHERE event_id=? AND user_id=?",
        (event_id, session["user_id"]),
    ).fetchone()
    if individual_entry:
        conn.close()
        flash("你已经选择个人报名，请先取消个人报名", "error")
        return redirect(url_for("event_detail", event_id=event_id))
    duplicate_name = conn.execute(
        "SELECT 1 FROM event_registrations WHERE event_id=? AND status='pending' AND team_name=?",
        (event_id, team_name),
    ).fetchone()
    if duplicate_name:
        conn.close()
        flash("该队伍名已经提交过报名", "error")
        return redirect(url_for("event_detail", event_id=event_id))

    slots = []
    for i in range(5):
        pname = request.form.get(f"pname_{i}", "").strip()
        psteam = request.form.get(f"psteam_{i}", "").strip()
        if psteam and (not psteam.isdigit() or len(psteam) != 17):
            conn.close()
            flash(f"位置 {i + 1} 的 SteamID 格式不正确", "error")
            return redirect(url_for("event_detail", event_id=event_id))
        slot_user_id = session["user_id"] if i == my_slot else None
        if slot_user_id:
            pname = user["username"]
            psteam = user["steam_id64"]
        slots.append((i, slot_user_id, pname, psteam))

    logo_file = request.files.get("team_logo")
    team_logo = None
    if logo_file and logo_file.filename:
        team_logo = save_uploaded_team_logo(logo_file, BASE_DIR)
        if not team_logo:
            conn.close()
            flash("队标无效，请上传不超过 5MB 的 PNG、JPG 或 GIF 图片", "error")
            return redirect(url_for("event_detail", event_id=event_id))

    # 旧数据库仍可能保留不可为空的 captain_user_id；新旧字段同时写入。
    reg_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(event_registrations)").fetchall()
    }
    if "captain_user_id" in reg_columns:
        conn.execute(
            """INSERT INTO event_registrations(
            event_id, team_name, captain_user_id, creator_user_id, team_logo, status
        ) VALUES(?,?,?,?,?,?)""",
            (
                event_id,
                team_name,
                session["user_id"],
                session["user_id"],
                team_logo,
                "pending",
            ),
        )
    else:
        conn.execute(
            """INSERT INTO event_registrations(
                   event_id, team_name, creator_user_id, team_logo, status
               ) VALUES(?,?,?,?,?)""",
            (event_id, team_name, session["user_id"], team_logo, "pending"),
        )
    reg_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # 填充 5 个位置
    for i, slot_user_id, pname, psteam in slots:
        conn.execute(
            """INSERT INTO event_registration_slots(registration_id, slot_index, user_id, player_name, steam_id, filled_by_creator)
            VALUES(?,?,?,?,?,?)""",
            (reg_id, i, slot_user_id, pname or f"位置{i + 1}", psteam or "", 1 if pname else 0),
        )

    conn.commit()
    conn.close()
    flash(f"队伍“{team_name}”创建成功，你现在是队长", "success")
    return redirect(url_for("event_detail", event_id=event_id))


@app.route("/events/<int:event_id>/register-individual", methods=["POST"])
@csrf_required
def event_register_individual(event_id):
    """选手不组队直接报名，之后由管理员随机分配队伍。"""
    if not _individual_registration_is_open():
        return _registration_failure(
            event_id,
            f"个人报名将于 {_individual_registration_open_label()}开放",
            403,
        )
    if "user_id" not in session:
        return _registration_failure(event_id, "请先登录后再报名", 401)

    conn = get_db()
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not event or not event["registration_open"]:
        conn.close()
        return _registration_failure(event_id, "该赛事未开放报名", 403)
    user = conn.execute(
        "SELECT id, username, steam_id64 FROM users WHERE id=?",
        (session["user_id"],),
    ).fetchone()
    if not user or not user["steam_id64"]:
        conn.close()
        return _registration_failure(event_id, "个人报名需要先绑定 Steam 账号")
    if conn.execute(
        """
        SELECT 1 FROM event_individual_registrations
        WHERE event_id=? AND assignment_status<>'pending'
        LIMIT 1
        """,
        (event_id,),
    ).fetchone():
        conn.close()
        return _registration_failure(event_id, "本次个人报名已经完成分队", 409)
    if conn.execute(
        """
        SELECT 1 FROM event_registration_slots s
        JOIN event_registrations r ON r.id=s.registration_id
        WHERE r.event_id=? AND r.status='pending' AND s.user_id=?
        """,
        (event_id, session["user_id"]),
    ).fetchone():
        conn.close()
        return _registration_failure(event_id, "你已经加入该赛事的一支报名队伍", 409)
    if conn.execute(
        "SELECT 1 FROM event_individual_registrations WHERE event_id=? AND user_id=?",
        (event_id, session["user_id"]),
    ).fetchone():
        conn.close()
        return _registration_failure(event_id, "你已经提交过个人报名", 409)

    conn.execute(
        """
        INSERT INTO event_individual_registrations(
            event_id, user_id, player_name, steam_id
        ) VALUES(?,?,?,?)
        """,
        (event_id, user["id"], user["username"], user["steam_id64"]),
    )
    conn.commit()
    conn.close()
    return _registration_success(event_id, "个人报名成功，等待按游戏时长平衡分队")


@app.route("/events/<int:event_id>/register-substitute", methods=["POST"])
@csrf_required
def event_register_substitute(event_id):
    """正式分队完成后，选手报名公共或指定队伍替补。"""
    if "user_id" not in session:
        return _registration_failure(event_id, "请先登录后再报名替补", 401)
    if not rate_limit("event_register_substitute", 10, 3600, by_ip=True):
        return _registration_failure(event_id, "报名操作过于频繁，请稍后再试", 429)

    conn = get_db()
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not event:
        conn.close()
        return _registration_failure(event_id, "赛事不存在", 404)
    user = conn.execute(
        "SELECT id, username, steam_id64 FROM users WHERE id=?",
        (session["user_id"],),
    ).fetchone()
    if not user or not user["steam_id64"]:
        conn.close()
        return _registration_failure(event_id, "替补报名需要先绑定 Steam 账号")

    preferred_registration_id = None
    preferred_team_name = ""
    raw_preferred_id = str(request.form.get("preferred_registration_id") or "").strip()
    if raw_preferred_id:
        try:
            preferred_registration_id = int(raw_preferred_id)
        except ValueError:
            conn.close()
            return _registration_failure(event_id, "请选择有效的替补队伍")
        preferred_registration = conn.execute(
            """SELECT id, team_name FROM event_registrations
               WHERE id=? AND event_id=? AND status='pending'""",
            (preferred_registration_id, event_id),
        ).fetchone()
        if not preferred_registration:
            conn.close()
            return _registration_failure(event_id, "所选队伍不属于当前赛事", 409)
        preferred_team_name = preferred_registration["team_name"]

    finalized = conn.execute(
        """
        SELECT 1
        FROM event_individual_registrations ir
        WHERE ir.event_id=? AND ir.assignment_status='assigned'
          AND EXISTS(
              SELECT 1
              FROM event_registration_slots s
              JOIN event_registrations r ON r.id=s.registration_id
              WHERE r.event_id=ir.event_id AND r.status='pending'
                AND s.user_id=ir.user_id
          )
        LIMIT 1
        """,
        (event_id,),
    ).fetchone()
    if not finalized:
        conn.close()
        return _registration_failure(event_id, "正式分队完成后才会开放替补报名", 409)

    formal_member = conn.execute(
        """
        SELECT 1
        FROM event_registration_slots s
        JOIN event_registrations r ON r.id=s.registration_id
        WHERE r.event_id=? AND r.status='pending' AND s.user_id=?
        LIMIT 1
        """,
        (event_id, user["id"]),
    ).fetchone()
    if formal_member:
        conn.close()
        return _registration_failure(event_id, "你已经是该赛事的正式队员", 409)

    existing = conn.execute(
        """
        SELECT id, assignment_status FROM event_individual_registrations
        WHERE event_id=? AND user_id=?
        """,
        (event_id, user["id"]),
    ).fetchone()
    if existing:
        if existing["assignment_status"] == "reserve":
            conn.execute(
                """UPDATE event_individual_registrations
                   SET preferred_registration_id=?, assigned_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (preferred_registration_id, existing["id"]),
            )
            conn.commit()
            conn.close()
            message = (
                f"替补队伍已改为 {preferred_team_name}"
                if preferred_team_name
                else "已改为赛事公共替补，可替补任意队伍"
            )
            return _registration_success(event_id, message)
        conn.close()
        return _registration_failure(event_id, "你已经参加该赛事的报名", 409)

    conn.execute(
        """
        INSERT INTO event_individual_registrations(
            event_id, user_id, player_name, steam_id,
            assignment_status, assigned_at, preferred_registration_id
        ) VALUES(?,?,?,?, 'reserve', CURRENT_TIMESTAMP, ?)
        """,
        (
            event_id,
            user["id"],
            user["username"],
            user["steam_id64"],
            preferred_registration_id,
        ),
    )
    conn.commit()
    conn.close()
    return _registration_success(
        event_id,
        (
            f"替补报名成功。你已指定 {preferred_team_name}"
            if preferred_team_name
            else "替补报名成功。你已进入赛事公共替补池，可根据实际情况替补任意队伍"
        ),
    )


@app.route("/events/<int:event_id>/individual-registration/withdraw", methods=["POST"])
@csrf_required
def event_withdraw_individual(event_id):
    """选手取消尚未分队的个人报名，或退出公共替补池。"""
    if "user_id" not in session:
        return _registration_failure(event_id, "请先登录", 401)
    conn = get_db()
    entry = conn.execute(
        """
        SELECT * FROM event_individual_registrations
        WHERE event_id=? AND user_id=?
        """,
        (event_id, session["user_id"]),
    ).fetchone()
    if not entry:
        conn.close()
        return _registration_failure(event_id, "没有找到你的个人报名", 404)
    if entry["assignment_status"] == "assigned":
        conn.close()
        return _registration_failure(event_id, "你已经进入正式队伍，请联系队长或管理员调整", 409)
    was_substitute = entry["assignment_status"] == "reserve"
    conn.execute("DELETE FROM event_individual_registrations WHERE id=?", (entry["id"],))
    conn.commit()
    conn.close()
    return _registration_success(
        event_id,
        "已取消替补报名" if was_substitute else "已取消个人报名",
    )


@app.route(
    "/events/<int:event_id>/individual-registration/<int:entry_id>/remove",
    methods=["POST"],
)
@csrf_required
def event_remove_individual_registration(event_id, entry_id):
    """管理员移除个人报名；公共替补可单独移除。"""
    if "admin_id" not in session:
        return _registration_failure(event_id, "只有管理员可以移除个人报名", 403)
    conn = get_db()
    entry = conn.execute(
        """
        SELECT ir.*,
               EXISTS(
                   SELECT 1
                   FROM event_registration_slots s
                   JOIN event_registrations r ON r.id=s.registration_id
                   WHERE r.event_id=ir.event_id AND r.status='pending'
                     AND s.user_id=ir.user_id
               ) AS is_formal_member
        FROM event_individual_registrations ir
        WHERE ir.id=? AND ir.event_id=?
        """,
        (entry_id, event_id),
    ).fetchone()
    if not entry:
        conn.close()
        return _registration_failure(event_id, "个人报名不存在", 404)
    if entry["is_formal_member"]:
        conn.close()
        return _registration_failure(
            event_id,
            "该选手已经进入正式队伍，请在对应队伍中移除",
            409,
        )
    reset_assignment = entry["assignment_status"] == "assigned"
    conn.execute("DELETE FROM event_individual_registrations WHERE id=?", (entry_id,))
    if reset_assignment:
        conn.execute(
            """
            UPDATE event_individual_registrations
            SET assignment_status='pending', team_number=NULL, assigned_at=NULL
            WHERE event_id=?
            """,
            (event_id,),
        )
    conn.commit()
    conn.close()
    suffix = "，原分队结果已清空" if reset_assignment else ""
    return _registration_success(event_id, f"已移除 {entry['player_name']}{suffix}")


@app.route("/events/<int:event_id>/individual-registration/randomize", methods=["POST"])
@csrf_required
def event_randomize_individual_teams(event_id):
    """管理员参考公开的 CS2 游戏时长，按每五人一队平衡分组。"""
    if "admin_id" not in session:
        return _registration_failure(event_id, "只有管理员可以进行平衡分队", 403)
    conn = get_db()
    event = conn.execute("SELECT id FROM events WHERE id=?", (event_id,)).fetchone()
    if not event:
        conn.close()
        return _registration_failure(event_id, "赛事不存在", 404)
    if conn.execute(
        """
        SELECT 1
        FROM event_individual_registrations ir
        WHERE ir.event_id=?
          AND EXISTS(
              SELECT 1
              FROM event_registration_slots s
              JOIN event_registrations r ON r.id=s.registration_id
              WHERE r.event_id=ir.event_id AND r.status='pending'
                AND s.user_id=ir.user_id
          )
        LIMIT 1
        """,
        (event_id,),
    ).fetchone():
        conn.close()
        return _registration_failure(event_id, "个人报名选手已经进入正式队伍", 409)
    rows = conn.execute(
        """
        SELECT id, steam_id, cs2_playtime_minutes, playtime_status,
               playtime_checked_at
        FROM event_individual_registrations
        WHERE event_id=?
        ORDER BY id
        """,
        (event_id,),
    ).fetchall()
    if len(rows) < 5:
        conn.close()
        return _registration_failure(event_id, "至少需要 5 名个人报名选手才能分队")

    refresh_result = refresh_registration_playtimes(conn, rows)
    rows = conn.execute(
        """
        SELECT id, steam_id, cs2_playtime_minutes, playtime_status,
               playtime_checked_at
        FROM event_individual_registrations
        WHERE event_id=?
        ORDER BY id
        """,
        (event_id,),
    ).fetchall()
    draw = build_balanced_assignments(rows, team_size=5)
    conn.execute(
        """
        UPDATE event_individual_registrations
        SET assignment_status='pending', team_number=NULL, assigned_at=NULL
        WHERE event_id=?
        """,
        (event_id,),
    )
    for entry_id, team_number in draw["assignments"].items():
        conn.execute(
            """
            UPDATE event_individual_registrations
            SET assignment_status='assigned', team_number=?, assigned_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (team_number, entry_id),
        )
    for entry_id in draw["reserves"]:
        conn.execute(
            """
            UPDATE event_individual_registrations
            SET assignment_status='reserve', team_number=NULL, assigned_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (entry_id,),
        )
    conn.commit()
    conn.close()
    team_count = len(draw["team_totals"])
    reserve_count = len(draw["reserves"])
    message = f"已按 CS2 游戏时长平衡分成 {team_count} 支队伍"
    if not refresh_result["configured"]:
        message += "（Steam 接口未配置，本次按随机顺序分配）"
    elif not draw["known_count"]:
        message += "（没有可读取的公开时长，本次按随机顺序分配）"
    elif draw["unknown_count"]:
        message += f"，{draw['unknown_count']} 名选手时长不可见，已按公开选手的中位时长参与平衡"
    if reserve_count:
        message += f"，另有 {reserve_count} 名候补"
    return _registration_success(event_id, message)


@app.route(
    "/events/<int:event_id>/individual-registration/finalize",
    methods=["POST"],
)
@csrf_required
def event_finalize_individual_teams(event_id):
    """管理员一键补满现有队伍，并把个人报名转成正式队伍。"""
    if "admin_id" not in session:
        return _registration_failure(event_id, "只有管理员可以完成正式分队", 403)

    conn = get_db()
    event = conn.execute("SELECT id FROM events WHERE id=?", (event_id,)).fetchone()
    if not event:
        conn.close()
        return _registration_failure(event_id, "赛事不存在", 404)

    refresh_rows = conn.execute(
        """
        SELECT id, steam_id, cs2_playtime_minutes, playtime_status,
               playtime_checked_at
        FROM event_individual_registrations
        WHERE event_id=?
        ORDER BY created_at, id
        """,
        (event_id,),
    ).fetchall()
    if not refresh_rows:
        conn.close()
        return _registration_failure(event_id, "暂时没有个人报名选手")

    refresh_result = refresh_registration_playtimes(conn, refresh_rows)
    conn.commit()

    try:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute(
            """
            SELECT 1
            FROM event_individual_registrations ir
            WHERE ir.event_id=?
              AND EXISTS(
                  SELECT 1
                  FROM event_registration_slots s
                  JOIN event_registrations r ON r.id=s.registration_id
                  WHERE r.event_id=ir.event_id AND r.status='pending'
                    AND s.user_id=ir.user_id
              )
            LIMIT 1
            """,
            (event_id,),
        ).fetchone():
            raise ValueError("个人报名已经完成正式分队，不能重复执行")

        candidates = [
            dict(row)
            for row in conn.execute(
                """
                SELECT id, event_id, user_id, player_name, steam_id,
                       created_at, cs2_playtime_minutes, playtime_status,
                       playtime_checked_at
                FROM event_individual_registrations
                WHERE event_id=?
                ORDER BY created_at, id
                """,
                (event_id,),
            ).fetchall()
        ]

        registration_groups = _load_event_registrations(conn, event_id)
        partial_teams = []
        partial_by_id = {}
        for group in registration_groups:
            open_slots = [slot for slot in group["slots"] if _registration_slot_is_open(slot)]
            if not open_slots:
                continue
            occupied_slots = [
                slot for slot in group["slots"] if not _registration_slot_is_open(slot)
            ]
            fixed_players = attach_latest_playtime(conn, occupied_slots, "steam_id")
            partial = {
                "registration_id": group["info"]["id"],
                "players": fixed_players,
                "open_slots": open_slots,
            }
            partial_teams.append(partial)
            partial_by_id[partial["registration_id"]] = partial

        required_for_partial = sum(len(team["open_slots"]) for team in partial_teams)
        if len(candidates) < required_for_partial:
            raise ValueError(f"个人报名人数不足：补满现有队伍还需要 {required_for_partial} 人")
        if not partial_teams and len(candidates) < 5:
            raise ValueError("至少需要 5 名个人报名选手才能创建正式队伍")

        draw = build_balanced_roster_plan(
            candidates,
            fixed_teams=partial_teams,
            team_size=5,
        )
        candidate_by_id = {row["id"]: row for row in candidates}
        existing_names = {
            str(row["team_name"] or "").strip().casefold()
            for row in conn.execute(
                "SELECT team_name FROM event_registrations WHERE event_id=?",
                (event_id,),
            ).fetchall()
        }
        registration_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(event_registrations)").fetchall()
        }
        next_team_number = 1
        created_team_count = 0
        completed_existing_count = 0

        for team_plan in draw["teams"]:
            assigned_rows = [candidate_by_id[entry_id] for entry_id in team_plan["candidate_ids"]]
            registration_id = team_plan["registration_id"]
            if registration_id is not None:
                partial = partial_by_id[registration_id]
                if len(assigned_rows) != len(partial["open_slots"]):
                    raise RuntimeError("分队计划与现有空位数量不一致")
                for slot, entry in zip(partial["open_slots"], assigned_rows):
                    conn.execute(
                        """
                        UPDATE event_registration_slots
                        SET user_id=?, player_name=?, steam_id=?, filled_by_creator=0
                        WHERE id=? AND user_id IS NULL
                          AND COALESCE(steam_id, '')=''
                          AND COALESCE(filled_by_creator, 0)=0
                        """,
                        (
                            entry["user_id"],
                            entry["player_name"],
                            entry["steam_id"],
                            slot["id"],
                        ),
                    )
                    if conn.execute("SELECT changes()").fetchone()[0] != 1:
                        raise RuntimeError("现有队伍空位已经发生变化，请刷新后重试")
                completed_existing_count += 1
            else:
                while True:
                    team_name = f"个人报名队 {next_team_number}"
                    next_team_number += 1
                    if team_name.casefold() not in existing_names:
                        existing_names.add(team_name.casefold())
                        break
                captain = min(
                    assigned_rows,
                    key=lambda row: (str(row.get("created_at") or ""), row["id"]),
                )
                if "captain_user_id" in registration_columns:
                    conn.execute(
                        """
                        INSERT INTO event_registrations(
                            event_id, team_name, captain_user_id,
                            creator_user_id, team_logo, status
                        ) VALUES(?,?,?,?,NULL,'pending')
                        """,
                        (
                            event_id,
                            team_name,
                            captain["user_id"],
                            captain["user_id"],
                        ),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO event_registrations(
                            event_id, team_name, creator_user_id, team_logo, status
                        ) VALUES(?,?,?,NULL,'pending')
                        """,
                        (event_id, team_name, captain["user_id"]),
                    )
                registration_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                ordered_rows = [captain] + [
                    row for row in assigned_rows if row["id"] != captain["id"]
                ]
                for slot_index, entry in enumerate(ordered_rows):
                    conn.execute(
                        """
                        INSERT INTO event_registration_slots(
                            registration_id, slot_index, user_id,
                            player_name, steam_id, filled_by_creator
                        ) VALUES(?,?,?,?,?,0)
                        """,
                        (
                            registration_id,
                            slot_index,
                            entry["user_id"],
                            entry["player_name"],
                            entry["steam_id"],
                        ),
                    )
                created_team_count += 1

            for entry in assigned_rows:
                conn.execute(
                    """
                    UPDATE event_individual_registrations
                    SET assignment_status='assigned', team_number=?,
                        assigned_at=CURRENT_TIMESTAMP
                    WHERE id=? AND event_id=?
                    """,
                    (registration_id, entry["id"], event_id),
                )

        reserve_ids = set(draw["reserves"])
        if reserve_ids:
            placeholders = ",".join("?" for _ in reserve_ids)
            conn.execute(
                f"""
                UPDATE event_individual_registrations
                SET assignment_status='reserve', team_number=NULL,
                    assigned_at=CURRENT_TIMESTAMP
                WHERE event_id=? AND id IN ({placeholders})
                """,
                (event_id, *sorted(reserve_ids)),
            )

        conn.commit()
    except ValueError as exc:
        conn.rollback()
        conn.close()
        return _registration_failure(event_id, str(exc), 409)
    except Exception:
        conn.rollback()
        conn.close()
        app.logger.exception("Failed to finalize event registration teams")
        return _registration_failure(event_id, "正式分队失败，请刷新后重试", 500)

    conn.close()
    parts = []
    if completed_existing_count:
        parts.append(f"补满 {completed_existing_count} 支现有队伍")
    if created_team_count:
        parts.append(f"新建 {created_team_count} 支正式队伍")
    if reserve_ids:
        parts.append(f"{len(reserve_ids)} 名选手进入公共替补池")
    message = "一键分队完成：" + "，".join(parts)
    if not refresh_result["configured"]:
        message += "（Steam 接口未配置，未知时长按统一值参与平衡）"
    elif not draw["known_count"]:
        message += "（没有可读取的公开时长，已按报名顺序完成分队）"
    elif draw["unknown_count"]:
        message += f"；{draw['unknown_count']} 名选手时长不可见，已按公开选手的中位时长参与平衡"
    return _registration_success(event_id, message)


@app.route("/events/<int:event_id>/join/<int:reg_id>/<int:slot>", methods=["POST"])
@csrf_required
def event_join_slot(event_id, reg_id, slot):
    """选手加入已有队伍的某个空位"""
    if "user_id" not in session:
        return _registration_failure(event_id, "请先登录后再加入队伍", 401)

    if slot not in range(5):
        return _registration_failure(event_id, "该位置不存在", 404)

    conn = get_db()
    user = conn.execute(
        "SELECT username, steam_id64 FROM users WHERE id=?", (session["user_id"],)
    ).fetchone()
    if not user or not user["steam_id64"]:
        conn.close()
        return _registration_failure(event_id, "加入队伍前请先绑定 Steam 账号")
    slot_row = conn.execute(
        """
        SELECT s.* FROM event_registration_slots s
        JOIN event_registrations r ON r.id=s.registration_id
        JOIN events e ON e.id=r.event_id
        WHERE s.registration_id=? AND s.slot_index=?
          AND r.event_id=? AND r.status='pending' AND e.registration_open=1
    """,
        (reg_id, slot, event_id),
    ).fetchone()
    if not slot_row:
        conn.close()
        return _registration_failure(event_id, "该位置不存在", 404)
    if slot_row["user_id"]:
        conn.close()
        return _registration_failure(event_id, "该位置已被占用", 409)

    already_joined = conn.execute(
        """
        SELECT 1 FROM event_registration_slots s
        JOIN event_registrations r ON r.id=s.registration_id
        WHERE r.event_id=? AND r.status='pending' AND s.user_id=?
    """,
        (event_id, session["user_id"]),
    ).fetchone()
    if already_joined:
        conn.close()
        return _registration_failure(event_id, "你已经加入该赛事的一支报名队伍", 409)
    individual_entry = conn.execute(
        "SELECT 1 FROM event_individual_registrations WHERE event_id=? AND user_id=?",
        (event_id, session["user_id"]),
    ).fetchone()
    if individual_entry:
        conn.close()
        return _registration_failure(event_id, "你已经选择个人报名，请先取消个人报名", 409)

    conn.execute(
        """UPDATE event_registration_slots
                    SET user_id=?, player_name=?, steam_id=?
                    WHERE id=? AND user_id IS NULL""",
        (session["user_id"], user["username"], user["steam_id64"], slot_row["id"]),
    )
    changed = conn.execute("SELECT changes()").fetchone()[0]
    if changed != 1:
        conn.rollback()
        conn.close()
        return _registration_failure(event_id, "该位置刚刚被其他选手加入，请选择其他位置", 409)
    conn.commit()
    conn.close()
    return _registration_success(event_id, "加入成功")


@app.route("/events/<int:event_id>/leave/<int:reg_id>/<int:slot>", methods=["POST"])
@csrf_required
def event_leave_slot(event_id, reg_id, slot):
    """选手退出自己已加入的报名位置"""
    if "user_id" not in session:
        return _registration_failure(event_id, "请先登录后再退出位置", 401)

    if slot not in range(5):
        return _registration_failure(event_id, "该位置不存在", 404)

    conn = get_db()
    slot_row = conn.execute(
        """
        SELECT s.id, s.slot_index, r.team_name, r.creator_user_id
        FROM event_registration_slots s
        JOIN event_registrations r ON r.id=s.registration_id
        JOIN events e ON e.id=r.event_id
        WHERE s.registration_id=? AND s.slot_index=?
          AND r.event_id=? AND r.status='pending' AND e.registration_open=1
          AND s.user_id=?
    """,
        (reg_id, slot, event_id, session["user_id"]),
    ).fetchone()
    if not slot_row:
        conn.close()
        return _registration_failure(event_id, "只能退出你自己加入的位置，或该报名已不可修改", 403)
    if slot_row["creator_user_id"] == session["user_id"]:
        conn.close()
        return _registration_failure(event_id, "队长不能直接退出，请解散队伍", 403)

    conn.execute(
        """
        UPDATE event_registration_slots
        SET user_id=NULL,
            player_name=?,
            steam_id='',
            filled_by_creator=0
        WHERE id=? AND user_id=?
    """,
        (f"位置{slot_row['slot_index'] + 1}", slot_row["id"], session["user_id"]),
    )
    changed = conn.execute("SELECT changes()").fetchone()[0]
    if changed != 1:
        conn.rollback()
        conn.close()
        return _registration_failure(event_id, "退出失败，请刷新页面后重试", 409)

    _move_individual_registration_to_reserve(conn, event_id, session["user_id"])
    conn.commit()
    conn.close()
    return _registration_success(
        event_id,
        f'已退出 "{slot_row["team_name"]}" 的位置 {slot_row["slot_index"] + 1}',
    )


@app.route("/events/<int:event_id>/registrations/<int:reg_id>/rename", methods=["POST"])
@csrf_required
def event_registration_rename(event_id, reg_id):
    """队长或管理员直接修改报名队伍名称。"""
    conn = get_db()
    registration = _registration_for_management(conn, event_id, reg_id)
    if not _can_manage_registration(registration):
        conn.close()
        return _registration_failure(event_id, "只有队长或管理员可以修改队名", 403)

    team_name = request.form.get("team_name", "").strip()
    if not 2 <= len(team_name) <= 40:
        conn.close()
        return _registration_failure(event_id, "队伍名需要为 2 至 40 个字符")
    duplicate = conn.execute(
        """SELECT 1 FROM event_registrations
           WHERE event_id=? AND status='pending' AND id<>?
             AND team_name=? COLLATE NOCASE""",
        (event_id, reg_id, team_name),
    ).fetchone()
    if duplicate:
        conn.close()
        return _registration_failure(event_id, "该队伍名已经被使用", 409)

    conn.execute("UPDATE event_registrations SET team_name=? WHERE id=?", (team_name, reg_id))
    conn.commit()
    conn.close()
    return _registration_success(event_id, f'队伍已更名为 "{team_name}"')


@app.route("/events/<int:event_id>/registrations/<int:reg_id>/logo", methods=["POST"])
@csrf_required
def event_registration_upload_logo(event_id, reg_id):
    """队长或管理员上传、替换报名队伍的队标。"""
    conn = get_db()
    registration = _registration_for_management(conn, event_id, reg_id)
    if not _can_manage_registration(registration):
        conn.close()
        return _registration_failure(event_id, "只有队长或管理员可以修改队标", 403)

    logo_file = request.files.get("team_logo")
    new_logo = save_uploaded_team_logo(logo_file, BASE_DIR)
    if not new_logo:
        conn.close()
        return _registration_failure(event_id, "队标无效，请上传不超过 5MB 的 PNG、JPG 或 GIF 图片")

    old_logo = registration["team_logo"]
    try:
        conn.execute(
            "UPDATE event_registrations SET team_logo=? WHERE id=?",
            (new_logo, reg_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        remove_uploaded_team_logo(BASE_DIR, new_logo)
        return _registration_failure(event_id, "队标保存失败，请稍后重试", 500)
    conn.close()
    remove_uploaded_team_logo(BASE_DIR, old_logo)
    return _registration_success(event_id, "队标已更新")


@app.route(
    "/events/<int:event_id>/registrations/<int:reg_id>/logo/remove",
    methods=["POST"],
)
@csrf_required
def event_registration_remove_logo(event_id, reg_id):
    """队长或管理员移除报名队伍的队标。"""
    conn = get_db()
    registration = _registration_for_management(conn, event_id, reg_id)
    if not _can_manage_registration(registration):
        conn.close()
        return _registration_failure(event_id, "只有队长或管理员可以移除队标", 403)

    old_logo = registration["team_logo"]
    conn.execute("UPDATE event_registrations SET team_logo=NULL WHERE id=?", (reg_id,))
    conn.commit()
    conn.close()
    remove_uploaded_team_logo(BASE_DIR, old_logo)
    return _registration_success(event_id, "队标已移除")


@app.route("/events/<int:event_id>/registrations/<int:reg_id>/dissolve", methods=["POST"])
@csrf_required
def event_registration_dissolve(event_id, reg_id):
    """队长或管理员解散报名队伍。"""
    conn = get_db()
    registration = _registration_for_management(conn, event_id, reg_id)
    if not _can_manage_registration(registration):
        conn.close()
        return _registration_failure(event_id, "只有队长或管理员可以解散队伍", 403)

    team_name = registration["team_name"]
    team_logo = registration["team_logo"]
    member_rows = conn.execute(
        "SELECT user_id FROM event_registration_slots WHERE registration_id=?",
        (reg_id,),
    ).fetchall()
    for member in member_rows:
        _move_individual_registration_to_reserve(conn, event_id, member["user_id"])
    conn.execute("DELETE FROM event_registration_slots WHERE registration_id=?", (reg_id,))
    conn.execute("DELETE FROM event_registrations WHERE id=?", (reg_id,))
    conn.commit()
    conn.close()
    remove_uploaded_team_logo(BASE_DIR, team_logo)
    return _registration_success(event_id, f'队伍 "{team_name}" 已解散')


@app.route(
    "/events/<int:event_id>/registrations/<int:reg_id>/slots/<int:slot>/remove",
    methods=["POST"],
)
@csrf_required
def event_registration_remove_member(event_id, reg_id, slot):
    """队长或管理员移除队员或清空预留位置。"""
    if slot not in range(5):
        return _registration_failure(event_id, "该位置不存在", 404)

    conn = get_db()
    registration = _registration_for_management(conn, event_id, reg_id)
    if not _can_manage_registration(registration):
        conn.close()
        return _registration_failure(event_id, "只有队长或管理员可以移除队员", 403)
    slot_row = conn.execute(
        """SELECT * FROM event_registration_slots
           WHERE registration_id=? AND slot_index=?""",
        (reg_id, slot),
    ).fetchone()
    if not slot_row:
        conn.close()
        return _registration_failure(event_id, "该位置不存在", 404)
    if slot_row["user_id"] == registration["creator_user_id"]:
        conn.close()
        return _registration_failure(event_id, "队长位置不能被移除，请解散队伍", 403)

    removed_name = slot_row["player_name"]
    conn.execute(
        """UPDATE event_registration_slots
           SET user_id=NULL, player_name=?, steam_id='', filled_by_creator=0
           WHERE id=?""",
        (f"位置{slot + 1}", slot_row["id"]),
    )
    _move_individual_registration_to_reserve(conn, event_id, slot_row["user_id"])
    conn.commit()
    conn.close()
    return _registration_success(event_id, f'已移除队员 "{removed_name}"')


@app.route(
    "/events/<int:event_id>/registrations/<int:reg_id>/slots/<int:slot>/update",
    methods=["POST"],
)
@csrf_required
def event_registration_update_member(event_id, reg_id, slot):
    """管理员可修改任意队员；队长可修改未被账号认领的预留位置。"""
    if slot not in range(5):
        return _registration_failure(event_id, "该位置不存在", 404)

    conn = get_db()
    registration = _registration_for_management(conn, event_id, reg_id)
    if not _can_manage_registration(registration):
        conn.close()
        return _registration_failure(event_id, "只有队长或管理员可以修改队员", 403)
    slot_row = conn.execute(
        """SELECT * FROM event_registration_slots
           WHERE registration_id=? AND slot_index=?""",
        (reg_id, slot),
    ).fetchone()
    if not slot_row:
        conn.close()
        return _registration_failure(event_id, "该位置不存在", 404)
    if not session.get("admin_id") and slot_row["user_id"]:
        conn.close()
        return _registration_failure(event_id, "队长不能修改已认领队员的账号资料", 403)

    player_name = request.form.get("player_name", "").strip()
    steam_id = request.form.get("steam_id", "").strip()
    if len(player_name) > 40:
        conn.close()
        return _registration_failure(event_id, "选手名不能超过 40 个字符")
    if steam_id and (not steam_id.isdigit() or len(steam_id) != 17):
        conn.close()
        return _registration_failure(event_id, "SteamID 必须是 17 位数字")
    if slot_row["user_id"] and not player_name:
        conn.close()
        return _registration_failure(event_id, "已加入的队员名称不能为空")

    display_name = player_name or f"位置{slot + 1}"
    display_steam = steam_id if player_name else ""
    filled_by_creator = slot_row["filled_by_creator"]
    if not slot_row["user_id"]:
        filled_by_creator = 1 if player_name else 0
    conn.execute(
        """UPDATE event_registration_slots
           SET player_name=?, steam_id=?, filled_by_creator=? WHERE id=?""",
        (display_name, display_steam, filled_by_creator, slot_row["id"]),
    )
    conn.commit()
    conn.close()
    return _registration_success(event_id, f"位置 {slot + 1} 已更新")


@app.route(
    "/events/<int:event_id>/registrations/<int:reg_id>/slots/<int:slot>/captain",
    methods=["POST"],
)
@csrf_required
def event_registration_transfer_captain(event_id, reg_id, slot):
    """管理员把队长权限直接转交给队伍中的另一名注册用户。"""
    if not session.get("admin_id"):
        return _registration_failure(event_id, "只有管理员可以转移队长权限", 403)
    if slot not in range(5):
        return _registration_failure(event_id, "该位置不存在", 404)

    conn = get_db()
    registration = _registration_for_management(conn, event_id, reg_id)
    if not registration:
        conn.close()
        return _registration_failure(event_id, "报名队伍不存在", 404)

    slot_row = conn.execute(
        """SELECT * FROM event_registration_slots
           WHERE registration_id=? AND slot_index=?""",
        (reg_id, slot),
    ).fetchone()
    if not slot_row:
        conn.close()
        return _registration_failure(event_id, "该位置不存在", 404)
    if not slot_row["user_id"]:
        conn.close()
        return _registration_failure(event_id, "只能任命已经加入队伍的注册用户", 400)
    if slot_row["user_id"] == registration["creator_user_id"]:
        conn.close()
        return _registration_failure(event_id, "该玩家已经是队长", 400)

    conn.execute(
        "UPDATE event_registrations SET creator_user_id=? WHERE id=?",
        (slot_row["user_id"], reg_id),
    )
    conn.commit()
    new_captain_name = slot_row["player_name"]
    conn.close()
    return _registration_success(event_id, f'已任命 "{new_captain_name}" 为队长')


@app.route("/events/<event_id>/stats")
def event_stats(event_id):
    """赛事数据统计"""
    conn = get_db()
    event_ref = str(event_id)
    event = resolve_event_ref(conn, event_ref)
    if not event:
        conn.close()
        return "赛事不存在", 404
    if event["slug"] and event_ref != event["slug"]:
        conn.close()
        return redirect(event_path(event) + "/stats", code=301)
    event_id = event["id"]

    # 选手排行
    rankings = conn.execute(
        """
        SELECT p.nickname, p.id, t.short_name AS team,
               AVG(ms.rating) AS rating,
               (SUM(ms.kills) * 1.0 / NULLIF(SUM(ms.deaths), 0)) AS kd,
               AVG(ms.adr) AS adr,
               AVG(ms.kast) AS kast,
               AVG(ms.impact) AS impact,
               AVG(ms.headshot_percentage) AS hs,
               SUM(ms.clutches_won) AS clutch,
               COUNT(ms.id) AS matches
        FROM match_stats ms
        JOIN players p ON ms.player_id=p.id
        LEFT JOIN teams t ON p.team_id=t.id
        JOIN matches m ON ms.match_id=m.id
        WHERE m.event_id=?
          AND COALESCE(ms.data_status, 'final') <> 'superseded'
        GROUP BY p.id
        ORDER BY rating DESC LIMIT 30
    """,
        (event_id,),
    ).fetchall()

    # 地图统计
    map_stats = conn.execute(
        """
        SELECT ms.map_name,
               COUNT(DISTINCT ms.match_id) AS times_played,
               AVG(ms.rating) AS avg_rating,
               (SUM(ms.kills) * 1.0 / NULLIF(SUM(ms.deaths), 0)) AS avg_kd
        FROM match_stats ms
        JOIN matches m ON ms.match_id=m.id
        WHERE m.event_id=? AND ms.map_name != '' AND ms.map_name IS NOT NULL
          AND COALESCE(ms.data_status, 'final') <> 'superseded'
        GROUP BY ms.map_name
        ORDER BY times_played DESC
    """,
        (event_id,),
    ).fetchall()

    # 队伍数据
    team_rankings = conn.execute(
        """
        SELECT t.name AS team_name, t.short_name AS team_short, t.id AS team_id,
               COUNT(DISTINCT m.id) AS match_count,
               SUM(CASE WHEN
                   (m.team1_id = t.id AND m.team1_score > m.team2_score) OR
                   (m.team2_id = t.id AND m.team2_score > m.team1_score)
               THEN 1 ELSE 0 END) AS wins,
               AVG(CASE WHEN m.team1_id = t.id THEN m.team1_score ELSE m.team2_score END) AS avg_score
        FROM matches m
        JOIN teams t ON (m.team1_id = t.id OR m.team2_id = t.id)
        WHERE m.event_id=? AND m.team1_score IS NOT NULL
        GROUP BY t.id
        ORDER BY wins DESC
    """,
        (event_id,),
    ).fetchall()

    conn.close()
    return render_template(
        "event_stats.html",
        event=event,
        rankings=rankings,
        map_stats=map_stats,
        team_rankings=team_rankings,
    )
