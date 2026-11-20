"""Writes for legacy event signups, inside the caller's event-owner transaction."""

from src.website.domains.events.status import add_effective_event_status
from src.website.runtime.host import HostError


def _bound_account(conn, user_id, missing_steam_message):
    user = conn.execute(
        "SELECT id, username, steam_id64 FROM users WHERE id=?", (user_id,)
    ).fetchone()
    if not user or not user["steam_id64"]:
        raise HostError(missing_steam_message, 400, code="steam_required")
    return user


def _pending_team_member(conn, event_id, user_id):
    return (
        conn.execute(
            """SELECT 1 FROM event_registration_slots s
           JOIN event_registrations r ON r.id=s.registration_id
           WHERE r.event_id=? AND r.status='pending' AND s.user_id=? LIMIT 1""",
            (event_id, user_id),
        ).fetchone()
        is not None
    )


def _individual_entry(conn, event_id, user_id):
    return conn.execute(
        """SELECT id, assignment_status FROM event_individual_registrations
           WHERE event_id=? AND user_id=?""",
        (event_id, user_id),
    ).fetchone()


def has_individuals_on_teams(conn, event_id, *, assigned_only=False):
    return (
        conn.execute(
            """SELECT 1 FROM event_individual_registrations ir
           JOIN event_registration_slots s ON s.user_id=ir.user_id
           JOIN event_registrations r ON r.id=s.registration_id AND r.event_id=ir.event_id
           WHERE ir.event_id=? AND r.status='pending'
             AND (NOT ? OR ir.assignment_status='assigned') LIMIT 1""",
            (event_id, assigned_only),
        ).fetchone()
        is not None
    )


def enroll_individual(conn, event_id, user_id):
    event = conn.execute("SELECT registration_open FROM events WHERE id=?", (event_id,)).fetchone()
    if not event or not event["registration_open"]:
        raise HostError("该赛事未开放报名", 403, code="signup_not_open")
    user = _bound_account(conn, user_id, "个人报名需要先绑定 Steam 账号")
    if conn.execute(
        """SELECT 1 FROM event_individual_registrations
           WHERE event_id=? AND assignment_status<>'pending' LIMIT 1""",
        (event_id,),
    ).fetchone():
        raise HostError("本次个人报名已经完成分队", 409, code="signup_already_drawn")
    if _pending_team_member(conn, event_id, user_id):
        raise HostError("你已经加入该赛事的一支报名队伍", 409, code="already_on_team")
    if _individual_entry(conn, event_id, user_id):
        raise HostError("你已经提交过个人报名", 409, code="already_signed_up")
    conn.execute(
        """INSERT INTO event_individual_registrations(event_id, user_id, player_name, steam_id)
           VALUES(?,?,?,?)""",
        (event_id, user["id"], user["username"], user["steam_id64"]),
    )


def substitute_entrant(conn, event_id, user_id):
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not event:
        raise HostError("赛事不存在", 404, code="missing_event")
    if (
        str(event["status"] or "").strip().lower() == "completed"
        or add_effective_event_status(event)["effective_event_status"] == "completed"
    ):
        raise HostError("赛事已经结束，无法报名替补", 409, code="event_ended_no_reserves")
    return _bound_account(conn, user_id, "替补报名需要先绑定 Steam 账号")


def enroll_substitute(conn, event_id, user, preferred_id):
    team_name = ""
    if preferred_id is not None:
        preferred = conn.execute(
            """SELECT team_name FROM event_registrations
               WHERE id=? AND event_id=? AND status='pending'""",
            (preferred_id, event_id),
        ).fetchone()
        if not preferred:
            raise HostError("所选队伍不属于当前赛事", 409, code="reserve_team_wrong_event")
        team_name = preferred["team_name"]
    if not has_individuals_on_teams(conn, event_id, assigned_only=True):
        raise HostError("正式分队完成后才会开放替补报名", 409, code="reserves_not_open")
    if _pending_team_member(conn, event_id, user["id"]):
        raise HostError("你已经是该赛事的正式队员", 409, code="formal_member_no_reserve")

    existing = _individual_entry(conn, event_id, user["id"])
    if existing:
        if existing["assignment_status"] != "reserve":
            raise HostError("你已经参加该赛事的报名", 409, code="already_signed_up")
        conn.execute(
            """UPDATE event_individual_registrations
               SET preferred_registration_id=?, assigned_at=CURRENT_TIMESTAMP WHERE id=?""",
            (preferred_id, existing["id"]),
        )
    else:
        conn.execute(
            """INSERT INTO event_individual_registrations(
               event_id, user_id, player_name, steam_id, assignment_status, assigned_at,
               preferred_registration_id
               ) VALUES(?,?,?,?, 'reserve', CURRENT_TIMESTAMP, ?)""",
            (event_id, user["id"], user["username"], user["steam_id64"], preferred_id),
        )
    return team_name, existing is not None


def withdraw_individual(conn, event_id, user_id):
    entry = _individual_entry(conn, event_id, user_id)
    if not entry:
        raise HostError("没有找到你的个人报名", 404, code="no_own_signup")
    if entry["assignment_status"] == "assigned":
        raise HostError("你已经进入正式队伍，请联系队长或管理员调整", 409, code="already_in_lineup")
    conn.execute("DELETE FROM event_individual_registrations WHERE id=?", (entry["id"],))
    return entry["assignment_status"] == "reserve"


def clear_draft_assignments(conn, event_id):
    conn.execute(
        """UPDATE event_individual_registrations
           SET assignment_status='pending', team_number=NULL, assigned_at=NULL WHERE event_id=?""",
        (event_id,),
    )


def remove_individual(conn, event_id, entry_id):
    entry = conn.execute(
        """SELECT user_id, player_name, assignment_status FROM event_individual_registrations
           WHERE id=? AND event_id=?""",
        (entry_id, event_id),
    ).fetchone()
    if not entry:
        raise HostError("个人报名不存在", 404, code="missing_signup")
    if _pending_team_member(conn, event_id, entry["user_id"]):
        raise HostError(
            "该选手已经进入正式队伍，请在对应队伍中移除", 409, code="player_already_on_team"
        )
    conn.execute("DELETE FROM event_individual_registrations WHERE id=?", (entry_id,))
    reset_assignment = entry["assignment_status"] == "assigned"
    if reset_assignment:
        clear_draft_assignments(conn, event_id)
    return entry["player_name"], reset_assignment


def move_individual_to_reserve(conn, event_id, user_id):
    if not user_id:
        return
    conn.execute(
        """UPDATE event_individual_registrations
           SET assignment_status='reserve', team_number=NULL, assigned_at=CURRENT_TIMESTAMP
           WHERE event_id=? AND user_id=? AND assignment_status='assigned'""",
        (event_id, user_id),
    )
