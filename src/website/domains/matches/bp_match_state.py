"""Read BP match eligibility and persist the resulting map plan."""

import json

from src.website.domains.matches import bp_manager as rules
from src.website.domains.matches.bp_log import format_bp_log
from src.website.domains.matches.maps import clear_bp_plan, save_bp_plan
from src.website.domains.matches.match_roster_service import resolve_match_roster
from src.website.domains.matches.opponents import supplement_temp_teams
from src.website.runtime.host import is_managed_match


def window_is_open(match):
    return bool(match and str(match["status"] or "").lower() not in {"completed", "cancelled"})


def change_lock_error(match):
    if not window_is_open(match):
        return "比赛已结束或取消，不能重置或撤回 BP"
    fields = ["team1_score", "team2_score"]
    fields.extend(f"map{slot}_t{side}" for slot in range(1, 6) for side in (1, 2))
    if any(match[field] not in (None, 0, "0", "") for field in fields):
        return "比赛已产生比分，不能重置或撤回 BP"
    return None


def clear_generated_maps(conn, match_id, bo_format):
    if is_managed_match(conn, match_id):
        clear_bp_plan(conn, match_id, bo_format)
        conn.execute("UPDATE matches SET bp_process=NULL WHERE id=?", (match_id,))
        return
    updates: dict[str, int | None] = {f"map{slot}": None for slot in range(1, 6)}
    updates.update({f"map{slot}_picked_by": None for slot in range(1, 6)})
    updates.update(
        {
            "bp_process": None,
            "decider_knife_winner": None,
            "decider_start_side": None,
            "has_map3": int(bo_format in ("BO3", "BO5")),
            "has_map4": int(bo_format == "BO5"),
            "has_map5": int(bo_format == "BO5"),
        }
    )
    conn.execute(
        "UPDATE matches SET " + ", ".join(f"{field}=?" for field in updates) + " WHERE id=?",
        (*updates.values(), match_id),
    )


def _get_player_team(player, match, conn):
    """确定选手属于 t1 还是 t2，无法确定返回 None。"""
    if not player:
        return None
    steam_id = str(player["steam_id"] or "").strip()
    return resolve_match_roster(conn, match)["side_by_steam_id"].get(steam_id)


def parse_bp_state(raw):
    if raw:
        try:
            state = json.loads(raw) if isinstance(raw, str) else raw
            return state, rules.normalize_bp_state(state)
        except (TypeError, ValueError):
            pass
    return None, False


def ensure_bp_started(conn, match):
    """旧比赛可升级已存状态；托管比赛的读取不得写入地图或 BP。"""
    raw = match["bp_state"] if "bp_state" in match.keys() else None
    state, changed = parse_bp_state(raw)
    if not changed or is_managed_match(conn, match["id"]):
        return state, False
    updated = conn.execute(
        "UPDATE matches SET bp_state=? WHERE id=? AND bp_state=?",
        (json.dumps(state, ensure_ascii=False), match["id"], raw),
    )
    if updated.rowcount:
        return state, True
    latest = conn.execute("SELECT id,bp_state FROM matches WHERE id=?", (match["id"],)).fetchone()
    return ensure_bp_started(conn, latest) if latest else (None, False)


def map_pool(raw):
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    return raw if isinstance(raw, list) else None


def find_match(conn, match_id):
    return conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()


def player_team_for_account(conn, match, user_id):
    if user_id is None:
        return None
    account = conn.execute(
        "SELECT steam_id64 AS steam_id FROM users WHERE id=?", (user_id,)
    ).fetchone()
    if not account or not account["steam_id"]:
        return None
    return _get_player_team(account, match, conn)


def lock_match(conn, match_id):
    # Read the shared JSON only after reserving the writer, even on older libSQL databases.
    if is_managed_match(conn, match_id):
        conn.execute("BEGIN IMMEDIATE")
    else:
        conn.execute("UPDATE matches SET bp_state=bp_state WHERE id=?", (match_id,))
    return find_match(conn, match_id)


def persist_state(conn, match_id, state):
    conn.execute(
        "UPDATE matches SET bp_state=? WHERE id=?",
        (json.dumps(state, ensure_ascii=False), match_id),
    )


def save_action(conn, match_id, state):
    if state["status"] == "completed":
        return save_bp_to_match(conn, match_id, state)
    persist_state(conn, match_id, state)
    return True


def save_bp_to_match(conn, match_id, state):
    """
    将 BP 结果保存到 matches 表
    更新 map_pool, map1-5, map*_picked_by, bp_process
    """
    if state["status"] != "completed":
        return False

    map_order = state["map_order"]
    bo = state["bo"].upper()
    expected_count = rules.FORMAT_MAP_COUNTS.get(bo)
    if expected_count is None or len(map_order) != expected_count:
        return False
    if len({rules._storage_map_name(name) for name in map_order}) != len(map_order):
        return False

    managed = is_managed_match(conn, match_id)
    if (
        managed
        or conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='teams'"
        ).fetchone()
    ):
        match_row = conn.execute(
            """SELECT m.*,
                      t1.name AS team1_name, t2.name AS team2_name,
                      t1.short_name AS t1s, t2.short_name AS t2s
               FROM matches m
               LEFT JOIN teams t1 ON t1.id=m.team1_id
               LEFT JOIN teams t2 ON t2.id=m.team2_id
               WHERE m.id=?""",
            (match_id,),
        ).fetchone()
        filled = supplement_temp_teams(match_row, conn)
        team1_name = filled.get("team1_name") or "TBD"
        team2_name = filled.get("team2_name") or "TBD"
    else:
        # Old single-table match archives have no team directory.
        team1_name, team2_name = "TBD", "TBD"

    updates: dict[str, object] = {
        "bp_process": format_bp_log(state, team1_name, team2_name),
        "bp_state": json.dumps(state, ensure_ascii=False),
        "map_pool": json.dumps(state.get("initial_pool", rules.ALL_MAPS), ensure_ascii=False),
    }

    if managed:
        picks = {pick["map"]: pick for pick in state["picks"]}
        if len(picks) != len(map_order) or any(name not in picks for name in map_order):
            return False
        plan = []
        for name in map_order:
            pick = picks[name]
            picker = pick.get("picked_by")
            chooser = pick.get("side_team") or rules._opposite_team(picker)
            if picker == "remaining" and bo == "BO1" and not chooser:
                chooser = rules._bo1_remaining_side_team(state)
            plan.append((rules._storage_map_name(name), picker, chooser, pick.get("side")))
        save_bp_plan(conn, match_id, bo, plan)
        conn.execute(
            "UPDATE matches SET bp_process=?,bp_state=?,map_pool=? WHERE id=?",
            (updates["bp_process"], updates["bp_state"], updates["map_pool"], match_id),
        )
        return True

    # Legacy slots must also clear any maps left by a previous, longer series.
    picks = {pick["map"]: pick.get("picked_by") for pick in state["picks"]}
    for slot in range(1, 6):
        name = map_order[slot - 1] if slot <= len(map_order) else None
        picker = picks.get(name)
        updates[f"map{slot}"] = rules._storage_map_name(name) if name else None
        updates[f"map{slot}_picked_by"] = (
            "decider" if picker == "remaining" else picker if picker in ("t1", "t2") else None
        )
        if slot >= 3:
            updates[f"has_map{slot}"] = int(slot <= expected_count)
    conn.execute(
        "UPDATE matches SET " + ", ".join(f"{key}=?" for key in updates) + " WHERE id=?",
        (*updates.values(), match_id),
    )
    return True
