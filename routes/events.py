"""???????????????"""

from flask import flash, redirect, render_template, request, send_file, session, url_for

from config import BASE_DIR
from models import get_db
from services.award_service import (
    build_event_award_poster,
    find_event_award_player,
    list_event_award_players,
)
from services.match_service import add_effective_event_status, supplement_temp_teams
from utils.match_utils import get_sql_effective_status
from utils.web_helpers import csrf_required
from web_app import app

_SQL_EFFECTIVE_STATUS = get_sql_effective_status()


@app.route("/events")
def events_list():
    """赛事列表"""
    status_filter = request.args.get("status", "")
    view_mode = request.args.get("view", "")  # calendar

    conn = get_db()
    events = conn.execute("""
        SELECT e.*, COUNT(DISTINCT m.id) AS match_count,
               (SELECT COUNT(DISTINCT team_id) FROM (
                   SELECT team1_id AS team_id FROM matches WHERE event_id = e.id
                   UNION
                   SELECT team2_id FROM matches WHERE event_id = e.id
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


@app.route("/events/<int:event_id>")
def event_detail(event_id):
    """赛事详情"""
    conn = get_db()
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()

    if not event:
        conn.close()
        return "赛事不存在", 404

    event = add_effective_event_status(event)

    matches = conn.execute(
        f"""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s,
               {_SQL_EFFECTIVE_STATUS}
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        WHERE m.event_id=?
        ORDER BY m.match_time
    """,
        (event_id,),
    ).fetchall()
    matches = [supplement_temp_teams(m, conn) for m in matches]

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

    # 组装最终 teams 列表
    teams = []
    for key, t in team_map.items():
        players = []
        for pid in t["player_ids"]:
            if pid in player_info:
                players.append(dict(player_info[pid]))
        teams.append(
            {
                "id": t["id"],
                "name": t["name"],
                "short_name": t["short_name"],
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

    # 补充所有注册队伍的选手（即使没有比赛数据也查）
    all_team_ids = set()
    for t in teams:
        if t["id"] is not None and t["id"] > 0:
            all_team_ids.add(t["id"])
    if all_team_ids:
        ph = ",".join("?" * len(all_team_ids))
        rows = conn.execute(
            f"SELECT p.id, p.nickname, p.avatar, p.team_id FROM players p WHERE p.team_id IN ({ph})",
            tuple(all_team_ids),
        ).fetchall()
        for r in rows:
            key = str(r["team_id"])
            if key not in team_players_map:
                team_players_map[key] = []
            team_players_map[key].append(dict(r))

    # 赛事图池：标准 CS2 7 张地图，固定顺序
    event_map_pool = ["Mirage", "Inferno", "Dust2", "Ancient", "Anubis", "Nuke", "Overpass"]

    # 报名数据
    registrations = []
    if event["registration_open"]:
        regs = conn.execute(
            """
            SELECT r.*, u.username AS creator_name FROM event_registrations r
            LEFT JOIN users u ON r.creator_user_id=u.id
            WHERE r.event_id=? AND r.status='pending' ORDER BY r.created_at DESC
        """,
            (event_id,),
        ).fetchall()
        for reg in regs:
            slots = conn.execute(
                "SELECT * FROM event_registration_slots WHERE registration_id=? ORDER BY slot_index",
                (reg["id"],),
            ).fetchall()
            registrations.append({"info": dict(reg), "slots": [dict(s) for s in slots]})

    award_players = list_event_award_players(conn, event_id)
    current_user = None
    if session.get("user_id"):
        current_user = conn.execute(
            "SELECT id, username, steam_id64 FROM users WHERE id=?", (session["user_id"],)
        ).fetchone()
    conn.close()

    return render_template(
        "event_detail.html",
        event=event,
        matches=matches,
        teams=teams,
        team_players_map=team_players_map,
        event_map_pool=event_map_pool,
        registrations=registrations,
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
    duplicate_name = conn.execute(
        "SELECT 1 FROM event_registrations WHERE event_id=? AND status='pending' AND team_name=?",
        (event_id, team_name),
    ).fetchone()
    if duplicate_name:
        conn.close()
        flash("该队伍名已经提交过报名", "error")
        return redirect(url_for("event_detail", event_id=event_id))

    # 旧数据库仍可能保留不可为空的 captain_user_id；新旧字段同时写入。
    reg_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(event_registrations)").fetchall()
    }
    if "captain_user_id" in reg_columns:
        conn.execute(
            """INSERT INTO event_registrations(
            event_id, team_name, captain_user_id, creator_user_id, status
        ) VALUES(?,?,?,?,?)""",
            (event_id, team_name, session["user_id"], session["user_id"], "pending"),
        )
    else:
        conn.execute(
            """INSERT INTO event_registrations(event_id, team_name, creator_user_id, status)
            VALUES(?,?,?,?)""",
            (event_id, team_name, session["user_id"], "pending"),
        )
    reg_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # 填充 5 个位置
    for i in range(5):
        pname = request.form.get(f"pname_{i}", "").strip()
        psteam = request.form.get(f"psteam_{i}", "").strip()
        if psteam and (not psteam.isdigit() or len(psteam) != 17):
            conn.rollback()
            conn.close()
            flash(f"位置 {i + 1} 的 SteamID 格式不正确", "error")
            return redirect(url_for("event_detail", event_id=event_id))
        # 如果该位置是当前用户选的，关联 user_id
        slot_user_id = session["user_id"] if i == my_slot else None
        if slot_user_id:
            pname = user["username"]
            psteam = user["steam_id64"]
        conn.execute(
            """INSERT INTO event_registration_slots(registration_id, slot_index, user_id, player_name, steam_id, filled_by_creator)
            VALUES(?,?,?,?,?,?)""",
            (reg_id, i, slot_user_id, pname or f"位置{i + 1}", psteam or "", 1 if pname else 0),
        )

    conn.commit()
    conn.close()
    flash(f'报名成功！队伍"{team_name}"已提交，等待队友加入和管理员审批', "success")
    return redirect(url_for("event_detail", event_id=event_id))


@app.route("/events/<int:event_id>/join/<int:reg_id>/<int:slot>", methods=["POST"])
@csrf_required
def event_join_slot(event_id, reg_id, slot):
    """选手加入已有队伍的某个空位"""
    if "user_id" not in session:
        flash("请先登录后再加入队伍", "error")
        return redirect(url_for("user_login", next=url_for("event_detail", event_id=event_id)))

    if slot not in range(5):
        flash("该位置不存在", "error")
        return redirect(url_for("event_detail", event_id=event_id))

    conn = get_db()
    user = conn.execute(
        "SELECT username, steam_id64 FROM users WHERE id=?", (session["user_id"],)
    ).fetchone()
    if not user or not user["steam_id64"]:
        conn.close()
        flash("加入队伍前请先绑定 Steam 账号", "error")
        return redirect(url_for("user_profile"))
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
        flash("该位置不存在", "error")
        return redirect(url_for("event_detail", event_id=event_id))
    if slot_row["user_id"]:
        conn.close()
        flash("该位置已被占用", "error")
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
        flash("该位置刚刚被其他选手加入，请选择其他位置", "error")
        return redirect(url_for("event_detail", event_id=event_id))
    conn.commit()
    conn.close()
    flash("加入成功！", "success")
    return redirect(url_for("event_detail", event_id=event_id))


@app.route("/events/<int:event_id>/leave/<int:reg_id>/<int:slot>", methods=["POST"])
@csrf_required
def event_leave_slot(event_id, reg_id, slot):
    """选手退出自己已加入的报名位置"""
    if "user_id" not in session:
        flash("请先登录后再退出位置", "error")
        return redirect(url_for("user_login", next=url_for("event_detail", event_id=event_id)))

    if slot not in range(5):
        flash("该位置不存在", "error")
        return redirect(url_for("event_detail", event_id=event_id))

    conn = get_db()
    slot_row = conn.execute(
        """
        SELECT s.id, s.slot_index, r.team_name
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
        flash("只能退出你自己加入的位置，或该报名已不可修改", "error")
        return redirect(url_for("event_detail", event_id=event_id))

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
        flash("退出失败，请刷新页面后重试", "error")
        return redirect(url_for("event_detail", event_id=event_id))

    conn.commit()
    conn.close()
    flash(f'已退出 "{slot_row["team_name"]}" 的位置 {slot_row["slot_index"] + 1}', "success")
    return redirect(url_for("event_detail", event_id=event_id))


@app.route("/events/<int:event_id>/stats")
def event_stats(event_id):
    """赛事数据统计"""
    conn = get_db()
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not event:
        conn.close()
        return "赛事不存在", 404

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
