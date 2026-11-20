"""Create and edit teams in the legacy event-registration tables."""

from src.website.domains.events.legacy_registration import (
    _bound_account,
    _individual_entry,
    _pending_team_member,
    move_individual_to_reserve,
)
from src.website.domains.matches.match_roster_service import (
    match_snapshot_uses_logo,
    preserve_event_rosters,
)
from src.website.runtime.host import HostError


def signup_slots(conn, event_id, account_id, team_name, own_slot, reservations):
    """Validate a new team before its optional logo is saved within the same write."""
    event = conn.execute("SELECT registration_open FROM events WHERE id=?", (event_id,)).fetchone()
    if not event or not event["registration_open"]:
        raise HostError("该赛事未开放报名", 403, code="signup_not_open")
    user = _bound_account(conn, account_id, "创建队伍前请先绑定 Steam 账号")
    if not team_name:
        raise HostError("请填写队伍名称", 400, code="team_name_required")
    if own_slot not in range(5):
        raise HostError("请选择有效的位置", 400, code="select_slot")
    if _pending_team_member(conn, event_id, account_id):
        raise HostError("你已经加入该赛事的一支报名队伍", code="already_on_team")
    if _individual_entry(conn, event_id, account_id):
        raise HostError(
            "你已经选择个人报名，请先取消个人报名", code="cancel_individual_before_joining"
        )
    if conn.execute(
        "SELECT 1 FROM event_registrations WHERE event_id=? AND status='pending' AND team_name=?",
        (event_id, team_name),
    ).fetchone():
        raise HostError("本届已有同名报名队", code="team_name_taken")

    slots = []
    for index, (name, steam) in enumerate(reservations):
        if steam and (not steam.isdigit() or len(steam) != 17):
            raise HostError(
                "队员 SteamID 格式无效",
                400,
                code="invalid_signup_slot_steam",
                params={"value1": index + 1},
            )
        user_id = account_id if index == own_slot else None
        if user_id:
            name, steam = user["username"], user["steam_id64"]
        slots.append((index, user_id, name or f"位置{index + 1}", steam or "", int(bool(name))))
    return slots


def has_legacy_captain_column(conn):
    return any(
        row[1] == "captain_user_id"
        for row in conn.execute("PRAGMA table_info(event_registrations)")
    )


def register_team(conn, event_id, name, captain_id, slots, *, logo=None, has_old_captain=None):
    # The earliest databases still require the retired captain column on INSERT.
    if has_old_captain is None:
        has_old_captain = has_legacy_captain_column(conn)
    extra_column = ", captain_user_id" if has_old_captain else ""
    extra_value = ",?" if has_old_captain else ""
    args = (event_id, name, captain_id, logo)
    reg_id = conn.execute(
        f"""INSERT INTO event_registrations(event_id,team_name,creator_user_id,team_logo,status{extra_column})
            VALUES(?,?,?,?,'pending'{extra_value})""",
        args + ((captain_id,) if has_old_captain else ()),
    ).lastrowid
    conn.executemany(
        """INSERT INTO event_registration_slots(
               registration_id,slot_index,user_id,player_name,steam_id,filled_by_creator
           ) VALUES(?,?,?,?,?,?)""",
        [(reg_id, *slot) for slot in slots],
    )
    return reg_id


def slot_is_open(slot):
    """Captain reservations are not empty even if no account has claimed them."""
    player_name = str(slot.get("player_name") or "").strip()
    try:
        slot_index = int(slot.get("slot_index"))
    except (TypeError, ValueError):
        slot_index = None
    placeholder = f"位置{slot_index + 1}" if slot_index is not None else ""
    return bool(
        not slot.get("user_id")
        and not str(slot.get("steam_id") or "").strip()
        and not int(slot.get("filled_by_creator") or 0)
        and (not player_name or player_name == placeholder)
    )


def join_team(conn, event_id, reg_id, slot, user_id):
    user = _bound_account(conn, user_id, "加入队伍前请先绑定 Steam 账号")
    slot_row = conn.execute(
        """SELECT s.* FROM event_registration_slots s
           JOIN event_registrations r ON r.id=s.registration_id
           JOIN events e ON e.id=r.event_id
           WHERE s.registration_id=? AND s.slot_index=?
             AND r.event_id=? AND r.status='pending' AND e.registration_open=1""",
        (reg_id, slot, event_id),
    ).fetchone()
    if not slot_row:
        raise HostError("该位置不存在", 404, code="slot_not_found")
    if not slot_is_open(dict(slot_row)):
        raise HostError("该位置已被占用", 409, code="slot_taken")
    if _pending_team_member(conn, event_id, user_id):
        raise HostError("你已经加入该赛事的一支报名队伍", 409, code="already_on_team")
    if _individual_entry(conn, event_id, user_id):
        raise HostError(
            "你已经选择个人报名，请先取消个人报名", 409, code="cancel_individual_before_joining"
        )

    preserve_event_rosters(conn, event_id, reg_id)
    changed = conn.execute(
        """UPDATE event_registration_slots SET user_id=?, player_name=?, steam_id=?
           WHERE id=? AND user_id IS NULL AND TRIM(COALESCE(steam_id, ''))=''
             AND COALESCE(filled_by_creator, 0)=0
             AND TRIM(COALESCE(player_name, '')) IN ('', ?)""",
        (user_id, user["username"], user["steam_id64"], slot_row["id"], f"位置{slot + 1}"),
    ).rowcount
    if changed != 1:
        raise HostError("该位置刚刚被其他选手加入，请选择其他位置", 409, code="slot_just_taken")


def leave_team(conn, event_id, reg_id, slot, user_id):
    slot_row = conn.execute(
        """SELECT s.id, s.slot_index, r.team_name, r.creator_user_id
           FROM event_registration_slots s
           JOIN event_registrations r ON r.id=s.registration_id
           JOIN events e ON e.id=r.event_id
           WHERE s.registration_id=? AND s.slot_index=?
             AND r.event_id=? AND r.status='pending' AND e.registration_open=1
             AND s.user_id=?""",
        (reg_id, slot, event_id, user_id),
    ).fetchone()
    if not slot_row:
        raise HostError(
            "只能退出你自己加入的位置，或该报名已不可修改", 403, code="cannot_leave_slot"
        )
    if slot_row["creator_user_id"] == user_id:
        raise HostError("队长不能直接退出，请解散队伍", 403, code="captain_cannot_leave")
    preserve_event_rosters(conn, event_id, reg_id)
    position = slot_row["slot_index"] + 1
    changed = conn.execute(
        """UPDATE event_registration_slots
           SET user_id=NULL, player_name=?, steam_id='', filled_by_creator=0
           WHERE id=? AND user_id=?""",
        (f"位置{position}", slot_row["id"], user_id),
    ).rowcount
    if changed != 1:
        raise HostError("退出失败，请刷新页面后重试", 409, code="leave_failed")
    move_individual_to_reserve(conn, event_id, user_id)
    return slot_row["team_name"], position


def _pending_registration(conn, event_id, reg_id):
    return conn.execute(
        """SELECT r.* FROM event_registrations r
           JOIN events e ON e.id=r.event_id
           WHERE r.id=? AND r.event_id=? AND r.status='pending'""",
        (reg_id, event_id),
    ).fetchone()


def _slot_row(conn, reg_id, slot):
    row = conn.execute(
        "SELECT * FROM event_registration_slots WHERE registration_id=? AND slot_index=?",
        (reg_id, slot),
    ).fetchone()
    if not row:
        raise HostError("该位置不存在", 404, code="slot_not_found")
    return row


_EDIT_PERMISSION = {
    "rename": ("只有队长或管理员可以修改队名", "captain_or_admin_rename"),
    "upload_logo": ("只有队长或管理员可以修改队标", "captain_or_admin_logo"),
    "remove_logo": ("只有队长或管理员可以移除队标", "captain_or_admin_remove_logo"),
    "dissolve": ("只有队长或管理员可以解散队伍", "captain_or_admin_dissolve"),
    "remove_member": ("只有队长或管理员可以移除队员", "captain_or_admin_remove"),
    "update_member": ("只有队长或管理员可以修改队员", "captain_or_admin_update"),
}


def authorize_team_edit(conn, event_id, reg_id, account_id, admin_id, operation):
    team = _pending_registration(conn, event_id, reg_id)
    if not team or not (admin_id or account_id == team["creator_user_id"]):
        message, code = _EDIT_PERMISSION[operation]
        raise HostError(message, 403, code=code)
    return team


def rename_team(conn, event_id, reg_id, account_id, admin_id, new_name):
    authorize_team_edit(conn, event_id, reg_id, account_id, admin_id, "rename")
    if not 2 <= len(new_name) <= 40:
        raise HostError("队伍名需要为 2 至 40 个字符", 400, code="team_name_length")
    if conn.execute(
        """SELECT 1 FROM event_registrations
           WHERE event_id=? AND status='pending' AND id<>? AND team_name=? COLLATE NOCASE""",
        (event_id, reg_id, new_name),
    ).fetchone():
        raise HostError("该队伍名已经被使用", 409, code="legacy_team_name_taken")
    preserve_event_rosters(conn, event_id, reg_id)
    conn.execute("UPDATE event_registrations SET team_name=? WHERE id=?", (new_name, reg_id))


def replace_team_logo(conn, team, new_logo):
    preserve_event_rosters(conn, team["event_id"], team["id"])
    old_logo = team["team_logo"]
    keep_logo = match_snapshot_uses_logo(conn, old_logo)
    conn.execute("UPDATE event_registrations SET team_logo=? WHERE id=?", (new_logo, team["id"]))
    return None if keep_logo else old_logo


def dissolve_team(conn, team):
    event_id, reg_id = team["event_id"], team["id"]
    preserve_event_rosters(conn, event_id, reg_id)
    logo = team["team_logo"]
    keep_logo = match_snapshot_uses_logo(conn, logo)
    members = conn.execute(
        "SELECT user_id FROM event_registration_slots WHERE registration_id=?", (reg_id,)
    ).fetchall()
    conn.execute(
        """UPDATE event_individual_registrations SET preferred_registration_id=NULL
           WHERE preferred_registration_id=?""",
        (reg_id,),
    )
    for member in members:
        move_individual_to_reserve(conn, event_id, member["user_id"])
    conn.execute("DELETE FROM event_registration_slots WHERE registration_id=?", (reg_id,))
    conn.execute("DELETE FROM event_registrations WHERE id=?", (reg_id,))
    return team["team_name"], None if keep_logo else logo


def remove_member(conn, event_id, reg_id, slot, account_id, admin_id):
    team = authorize_team_edit(conn, event_id, reg_id, account_id, admin_id, "remove_member")
    current = _slot_row(conn, reg_id, slot)
    if current["user_id"] == team["creator_user_id"]:
        raise HostError("队长位置不能被移除，请解散队伍", 403, code="clear_captain_slot")
    preserve_event_rosters(conn, event_id, reg_id)
    conn.execute(
        """UPDATE event_registration_slots
           SET user_id=NULL, player_name=?, steam_id='', filled_by_creator=0 WHERE id=?""",
        (f"位置{slot + 1}", current["id"]),
    )
    move_individual_to_reserve(conn, event_id, current["user_id"])
    return current["player_name"]


def update_member(conn, event_id, reg_id, slot, account_id, admin_id, name, steam):
    authorize_team_edit(conn, event_id, reg_id, account_id, admin_id, "update_member")
    current = _slot_row(conn, reg_id, slot)
    claimed = bool(current["user_id"])
    if not admin_id and claimed:
        raise HostError("队长不能修改已认领队员的账号资料", 403, code="captain_cannot_edit_claimed")
    if len(name) > 40:
        raise HostError("选手名不能超过 40 个字符", 400, code="player_name_too_long")
    if steam and (not steam.isdigit() or len(steam) != 17):
        raise HostError("SteamID 必须是 17 位数字", 400, code="invalid_steam_id")
    if claimed and not name:
        raise HostError("已加入的队员名称不能为空", 400, code="player_name_required")

    preserve_event_rosters(conn, event_id, reg_id)
    conn.execute(
        """UPDATE event_registration_slots
           SET player_name=?, steam_id=?, filled_by_creator=? WHERE id=?""",
        (
            name or f"位置{slot + 1}",
            steam if name else "",
            current["filled_by_creator"] if claimed else int(bool(name)),
            current["id"],
        ),
    )


def transfer_captain(conn, event_id, reg_id, slot, admin_id):
    if not admin_id:
        raise HostError("只有管理员可以转移队长权限", 403, code="admin_transfer_captain")
    team = _pending_registration(conn, event_id, reg_id)
    if not team:
        raise HostError("报名队伍不存在", 404, code="team_not_found")
    current = _slot_row(conn, reg_id, slot)
    if not current["user_id"]:
        raise HostError("只能任命已经加入队伍的注册用户", 400, code="require_joined_member")
    if current["user_id"] == team["creator_user_id"]:
        raise HostError("该玩家已经是队长", 400, code="already_captain")
    conn.execute(
        "UPDATE event_registrations SET creator_user_id=? WHERE id=?", (current["user_id"], reg_id)
    )
    return current["player_name"]
