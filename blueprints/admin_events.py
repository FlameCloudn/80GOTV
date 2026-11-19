"""Admin event and bracket management pages."""

import json
import time
from contextlib import closing, nullcontext
from datetime import datetime, timedelta, timezone

from flask import flash, jsonify, redirect, render_template, request, session, url_for

from blueprints.admin import admin_bp
from models import get_db
from services.bracket_service import build_event_bracket, refresh_event_bracket
from services.match_service import (
    add_effective_event_status,
    supplement_temp_teams,
    update_match_slug,
)
from services.player_awards_service import (
    delete_event_awards,
    event_medal_selections,
    managed_event_medals,
    save_legacy_event_awards,
    save_managed_event_medals,
)
from site_core.awards.championship import award_championship, championship_status
from site_core.events import public as event_rosters
from site_core.events import registration as signup
from site_core.events.legacy_matches import has_unfinished_binding
from site_core.host import HostError, has_event_schema, is_managed_event, write
from utils.helpers import event_short_slug
from utils.web_helpers import admin_required as login_required
from utils.web_helpers import csrf_required

_UTC8 = timezone(timedelta(hours=8))

_RESERVE_ORIGIN_LABELS = {
    "independent_reserve": "独立候补",
    "individual": "个人报名未入队",
    "group": "分队调出队员",
}


def _epoch_iso(ts):
    if ts is None:
        return ""
    return datetime.fromtimestamp(int(ts), _UTC8).isoformat()


def _event_phase(event_status, archived_at, deadline, has_batch, active_entrants, confirmed_entrants, now):
    if archived_at is not None or event_status == "completed":
        return "archived", "已归档", "badge-done"
    if not has_batch:
        if now < deadline:
            return "signup", "报名中", "badge-green"
        return "due", "已截止 · 待分队", "badge-gold"
    if active_entrants > 0 and confirmed_entrants < active_entrants:
        return "formed_unconfirmed", "已分队 · 首五待确认", "badge-gold"
    return "initial_confirmed", "首五已确认", "badge-accent"


def _event_enable_blockers(conn, event, now):
    blockers = []
    if event["registration_open"]:
        blockers.append("已开放原报名开关")
    if (event["status"] or "upcoming") != "upcoming":
        blockers.append("赛事状态不是「即将开始」")
    if str(event["bracket_data"] or "").strip():
        blockers.append("已保存对阵图")
    if (
        add_effective_event_status(event, datetime.fromtimestamp(now))["effective_event_status"]
        == "completed"
    ):
        blockers.append("按赛期已达到「已结束」状态")
    event_id = event["id"]
    reg_cnt = conn.execute(
        "SELECT COUNT(*) FROM event_registrations WHERE event_id=?", (event_id,)
    ).fetchone()[0]
    if reg_cnt:
        blockers.append(f"已有 {reg_cnt} 条旧队伍报名记录")
    ind_cnt = conn.execute(
        "SELECT COUNT(*) FROM event_individual_registrations WHERE event_id=?", (event_id,)
    ).fetchone()[0]
    if ind_cnt:
        blockers.append(f"已有 {ind_cnt} 条个人报名记录")
    match_cnt = conn.execute(
        "SELECT COUNT(*) FROM matches WHERE event_id=?", (event_id,)
    ).fetchone()[0]
    if match_cnt:
        blockers.append(f"已有 {match_cnt} 场比赛")
    award_cnt = conn.execute(
        """SELECT (SELECT COUNT(*) FROM event_champions WHERE event_id=?)
                + (SELECT COUNT(*) FROM player_medals WHERE event_id=?)""",
        (event_id, event_id),
    ).fetchone()[0]
    if award_cnt:
        blockers.append("已有赛后冠军或 MVP / EVP 荣誉记录")
    return blockers


def _event_registration_control(conn, event, now=None):
    """Read-only status summary for event forms and the roster workbench."""
    now = int(time.time()) if now is None else now
    if not has_event_schema(conn):
        return {"schema_ready": False, "enabled": False, "can_enable": False, "blockers": []}
    event_id = event["id"]
    control = conn.execute(
        """SELECT c.*, b.formed_at, b.formation_revision
           FROM event_registration_control c
           LEFT JOIN event_formation_batches b USING(event_id)
           WHERE c.event_id=?""",
        (event_id,),
    ).fetchone()
    if control is None:
        blockers = _event_enable_blockers(conn, event, now)
        return {
            "schema_ready": True,
            "enabled": False,
            "can_enable": not blockers,
            "blockers": blockers,
        }
    counts = conn.execute(
        """SELECT COUNT(DISTINCT CASE WHEN g.archived_at IS NULL THEN e.event_entrant_id END) AS active_entrants,
                  COUNT(DISTINCT CASE WHEN g.archived_at IS NULL AND i.event_entrant_id IS NOT NULL THEN e.event_entrant_id END) AS confirmed_entrants
           FROM event_entrants e
           JOIN event_registration_groups g USING(event_id, registration_id)
           LEFT JOIN event_initial_rosters i USING(event_entrant_id)
           WHERE e.event_id=?""",
        (event_id,),
    ).fetchone()
    active_entrants = counts["active_entrants"] if counts else 0
    confirmed_entrants = counts["confirmed_entrants"] if counts else 0
    has_batch = control["formed_at"] is not None
    phase, phase_label, phase_badge = _event_phase(
        event["status"],
        control["archived_at"],
        control["registration_deadline"],
        has_batch,
        active_entrants,
        confirmed_entrants,
        now,
    )
    legacy_writes = bool(
        conn.execute(
            """SELECT 1 FROM matches WHERE event_id=? UNION ALL
               SELECT 1 FROM event_registrations WHERE event_id=? LIMIT 1""",
            (event_id, event_id),
        ).fetchone()
    )
    can_disable = control["first_write_at"] is None and not legacy_writes
    disable_block_reason = ""
    if not can_disable:
        disable_block_reason = (
            "本届已有比赛或报名记录，不能退回原报名流程"
            if legacy_writes
            else "本届已有切换后的业务写入记录，不能退回原报名流程"
        )
    return {
        "schema_ready": True,
        "enabled": True,
        "deadline": control["registration_deadline"],
        "deadline_iso": _epoch_iso(control["registration_deadline"]),
        "is_due": now >= control["registration_deadline"],
        "enabled_at": control["enabled_at"],
        "enabled_at_iso": _epoch_iso(control["enabled_at"]),
        "archived_at": control["archived_at"],
        "archived_at_iso": _epoch_iso(control["archived_at"]),
        "first_write_at": control["first_write_at"],
        "formed": has_batch,
        "formed_at": control["formed_at"],
        "formed_at_iso": _epoch_iso(control["formed_at"]),
        "formation_revision": control["formation_revision"],
        "active_entrants": active_entrants,
        "confirmed_entrants": confirmed_entrants,
        "phase": phase,
        "phase_label": phase_label,
        "phase_badge": phase_badge,
        "can_disable": can_disable,
        "disable_block_reason": disable_block_reason,
    }


def _admin_events_control_map(conn, now=None):
    if not has_event_schema(conn):
        return {}
    now = int(time.time()) if now is None else now
    rows = conn.execute(
        """SELECT c.event_id, c.registration_deadline, c.archived_at,
                  b.formed_at, ev.status AS event_status,
                  COUNT(DISTINCT CASE WHEN g.archived_at IS NULL THEN e.event_entrant_id END) AS active_entrants,
                  COUNT(DISTINCT CASE WHEN g.archived_at IS NULL AND i.event_entrant_id IS NOT NULL THEN e.event_entrant_id END) AS confirmed_entrants
           FROM event_registration_control c
           JOIN events ev ON ev.id=c.event_id
           LEFT JOIN event_formation_batches b USING(event_id)
           LEFT JOIN event_entrants e ON e.event_id=c.event_id
           LEFT JOIN event_registration_groups g ON g.event_id=e.event_id AND g.registration_id=e.registration_id
           LEFT JOIN event_initial_rosters i ON i.event_entrant_id=e.event_entrant_id
           GROUP BY c.event_id"""
    ).fetchall()
    result = {}
    for r in rows:
        phase, phase_label, phase_badge = _event_phase(
            r["event_status"],
            r["archived_at"],
            r["registration_deadline"],
            r["formed_at"] is not None,
            r["active_entrants"],
            r["confirmed_entrants"],
            now,
        )
        result[r["event_id"]] = {
            "enabled": True,
            "deadline": r["registration_deadline"],
            "deadline_iso": _epoch_iso(r["registration_deadline"]),
            "is_due": now >= r["registration_deadline"],
            "phase": phase,
            "phase_label": phase_label,
            "phase_badge": phase_badge,
        }
    return result


def _event_form_values(event=None):
    short_name = request.form.get("short_name", "").strip()
    name = request.form.get("name", "").strip()
    slug = event_short_slug(short_name)
    if event is not None and short_name == event["short_name"] and event["slug"]:
        slug = event["slug"]  # 修改描述等无关字段时，不重写已经发布的历史网址。
    status = request.form.get("status", "upcoming") if event is not None else "upcoming"
    registration_open = (
        1 if request.form.get("registration_open") == "1" and status != "completed" else 0
    )
    return (
        name,
        short_name,
        slug,
        request.form.get("description", "").strip(),
        request.form.get("start_date", "").strip(),
        request.form.get("end_date", "").strip(),
        request.form.get("format", "").strip(),
        status,
        request.form.get("stream_url", "").strip() or None,
        registration_open,
    )


def _form_number(raw, *, minimum=1):
    value = str(raw)
    if (
        not value.isascii()
        or not value.isdecimal()
        or len(value) > 19
        or not minimum <= int(value) <= 2**63 - 1
    ):
        raise HostError("编号、版本或时间格式不正确", 400)
    return int(value)


@admin_bp.get("/events/<int:event_id>/registration-control")
@login_required
def admin_registration_control(event_id):
    with closing(get_db()) as conn:
        if not has_event_schema(conn):
            return jsonify(success=False, error="此数据库未开放赛前托管"), 409
        conn.execute("BEGIN")
        try:
            signup.require_admin(conn, session.get("admin_id"))
        except HostError as exc:
            return jsonify(success=False, error=str(exc)), exc.status
        state = conn.execute(
            """SELECT c.*,b.formation_revision,b.formed_at FROM event_registration_control c
            LEFT JOIN event_formation_batches b USING(event_id) WHERE c.event_id=?""",
            (event_id,),
        ).fetchone()
        if state is None:
            return jsonify(success=False, error="本届尚未启用"), 404
        entrants = [
            event_rosters.roster(conn, event_id, r[0])
            for r in conn.execute(
                "SELECT event_entrant_id FROM event_entrants WHERE event_id=? ORDER BY event_entrant_id",
                (event_id,),
            )
        ]
        candidates = [
            dict(r)
            for r in conn.execute(
                """SELECT c.player_id,c.assigned_entrant_id,
            e.registration_origin,e.preferred_registration_id FROM event_reserve_candidates c JOIN event_signup_entries e
            USING(event_id,player_id) WHERE event_id=? AND withdrawn_at IS NULL ORDER BY c.player_id""",
                (event_id,),
            )
        ]
        unverified = [dict(r) for r in conn.execute("""SELECT s.registration_id,s.roster_slot,
            s.display_label,s.steam_id FROM event_signup_reservations s JOIN event_registration_groups g
            USING(registration_id) WHERE g.event_id=? ORDER BY s.registration_id,s.roster_slot""", (event_id,))]
        return jsonify(**dict(state), entrants=entrants, reserve_candidates=candidates, unverified_reservations=unverified)


@admin_bp.post("/events/<int:event_id>/registration-control/<action>")
@csrf_required
@login_required
def admin_registration_action(event_id, action):
    return _registration_action(event_id,action)


def _registration_action(event_id, action):
    body = request.get_json(silent=True) if request.is_json else request.form.to_dict()
    if not isinstance(body, dict):
        return jsonify(success=False, error="请求需要有效的表单或 JSON 对象"), 400
    try:
        with closing(get_db()) as conn, (nullcontext() if action=="form-due" else write(conn)):
            admin = session.get("admin_id")
            signup.require_admin(conn, admin)
            now = int(time.time())
            common = dict(admin_id=admin, now=now)
            reason = body.get("reason", "")
            if not isinstance(reason, str):
                raise HostError("理由必须是文字", 400)

            def number(key):
                return _form_number(body.get(key))

            def structured(key, kind):
                value = body.get(key, {} if kind is dict else None)
                if not request.is_json and isinstance(value, str):
                    try:
                        value = json.loads(value)
                    except ValueError:
                        raise HostError("名单或协商资料格式不正确", 400) from None
                if not isinstance(value, kind):
                    raise HostError("名单或协商资料格式不正确", 400)
                return value

            def ids(value):
                if not isinstance(value, list) or not value:
                    raise HostError("请选择非空名单", 400)
                return [_form_number(x) for x in value]

            result = {"event_id": event_id}
            if action == "enable":
                signup.enable_event(conn, event_id, number("registration_deadline"), **common)
            elif action == "disable":
                signup.disable_unused_event(conn, event_id, **common)
            elif action == "archive-team":
                if "registration_id" in body and "event_entrant_id" not in body:
                    reg = number("registration_id")
                elif "event_entrant_id" in body and "registration_id" not in body:
                    reg = event_rosters.roster(conn, event_id, number("event_entrant_id"))[
                        "registration_id"
                    ]
                else:
                    raise HostError("请提供本届的一个报名号或参赛身份", 400)
                result = event_rosters.archive_team(conn, event_id, reg, reason=reason, **common)
            elif action == "form-due":
                result = event_rosters.process_due_event(conn,event_id,admin_id=admin)
            elif action == "archive":
                signup.archive_event(conn, event_id, admin_id=admin, now=now)
            elif action == "link-club":
                signup.link_club(
                    conn, event_id, number("registration_id"), number("club_id"), admin_id=admin, now=now
                )
            elif action == "review-reservation":
                slot = _form_number(body.get("roster_slot"), minimum=0)
                if slot > 4:
                    raise HostError("位置须为 0 至 4", 400)
                account = body.get("verified_account_id")
                signup.review_reservation(
                    conn,
                    event_id,
                    number("registration_id"),
                    slot,
                    _form_number(account) if account not in (None, "") else None,
                    reason=reason,
                    **common,
                )
            elif action == "confirm-initial":
                if set(body) - {
                    "registration_action",
                    "csrf_token",
                    "event_entrant_ids",
                    "expected_revision",
                }:
                    raise HostError("只能确认该版本当前的五人，不能同时更改名单", 400)
                result = event_rosters.confirm_initial_rosters(
                    conn,
                    event_id,
                    ids(structured("event_entrant_ids", list)),
                    expected_revision=number("expected_revision"),
                    **common,
                )
            elif action == "adjust-formation":
                assignments = {
                    _form_number(k): ids(v) for k, v in structured("assignments", dict).items()
                }
                result = event_rosters.adjust_formation(
                    conn,
                    event_id,
                    assignments,
                    expected_revision=number("expected_revision"),
                    reason=reason,
                    **common,
                )
            elif action == "assign-reserve":
                excluded = {
                    _form_number(k): v for k, v in structured("excluded_candidates", dict).items()
                }
                result = event_rosters.assign_reserve(
                    conn,
                    event_id,
                    number("event_entrant_id"),
                    number("player_id"),
                    excluded_candidates=excluded,
                    expected_revision=number("expected_revision"),
                    reason=reason,
                    **common,
                )
            elif action == "replace-before-series":
                result = event_rosters.replace_before_series(
                    conn,
                    event_id,
                    number("event_entrant_id"),
                    number("outgoing_player_id"),
                    number("incoming_player_id"),
                    expected_revision=number("expected_revision"),
                    reason=reason,
                    **common,
                )
            else:
                raise HostError("未识别的赛事操作", 404)
    except HostError as exc:
        return jsonify(success=False, error=str(exc)), exc.status
    return jsonify(result)


def _event_validation_error(conn, values, exclude_id=None):
    name, short_name, slug, _, start_date, end_date, _, status, _, _ = values
    if not name or not short_name:
        return "赛事名和简称不能为空"
    if not slug:
        return "赛事简称至少需要一个汉字、字母或数字"
    if not start_date or not end_date:
        return "开始时间和结束时间不能为空"
    if end_date < start_date:
        return "结束时间不能早于开始时间"
    if status not in ("upcoming", "ongoing", "completed"):
        return "赛事状态无效"
    for column, value, message in (
        ("name", name, "已存在同名赛事"),
        ("short_name", short_name, "已存在相同简称的赛事"),
        ("slug", slug, "该网址名称已被其他赛事使用"),
    ):
        sql = f"SELECT id FROM events WHERE LOWER(TRIM({column}))=LOWER(TRIM(?))"
        params = [value]
        if exclude_id is not None:
            sql += " AND id<>?"
            params.append(exclude_id)
        if conn.execute(sql, params).fetchone():
            return message
    alias = conn.execute("SELECT event_id FROM event_slug_aliases WHERE slug=?", (slug,)).fetchone()
    if alias and (exclude_id is None or alias["event_id"] != exclude_id):
        return "该网址名称是其他赛事使用过的旧地址"
    return None


def _event_dict(values, event_id=None):
    keys = (
        "name",
        "short_name",
        "slug",
        "description",
        "start_date",
        "end_date",
        "format",
        "status",
        "stream_url",
        "registration_open",
    )
    result: dict[str, object] = dict(zip(keys, values))
    if event_id is not None:
        result["id"] = event_id
    return result


def _submit_event_awards(conn, event_id):
    champion_team_id = request.form.get("champion_team_id", "")
    mvp_player_id = request.form.get("mvp_player_id", "")
    save_legacy_event_awards(
        conn,
        event_id,
        champion_team_id=_form_number(champion_team_id) if champion_team_id else None,
        mvp_player_id=_form_number(mvp_player_id) if mvp_player_id else None,
        evp_player_ids=tuple(
            _form_number(player_id)
            for player_id in request.form.getlist("evp_player_ids")
            if player_id
        ),
    )


def _event_award_options(conn, event_id):
    champion_team = conn.execute(
        "SELECT t.* FROM event_champions ec JOIN teams t ON ec.team_id=t.id WHERE ec.event_id=?",
        (event_id,),
    ).fetchone()
    teams = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
    players = conn.execute("""SELECT p.*, t.name AS team_name
        FROM players p LEFT JOIN teams t ON p.team_id=t.id ORDER BY p.nickname""").fetchall()
    mvp_player, evp_players = event_medal_selections(conn, event_id)
    return teams, players, champion_team, mvp_player, evp_players


def _build_reservation_rows(conn, event_id):
    rows = conn.execute(
        """SELECT s.registration_id, s.roster_slot, s.display_label, s.steam_id,
                  r.team_name
           FROM event_signup_reservations s
           JOIN event_registration_groups g USING(registration_id)
           JOIN event_registrations r ON r.id=g.registration_id
           WHERE g.event_id=?
           ORDER BY s.registration_id, s.roster_slot""",
        (event_id,),
    ).fetchall()
    used_accounts = {
        r[0]
        for r in conn.execute(
            "SELECT account_id FROM event_signup_entries WHERE event_id=?", (event_id,)
        )
    }
    used_players = {
        r[0]
        for r in conn.execute(
            "SELECT player_id FROM event_signup_entries WHERE event_id=?", (event_id,)
        )
    }
    result = []
    for row in rows:
        item = dict(row)
        steam = (row["steam_id"] or "").strip()
        matched_account = None
        claim_block_reason = ""
        if not steam:
            claim_block_reason = "预留未填写 Steam ID，只能释放"
        else:
            users = conn.execute(
                "SELECT id, username, group_username, approval_status, is_placeholder FROM users WHERE steam_id64=? LIMIT 2",
                (steam,),
            ).fetchall()
            players = conn.execute(
                "SELECT id, nickname FROM players WHERE steam_id=? LIMIT 2", (steam,)
            ).fetchall()
            if not users:
                claim_block_reason = "未找到该 Steam ID 对应的注册账号"
            elif len(users) > 1:
                claim_block_reason = "该 Steam ID 绑定了多个账号，无法自动匹配"
            else:
                user = users[0]
                if user["approval_status"] != "approved" or user["is_placeholder"]:
                    claim_block_reason = "对应账号尚未通过审核（或为占位账号）"
                elif len(players) != 1:
                    claim_block_reason = "该 Steam ID 缺少唯一选手档案"
                elif user["id"] in used_accounts or players[0]["id"] in used_players:
                    claim_block_reason = "对应账号或选手已参加本届报名"
                else:
                    matched_account = {
                        "id": user["id"],
                        "username": user["username"],
                        "group_username": user["group_username"] or "",
                        "player_id": players[0]["id"],
                        "player_nickname": players[0]["nickname"] or "",
                    }
        item["matched_account"] = matched_account
        item["claim_block_reason"] = claim_block_reason
        result.append(item)
    return result


def _event_roster_context(conn, event, control):
    event_id = event["id"]
    now = int(time.time())
    groups = conn.execute(
        """SELECT g.registration_id, g.club_id, g.group_origin, g.archived_at, g.archive_reason,
                  r.team_name, r.team_logo, r.status AS reg_status, r.created_at,
                  t.name AS club_name
           FROM event_registration_groups g
           JOIN event_registrations r ON r.id=g.registration_id
           LEFT JOIN teams t ON t.id=g.club_id
           WHERE g.event_id=?
           ORDER BY r.created_at DESC, g.registration_id""",
        (event_id,),
    ).fetchall()
    entries = conn.execute(
        """SELECT e.registration_entry_id, e.account_id, e.player_id, e.registration_origin,
                  e.registration_id, e.roster_slot, e.preferred_registration_id, e.created_at,
                  p.nickname, p.group_username_override, p.steam_id,
                  u.username
           FROM event_signup_entries e
           JOIN players p ON p.id=e.player_id
           JOIN users u ON u.id=e.account_id
           WHERE e.event_id=?
           ORDER BY e.created_at, e.registration_entry_id""",
        (event_id,),
    ).fetchall()
    reservations = _build_reservation_rows(conn, event_id)

    group_members = {}
    individual_entries = []
    independent_reserve_entries = []
    for e in entries:
        origin = e["registration_origin"]
        if origin == "group":
            group_members.setdefault(e["registration_id"], []).append(dict(e))
        elif origin == "independent_reserve":
            independent_reserve_entries.append(dict(e))
        else:
            individual_entries.append(dict(e))

    registered_groups = [dict(g) for g in groups if g["group_origin"] == "registered"]
    res_by_group = {}
    for res in reservations:
        res_by_group.setdefault(res["registration_id"], []).append(res)
    for g in registered_groups:
        g["members"] = sorted(group_members.get(g["registration_id"], []), key=lambda x: x["roster_slot"])
        g["reservations"] = res_by_group.get(g["registration_id"], [])
        g["claimed_count"] = len(g["members"])

    incomplete_groups = [g for g in registered_groups if g["claimed_count"] < 5]
    vacancies = sum(5 - g["claimed_count"] for g in incomplete_groups)
    individual_count = len(individual_entries)
    can_form_due = (
        not control["formed"]
        and not control["archived_at"]
        and control["is_due"]
        and len(reservations) == 0
        and individual_count >= vacancies
    )
    precheck = {
        "group_count": len(registered_groups),
        "incomplete_group_count": len(incomplete_groups),
        "vacancies": vacancies,
        "individual_count": individual_count,
        "independent_reserve_count": len(independent_reserve_entries),
        "unverified_count": len(reservations),
        "enough_individuals": individual_count >= vacancies,
        "can_form_due": can_form_due,
        "registered_groups": registered_groups,
    }

    entrants = []
    reserve_candidates = []
    roster_payload = {
        "event_id": event_id,
        "revision": control.get("formation_revision") or 0,
        "archived": bool(control.get("archived_at") or event["status"] == "completed"),
        "entrants": [],
        "reserves": [],
        "pool_candidates": [],
    }
    if control["formed"]:
        group_map = {g["registration_id"]: dict(g) for g in groups}
        admins_map = {
            r["id"]: r["username"]
            for r in conn.execute("SELECT id, username FROM admins").fetchall()
        }
        entrant_rows = conn.execute(
            "SELECT event_entrant_id FROM event_entrants WHERE event_id=? ORDER BY event_entrant_id",
            (event_id,),
        ).fetchall()
        candidate_rows = conn.execute(
            """SELECT c.player_id, c.assigned_entrant_id,
                      e.registration_origin, e.preferred_registration_id, e.created_at,
                      p.nickname, p.group_username_override, p.steam_id,
                      pr.team_name AS preferred_team_name,
                      ar.team_name AS assigned_team_name
               FROM event_reserve_candidates c
               JOIN event_signup_entries e USING(event_id, player_id)
               JOIN players p ON p.id=c.player_id
               LEFT JOIN event_registrations pr ON pr.id=e.preferred_registration_id
               LEFT JOIN event_entrants ae ON ae.event_entrant_id=c.assigned_entrant_id
               LEFT JOIN event_registrations ar ON ar.id=ae.registration_id
               WHERE c.event_id=? AND c.withdrawn_at IS NULL
               ORDER BY CASE e.registration_origin
                            WHEN 'independent_reserve' THEN 0
                            WHEN 'individual' THEN 1
                            ELSE 2
                        END,
                        c.player_id""",
            (event_id,),
        ).fetchall()
        reserves_by_entrant = {}
        for c in candidate_rows:
            item = dict(c)
            item["origin_label"] = _RESERVE_ORIGIN_LABELS.get(
                c["registration_origin"], c["registration_origin"]
            )
            item["created_at_iso"] = _epoch_iso(c["created_at"])
            item["is_independent"] = c["registration_origin"] == "independent_reserve"
            reserve_candidates.append(item)
            if c["assigned_entrant_id"] is not None:
                reserves_by_entrant.setdefault(c["assigned_entrant_id"], []).append(item)

        player_ids = set()
        raw_rosters = []
        for (eid,) in entrant_rows:
            r = event_rosters.roster(conn, event_id, eid)
            raw_rosters.append(r)
            player_ids.update(r["initial_player_ids"])
            player_ids.update(r["current_player_ids"])
            for ch in r["changes"]:
                player_ids.add(ch["outgoing_player_id"])
                player_ids.add(ch["incoming_player_id"])
        players_map = {}
        if player_ids:
            placeholders = ",".join("?" for _ in player_ids)
            for p in conn.execute(
                f"SELECT id, nickname, group_username_override, steam_id FROM players WHERE id IN ({placeholders})",
                tuple(player_ids),
            ):
                players_map[p["id"]] = dict(p)

        for r in raw_rosters:
            eid = r["event_entrant_id"]
            reg_id = r["registration_id"]
            grp = group_map.get(reg_id, {})
            initial_set = set(r["initial_player_ids"])
            current_set = set(r["current_player_ids"])
            initial_players = [
                {
                    **(players_map.get(pid) or {"id": pid, "nickname": f"#{pid}"}),
                    "swapped_out": pid not in current_set,
                }
                for pid in r["initial_player_ids"]
            ]
            current_players = [
                {
                    **(players_map.get(pid) or {"id": pid, "nickname": f"#{pid}"}),
                    "is_added_sub": bool(r["is_frozen"] and pid not in initial_set),
                }
                for pid in r["current_player_ids"]
            ]
            changes = [
                {
                    **ch,
                    "changed_at_iso": _epoch_iso(ch["changed_at"]),
                    "admin_name": admins_map.get(ch["admin_id"], f"#{ch['admin_id']}"),
                    "outgoing_nickname": (players_map.get(ch["outgoing_player_id"]) or {}).get(
                        "nickname", f"#{ch['outgoing_player_id']}"
                    ),
                    "incoming_nickname": (players_map.get(ch["incoming_player_id"]) or {}).get(
                        "nickname", f"#{ch['incoming_player_id']}"
                    ),
                }
                for ch in r["changes"]
            ]
            team_reserves = reserves_by_entrant.get(eid, [])
            item = {
                **r,
                "team_name": grp.get("team_name") or f"参赛队 #{eid}",
                "club_id": grp.get("club_id"),
                "club_name": grp.get("club_name") or "",
                "group_origin": grp.get("group_origin") or "registered",
                "origin_label": "自动分队" if grp.get("group_origin") == "formed" else "报名队",
                "team_archived": r["team_archived_at"] is not None,
                "team_archived_iso": _epoch_iso(r["team_archived_at"]),
                "archive_reason": grp.get("archive_reason") or "",
                "confirmed_at_iso": _epoch_iso(r["confirmed_at"]),
                "confirmed_by_name": admins_map.get(r["confirmed_by"], "") if r["confirmed_by"] else "",
                "initial_players": initial_players,
                "current_players": current_players,
                "kept_initial_count": len(initial_set & current_set) if r["is_frozen"] else None,
                "assigned_reserves": team_reserves,
                "changes": changes,
                "has_unfinished_match": has_unfinished_binding(conn, event_id, reg_id, eid),
            }
            entrants.append(item)
            roster_payload["entrants"].append(
                {
                    "id": eid,
                    "name": item["team_name"],
                    "is_frozen": item["is_frozen"],
                    "team_archived": item["team_archived"],
                    "initial_player_ids": r["initial_player_ids"],
                    "current_players": [
                        {"id": p["id"], "nickname": p["nickname"]} for p in current_players
                    ],
                    "assigned_reserves": [
                        {"id": c["player_id"], "nickname": c["nickname"], "origin_label": c["origin_label"]}
                        for c in team_reserves
                    ],
                }
            )
        roster_payload["reserves"] = [
            {
                "id": c["player_id"],
                "nickname": c["nickname"],
                "origin": c["registration_origin"],
                "origin_label": c["origin_label"],
                "is_independent": c["is_independent"],
                "assigned_entrant_id": c["assigned_entrant_id"],
            }
            for c in reserve_candidates
        ]
        roster_payload["pool_candidates"] = [
            {"id": c["player_id"], "nickname": c["nickname"], "origin_label": c["origin_label"]}
            for c in reserve_candidates
            if c["assigned_entrant_id"] is None and c["registration_origin"] in ("group", "individual")
        ]

    clubs = [
        dict(r)
        for r in conn.execute("SELECT id, name, short_name FROM teams ORDER BY name").fetchall()
    ]
    return {
        "now": now,
        "precheck": precheck,
        "reservations": reservations,
        "entrants": entrants,
        "reserve_candidates": reserve_candidates,
        "roster_payload": roster_payload,
        "clubs": clubs,
    }


@admin_bp.route("/events")
@login_required
def admin_events():
    conn = get_db()
    events = conn.execute("SELECT * FROM events ORDER BY start_date DESC").fetchall()
    control_map = _admin_events_control_map(conn)
    events = [
        {**add_effective_event_status(e), "registration_control": control_map.get(e["id"])}
        for e in events
    ]
    conn.close()
    return render_template("admin/events.html", events=events)


@admin_bp.route("/events/add", methods=["GET", "POST"])
@csrf_required
@login_required
def admin_events_add():
    if request.method == "POST":
        conn = get_db()
        schema_ready = has_event_schema(conn)
        values = _event_form_values()
        error = _event_validation_error(conn, values)
        if error:
            conn.close()
            flash(error, "error")
            return render_template(
                "admin/events_form.html",
                event=_event_dict(values),
                registration_control={"schema_ready": schema_ready, "enabled": False, "can_enable": True, "blockers": []},
            ), 400
        deadline = request.form.get("registration_deadline")
        cursor = conn.execute(
            """INSERT INTO events(name, short_name, slug, description, start_date, end_date, format, status, stream_url, registration_open)
                        VALUES(?,?,?,?,?,?,?,?,?,?)""",
            values if deadline is None else (*values[:-1], 0),
        )
        if deadline is not None:
            try:
                signup.enable_event(
                    conn,
                    cursor.lastrowid,
                    _form_number(deadline),
                    admin_id=session.get("admin_id"),
                    now=int(time.time()),
                )
            except HostError as exc:
                conn.rollback()
                conn.close()
                flash(str(exc), "error")
                return render_template(
                    "admin/events_form.html",
                    event=_event_dict(values),
                    registration_control={"schema_ready": schema_ready, "enabled": False, "can_enable": True, "blockers": []},
                ), exc.status
        conn.commit()
        conn.close()
        flash("赛事添加成功", "success")
        return redirect(url_for("admin.admin_events"))
    conn = get_db()
    schema_ready = has_event_schema(conn)
    conn.close()
    return render_template(
        "admin/events_form.html",
        event=None,
        registration_control={"schema_ready": schema_ready, "enabled": False, "can_enable": True, "blockers": []},
    )


@admin_bp.route("/events/edit/<int:event_id>", methods=["GET", "POST"])
@csrf_required
@login_required
def admin_events_edit(event_id):
    if request.method == "POST" and request.form.get("registration_action"):
        return _registration_action(event_id, request.form["registration_action"])
    conn = get_db()
    if request.method == "POST":
        conn.execute("BEGIN IMMEDIATE")
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not event:
        conn.close()
        return "赛事不存在", 404
    reg_control = _event_registration_control(conn, event)
    if request.method == "POST":
        values = _event_form_values(event)
        managed = is_managed_event(conn, event_id)
        award_fields = ("champion_team_id", "mvp_player_id", "evp_player_ids")
        submit_awards = any(field in request.form for field in award_fields)
        if managed:
            submit_awards = any(any(request.form.getlist(field)) for field in award_fields)
            if values[7] == "ongoing" or (
                event["status"] == "completed" and values[7] != "completed"
            ):
                conn.close()
                return "本届只办理赛前管理和归档，不能开赛或重新开放已归档赛事", 409
            values = (*values[:-1], event["registration_open"] if values[7] != "completed" else 0)
        error = _event_validation_error(conn, values, event_id)
        if not error and submit_awards:
            try:
                _submit_event_awards(conn, event_id)
            except HostError as exc:
                if exc.status != 400:
                    conn.close()
                    return exc.message, exc.status
                error = exc.message
        if error:
            teams, players, champion_team, mvp_player, evp_players = _event_award_options(
                conn, event_id
            )
            conn.close()
            flash(error, "error")
            return render_template(
                "admin/events_form.html",
                event=_event_dict(values, event_id),
                teams=teams,
                champion_team=champion_team,
                mvp_player=mvp_player,
                evp_players=evp_players,
                all_players=players,
                registration_control=reg_control,
            ), 400
        if event["slug"] and event["slug"] != values[2]:
            conn.execute(
                "INSERT OR IGNORE INTO event_slug_aliases(slug,event_id) VALUES(?,?)",
                (event["slug"], event_id),
            )
        conn.execute(
            """UPDATE events SET name=?, short_name=?, slug=?, description=?, start_date=?, end_date=?, format=?, status=?, stream_url=?, registration_open=?
                        WHERE id=?""",
            values + (event_id,),
        )
        if event["short_name"] != values[1]:
            for match in conn.execute("SELECT id FROM matches WHERE event_id=? ORDER BY id", (event_id,)).fetchall():
                update_match_slug(conn, match["id"])
        if managed and values[7] == "completed":
            signup.archive_event(
                conn, event_id, admin_id=session.get("admin_id"), now=int(time.time())
            )
        conn.commit()
        conn.close()
        flash("赛事更新成功", "success")
        return redirect(url_for("admin.admin_events"))
    teams, players, champion_team, mvp_player, evp_players = _event_award_options(conn, event_id)
    conn.close()
    return render_template(
        "admin/events_form.html",
        event=event,
        teams=teams,
        champion_team=champion_team,
        mvp_player=mvp_player,
        evp_players=evp_players,
        all_players=players,
        registration_control=reg_control,
    )


@admin_bp.get("/events/<int:event_id>/roster")
@login_required
def admin_event_roster(event_id):
    with closing(get_db()) as conn:
        event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        if not event:
            return "赛事不存在", 404
        if not has_event_schema(conn):
            flash("此数据库尚未开放赛前托管", "error")
            return redirect(url_for("admin.admin_events_edit", event_id=event_id))
        try:
            signup.require_admin(conn, session.get("admin_id"))
        except HostError as exc:
            flash(str(exc), "error")
            return redirect(url_for("admin.admin_events"))
        control = _event_registration_control(conn, event)
        if not control["enabled"]:
            flash("本届赛事尚未启用新报名管理", "error")
            return redirect(url_for("admin.admin_events_edit", event_id=event_id))
        ctx = _event_roster_context(conn, event, control)
        return render_template(
            "admin/event_roster.html",
            event=event,
            control=control,
            **ctx,
        )


@admin_bp.route("/events/<int:event_id>/operations/championship", methods=["GET", "POST"])
@csrf_required
@login_required
def managed_championship(event_id):
    with closing(get_db()) as conn:
        try:
            if request.method == "GET":
                conn.execute("BEGIN")
                return jsonify(ok=True, **championship_status(conn, event_id))
            body = request.get_json(silent=True)
            if not isinstance(body, dict):
                raise HostError("请提交已核对的决赛、正式结算和获奖五人", 400)
            match_id, settlement_id, players = (
                body.get("match_id"),
                body.get("settlement_id"),
                body.get("player_ids"),
            )
            if (
                not isinstance(players, list)
                or len(players) != 5
                or any(
                    type(value) is not int or not 1 <= value <= 2**63 - 1
                    for value in (match_id, settlement_id, *players)
                )
                or len(set(players)) != 5
            ):
                raise HostError("请提供有效的决赛、正式结算编号和五名不同的选手", 400)
            with write(conn):
                result = award_championship(
                    conn,
                    event_id,
                    match_id=match_id,
                    settlement_id=settlement_id,
                    player_ids=tuple(players),
                    admin_id=session["admin_id"],
                )
            return jsonify(ok=True, **result), 200 if result["duplicate"] else 201
        except HostError as exc:
            return jsonify(ok=False, error=exc.message), exc.status


@admin_bp.route("/events/<int:event_id>/operations/player-awards", methods=["GET", "POST"])
@csrf_required
@login_required
def managed_player_awards(event_id):
    with closing(get_db()) as conn:
        try:
            if request.method == "GET":
                conn.execute("BEGIN")
                return jsonify(ok=True, **managed_event_medals(conn, event_id))
            body = request.get_json(silent=True)
            if not isinstance(body, dict) or not {"mvp_player_id", "evp_player_ids"} <= body.keys():
                raise HostError("请明确提交赛事 MVP 和 EVP 名单", 400)
            mvp = body["mvp_player_id"]
            evps = body["evp_player_ids"]
            if not isinstance(evps, list) or any(
                type(value) is not int or not 1 <= value <= 2**63 - 1
                for value in ([*evps, mvp] if mvp is not None else evps)
            ):
                raise HostError("获奖人编号必须是正整数，EVP 须按公布顺序提交", 400)
            with write(conn):
                result = save_managed_event_medals(
                    conn, event_id, mvp_player_id=mvp, evp_player_ids=tuple(evps), admin_id=session["admin_id"],
                )
            return jsonify(ok=True, **result)
        except HostError as exc:
            return jsonify(ok=False, error=exc.message), exc.status


@admin_bp.route("/events/delete/<int:event_id>", methods=["POST"])
@csrf_required
@login_required
def admin_events_delete(event_id):
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if is_managed_event(conn, event_id):
            flash("本届报名与阵容需要保留，请使用赛事归档。", "error")
            return redirect(url_for("admin.admin_events"))
        event = conn.execute("SELECT id FROM events WHERE id=?", (event_id,)).fetchone()
        if not event:
            flash("赛事不存在", "error")
            return redirect(url_for("admin.admin_events"))
        references = conn.execute(
            """SELECT
                 (SELECT COUNT(*) FROM matches WHERE event_id=?) +
                 (SELECT COUNT(*) FROM event_registrations WHERE event_id=?) +
                 (SELECT COUNT(*) FROM event_individual_registrations WHERE event_id=?)""",
            (event_id, event_id, event_id),
        ).fetchone()[0]
        if references:
            flash("该赛事仍有比赛或报名数据，不能直接删除", "error")
            return redirect(url_for("admin.admin_events"))
        delete_event_awards(conn, event_id)
        conn.execute("DELETE FROM event_slug_aliases WHERE event_id=?", (event_id,))
        conn.execute("DELETE FROM events WHERE id=?", (event_id,))
        conn.commit()
        flash("赛事删除成功", "success")
    except Exception as e:
        conn.rollback()
        flash(f"删除失败：{str(e)}", "error")
    finally:
        conn.close()
    return redirect(url_for("admin.admin_events"))


def _event_bracket_matches(conn, event_id):
    matches = conn.execute(
        """SELECT m.*,
                  t1.name AS team1_name, t1.short_name AS t1s,
                  t2.name AS team2_name, t2.short_name AS t2s
        FROM matches m LEFT JOIN teams t1 ON m.team1_id=t1.id LEFT JOIN teams t2 ON m.team2_id=t2.id
        WHERE m.event_id=? AND m.status!='cancelled'
        ORDER BY CASE WHEN m.match_time IS NULL OR m.match_time='' THEN 1 ELSE 0 END,
                 m.match_time, m.id""",
        (event_id,),
    ).fetchall()
    result = []
    for match in matches:
        display = supplement_temp_teams(match, conn)
        # 只返回编辑器原有字段；阵容与报名资料仅用于补全对阵名称。
        item = {key: display[key] for key in (
            "id", "match_time", "bo_format", "team1_score", "team2_score",
            "status", "stage", "team1_id", "team2_id",
        )}
        for side in (1, 2):
            item[f"t{side}_name"] = display[f"team{side}_name"]
            item[f"t{side}_short_name"] = display[f"t{side}s"]
        result.append(item)
    return result


@admin_bp.route("/events/<int:event_id>/bracket", methods=["GET", "POST"])
@csrf_required
@login_required
def admin_event_bracket(event_id):
    conn = get_db()
    if request.method=="POST":
        conn.execute("BEGIN IMMEDIATE")
        if is_managed_event(conn,event_id):
            conn.close()
            return "本届尚未接管签表写入，请通过比赛管理安排赛前对阵",409
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not event:
        conn.close()
        return "赛事不存在", 404
    if request.method == "POST":
        bracket_data = request.form.get("bracket_data", "").strip()
        if bracket_data:
            try:
                parsed = json.loads(bracket_data)
                validated = refresh_event_bracket(conn, event_id, data=parsed)
                bracket_data = json.dumps(validated, ensure_ascii=False)
            except (ValueError, TypeError) as exc:
                conn.rollback()
                flash(f"对阵图保存失败：{exc}", "error")
                matches = _event_bracket_matches(conn, event_id)
                conn.close()
                return render_template(
                    "admin/event_bracket.html",
                    event=event,
                    bracket_data=bracket_data,
                    event_matches=[dict(row) for row in matches],
                ), 400
        conn.execute(
            "UPDATE events SET bracket_data=? WHERE id=?", (bracket_data or None, event_id)
        )
        conn.commit()
        conn.close()
        flash("对阵图保存成功", "success")
        return redirect(url_for("admin.admin_events"))
    matches = _event_bracket_matches(conn, event_id)
    if is_managed_event(conn, event_id):
        from services.bracket_service import get_bracket_links

        links = get_bracket_links(conn, event_id)
        entrants = [
            dict(r)
            for r in conn.execute(
                """SELECT ee.event_entrant_id, r.team_name, g.club_id, t.name AS club_name
                   FROM event_entrants ee
                   JOIN event_registration_groups g ON g.registration_id=ee.registration_id
                   JOIN event_registrations r ON r.id=g.registration_id
                   LEFT JOIN teams t ON t.id=g.club_id
                   WHERE ee.event_id=? ORDER BY ee.event_entrant_id""",
                (event_id,),
            ).fetchall()
        ]
        conn.close()
        return render_template(
            "admin/event_bracket_managed.html",
            event=event,
            event_matches=[dict(r) for r in matches],
            managed_links=links,
            entrants=entrants,
        )
    conn.close()
    return render_template(
        "admin/event_bracket.html",
        event=event,
        bracket_data=event["bracket_data"] or "",
        event_matches=[dict(r) for r in matches],
    )


@admin_bp.route("/events/<int:event_id>/bracket/api/teams")
@login_required
def bracket_api_teams(event_id):
    conn = get_db()
    teams = conn.execute(
        """SELECT DISTINCT t.* FROM teams t
        JOIN matches m ON (t.id=m.team1_id OR t.id=m.team2_id) WHERE m.event_id=?""",
        (event_id,),
    ).fetchall()
    all_teams = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
    conn.close()
    return {"event_teams": [dict(t) for t in teams], "all_teams": [dict(t) for t in all_teams]}


@admin_bp.route("/events/<int:event_id>/bracket/api/save", methods=["POST"])
@csrf_required
@login_required
def bracket_api_save(event_id):
    data = request.get_json(force=True, silent=True)
    if not data:
        return {"success": False, "error": "无效的 JSON"}, 400
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if is_managed_event(conn,event_id):
            return {"success":False,"error":"本届尚未接管自动签表，请通过比赛管理安排赛前对阵"},409
        saved = build_event_bracket(conn, event_id, data)
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        return {"success": False, "error": str(exc)}, 400
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {
        "success": True,
        "message": "对阵图与全部比赛已生成",
        "bracket": saved,
    }
