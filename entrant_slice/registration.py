"""Registration intent lives here; forming a team or recording an appearance is a different fact."""

import re
import sqlite3
from collections.abc import Mapping
from datetime import datetime

from .storage import SliceError, require_admin


def create_event(
    conn,
    name: str,
    slug: str,
    deadline: int,
    *,
    admin_id: int | None,
    now: int,
    starts_at: int | None = None,
    ends_at: int | None = None,
) -> int:
    require_admin(conn, admin_id)
    if not name.strip() or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) or slug.isdigit():
        raise SliceError("赛事名不能为空；地址须为非纯数字的小写字母、数字或连字符", 400)
    if deadline <= now:
        raise SliceError("新赛事的报名截止时间须在未来", 400)
    if ends_at is not None and (ends_at <= now or (starts_at is not None and ends_at < starts_at)):
        raise SliceError("请检查赛事开始和结束时间", 400)
    try:
        datetime.fromtimestamp(deadline)
        start_date, end_date = (
            datetime.fromtimestamp(v).isoformat(timespec="seconds") if v is not None else None
            for v in (starts_at, ends_at)
        )
    except (OverflowError, OSError, ValueError) as exc:
        raise SliceError("赛事时间超出支持范围", 400) from exc
    if conn.execute(
        "SELECT 1 FROM events WHERE slug=? UNION ALL SELECT 1 FROM event_slug_aliases WHERE slug=?",
        (slug, slug),
    ).fetchone():
        raise SliceError("这个赛事地址已在使用")
    event_id = conn.execute(
        "INSERT INTO events(name,slug,start_date,end_date,status,registration_open) VALUES(?,?,?,?,'upcoming',1)",
        (name.strip(), slug, start_date, end_date),
    ).lastrowid
    conn.execute(
        "INSERT INTO entrant_event(event_id,registration_deadline) VALUES(?,?)",
        (event_id, deadline),
    )
    return event_id


def _open_event(conn, event_id: int, now: int, *, reserves=False):
    event = conn.execute(
        """SELECT ee.*,e.id,e.slug,e.start_date,e.end_date,e.status FROM entrant_event ee JOIN events e ON e.id=ee.event_id
                            WHERE ee.event_id=?""",
        (event_id,),
    ).fetchone()
    if event is None:
        raise SliceError("不属于本次隔离报名的赛事", 404)
    from services.match_service import add_effective_event_status

    if (
        event["archived_at"] is not None
        or event["status"] == "completed"
        or add_effective_event_status(event, datetime.fromtimestamp(now))["effective_event_status"]
        == "completed"
    ):
        raise SliceError("赛事已经结束，不能变更报名")
    if not reserves and now >= event["registration_deadline"]:
        raise SliceError("正式报名已截止")
    return event


def active_event(conn, event_id: int, now: int):
    return _open_event(conn, event_id, now, reserves=True)


def eligible_player(conn, account_id: int):
    user = conn.execute(
        "SELECT approval_status,is_placeholder,steam_id64 FROM users WHERE id=?", (account_id,)
    ).fetchone()
    if user is None or user["approval_status"] != "approved" or user["is_placeholder"]:
        raise SliceError("请使用通过审核的选手账号报名", 403)
    steam = (user["steam_id64"] or "").strip()
    if not steam:
        raise SliceError("请先绑定 Steam 账号", 400)
    if (
        len(conn.execute("SELECT id FROM users WHERE steam_id64=? LIMIT 2", (steam,)).fetchall())
        != 1
    ):
        raise SliceError("Steam 绑定匹配多个账号，需要管理员核实身份")
    players = conn.execute("SELECT id FROM players WHERE steam_id=? LIMIT 2", (steam,)).fetchall()
    if len(players) != 1:
        raise SliceError("Steam 绑定没有唯一的选手档案，需要管理员核实身份")
    return players[0]["id"], steam


def _group(conn, event_id: int, group_id: int):
    group = conn.execute(
        "SELECT * FROM registration_group WHERE event_id=? AND registration_group_id=?",
        (event_id, group_id),
    ).fetchone()
    if group is None:
        raise SliceError("该报名队不属于当前赛事", 404)
    return group


def _captain(
    conn, event_id: int, group_id: int, account_id: int | None, admin_id: int | None = None
):
    group = _group(conn, event_id, group_id)
    if admin_id is not None:
        require_admin(conn, admin_id)
    elif account_id is None or group["captain_account_id"] != account_id:
        raise SliceError("只有本队队长可以执行此操作", 403)
    return group


def _available_name(conn, event_id: int, name: str, group_id: int = 0) -> str:
    name = name.strip()
    if not name:
        raise SliceError("请填写队伍名称", 400)
    if conn.execute(
        "SELECT 1 FROM registration_group WHERE event_id=? AND display_name=? AND registration_group_id<>?",
        (event_id, name, group_id),
    ).fetchone():
        raise SliceError("本届已有同名报名队")
    return name


def _insert_group(conn, event_id, name, captain_account_id, origin, now):
    # The old director persists registration-<number>; this includes numbers used by unmanaged events.
    group_id = conn.execute("""SELECT MAX(n)+1 FROM (
        SELECT COALESCE(MAX(registration_group_id),0) AS n FROM registration_group
        UNION ALL SELECT COALESCE(MAX(id),0) FROM event_registrations
        UNION ALL SELECT seq FROM sqlite_sequence WHERE name IN ('registration_group','event_registrations'))""").fetchone()[
        0
    ]
    conn.execute(
        """INSERT INTO registration_group(registration_group_id,event_id,display_name,captain_account_id,
                    group_origin,created_at) VALUES(?,?,?,?,?,?)""",
        (
            group_id,
            event_id,
            _available_name(conn, event_id, name),
            captain_account_id,
            origin,
            now,
        ),
    )
    return group_id


def create_formed_group(
    conn, event_id: int, display_name: str, *, captain_account_id: int | None, now: int
) -> int:
    return _insert_group(conn, event_id, display_name, captain_account_id, "formed", now)


def _unused_entry(conn, event_id, account_id, player_id):
    if conn.execute(
        "SELECT 1 FROM registration_entry WHERE event_id=? AND (account_id=? OR player_id=?)",
        (event_id, account_id, player_id),
    ).fetchone():
        raise SliceError("你已经参加本届报名，不能重复占位")


def _slot(slot: int | None) -> None:
    if type(slot) is not int or slot not in range(5):
        raise SliceError("请选择五个位置中的一个", 400)


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
        """INSERT INTO registration_entry(event_id,account_id,player_id,registration_origin,
                    registration_group_id,roster_slot,created_at) VALUES(?,?,?,'group',?,?,?)""",
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
        raise SliceError("选手名不能超过 40 个字符", 400)
    if steam and not re.fullmatch(r"[0-9]{17}", steam):
        raise SliceError("预留位置的 SteamID 格式不正确", 400)
    if conn.execute(
        "SELECT 1 FROM registration_entry WHERE registration_group_id=? AND roster_slot=?",
        (group_id, roster_slot),
    ).fetchone():
        raise SliceError("不能更改已认领位置的身份")
    if label or steam:
        conn.execute(
            """INSERT INTO registration_reservation VALUES(?,?,?,?) ON CONFLICT(registration_group_id,roster_slot)
                        DO UPDATE SET display_label=excluded.display_label,steam_id=excluded.steam_id""",
            (group_id, roster_slot, label, steam),
        )
    else:
        conn.execute(
            "DELETE FROM registration_reservation WHERE registration_group_id=? AND roster_slot=?",
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
        "SELECT 1 FROM registration_entry WHERE registration_group_id=? AND roster_slot=?",
        (group_id, roster_slot),
    ).fetchone():
        raise SliceError("这个位置已有正式报名者")
    reserved = conn.execute(
        "SELECT steam_id FROM registration_reservation WHERE registration_group_id=? AND roster_slot=?",
        (group_id, roster_slot),
    ).fetchone()
    if reserved and reserved["steam_id"] != steam:
        raise SliceError("这个位置已预留，请队长核实后调整")
    conn.execute(
        "DELETE FROM registration_reservation WHERE registration_group_id=? AND roster_slot=?",
        (group_id, roster_slot),
    )
    conn.execute(
        """INSERT INTO registration_entry(event_id,account_id,player_id,registration_origin,registration_group_id,
                    roster_slot,created_at) VALUES(?,?,?,'group',?,?,?)""",
        (event_id, account_id, player_id, group_id, roster_slot, now),
    )


def enroll(
    conn,
    event_id: int,
    account_id: int,
    origin: str,
    *,
    preferred_group_id: int | None = None,
    now: int,
) -> int:
    if origin not in ("individual", "independent_reserve") or (
        origin == "individual" and preferred_group_id is not None
    ):
        raise SliceError("报名入口或候补意向无效", 400)
    _open_event(conn, event_id, now, reserves=origin == "independent_reserve")
    player_id, _ = eligible_player(conn, account_id)
    if preferred_group_id is not None:
        _group(conn, event_id, preferred_group_id)
    previous = conn.execute(
        "SELECT * FROM registration_entry WHERE event_id=? AND account_id=?", (event_id, account_id)
    ).fetchone()
    formed = conn.execute("SELECT 1 FROM formation_batch WHERE event_id=?", (event_id,)).fetchone()
    if previous is not None:
        if previous["player_id"] != player_id:
            raise SliceError("本次绑定与原报名选手不一致，请管理员核实")
        candidate = conn.execute(
            "SELECT assigned_entrant_id FROM reserve_candidate WHERE event_id=? AND player_id=?",
            (event_id, player_id),
        ).fetchone()
        if (
            origin != "independent_reserve"
            or (previous["registration_origin"] != origin and candidate is None)
            or (formed and candidate is None)
            or (candidate and candidate["assigned_entrant_id"] is not None)
            or conn.execute(
                "SELECT 1 FROM entrant_member WHERE event_id=? AND player_id=?",
                (event_id, player_id),
            ).fetchone()
        ):
            raise SliceError("你已经参加该赛事的报名")
        conn.execute(
            "UPDATE registration_entry SET preferred_group_id=? WHERE registration_entry_id=?",
            (preferred_group_id, previous["registration_entry_id"]),
        )
        if candidate:
            conn.execute(
                "UPDATE reserve_candidate SET withdrawn_at=NULL WHERE event_id=? AND player_id=?",
                (event_id, player_id),
            )
        return previous["registration_entry_id"]
    _unused_entry(conn, event_id, account_id, player_id)
    entry_id = conn.execute(
        """INSERT INTO registration_entry(event_id,account_id,player_id,registration_origin,preferred_group_id,created_at)
                               VALUES(?,?,?,?,?,?)""",
        (event_id, account_id, player_id, origin, preferred_group_id, now),
    ).lastrowid
    if formed:
        from .formation import record_late_reserve

        record_late_reserve(conn, event_id, player_id)
    return entry_id


def withdraw(conn, event_id: int, account_id: int, *, now: int) -> None:
    entry = conn.execute(
        "SELECT * FROM registration_entry WHERE account_id=? AND event_id=?", (account_id, event_id)
    ).fetchone()
    if not entry:
        raise SliceError("没有找到本人的报名", 404)
    candidate = conn.execute(
        "SELECT * FROM reserve_candidate WHERE event_id=? AND player_id=?",
        (event_id, entry["player_id"]),
    ).fetchone()
    _open_event(
        conn,
        event_id,
        now,
        reserves=entry["registration_origin"] == "independent_reserve" or bool(candidate),
    )
    if (
        conn.execute("SELECT 1 FROM formation_batch WHERE event_id=?", (event_id,)).fetchone()
        and not candidate
    ):
        raise SliceError("这是已分队或曾换入阵容的报名，原记录不能撤回")
    if candidate:
        if (
            candidate["assigned_entrant_id"] is not None
            or conn.execute(
                "SELECT 1 FROM entrant_member WHERE event_id=? AND player_id=?",
                (event_id, entry["player_id"]),
            ).fetchone()
        ):
            raise SliceError("已经获得席位，须由管理员处理")
        conn.execute(
            "UPDATE reserve_candidate SET withdrawn_at=? WHERE event_id=? AND player_id=?",
            (now, event_id, entry["player_id"]),
        )
        return
    if (
        entry["registration_group_id"]
        and _group(conn, event_id, entry["registration_group_id"])["captain_account_id"]
        == account_id
    ):
        raise SliceError("队长须先移交队长或解散报名队")
    conn.execute(
        "DELETE FROM registration_entry WHERE registration_entry_id=?",
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
    _open_event(conn, event_id, now)
    _captain(conn, event_id, group_id, account_id, admin_id)
    conn.execute(
        "UPDATE registration_group SET display_name=? WHERE registration_group_id=?",
        (_available_name(conn, event_id, name, group_id), group_id),
    )


def leave_slot(conn, event_id, group_id, slot, account_id, *, now):
    if not conn.execute(
        "SELECT 1 FROM registration_entry WHERE event_id=? AND registration_group_id=? AND roster_slot=? AND account_id=?",
        (event_id, group_id, slot, account_id),
    ).fetchone():
        raise SliceError("只能退出本人已认领的位置", 403)
    withdraw(conn, event_id, account_id, now=now)


def review_reservation(
    conn, event_id, group_id, slot, verified_account_id, *, admin_id, reason, now
):
    require_admin(conn, admin_id)
    event = active_event(conn, event_id, now)
    if (
        now < event["registration_deadline"]
        or conn.execute("SELECT 1 FROM formation_batch WHERE event_id=?", (event_id,)).fetchone()
    ):
        raise SliceError("只在截止后、分队尚未完成时复核原预留")
    _group(conn, event_id, group_id)
    held = conn.execute(
        "SELECT * FROM registration_reservation WHERE registration_group_id=? AND roster_slot=?",
        (group_id, slot),
    ).fetchone()
    if not held or not reason.strip():
        raise SliceError("没有该预留，或缺少核实依据", 400)
    player_id = None
    if verified_account_id is not None:
        player_id, steam = eligible_player(conn, verified_account_id)
        if not held["steam_id"] or held["steam_id"] != steam:
            raise SliceError("截止后只能按原先预留的 Steam 身份核实，不能用昵称补报")
        _unused_entry(conn, event_id, verified_account_id, player_id)
        conn.execute(
            """INSERT INTO registration_entry(event_id,account_id,player_id,registration_origin,registration_group_id,
                        roster_slot,created_at) VALUES(?,?,?,'group',?,?,?)""",
            (event_id, verified_account_id, player_id, group_id, slot, now),
        )
    conn.execute(
        """INSERT INTO reservation_review(registration_group_id,roster_slot,original_label,original_steam_id,
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
        "DELETE FROM registration_reservation WHERE registration_group_id=? AND roster_slot=?",
        (group_id, slot),
    )


def authorize_group_edit(conn, event_id, group_id, account_id, *, admin_id=None, now):
    _open_event(conn, event_id, now)
    return _captain(conn, event_id, group_id, account_id, admin_id)


def manage_group(
    conn, event_id, group_id, account_id, action, *, now, admin_id=None, slot=None, logo=None
):
    group = authorize_group_edit(conn, event_id, group_id, account_id, admin_id=admin_id, now=now)
    if action == "logo":
        conn.execute(
            "UPDATE registration_group SET logo=? WHERE registration_group_id=?", (logo, group_id)
        )
    elif action == "dissolve":
        conn.execute(
            "UPDATE registration_entry SET preferred_group_id=NULL WHERE preferred_group_id=?",
            (group_id,),
        )
        conn.execute("DELETE FROM registration_entry WHERE registration_group_id=?", (group_id,))
        conn.execute("DELETE FROM registration_group WHERE registration_group_id=?", (group_id,))
    elif action in ("remove", "captain"):
        _slot(slot)
        entry = conn.execute(
            "SELECT account_id FROM registration_entry WHERE registration_group_id=? AND roster_slot=?",
            (group_id, slot),
        ).fetchone()
        if action == "captain":
            require_admin(conn, admin_id)
            if not entry:
                raise SliceError("只能任命已认领位置的成员", 400)
            conn.execute(
                "UPDATE registration_group SET captain_account_id=? WHERE registration_group_id=?",
                (entry[0], group_id),
            )
        elif entry and entry[0] == group["captain_account_id"]:
            raise SliceError("队长的位置不能移除", 403)
        else:
            conn.execute(
                "DELETE FROM registration_entry WHERE registration_group_id=? AND roster_slot=?",
                (group_id, slot),
            )
            conn.execute(
                "DELETE FROM registration_reservation WHERE registration_group_id=? AND roster_slot=?",
                (group_id, slot),
            )
    else:
        raise SliceError("未识别的报名操作", 400)


def link_club(
    conn, event_id: int, group_id: int, club_id: int, *, admin_id: int | None, now: int
) -> None:
    require_admin(conn, admin_id)
    _open_event(conn, event_id, now)
    _group(conn, event_id, group_id)
    if not conn.execute("SELECT 1 FROM teams WHERE id=?", (club_id,)).fetchone():
        raise SliceError("长期俱乐部不存在", 404)
    conn.execute(
        "UPDATE registration_group SET club_id=? WHERE registration_group_id=?", (club_id, group_id)
    )


def archive_event(
    conn: sqlite3.Connection, event_id: int, *, admin_id: int | None, now: int
) -> None:
    require_admin(conn, admin_id)
    if not conn.execute("SELECT 1 FROM entrant_event WHERE event_id=?", (event_id,)).fetchone():
        raise SliceError("赛事不存在", 404)
    conn.execute(
        "UPDATE entrant_event SET archived_at=COALESCE(archived_at,?) WHERE event_id=?",
        (now, event_id),
    )
    conn.execute("UPDATE events SET registration_open=0,status='completed' WHERE id=?", (event_id,))
