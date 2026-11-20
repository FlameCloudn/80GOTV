"""Read managed lineup and freeze status without changing a match."""

from src.website.domains.events import roster_management as event_rosters
from src.website.domains.matches import participants
from src.website.domains.matches.maps import match_has_started
from src.website.runtime.database import row_get
from src.website.runtime.host import HostError


def review_rosters(conn, match):
    match_id = match["id"]
    event_id = match["event_id"]
    fixed = participants.sides(conn, match_id)
    rosters_frozen = participants.rosters_frozen(conn, match_id)
    bp_started = bool(row_get(match, "bp_state"))
    has_started = match_has_started(conn, match)
    ctrl = conn.execute(
        "SELECT archived_at FROM event_registration_control WHERE event_id=?", (event_id,)
    ).fetchone()
    event_archived = bool(ctrl and ctrl["archived_at"] is not None) or (
        match.get("status") == "completed"
    )
    admins_map = {
        r["id"]: r["username"] for r in conn.execute("SELECT id, username FROM admins").fetchall()
    }
    club_names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM teams").fetchall()}

    approved_by_side = {}
    all_player_ids = set()
    for side_num, side_info in fixed.items():
        approved = event_rosters.roster(conn, event_id, side_info["event_entrant_id"])
        approved_by_side[side_num] = approved
        all_player_ids.update(approved["initial_player_ids"])
        all_player_ids.update(approved["current_player_ids"])
        all_player_ids.update(p["id"] for p in side_info["players"])

    players_map = {}
    if all_player_ids:
        placeholders = ",".join("?" for _ in all_player_ids)
        for p in conn.execute(
            f"SELECT id, nickname, steam_id FROM players WHERE id IN ({placeholders})",
            tuple(all_player_ids),
        ):
            players_map[p["id"]] = dict(p)

    sides_out = {}
    freeze_blockers = []
    if bp_started or has_started:
        freeze_blockers.append("比赛已开始或已有 BP / 赛果记录，不能新建固定双方或重新冻结名单")
    if event_archived:
        freeze_blockers.append("本届赛事已归档，不能冻结新比赛名单")
    if len(fixed) != 2:
        freeze_blockers.append("请先确认本场的两支参赛队伍")
    elif any(s["frozen_at"] for s in fixed.values()) and not rosters_frozen:
        freeze_blockers.append("本场只有一侧已冻结，请核对原名单")

    seen_player_ids = set()
    seen_steam_ids = set()
    for side_num in (1, 2):
        side_info = fixed.get(side_num)
        if not side_info:
            sides_out[side_num] = None
            continue
        approved = approved_by_side[side_num]
        initial_ids = approved["initial_player_ids"]
        current_ids = approved["current_player_ids"]
        initial_set = set(initial_ids)
        current_set = set(current_ids)
        initial_players = [
            {
                "id": pid,
                "nickname": (players_map.get(pid) or {}).get("nickname") or f"#{pid}",
                "swapped_out": pid not in current_set,
            }
            for pid in initial_ids
        ]
        current_players = [
            {
                "id": pid,
                "nickname": (players_map.get(pid) or {}).get("nickname") or f"#{pid}",
                "is_added_sub": bool(approved["is_frozen"] and pid not in initial_set),
                "steam_id": str((players_map.get(pid) or {}).get("steam_id") or "").strip(),
            }
            for pid in current_ids
        ]
        kept_initial = len(initial_set & current_set) if approved["is_frozen"] else None

        frozen_meta = None
        frozen_players = []
        if side_info["frozen_at"]:
            mr = conn.execute(
                "SELECT frozen_by, frozen_at, team_name FROM match_rosters WHERE match_participant_id=?",
                (side_info["match_participant_id"],),
            ).fetchone()
            frozen_meta = {
                "frozen_at": mr["frozen_at"] if mr else side_info["frozen_at"],
                "frozen_by_name": admins_map.get(mr["frozen_by"], "") if mr else "",
                "frozen_team_name": mr["team_name"] if mr else side_info["name"],
            }
            frozen_players = [
                {
                    "slot": p["slot"],
                    "id": p["id"],
                    "nickname": p["nickname"] or f"#{p['id']}",
                    "is_substitute": bool(p["is_substitute"]),
                }
                for p in side_info["players"]
            ]

        team_archived = bool(
            side_info["group_status"] != "pending" or approved["team_archived_at"] is not None
        )
        if not rosters_frozen and not (bp_started or has_started or event_archived):
            if team_archived:
                freeze_blockers.append(f"{side_info['name']} 已归档，不能冻结新比赛名单")
            if not approved["is_frozen"]:
                freeze_blockers.append(f"{side_info['name']} 尚未在「报名与阵容」页确认初始五人")
            elif len(current_ids) != 5:
                freeze_blockers.append(f"{side_info['name']} 当前阵容不足 5 人")
            elif not event_rosters.keeps_initial_majority(initial_ids, current_ids):
                freeze_blockers.append(f"{side_info['name']} 当前阵容保留初始成员不足 3 名")
            if current_ids:
                try:
                    event_rosters.verify_registered_players(conn, event_id, current_ids)
                except HostError as exc:
                    freeze_blockers.append(f"{side_info['name']}：{exc.message}")
            steams = [p["steam_id"] for p in current_players]
            if len(current_ids) == 5 and (
                not all(steams)
                or len(set(steams)) != 5
                or (set(steams) & seen_steam_ids)
                or (set(current_ids) & seen_player_ids)
            ):
                freeze_blockers.append("本场十名选手须具备有效且互不重复的选手编号及 Steam ID")
            seen_player_ids.update(current_ids)
            seen_steam_ids.update(s for s in steams if s)

        sides_out[side_num] = {
            "event_entrant_id": side_info["event_entrant_id"],
            "registration_id": side_info["registration_id"],
            "name": side_info["name"],
            "short_name": side_info["short_name"],
            "club_name": club_names.get(side_info["team_id"], "") if side_info["team_id"] else "",
            "team_archived": team_archived,
            "initial_confirmed": bool(approved["is_frozen"]),
            "initial_confirmed_at": approved["confirmed_at"],
            "initial_players": initial_players,
            "current_players": current_players,
            "kept_initial_count": kept_initial,
            "frozen": bool(side_info["frozen_at"]),
            "frozen_at": frozen_meta["frozen_at"] if frozen_meta else "",
            "frozen_by_name": frozen_meta["frozen_by_name"] if frozen_meta else "",
            "frozen_team_name": frozen_meta["frozen_team_name"] if frozen_meta else "",
            "frozen_players": frozen_players,
        }

    # Deduplicate blocker messages while preserving order
    unique_blockers = list(dict.fromkeys(freeze_blockers))
    return {
        "is_managed": True,
        "rosters_frozen": rosters_frozen,
        "bp_started": bp_started,
        "has_started": has_started,
        "event_archived": event_archived,
        "can_freeze": not rosters_frozen and not unique_blockers,
        "freeze_blockers": unique_blockers,
        "sides": sides_out,
    }
