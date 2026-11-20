"""只读旧页面/导播合同。报名组用真实公开号码；展示占位永远不是选手号。"""

from src.website.domains.directory.team_names import team_abbr
from src.website.runtime.host import is_managed_event


def registration_groups(conn, event_id):
    groups = {}
    for row in conn.execute(
        """SELECT r.*,g.club_id,e.event_entrant_id,u.username AS creator_name,
                  CASE WHEN COALESCE(u.is_bashizhong_student,1)<>0 THEN u.group_username END
                  AS creator_group_username
           FROM event_registration_groups g JOIN event_registrations r ON r.id=g.registration_id
           LEFT JOIN users u ON u.id=r.creator_user_id
           LEFT JOIN event_entrants e ON e.registration_id=g.registration_id
           WHERE g.event_id=? ORDER BY r.created_at DESC,r.id DESC""",
        (event_id,),
    ):
        groups[row["id"]] = {"info": dict(row), "slots": []}
    for row in conn.execute(
        """SELECT * FROM host_registration_slots_read WHERE event_id=?
           ORDER BY registration_id,slot_index""",
        (event_id,),
    ):
        slot = dict(row)
        # 仅在边界保留桌面端可区分的负占位号，不能拿它认人或更新席位。
        slot["id"] = -(1000000 + slot["registration_id"] * 5 + slot["slot_index"])
        groups[slot["registration_id"]]["slots"].append(slot)
    return list(groups.values())


def individual_registrations(conn, event_id, current_user_id=None):
    entries = [
        dict(row)
        for row in conn.execute(
            """SELECT * FROM host_individual_entries_read WHERE event_id=?
           ORDER BY CASE assignment_status WHEN 'assigned' THEN 0 WHEN 'reserve' THEN 1 ELSE 2 END,
                    team_number,created_at,id""",
            (event_id,),
        )
    ]
    reserves = [e for e in entries if e["assignment_status"] == "reserve"]
    members = [e for e in entries if e["is_formal_member"]]
    return {
        "entries": entries,
        "teams": [],
        "reserves": reserves,
        "pending": [e for e in entries if e["assignment_status"] == "pending"],
        "formal_members": members,
        "current_entry": next((e for e in entries if e["user_id"] == current_user_id), None),
        "has_assignment": bool(members or reserves),
        "has_formal_members": bool(members),
        "can_randomize": False,
        "count": len(entries),
        "individual_count": len(entries) - len(reserves),
        "substitute_count": len(reserves),
    }


def event_team_cards(groups):
    cards = []
    for group in groups:
        info = group["info"]
        players = [
            {**s, "id": s["player_id"], "nickname": s["player_name"], "slot": s["slot_index"] + 1}
            for s in group["slots"]
            if s["player_id"] is not None
        ]
        cards.append(
            {
                "id": info["club_id"],
                "registration_id": info["id"],
                "event_entrant_id": info["event_entrant_id"],
                "name": info["team_name"],
                "short_name": team_abbr(info["team_name"]),
                "logo": info["team_logo"] or "",
                "is_temp": info["club_id"] is None,
                "players": players,
            }
        )
    return cards


def public_event(conn, row):
    event = dict(row)
    if is_managed_event(conn, event["id"]):
        control = conn.execute(
            """SELECT archived_at IS NULL AND registration_deadline>unixepoch() AS before_cutoff,
                      (SELECT count(*) FROM event_registration_groups WHERE event_id=c.event_id) AS team_count
               FROM event_registration_control c WHERE event_id=?""",
            (event["id"],),
        ).fetchone()
        event.update(
            registration_open=bool(event["registration_open"] and control["before_cutoff"]),
            team_count=control["team_count"],
        )
    return event
