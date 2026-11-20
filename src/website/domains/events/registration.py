"""Registration intent lives here; forming a team or recording an appearance is a different fact."""

import re
import sqlite3
from collections.abc import Mapping
from datetime import datetime

from src.website.runtime.host import HostError, has_event_schema


def require_admin(conn, admin_id):
    if not admin_id or not conn.execute("SELECT 1 FROM admins WHERE id=?", (admin_id,)).fetchone():
        raise HostError("需要赛事管理员权限", 403, code="admin_required")


def enable_event(conn, event_id, deadline, *, admin_id, now):
    require_admin(conn, admin_id)
    if not has_event_schema(conn):
        raise HostError("此数据库尚未安装本机 SQLite 赛前结构，不能启用")
    row = conn.execute(
        "SELECT registration_open,status,start_date,end_date,bracket_data FROM events WHERE id=?",
        (event_id,),
    ).fetchone()
    if row is None:
        raise HostError("赛事不存在", 404)
    if type(deadline) is not int or not now < deadline <= 253402300799:
        raise HostError("请填写有效的未来报名截止时间（UTC 秒）", 400)
    previous = conn.execute(
        "SELECT registration_deadline FROM event_registration_control WHERE event_id=?", (event_id,)
    ).fetchone()
    if previous:
        if previous[0] != deadline:
            raise HostError("本届已经启用，不能覆盖原截止时间")
        return
    from src.website.domains.events.status import add_effective_event_status

    if (
        row["registration_open"]
        or (row["status"] or "upcoming") != "upcoming"
        or str(row["bracket_data"] or "").strip()
        or add_effective_event_status(row, datetime.fromtimestamp(now))["effective_event_status"]
        == "completed"
        or conn.execute(
            """SELECT 1 FROM event_registrations WHERE event_id=? UNION ALL
                SELECT 1 FROM event_individual_registrations WHERE event_id=? UNION ALL
                SELECT 1 FROM matches WHERE event_id=? UNION ALL
                SELECT 1 FROM event_champions WHERE event_id=? UNION ALL
                SELECT 1 FROM player_medals WHERE event_id=? LIMIT 1""",
            (event_id,) * 5,
        ).fetchone()
    ):
        raise HostError("只能接管尚未开放且没有旧报名、比赛、签表或奖项的新赛事")
    conn.execute(
        """INSERT INTO event_registration_control(event_id,registration_deadline,enabled_by,enabled_at)
                 VALUES(?,?,?,?)""",
        (event_id, deadline, admin_id, now),
    )
    conn.execute("UPDATE events SET registration_open=1 WHERE id=?", (event_id,))


def _open_event(conn, event_id: int, now: int, *, reserves=False):
    event = conn.execute(
        """SELECT ee.*,e.id,e.slug,e.start_date,e.end_date,e.status FROM event_registration_control ee JOIN events e ON e.id=ee.event_id
                            WHERE ee.event_id=?""",
        (event_id,),
    ).fetchone()
    if event is None:
        raise HostError("赛事未启用本届报名管理", 404, code="managed_not_enabled")
    from src.website.domains.events.status import add_effective_event_status

    if (
        event["archived_at"] is not None
        or event["status"] == "completed"
        or add_effective_event_status(event, datetime.fromtimestamp(now))["effective_event_status"]
        == "completed"
    ):
        raise HostError("赛事已经结束，不能变更报名", code="event_ended")
    if not reserves and (
        now >= event["registration_deadline"]
        or conn.execute(
            "SELECT 1 FROM event_formation_batches WHERE event_id=?", (event_id,)
        ).fetchone()
    ):
        raise HostError("正式报名已截止", code="signup_closed")
    return event


def active_event(conn, event_id: int, now: int):
    return _open_event(conn, event_id, now, reserves=True)


def disable_unused_event(conn, event_id, *, admin_id, now):
    require_admin(conn, admin_id)
    control = conn.execute(
        "SELECT first_write_at FROM event_registration_control WHERE event_id=?", (event_id,)
    ).fetchone()
    if control is None:
        raise HostError("本届未启用报名管理", 404)
    if (
        control[0] is not None
        or conn.execute(
            """SELECT 1 FROM matches WHERE event_id=? UNION ALL
         SELECT 1 FROM event_registrations WHERE event_id=? LIMIT 1""",
            (event_id, event_id),
        ).fetchone()
    ):
        raise HostError("本届已有切换后的业务记录，不能退回旧写入")
    conn.execute("DELETE FROM event_registration_control WHERE event_id=?", (event_id,))
    conn.execute("UPDATE events SET registration_open=0 WHERE id=?", (event_id,))


def eligible_player(conn, account_id: int):
    user = conn.execute(
        "SELECT approval_status,is_placeholder,steam_id64 FROM users WHERE id=?", (account_id,)
    ).fetchone()
    if user is None or user["approval_status"] != "approved" or user["is_placeholder"]:
        raise HostError("请使用通过审核的选手账号报名", 403, code="account_not_approved")
    steam = (user["steam_id64"] or "").strip()
    if not steam:
        raise HostError("请先绑定 Steam 账号", 400, code="steam_required")
    if (
        len(conn.execute("SELECT id FROM users WHERE steam_id64=? LIMIT 2", (steam,)).fetchall())
        != 1
    ):
        raise HostError(
            "Steam 绑定匹配多个账号，需要管理员核实身份", code="steam_multiple_accounts"
        )
    players = conn.execute("SELECT id FROM players WHERE steam_id=? LIMIT 2", (steam,)).fetchall()
    if len(players) != 1:
        raise HostError(
            "Steam 绑定没有唯一的选手档案，需要管理员核实身份", code="steam_no_unique_player"
        )
    return players[0]["id"], steam


def _group(conn, event_id: int, group_id: int):
    group = conn.execute(
        "SELECT g.*,r.creator_user_id AS captain_account_id,r.team_logo AS logo FROM event_registration_groups g JOIN event_registrations r ON r.id=g.registration_id WHERE g.event_id=? AND g.registration_id=?",
        (event_id, group_id),
    ).fetchone()
    if group is None:
        raise HostError("该报名队不属于当前赛事", 404, code="group_not_in_event")
    return group


def _captain(
    conn, event_id: int, group_id: int, account_id: int | None, admin_id: int | None = None
):
    group = _group(conn, event_id, group_id)
    if admin_id is not None:
        require_admin(conn, admin_id)
    elif account_id is None or group["captain_account_id"] != account_id:
        raise HostError("只有本队队长可以执行此操作", 403, code="captain_required")
    return group


def _available_name(conn, event_id: int, name: str, group_id: int = 0) -> str:
    name = name.strip()
    if not name:
        raise HostError("请填写队伍名称", 400, code="team_name_required")
    if conn.execute(
        "SELECT 1 FROM event_registrations WHERE event_id=? AND team_name=? COLLATE NOCASE AND id<>? AND status='pending'",
        (event_id, name, group_id),
    ).fetchone():
        raise HostError("本届已有同名报名队", code="team_name_taken")
    return name


def _insert_group(conn, event_id, name, captain_account_id, origin, now):
    name = _available_name(conn, event_id, name)
    has_old_captain = any(
        row[1] == "captain_user_id"
        for row in conn.execute("PRAGMA table_info(event_registrations)")
    )
    extra_col = ",captain_user_id" if has_old_captain else ""
    extra_val = ",?" if has_old_captain else ""
    args = (event_id, name, captain_account_id, now) + (
        (captain_account_id,) if has_old_captain else ()
    )
    group_id = conn.execute(
        f"""INSERT INTO event_registrations(event_id,team_name,creator_user_id,created_at{extra_col})
        VALUES(?,?,?,datetime(?,'unixepoch'){extra_val})""",
        args,
    ).lastrowid
    conn.execute(
        "INSERT INTO event_registration_groups(registration_id,event_id,group_origin) VALUES(?,?,?)",
        (group_id, event_id, origin),
    )
    return group_id


def create_formed_group(
    conn, event_id: int, display_name: str, *, captain_account_id: int | None, now: int
) -> int:
    return _insert_group(conn, event_id, display_name, captain_account_id, "formed", now)


def _unused_entry(conn, event_id, account_id, player_id):
    if conn.execute(
        "SELECT 1 FROM event_signup_entries WHERE event_id=? AND (account_id=? OR player_id=?)",
        (event_id, account_id, player_id),
    ).fetchone():
        raise HostError("你已经参加本届报名，不能重复占位", code="managed_duplicate")


def _slot(slot: int | None) -> None:
    if type(slot) is not int or slot not in range(5):
        raise HostError("请选择五个位置中的一个", 400, code="select_slot")


def create_group(
    conn,
    event_id: int,
    account_id: int,
    name: str,
    *,
    roster_slot: int = 0,
    reservations: Mapping[int, tuple[str, str]] | None = None,
    now: int,
) -> int:
    _open_event(conn, event_id, now)
    _slot(roster_slot)
    player_id, _ = eligible_player(conn, account_id)
    _unused_entry(conn, event_id, account_id, player_id)
    group_id = _insert_group(conn, event_id, name, account_id, "registered", now)
    conn.execute(
        """INSERT INTO event_signup_entries(event_id,account_id,player_id,registration_origin,
                    registration_id,roster_slot,created_at) VALUES(?,?,?,'group',?,?,?)""",
        (event_id, account_id, player_id, group_id, roster_slot, now),
    )
    for slot, (label, steam) in (reservations or {}).items():
        set_reservation(conn, event_id, group_id, account_id, slot, label, steam, now=now)
    return group_id


def set_reservation(
    conn,
    event_id: int,
    group_id: int,
    account_id: int | None,
    roster_slot: int,
    label: str,
    steam: str,
    *,
    now: int,
    admin_id: int | None = None,
) -> None:
    _open_event(conn, event_id, now)
    _captain(conn, event_id, group_id, account_id, admin_id)
    _slot(roster_slot)
    label, steam = label.strip(), steam.strip()
    if len(label) > 40:
        raise HostError("选手名不能超过 40 个字符", 400, code="player_name_too_long")
    if steam and not re.fullmatch(r"[0-9]{17}", steam):
        raise HostError("预留位置的 SteamID 格式不正确", 400, code="invalid_reservation_steam")
    if conn.execute(
        "SELECT 1 FROM event_signup_entries WHERE registration_id=? AND roster_slot=?",
        (group_id, roster_slot),
    ).fetchone():
        raise HostError("不能更改已认领位置的身份", code="claimed_player_identity")
    if label or steam:
        conn.execute(
            """INSERT INTO event_signup_reservations VALUES(?,?,?,?) ON CONFLICT(registration_id,roster_slot)
                        DO UPDATE SET display_label=excluded.display_label,steam_id=excluded.steam_id""",
            (group_id, roster_slot, label, steam),
        )
    else:
        conn.execute(
            "DELETE FROM event_signup_reservations WHERE registration_id=? AND roster_slot=?",
            (group_id, roster_slot),
        )


def join_group(
    conn, event_id: int, group_id: int, account_id: int, roster_slot: int, *, now: int
) -> None:
    _open_event(conn, event_id, now)
    _group(conn, event_id, group_id)
    _slot(roster_slot)
    player_id, steam = eligible_player(conn, account_id)
    _unused_entry(conn, event_id, account_id, player_id)
    if conn.execute(
        "SELECT 1 FROM event_signup_entries WHERE registration_id=? AND roster_slot=?",
        (group_id, roster_slot),
    ).fetchone():
        raise HostError("这个位置已有正式报名者", code="slot_taken")
    reserved = conn.execute(
        "SELECT steam_id FROM event_signup_reservations WHERE registration_id=? AND roster_slot=?",
        (group_id, roster_slot),
    ).fetchone()
    if reserved and reserved["steam_id"] != steam:
        raise HostError("这个位置已预留，请队长核实后调整", code="slot_reserved")
    conn.execute(
        "DELETE FROM event_signup_reservations WHERE registration_id=? AND roster_slot=?",
        (group_id, roster_slot),
    )
    conn.execute(
        """INSERT INTO event_signup_entries(event_id,account_id,player_id,registration_origin,registration_id,
                    roster_slot,created_at) VALUES(?,?,?,'group',?,?,?)""",
        (event_id, account_id, player_id, group_id, roster_slot, now),
    )


def enroll(
    conn,
    event_id: int,
    account_id: int,
    origin: str,
    *,
    preferred_registration_id: int | None = None,
    now: int,
) -> int:
    if origin not in ("individual", "independent_reserve") or (
        origin == "individual" and preferred_registration_id is not None
    ):
        raise HostError("报名入口或候补意向无效", 400, code="invalid_intent")
    _open_event(conn, event_id, now, reserves=origin == "independent_reserve")
    player_id, _ = eligible_player(conn, account_id)
    if preferred_registration_id is not None:
        if _group(conn, event_id, preferred_registration_id)["archived_at"] is not None:
            raise HostError("本队已归档，不再接收候补意向", code="reserve_team_archived")
    previous = conn.execute(
        "SELECT * FROM event_signup_entries WHERE event_id=? AND account_id=?",
        (event_id, account_id),
    ).fetchone()
    formed = conn.execute(
        "SELECT 1 FROM event_formation_batches WHERE event_id=?", (event_id,)
    ).fetchone()
    if previous is not None:
        if previous["player_id"] != player_id:
            raise HostError(
                "本次绑定与原报名选手不一致，请管理员核实", code="account_changed_since_signup"
            )
        candidate = conn.execute(
            "SELECT assigned_entrant_id FROM event_reserve_candidates WHERE event_id=? AND player_id=?",
            (event_id, player_id),
        ).fetchone()
        if (
            origin != "independent_reserve"
            or (previous["registration_origin"] != origin and candidate is None)
            or (formed and candidate is None)
            or (candidate and candidate["assigned_entrant_id"] is not None)
            or conn.execute(
                "SELECT 1 FROM event_current_members WHERE event_id=? AND player_id=?",
                (event_id, player_id),
            ).fetchone()
        ):
            raise HostError("你已经参加该赛事的报名", code="already_signed_up")
        conn.execute(
            "UPDATE event_signup_entries SET preferred_registration_id=? WHERE registration_entry_id=?",
            (preferred_registration_id, previous["registration_entry_id"]),
        )
        if candidate:
            conn.execute(
                "UPDATE event_reserve_candidates SET withdrawn_at=NULL WHERE event_id=? AND player_id=?",
                (event_id, player_id),
            )
        return previous["registration_entry_id"]
    _unused_entry(conn, event_id, account_id, player_id)
    entry_id = conn.execute(
        """INSERT INTO event_signup_entries(event_id,account_id,player_id,registration_origin,preferred_registration_id,created_at)
                               VALUES(?,?,?,?,?,?)""",
        (event_id, account_id, player_id, origin, preferred_registration_id, now),
    ).lastrowid
    if formed:
        from .roster_management import record_late_reserve

        record_late_reserve(conn, event_id, player_id)
    return entry_id


def withdraw(conn, event_id: int, account_id: int, *, now: int) -> None:
    entry = conn.execute(
        "SELECT * FROM event_signup_entries WHERE account_id=? AND event_id=?",
        (account_id, event_id),
    ).fetchone()
    if not entry:
        raise HostError("没有找到本人的报名", 404, code="no_own_signup")
    _withdraw_entry(conn, event_id, entry, now=now)


def withdraw_individual(conn, event_id, account_id, *, entry_id=None, admin_id=None, now):
    if entry_id is not None:
        require_admin(conn, admin_id)
    entry = conn.execute(
        """SELECT e.* FROM event_signup_entries e
           LEFT JOIN event_reserve_candidates c USING(event_id,player_id)
           WHERE e.event_id=? AND (e.registration_origin<>'group' OR c.player_id IS NOT NULL)
           AND """
        + ("e.registration_entry_id=?" if entry_id is not None else "e.account_id=?"),
        (event_id, entry_id if entry_id is not None else account_id),
    ).fetchone()
    if entry is None:
        raise HostError(
            "没有找到本届的个人或候补报名", 404, code="managed_no_own_individual_signup"
        )
    _withdraw_entry(conn, event_id, entry, now=now)


def _withdraw_entry(conn, event_id, entry, *, now):
    candidate = conn.execute(
        "SELECT * FROM event_reserve_candidates WHERE event_id=? AND player_id=?",
        (event_id, entry["player_id"]),
    ).fetchone()
    _open_event(
        conn,
        event_id,
        now,
        reserves=entry["registration_origin"] == "independent_reserve" or bool(candidate),
    )
    if (
        conn.execute(
            "SELECT 1 FROM event_formation_batches WHERE event_id=?", (event_id,)
        ).fetchone()
        and not candidate
    ):
        raise HostError(
            "这是已分队或曾换入阵容的报名，原记录不能撤回", code="cannot_retract_formed_signup"
        )
    if candidate:
        if (
            candidate["assigned_entrant_id"] is not None
            or conn.execute(
                "SELECT 1 FROM event_current_members WHERE event_id=? AND player_id=?",
                (event_id, entry["player_id"]),
            ).fetchone()
        ):
            raise HostError("已经获得席位，须由管理员处理", code="already_has_lineup_slot")
        conn.execute(
            "UPDATE event_reserve_candidates SET withdrawn_at=? WHERE event_id=? AND player_id=?",
            (now, event_id, entry["player_id"]),
        )
        return
    if (
        entry["registration_id"]
        and _group(conn, event_id, entry["registration_id"])["captain_account_id"]
        == entry["account_id"]
    ):
        raise HostError("队长须先移交队长或解散报名队", code="captain_must_transfer")
    conn.execute(
        "DELETE FROM event_signup_entries WHERE registration_entry_id=?",
        (entry["registration_entry_id"],),
    )


def rename_group(
    conn,
    event_id: int,
    group_id: int,
    account_id: int | None,
    name: str,
    *,
    now: int,
    admin_id: int | None = None,
) -> None:
    if not 2 <= len(name.strip()) <= 40:
        raise HostError("队伍名需要为 2 至 40 个字符", 400, code="team_name_length")
    _open_event(conn, event_id, now)
    _captain(conn, event_id, group_id, account_id, admin_id)
    conn.execute(
        "UPDATE event_registrations SET team_name=? WHERE id=?",
        (_available_name(conn, event_id, name, group_id), group_id),
    )


def leave_slot(conn, event_id, group_id, slot, account_id, *, now):
    if not conn.execute(
        "SELECT 1 FROM event_signup_entries WHERE event_id=? AND registration_id=? AND roster_slot=? AND account_id=?",
        (event_id, group_id, slot, account_id),
    ).fetchone():
        raise HostError("只能退出本人已认领的位置", 403, code="only_own_slot")
    withdraw(conn, event_id, account_id, now=now)


def review_reservation(
    conn, event_id, group_id, slot, verified_account_id, *, admin_id, reason, now
):
    require_admin(conn, admin_id)
    event = active_event(conn, event_id, now)
    if (
        now < event["registration_deadline"]
        or conn.execute(
            "SELECT 1 FROM event_formation_batches WHERE event_id=?", (event_id,)
        ).fetchone()
    ):
        raise HostError("只在截止后、分队尚未完成时复核原预留")
    _group(conn, event_id, group_id)
    held = conn.execute(
        "SELECT * FROM event_signup_reservations WHERE registration_id=? AND roster_slot=?",
        (group_id, slot),
    ).fetchone()
    if not held or not reason.strip():
        raise HostError("没有该预留，或缺少核实依据", 400)
    player_id = None
    if verified_account_id is not None:
        player_id, steam = eligible_player(conn, verified_account_id)
        if not held["steam_id"] or held["steam_id"] != steam:
            raise HostError("截止后只能按原先预留的 Steam 身份核实，不能用昵称补报")
        _unused_entry(conn, event_id, verified_account_id, player_id)
        conn.execute(
            """INSERT INTO event_signup_entries(event_id,account_id,player_id,registration_origin,registration_id,
                        roster_slot,created_at) VALUES(?,?,?,'group',?,?,?)""",
            (event_id, verified_account_id, player_id, group_id, slot, now),
        )
    conn.execute(
        """INSERT INTO event_reservation_reviews(registration_id,roster_slot,original_label,original_steam_id,
                    verified_player_id,reviewed_by,reviewed_at,reason) VALUES(?,?,?,?,?,?,?,?)""",
        (
            group_id,
            slot,
            held["display_label"],
            held["steam_id"],
            player_id,
            admin_id,
            now,
            reason.strip(),
        ),
    )
    conn.execute(
        "DELETE FROM event_signup_reservations WHERE registration_id=? AND roster_slot=?",
        (group_id, slot),
    )


def authorize_group_edit(conn, event_id, group_id, account_id, *, admin_id=None, now):
    _open_event(conn, event_id, now)
    return _captain(conn, event_id, group_id, account_id, admin_id)


def _removable_group_logo(conn, group):
    from src.website.domains.matches.match_roster_service import match_snapshot_uses_logo

    logo = group["logo"]
    return logo if logo and not match_snapshot_uses_logo(conn, logo) else None


def replace_group_logo(conn, group, logo):
    removable = _removable_group_logo(conn, group)
    conn.execute(
        "UPDATE event_registrations SET team_logo=? WHERE id=?", (logo, group["registration_id"])
    )
    return removable


def dissolve_group(conn, event_id, group_id, account_id, *, now, admin_id=None):
    group = authorize_group_edit(conn, event_id, group_id, account_id, admin_id=admin_id, now=now)
    removable = _removable_group_logo(conn, group)
    if conn.execute(
        "SELECT 1 FROM matches WHERE team1_registration_id=? OR team2_registration_id=?",
        (group_id, group_id),
    ).fetchone():
        raise HostError("本队已有比赛引用，不能解散", code="team_referenced_by_match")
    conn.execute(
        "UPDATE event_signup_entries SET preferred_registration_id=NULL WHERE preferred_registration_id=?",
        (group_id,),
    )
    conn.execute("DELETE FROM event_signup_entries WHERE registration_id=?", (group_id,))
    conn.execute("DELETE FROM event_registration_groups WHERE registration_id=?", (group_id,))
    conn.execute("DELETE FROM event_registrations WHERE id=?", (group_id,))
    return removable


def remove_group_member(conn, event_id, group_id, account_id, slot, *, now, admin_id=None):
    group = authorize_group_edit(conn, event_id, group_id, account_id, admin_id=admin_id, now=now)
    _slot(slot)
    entry = conn.execute(
        "SELECT account_id FROM event_signup_entries WHERE registration_id=? AND roster_slot=?",
        (group_id, slot),
    ).fetchone()
    if entry and entry[0] == group["captain_account_id"]:
        raise HostError("队长的位置不能移除", 403, code="cannot_remove_captain")
    conn.execute(
        "DELETE FROM event_signup_entries WHERE registration_id=? AND roster_slot=?",
        (group_id, slot),
    )
    conn.execute(
        "DELETE FROM event_signup_reservations WHERE registration_id=? AND roster_slot=?",
        (group_id, slot),
    )


def transfer_group_captain(conn, event_id, group_id, slot, *, now, admin_id):
    _open_event(conn, event_id, now)
    _group(conn, event_id, group_id)
    require_admin(conn, admin_id)
    _slot(slot)
    entry = conn.execute(
        "SELECT account_id FROM event_signup_entries WHERE registration_id=? AND roster_slot=?",
        (group_id, slot),
    ).fetchone()
    if not entry:
        raise HostError("只能任命已认领位置的成员", 400, code="require_claimed_member")
    conn.execute(
        "UPDATE event_registrations SET creator_user_id=? WHERE id=?", (entry[0], group_id)
    )


def link_club(
    conn, event_id: int, group_id: int, club_id: int, *, admin_id: int | None, now: int
) -> None:
    require_admin(conn, admin_id)
    _open_event(conn, event_id, now)
    _group(conn, event_id, group_id)
    if not conn.execute("SELECT 1 FROM teams WHERE id=?", (club_id,)).fetchone():
        raise HostError("长期俱乐部不存在", 404)
    conn.execute(
        "UPDATE event_registration_groups SET club_id=? WHERE registration_id=?",
        (club_id, group_id),
    )


def archive_event(
    conn: sqlite3.Connection, event_id: int, *, admin_id: int | None, now: int
) -> None:
    require_admin(conn, admin_id)
    if not conn.execute(
        "SELECT 1 FROM event_registration_control WHERE event_id=?", (event_id,)
    ).fetchone():
        raise HostError("赛事不存在", 404)
    conn.execute(
        "UPDATE event_registration_control SET archived_at=COALESCE(archived_at,?),first_write_at=COALESCE(first_write_at,?) WHERE event_id=?",
        (now, now, event_id),
    )
    conn.execute("UPDATE events SET registration_open=0,status='completed' WHERE id=?", (event_id,))
