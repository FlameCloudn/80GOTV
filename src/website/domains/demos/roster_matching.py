"""根据比赛当时的名单、队名、Steam ID 与历史昵称识别 Demo 中的 A/B 队。"""

from dataclasses import dataclass

from src.website.domains.directory.player_service import load_unique_player_alias_ids
from src.website.domains.matches.match_roster_service import match_player_ids
from src.website.runtime.database import row_get


@dataclass
class RosterPairing:
    team1_id: int | None
    team2_id: int | None
    team1_roster: set
    team2_roster: set
    demo_a: set
    demo_b: set
    players: dict
    a_to_t1: bool | None


def _stored_team_id(value):
    # 旧临时队用 -1/-2 占位，不能作为长期队伍 ID 写入统计外键。
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _show_preview_match(stat, rows, aliases, team_ids, roster):
    # 可供管理员核对的同名建议不等于允许导入的身份。
    steam = [p for p in rows if p["steam_id"] and str(stat["steam_id"]) == str(p["steam_id"])]
    name = stat["name"].casefold()
    hint = next((p for p in steam if p["team_id"] in team_ids or p["id"] in roster), None)
    key = "db_player"
    if hint is None:
        key = "db_player_by_name"
        hint = (
            steam[-1]
            if steam
            else next(
                (
                    p
                    for p in rows
                    if (p["team_id"] in team_ids or p["id"] in roster)
                    and (name == p["nickname"].casefold() or aliases.get(name) == p["id"])
                ),
                None,
            )
        )
    if hint is not None:
        stat[key] = {field: hint[field] for field in ("nickname", "team_name", "id", "team_id")}


def resolve_rosters(conn, match, info, players, *, preview=False):
    rows = conn.execute(
        "SELECT p.*, t.name AS team_name FROM players p LEFT JOIN teams t ON p.team_id=t.id"
    ).fetchall()
    aliases = load_unique_player_alias_ids(conn)
    team1, team2 = (_stored_team_id(match[key]) for key in ("team1_id", "team2_id"))
    roster1, roster2 = (match_player_ids(conn, match, side) for side in (1, 2))
    matched, a_ids, b_ids = {}, set(), set()
    for stat in players:
        if preview:
            _show_preview_match(
                stat, rows, aliases, (match["team1_id"], match["team2_id"]), roster1 | roster2
            )
        player = _match_player_from_db(stat, rows, aliases)
        matched[stat["steam_id"]] = player
        if player and stat.get("team_letter") in ("A", "B"):
            (a_ids if stat["team_letter"] == "A" else b_ids).add(player["id"])
    order = _infer_demo_team_order(info, match, a_ids, b_ids, rows, roster1, roster2, team1, team2)
    return RosterPairing(team1, team2, roster1, roster2, a_ids, b_ids, matched, order)


def _match_player_from_db(stat, db_players, alias_player_ids=None):
    """从数据库选手列表中匹配 demo 选手（先按 steam_id，再按昵称）"""
    for db_p in db_players:
        if db_p["steam_id"] and str(stat["steam_id"]) == str(db_p["steam_id"]):
            return db_p
    name = str(stat.get("name") or "").strip().casefold()
    candidates = {
        db_p["id"]: db_p
        for db_p in db_players
        if name and name == str(db_p["nickname"] or "").strip().casefold()
    }
    alias_player_id = (alias_player_ids or {}).get(stat["name"].casefold())
    if alias_player_id:
        candidates.update(
            {db_p["id"]: db_p for db_p in db_players if db_p["id"] == alias_player_id}
        )
    if len(candidates) == 1:
        candidate = next(iter(candidates.values()))
        if not candidate["steam_id"] or str(candidate["steam_id"]) == str(
            stat.get("steam_id") or ""
        ):
            return candidate
    return None


def _normalise_team_name(value):
    """用稳定的字母数字串比较 Demo 和网站里的队名。"""
    return "".join(ch.casefold() for ch in str(value or "") if ch.isalnum())


def _team_name_matches(left, right):
    left_key = _normalise_team_name(left)
    right_key = _normalise_team_name(right)
    return bool(
        left_key
        and right_key
        and (left_key == right_key or left_key in right_key or right_key in left_key)
    )


def _infer_demo_team_order(
    info,
    match,
    demo_a_db_ids,
    demo_b_db_ids,
    db_players,
    t1_pids_set,
    t2_pids_set,
    t1_key,
    t2_key,
):
    """把 Demo 的 A/B 队映射到比赛的固定左右队伍，避免顺序被 Demo 反转。"""
    demo_a_name = info.get("team_a_name", "")
    demo_b_name = info.get("team_b_name", "")
    match_t1_name = row_get(match, "team1_name", "")
    match_t2_name = row_get(match, "team2_name", "")

    def orientation(direct, reverse):
        if direct and not reverse:
            return True
        if reverse and not direct:
            return False
        return None

    # 比赛当时固定的名单比选手今天所在的队伍可靠；A/B 两边都参与核对。
    direct = len(demo_a_db_ids & t1_pids_set) + len(demo_b_db_ids & t2_pids_set)
    reverse = len(demo_a_db_ids & t2_pids_set) + len(demo_b_db_ids & t1_pids_set)
    if direct or reverse:
        return orientation(direct, reverse)

    direct = _team_name_matches(demo_a_name, match_t1_name) or _team_name_matches(
        demo_b_name, match_t2_name
    )
    reverse = _team_name_matches(demo_a_name, match_t2_name) or _team_name_matches(
        demo_b_name, match_t1_name
    )
    if direct or reverse:
        return orientation(direct, reverse)

    # 已有明确比赛阵容时，不能再用今天的长期队籍猜测方向。
    if (
        t1_pids_set
        or t2_pids_set
        or row_get(match, "roster_snapshot")
        or row_get(match, "team1_registration_id")
        or row_get(match, "team2_registration_id")
        or row_get(match, "team1_players") not in (None, "")
        or row_get(match, "team2_players") not in (None, "")
    ):
        return None

    db_by_id = {row["id"]: row for row in db_players}
    current_t1 = {
        pid for pid, row in db_by_id.items() if t1_key is not None and row["team_id"] == t1_key
    }
    current_t2 = {
        pid for pid, row in db_by_id.items() if t2_key is not None and row["team_id"] == t2_key
    }
    direct = len(demo_a_db_ids & current_t1) + len(demo_b_db_ids & current_t2)
    reverse = len(demo_a_db_ids & current_t2) + len(demo_b_db_ids & current_t1)
    if direct or reverse:
        return orientation(direct, reverse)
    return None
