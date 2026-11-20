"""Read signup phase, blockers, roster and reserve workbench details."""

import time
from datetime import datetime, timedelta, timezone

from src.website.domains.events import roster_management as event_rosters
from src.website.domains.events.legacy_matches import has_unfinished_binding
from src.website.domains.events.status import add_effective_event_status
from src.website.runtime.host import has_event_schema
from src.website.web.localization import t as ui_message

_UTC8 = timezone(timedelta(hours=8))


_RESERVE_ORIGINS = {"independent_reserve", "individual", "group"}


def _epoch_iso(ts):
    if ts is None:
        return ""
    return datetime.fromtimestamp(int(ts), _UTC8).isoformat()


def _event_phase(
    event_status, archived_at, deadline, has_batch, active_entrants, confirmed_entrants, now
):
    if archived_at is not None or event_status == "completed":
        return "archived", ui_message("roster.phase.archived"), "badge-done"
    if not has_batch:
        if now < deadline:
            return "signup", ui_message("roster.phase.signup"), "badge-green"
        return "due", ui_message("roster.phase.due"), "badge-gold"
    if active_entrants > 0 and confirmed_entrants < active_entrants:
        return "formed_unconfirmed", ui_message("roster.phase.formed_unconfirmed"), "badge-gold"
    return "initial_confirmed", ui_message("roster.phase.initial_confirmed"), "badge-accent"


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
        g["members"] = sorted(
            group_members.get(g["registration_id"], []), key=lambda x: x["roster_slot"]
        )
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
            origin = c["registration_origin"]
            item["origin_label"] = (
                ui_message(f"roster.reserve.origin.{origin}")
                if origin in _RESERVE_ORIGINS
                else origin
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
                "origin_label": ui_message(
                    "roster.origin.formed"
                    if grp.get("group_origin") == "formed"
                    else "roster.origin.registered"
                ),
                "team_archived": r["team_archived_at"] is not None,
                "team_archived_iso": _epoch_iso(r["team_archived_at"]),
                "archive_reason": grp.get("archive_reason") or "",
                "confirmed_at_iso": _epoch_iso(r["confirmed_at"]),
                "confirmed_by_name": admins_map.get(r["confirmed_by"], "")
                if r["confirmed_by"]
                else "",
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
                        {
                            "id": c["player_id"],
                            "nickname": c["nickname"],
                            "origin_label": c["origin_label"],
                        }
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
            if c["assigned_entrant_id"] is None
            and c["registration_origin"] in ("group", "individual")
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
