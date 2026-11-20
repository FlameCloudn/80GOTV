"""正式宿主的固定对阵和本场冻结名单。写入由调用方持有同一笔事务。"""

from time import time

from src.website.domains.directory.team_names import team_abbr
from src.website.domains.events.registration import active_event
from src.website.runtime.host import HostError, is_managed_event

SIDE_NUMBERS = {"home": 1, "away": 2}


def select_entrant(conn, event_id, *, entrant_id=None, club_id=None, player_ids=None):
    """把旧表单的目录队号或明确选中的五人转换成唯一的本届参赛方。"""
    query = """
        SELECT e.event_entrant_id
        FROM event_entrants e
        JOIN event_initial_rosters i ON i.event_entrant_id=e.event_entrant_id
        JOIN event_registration_groups g ON g.event_id=e.event_id
                                        AND g.registration_id=e.registration_id
        JOIN event_registrations r ON r.id=e.registration_id AND r.event_id=e.event_id
        WHERE e.event_id=? AND r.status='pending' AND g.archived_at IS NULL
    """
    args = [event_id]
    if entrant_id is not None:
        query += " AND e.event_entrant_id=?"
        args.append(entrant_id)
    elif club_id is not None:
        query += " AND g.club_id=?"
        args.append(club_id)
    else:
        if player_ids is None or len(player_ids) != 5 or len(set(player_ids)) != 5:
            raise HostError("请选择该赛事一支已确认队伍的完整五人名单", 400)
        query += """
            AND (SELECT COUNT(*) FROM event_current_members c
                 WHERE c.event_entrant_id=e.event_entrant_id AND c.event_id=e.event_id)=5
            AND (SELECT COUNT(*) FROM event_current_members c
                 WHERE c.event_entrant_id=e.event_entrant_id AND c.event_id=e.event_id
                   AND c.player_id IN (?,?,?,?,?))=5
        """
        args.extend(player_ids)
    found = conn.execute(query, args).fetchall()
    if len(found) != 1:
        raise HostError("无法唯一确定该赛事已确认的参赛队伍，请核对所选队伍或五人名单")
    return found[0]["event_entrant_id"]


def check_duplicate(conn, event_id, match_time, entrant_ids, *, exclude_id=None):
    """同届、同一时点和同一对手的比赛只登记一次，与左右输入顺序无关。"""
    match_time = conn.execute("SELECT datetime(?)", (match_time,)).fetchone()[0]
    if match_time is None:
        raise HostError("比赛时间格式无效", 400)
    row = conn.execute(
        """SELECT m.id FROM matches m JOIN match_participants p ON p.match_id=m.id
           WHERE m.event_id=? AND datetime(m.match_time)=? AND m.id IS NOT ?
             AND p.event_entrant_id IN (?,?)
           GROUP BY m.id HAVING COUNT(*)=2 LIMIT 1""",
        (event_id, match_time, exclude_id, *entrant_ids),
    ).fetchone()
    if row:
        raise HostError("相同赛事、时间和参赛方的比赛已存在")


def bind(conn, match_id, home_id, away_id):
    """建立本场始终不换义的两侧，重复绑定相同对阵不新发编号。"""
    match = _scheduled_match(conn, match_id)
    if home_id == away_id:
        raise HostError("两支参赛队伍不能相同", 400)
    fixed = {
        row["side_key"]: row["event_entrant_id"]
        for row in conn.execute(
            "SELECT side_key,event_entrant_id FROM match_participants WHERE match_id=?", (match_id,)
        )
    }
    requested = {"home": home_id, "away": away_id}
    if fixed:
        if fixed != requested:
            raise HostError("比赛双方已绑定，不能互换或改绑")
        return
    _require_prematch(conn, match)
    for entrant_id in requested.values():
        select_entrant(conn, match["event_id"], entrant_id=entrant_id)
    check_duplicate(
        conn, match["event_id"], match["match_time"], (home_id, away_id), exclude_id=match_id
    )
    conn.executemany(
        """INSERT INTO match_participants(match_id,event_id,event_entrant_id,side_key)
           VALUES (?,?,?,?)""",
        [(match_id, match["event_id"], entrant_id, side) for side, entrant_id in requested.items()],
    )


def _scheduled_match(conn, match_id):
    match = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
    if not match:
        raise HostError("比赛不存在", 404)
    if not is_managed_event(conn, match["event_id"]):
        raise HostError("该比赛仍使用原有名单流程")
    return match


def _require_prematch(conn, match):
    from src.website.domains.matches.maps import match_has_started

    active_event(conn, match["event_id"], int(time()))
    if (
        match["status"] != "upcoming"
        or match["bp_state"]
        or match["roster_snapshot"]
        or match_has_started(conn, match)
    ):
        raise HostError("比赛已有开赛、BP 或历史记录，不能新建固定双方或重新冻结名单")


def _fixed_sides(conn, match_id):
    rows = conn.execute(
        """SELECT p.match_participant_id,p.event_id,p.event_entrant_id,p.side_key,
                  e.registration_id,g.club_id AS team_id,r.creator_user_id,r.status AS group_status,
                  COALESCE(f.team_name,r.team_name) AS name,
                  COALESCE(f.team_logo,NULLIF(r.team_logo,''),t.logo,'') AS logo,
                  COALESCE(f.short_name,NULLIF(t.short_name,'')) AS short_name,f.frozen_at
           FROM match_participants p
           JOIN event_entrants e ON e.event_entrant_id=p.event_entrant_id AND e.event_id=p.event_id
           JOIN event_registration_groups g ON g.registration_id=e.registration_id AND g.event_id=p.event_id
           JOIN event_registrations r ON r.id=e.registration_id AND r.event_id=p.event_id
           LEFT JOIN teams t ON t.id=g.club_id
           LEFT JOIN match_rosters f ON f.match_participant_id=p.match_participant_id
           WHERE p.match_id=?""",
        (match_id,),
    )
    fixed = {}
    for row in rows:
        side = dict(row)
        side["short_name"] = side["short_name"] or team_abbr(side["name"])
        fixed[SIDE_NUMBERS[side["side_key"]]] = side
    return fixed


def _participants_players(conn, side):
    if side["frozen_at"]:
        roster_query = """
            SELECT p.id,p.nickname,p.group_username_override,p.avatar,p.is_bashizhong_student,
                   m.roster_slot AS slot,m.steam_id,m.is_substitute
            FROM match_roster_members m JOIN players p ON p.id=m.player_id
            WHERE m.match_participant_id=? ORDER BY m.roster_slot
        """
        params = (side["match_participant_id"],)
        roster_source = "match_roster"
    else:
        roster_query = """
            SELECT p.id,p.nickname,p.group_username_override,p.avatar,p.is_bashizhong_student,
                   c.roster_slot+1 AS slot,p.steam_id,
                   NOT EXISTS (SELECT 1 FROM event_initial_members i
                               WHERE i.event_entrant_id=c.event_entrant_id
                                 AND i.player_id=c.player_id) AS is_substitute
            FROM event_current_members c JOIN players p ON p.id=c.player_id
            WHERE c.event_entrant_id=? AND c.event_id=? ORDER BY c.roster_slot
        """
        params = (side["event_entrant_id"], side["event_id"])
        roster_source = "registration"
    return [
        {
            **dict(row),
            "team_id": side["team_id"],
            "roster_source": roster_source,
            "roster_frozen": bool(side["frozen_at"]),
            "is_substitute": bool(row["is_substitute"]),
        }
        for row in conn.execute(roster_query, params)
    ]


def sides(conn, match_id):
    """按固定边号 1/2 给读者准备对阵和名单。不从旧队号或名称猜队。"""
    fixed = _fixed_sides(conn, match_id)
    for side in fixed.values():
        side["players"] = _participants_players(conn, side)
    return fixed


def rosters_frozen(conn, match_id):
    row = conn.execute(
        """SELECT COUNT(*) AS members FROM match_participants p
           JOIN match_roster_members r ON r.match_participant_id=p.match_participant_id
           WHERE p.match_id=?""",
        (match_id,),
    ).fetchone()
    return row["members"] == 10


def freeze_rosters(conn, match_id, admin_id):
    """按托管赛事有效名单显式冻结双方，每方恰五人；不记录实际出场。"""
    from src.website.domains.events.roster_management import (
        keeps_initial_majority,
        roster,
        verify_registered_players,
    )

    match = _scheduled_match(conn, match_id)
    if not conn.execute("SELECT 1 FROM admins WHERE id=?", (admin_id,)).fetchone():
        raise HostError("只有管理员可以冻结本场名单", 403)
    fixed = sides(conn, match_id)
    if len(fixed) != 2:
        raise HostError("请先确认本场的两支参赛队伍")
    if rosters_frozen(conn, match_id):
        return fixed
    if any(side["frozen_at"] for side in fixed.values()):
        raise HostError("本场只有一侧已冻结，请核对原名单，未变更")
    _require_prematch(conn, match)

    ids, steam_ids = set(), set()
    for side in fixed.values():
        approved = roster(conn, match["event_id"], side["event_entrant_id"])
        if side["group_status"] != "pending" or approved["team_archived_at"] is not None:
            raise HostError("参赛队伍已归档，不能冻结新比赛名单")
        selected = [p["id"] for p in side["players"]]
        verify_registered_players(conn, match["event_id"], selected)
        steam = [str(p["steam_id"] or "").strip() for p in side["players"]]
        if (
            not approved["is_frozen"]
            or len(selected) != 5
            or len(set(selected)) != 5
            or [p["slot"] for p in side["players"]] != [1, 2, 3, 4, 5]
            or selected != list(approved["current_player_ids"])
        ):
            raise HostError("本场两边都必须使用已确认的本届五人名单")
        if not keeps_initial_majority(approved["initial_player_ids"], selected):
            raise HostError("本场名单必须保留至少三名本届初始选手")
        if not all(steam) or len(set(steam)) != 5 or set(steam) & steam_ids or set(selected) & ids:
            raise HostError("本场十名选手须有不同的选手编号及 Steam ID")
        for player, steam_id in zip(side["players"], steam):
            player["steam_id"] = steam_id
        ids.update(selected)
        steam_ids.update(steam)

    for side in fixed.values():
        key = side["match_participant_id"]
        conn.execute(
            """INSERT INTO match_rosters(match_participant_id,frozen_by,team_name,short_name,team_logo)
               VALUES (?,?,?,?,?)""",
            (key, admin_id, side["name"], side["short_name"], side["logo"]),
        )
        conn.executemany(
            """INSERT INTO match_roster_members(match_participant_id,roster_slot,player_id,steam_id,is_substitute)
               VALUES (?,?,?,?,?)""",
            [(key, p["slot"], p["id"], p["steam_id"], p["is_substitute"]) for p in side["players"]],
        )
    return sides(conn, match_id)
