"""
比赛计算工具函数：BO 地图数、raw_maps 构建、地图胜场计算
"""

import json

from utils.helpers import row_get


def _normalize_map_name_for_match(map_name):
    raw = str(map_name or "").strip().lower().replace(" ", "_")
    return raw[3:] if raw.startswith("de_") else raw


def _pick_opening_ct_team_from_bp(match_row, slot_index):
    bp_raw = row_get(match_row, "bp_state")
    if not bp_raw:
        return None

    try:
        state = json.loads(bp_raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None

    if not isinstance(state, dict):
        return None

    picks = state.get("picks")
    if not isinstance(picks, list):
        return None

    map_name = row_get(match_row, f"map{slot_index + 1}")
    normalized_map = _normalize_map_name_for_match(map_name)
    if not normalized_map:
        return None

    target_pick = None
    for pick in picks:
        if not isinstance(pick, dict):
            continue
        if _normalize_map_name_for_match(pick.get("map")) == normalized_map:
            target_pick = pick
            break

    if not target_pick:
        return None

    side = target_pick.get("side")
    side_team = target_pick.get("side_team")
    if not side_team and target_pick.get("picked_by") in {"t1", "t2"}:
        side_team = "t2" if target_pick["picked_by"] == "t1" else "t1"
    if side == "CT" and side_team in {"t1", "t2"}:
        return side_team
    if side == "T" and side_team in {"t1", "t2"}:
        return "t2" if side_team == "t1" else "t1"
    return None


def get_bo_max_maps(bo_format):
    """根据 BO 格式返回最大地图数"""
    if not bo_format:
        return 3
    bo = bo_format.upper()
    if bo == "BO5":
        return 5
    elif bo == "BO1":
        return 1
    else:
        return 3  # BO3 或未知


def get_demo_upload_slot_count(match_row):
    """返回 Demo 上传框数量：进行中按 BO 上限，结束后按实际地图数。"""
    bo_max = get_bo_max_maps(row_get(match_row, "bo_format", "BO3"))
    if row_get(match_row, "status", "") != "completed":
        return bo_max
    team1_score = int(row_get(match_row, "team1_score", 0) or 0)
    team2_score = int(row_get(match_row, "team2_score", 0) or 0)
    wins_needed = bo_max // 2 + 1
    if max(team1_score, team2_score) < wins_needed:
        return bo_max
    return min(team1_score + team2_score, bo_max)


def get_demo_map_names(match_row):
    """返回当前比赛允许导入 Demo 的地图槽位。"""
    slot_count = get_demo_upload_slot_count(match_row)
    return [row_get(match_row, f"map{i}", "") for i in range(1, slot_count + 1)]


def build_raw_maps(match_row, include_picked_by=True):
    """
    从比赛行数据构建地图列表。
    返回 list of (map_name, t1_score, t2_score, active, picked_by)
    """
    raw = [
        (
            row_get(match_row, "map1"),
            row_get(match_row, "map1_t1"),
            row_get(match_row, "map1_t2"),
            True,
            row_get(match_row, "map1_picked_by", ""),
        ),
        (
            row_get(match_row, "map2"),
            row_get(match_row, "map2_t1"),
            row_get(match_row, "map2_t2"),
            True,
            row_get(match_row, "map2_picked_by", ""),
        ),
        (
            row_get(match_row, "map3"),
            row_get(match_row, "map3_t1"),
            row_get(match_row, "map3_t2"),
            bool(row_get(match_row, "has_map3", 1)),
            row_get(match_row, "map3_picked_by", ""),
        ),
        (
            row_get(match_row, "map4"),
            row_get(match_row, "map4_t1"),
            row_get(match_row, "map4_t2"),
            bool(row_get(match_row, "has_map4", 1)),
            row_get(match_row, "map4_picked_by", ""),
        ),
        (
            row_get(match_row, "map5"),
            row_get(match_row, "map5_t1"),
            row_get(match_row, "map5_t2"),
            bool(row_get(match_row, "has_map5", 1)),
            row_get(match_row, "map5_picked_by", ""),
        ),
    ]
    if include_picked_by:
        return raw
    return [(mn, t1, t2, active) for mn, t1, t2, active, _pb in raw]


def calculate_map_wins(match_row, raw_maps=None):
    """
    从比赛行计算双方地图胜场数。
    返回 (t1_wins, t2_wins)
    """
    if raw_maps is None:
        raw_maps = build_raw_maps(match_row, include_picked_by=False)

    t1_wins = 0
    t2_wins = 0
    for map_row in raw_maps:
        mn, t1s, t2s, active = map_row[0], map_row[1], map_row[2], map_row[3]
        if mn and active:
            s1 = int(t1s or 0)
            s2 = int(t2s or 0)
            if s1 > s2:
                t1_wins += 1
            elif s2 > s1:
                t2_wins += 1
    return t1_wins, t2_wins


def parse_map_halves(match_row):
    """读取新旧两种半场 JSON。"""
    raw = row_get(match_row, "map_halves")
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def get_map_half_scores(match_row, slot_index, parsed_halves=None):
    """把旧版 map1/t1_h1 与新版 0/h1_t1 整理为同一种格式。"""
    halves = parsed_halves if parsed_halves is not None else parse_map_halves(match_row)
    item = halves.get(str(slot_index)) or halves.get(f"map{slot_index + 1}")
    if not isinstance(item, dict):
        return None
    opening_ct_team = item.get("opening_ct_team") or item.get("opening_ct_side_team")
    opening_from_bp = False
    if opening_ct_team not in {"t1", "t2"}:
        opening_ct_team = _pick_opening_ct_team_from_bp(match_row, slot_index)
        opening_from_bp = True
    side_source = item.get("side_source") or "unknown"
    if opening_from_bp and opening_ct_team in {"t1", "t2"} and side_source == "unknown":
        side_source = "website_bp"
    return {
        "h1_t1": item.get("h1_t1", item.get("t1_h1", 0)),
        "h1_t2": item.get("h1_t2", item.get("t2_h1", 0)),
        "h2_t1": item.get("h2_t1", item.get("t1_h2", 0)),
        "h2_t2": item.get("h2_t2", item.get("t2_h2", 0)),
        "opening_ct_team": opening_ct_team if opening_ct_team in {"t1", "t2"} else None,
        "side_source": side_source,
    }


def build_result_maps(match_row):
    """为赛果列表准备每张已完成地图的比分与半场比分。"""
    parsed_halves = parse_map_halves(match_row)
    result_maps = []
    for slot_index, map_row in enumerate(build_raw_maps(match_row)):
        map_name, t1_score, t2_score, active = map_row[0], map_row[1], map_row[2], map_row[3]
        if not map_name or not active or not (int(t1_score or 0) or int(t2_score or 0)):
            continue
        result_maps.append(
            {
                "name": map_name,
                "t1": t1_score or 0,
                "t2": t2_score or 0,
                "halves": get_map_half_scores(match_row, slot_index, parsed_halves),
            }
        )
    return result_maps


# SQL fragments for computed match status.
# 规则：状态可以是手动设的 completed/live/upcoming。
# 新建比赛固定保存为 upcoming；到达开赛时间后也必须自动进入 live，
# 否则管理员稍晚创建的比赛会同时从比赛和赛果页面消失。
_SQL_MATCH_COMPLETED = (
    "(COALESCE(m.status, '') = 'completed'"
    " OR (m.match_time IS NOT NULL"
    "     AND datetime(m.match_time) < datetime('now', 'localtime', '-1 day')"
    "     AND COALESCE(m.status, '') NOT IN ('live', 'cancelled')))"
)
_SQL_MATCH_UPCOMING = (
    "(COALESCE(m.status, '') NOT IN ('completed', 'live', 'cancelled')"
    " AND (m.match_time IS NULL OR datetime(m.match_time) > datetime('now', 'localtime')))"
)
_SQL_MATCH_LIVE = (
    "(COALESCE(m.status, '') = 'live'"
    " OR (COALESCE(m.status, '') NOT IN ('completed', 'cancelled')"
    "     AND m.match_time IS NOT NULL"
    "     AND datetime(m.match_time) >= datetime('now', 'localtime', '-1 day')"
    "     AND datetime(m.match_time) <= datetime('now', 'localtime')))"
)
_SQL_EFFECTIVE_STATUS = (
    "CASE"
    " WHEN COALESCE(m.status, '') = 'cancelled' THEN 'cancelled'"
    " WHEN COALESCE(m.status, '') = 'completed' THEN 'completed'"
    " WHEN m.match_time IS NOT NULL"
    "      AND datetime(m.match_time) < datetime('now', 'localtime', '-1 day')"
    "      AND COALESCE(m.status, '') NOT IN ('live', 'cancelled') THEN 'completed'"
    " WHEN COALESCE(m.status, '') = 'live' THEN 'live'"
    " WHEN m.match_time IS NOT NULL"
    "      AND datetime(m.match_time) >= datetime('now', 'localtime', '-1 day')"
    "      AND datetime(m.match_time) <= datetime('now', 'localtime')"
    "      AND COALESCE(m.status, '') NOT IN ('completed', 'cancelled') THEN 'live'"
    " ELSE 'upcoming' END AS effective_status"
)


def get_sql_match_completed():
    return _SQL_MATCH_COMPLETED


def get_sql_match_upcoming():
    return _SQL_MATCH_UPCOMING


def get_sql_match_live():
    return _SQL_MATCH_LIVE


def get_sql_effective_status():
    return _SQL_EFFECTIVE_STATUS
