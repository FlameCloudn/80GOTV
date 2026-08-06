"""
在线 BP (Ban/Pick) 状态管理器

BP 流程:
  BO1: ban2-ban3-ban1 -> 剩下 1 图，由未执行最后一次 Ban 的队伍选边
  BO3: ban1-ban1-pick1-pick1-ban1-ban1 -> 剩下 1 图 (即 3 图: 2 pick + 1 剩)
  BO5: ban1-ban1-pick1-pick1-pick1-pick1 -> 剩下 1 图 (即 5 图: 4 pick + 1 剩)

先手通过 roll 点决定 (1-100 随机数, 大者选择先/后)
选边: 被选图的对手选 CT/T
"""

import json
import random

ALL_MAPS = ["Dust2", "Mirage", "Inferno", "Nuke", "Cache", "Ancient", "Anubis"]
_MAP_STORAGE_NAMES = {
    "dust2": "de_dust2",
    "mirage": "de_mirage",
    "inferno": "de_inferno",
    "nuke": "de_nuke",
    "cache": "de_cache",
    "ancient": "de_ancient",
    "anubis": "de_anubis",
}
STATE_VERSION = 6

FORMAT_STEPS = {
    "BO1": [
        {"action": "ban", "team": "first", "count": 2},
        {"action": "ban", "team": "second", "count": 3},
        {"action": "ban", "team": "first", "count": 1},
    ],
    "BO3": [
        {"action": "ban", "team": "first", "count": 1},
        {"action": "ban", "team": "second", "count": 1},
        {"action": "pick", "team": "first", "count": 1},
        {"action": "pick", "team": "second", "count": 1},
        {"action": "ban", "team": "first", "count": 1},
        {"action": "ban", "team": "second", "count": 1},
    ],
    "BO5": [
        {"action": "ban", "team": "first", "count": 1},
        {"action": "ban", "team": "second", "count": 1},
        {"action": "pick", "team": "first", "count": 1},
        {"action": "pick", "team": "second", "count": 1},
        {"action": "pick", "team": "first", "count": 1},
        {"action": "pick", "team": "second", "count": 1},
    ],
}

FORMAT_MAP_COUNTS = {"BO1": 1, "BO3": 3, "BO5": 5}


def _storage_map_name(map_name):
    """将 BP 的展示名写成比赛表单和数据层统一使用的地图键。"""
    raw = str(map_name or "").strip().lower().replace(" ", "_")
    if raw.startswith("de_"):
        return raw
    return _MAP_STORAGE_NAMES.get(raw, raw)


def _format_steps_for_pool(bo, pool_size):
    """按实际图池数量生成 BP 步骤；7 图时保持原有顺序。"""
    bo = str(bo or "").upper()
    required_maps = FORMAT_MAP_COUNTS.get(bo)
    if required_maps is None:
        raise ValueError("仅支持 BO1、BO3、BO5")
    minimum_pool = 2 if bo == "BO1" else required_maps
    if pool_size < minimum_pool:
        raise ValueError(f"{bo} 图池至少需要 {minimum_pool} 张地图")

    def alternating_bans(count):
        return [
            {"action": "ban", "team": "first" if index % 2 == 0 else "second", "count": 1}
            for index in range(count)
        ]

    if bo == "BO1":
        ban_count = pool_size - 1
        first_count = min(2, ban_count)
        steps = []
        if first_count:
            steps.append({"action": "ban", "team": "first", "count": first_count})
        remaining = ban_count - first_count
        second_count = min(3, remaining)
        if second_count:
            steps.append({"action": "ban", "team": "second", "count": second_count})
        if remaining - second_count:
            steps.append({"action": "ban", "team": "first", "count": remaining - second_count})
        return steps

    if bo == "BO3":
        ban_count = pool_size - 3  # two picks plus one remaining decider
        initial_bans = min(2, ban_count)
        steps = alternating_bans(initial_bans)
        steps.extend(
            [
                {"action": "pick", "team": "first", "count": 1},
                {"action": "pick", "team": "second", "count": 1},
            ]
        )
        steps.extend(alternating_bans(max(0, ban_count - initial_bans)))
        return steps

    # BO5 keeps four picked maps and one remaining decider.
    steps = alternating_bans(pool_size - 5)
    steps.extend(
        [
            {"action": "pick", "team": "first", "count": 1},
            {"action": "pick", "team": "second", "count": 1},
            {"action": "pick", "team": "first", "count": 1},
            {"action": "pick", "team": "second", "count": 1},
        ]
    )
    return steps


def ensure_bp_started(conn, match):
    """读取并升级已有 BP 状态；不存在时等待操作员手动开始。"""
    raw_state = match["bp_state"] if "bp_state" in match.keys() else None
    if raw_state:
        try:
            state = json.loads(raw_state) if isinstance(raw_state, str) else raw_state
            changed = normalize_bp_state(state)
            if changed:
                conn.execute(
                    "UPDATE matches SET bp_state=? WHERE id=?",
                    (json.dumps(state, ensure_ascii=False), match["id"]),
                )
            return state, changed
        except (TypeError, ValueError, json.JSONDecodeError):
            return None, False

    return None, False


def init_bp_state(bo_format, map_pool=None):
    """
    初始化 BP 状态
    bo_format: 'BO1', 'BO3', 'BO5'
    map_pool: 自定义地图池, 默认 7 张
    """
    bo = bo_format.upper()
    if bo not in FORMAT_STEPS:
        raise ValueError("仅支持 BO1、BO3、BO5")

    # Use the match/event pool exactly as configured. A missing pool uses the
    # historical seven-map default; an invalid supplied pool fails loudly.
    pool = list(ALL_MAPS) if map_pool is None else list(map_pool)
    pool = [str(name or "").strip() for name in pool]
    if any(not name for name in pool):
        raise ValueError("地图池不能包含空地图名")
    if len({name.casefold() for name in pool}) != len(pool):
        raise ValueError("地图池不能包含重复地图")

    steps = [dict(step) for step in _format_steps_for_pool(bo, len(pool))]
    total_maps = FORMAT_MAP_COUNTS[bo]

    state = {
        "state_version": STATE_VERSION,
        "status": "rolling",  # rolling | bp | side_select | completed
        "bo": bo,
        "pool": pool,
        "initial_pool": list(pool),
        "bans": [],
        "picks": [],  # [{map, picked_by, side}]
        "current_step": 0,  # 当前步骤索引
        "current_step_progress": 0,  # 当前步骤已操作的地图数
        "steps": steps,
        "total_maps": total_maps,
        "rolls": {"t1": None, "t2": None},
        "first_picker": None,  # 't1' 或 't2', roll 赢家选择
        "first_choice": None,  # 'first' 或 'second' (赢家选了先手还是后手)
        "action_log": [],  # [{team, action, map, step}]
        "map_order": [],  # 最终地图顺序
        "sides": {},  # {map_name: 'CT'|'T'} 谁选了哪边
        "revision": 0,
        "controller_seats": {},
        "audit_log": [],
        "state_history": [],
    }
    return state


def normalize_bp_state(state):
    """把旧版 BP 状态补齐，尤其修复旧 BO1 只 Ban 了 3 张便结束的问题。"""
    if not isinstance(state, dict):
        raise ValueError("BP 状态格式错误")

    bo = str(state.get("bo", "")).upper()
    if bo not in FORMAT_STEPS:
        raise ValueError("BP 赛制无效")

    changed = state.get("state_version") != STATE_VERSION
    state["bo"] = bo
    state["total_maps"] = FORMAT_MAP_COUNTS[bo]
    initial_pool = state.get("initial_pool")
    if not isinstance(initial_pool, list):
        state["initial_pool"] = list(ALL_MAPS)
        changed = True
    else:
        cleaned_pool = [str(name or "").strip() for name in initial_pool]
        if (
            any(not name for name in cleaned_pool)
            or len({name.casefold() for name in cleaned_pool}) != len(cleaned_pool)
            or len(cleaned_pool) < (2 if bo == "BO1" else FORMAT_MAP_COUNTS[bo])
        ):
            state["initial_pool"] = list(ALL_MAPS)
            changed = True
        elif cleaned_pool != initial_pool:
            state["initial_pool"] = cleaned_pool
            changed = True
    expected_steps = _format_steps_for_pool(bo, len(state["initial_pool"]))
    if state.get("steps") != expected_steps:
        state["steps"] = expected_steps
        changed = True
    state.setdefault("action_log", [])
    state.setdefault("bans", [])
    state.setdefault("picks", [])
    state.setdefault("map_order", [])
    state.setdefault("rolls", {"t1": None, "t2": None})
    state.setdefault("sides", {})
    state.setdefault("revision", 0)
    state.setdefault("controller_seats", {})
    state.setdefault("audit_log", [])
    state.setdefault("state_history", [])
    if not isinstance(state.get("pool"), list):
        used_maps = set(state.get("bans") or []) | {
            pick.get("map") for pick in (state.get("picks") or []) if pick.get("map")
        }
        state["pool"] = [name for name in state["initial_pool"] if name not in used_maps]
        changed = True

    for pick in state["picks"]:
        if pick.get("picked_by") == "remaining" and bo == "BO1":
            side_team = pick.get("side_team") or _bo1_remaining_side_team(state)
            if pick.get("side_team") != side_team:
                pick["side_team"] = side_team
                changed = True

    if changed:
        action_count = len(state["action_log"])
        step_idx = 0
        step_progress = 0
        for index, step in enumerate(state["steps"]):
            if action_count >= step["count"]:
                action_count -= step["count"]
                step_idx = index + 1
            else:
                step_idx = index
                step_progress = action_count
                break

        state["current_step"] = step_idx
        state["current_step_progress"] = step_progress

        # 旧 BO1 会在只 Ban 3 张后误把其余 4 张都记为最终地图。
        if bo == "BO1" and step_idx < len(state["steps"]):
            state["picks"] = [
                pick for pick in state["picks"] if pick.get("picked_by") != "remaining"
            ]
            used_maps = set(state["bans"]) | {pick.get("map") for pick in state["picks"]}
            state["pool"] = [name for name in state["initial_pool"] if name not in used_maps]
            state["map_order"] = []
            if state.get("first_choice") is not None:
                state["status"] = "bp"
    else:
        state.setdefault("current_step_progress", 0)

    for legacy_key in ("turn_started_at", "turn_deadline", "auto_started", "auto_started_at"):
        if legacy_key in state:
            state.pop(legacy_key, None)
            changed = True

    state["state_version"] = STATE_VERSION
    return changed


def roll():
    """生成 1-100 随机数"""
    return random.randint(1, 100)


def process_roll(state, team, value):
    """记录 roll 点结果, 两队都 roll 完后确定先手"""
    if state.get("status") != "rolling":
        return False, "当前不能 Roll"
    if team not in ("t1", "t2"):
        return False, "队伍无效"
    if state["rolls"].get(team) is not None:
        return False, "本队已经 Roll 过了"

    state["rolls"][team] = value

    t1_roll = state["rolls"].get("t1")
    t2_roll = state["rolls"].get("t2")

    if t1_roll is not None and t2_roll is not None:
        if t1_roll == t2_roll:
            state["rolls"] = {"t1": None, "t2": None}
            state["first_picker"] = None
            return True, "tie"
        if t1_roll > t2_roll:
            state["first_picker"] = "t1"
        else:
            state["first_picker"] = "t2"
        state["status"] = "bp"
        return True, state["first_picker"]
    return True, None


def set_first_choice(state, team, choice):
    """
    Roll 赢家选择先手还是后手
    choice: 'first' (先 ban/pick) 或 'second' (后 ban/pick)
    """
    if state.get("status") != "bp" or not state.get("first_picker"):
        return False, "当前不能选择先后手"
    if state.get("first_choice") is not None:
        return False, "已经选择过先后手"
    if team != state["first_picker"]:
        return False, "只有 Roll 胜方可以选择先手或后手"
    if choice not in ("first", "second"):
        return False, "无效选择"

    state["first_choice"] = choice
    return True, "选择成功"


def get_team_for_step(state, step_idx):
    """获取某步骤对应的队伍 ('t1' 或 't2')"""
    if step_idx >= len(state["steps"]):
        return None
    step = state["steps"][step_idx]
    if step["team"] == "first":
        if state["first_choice"] == "first":
            return state["first_picker"]
        else:
            return "t2" if state["first_picker"] == "t1" else "t1"
    else:  # 'second'
        if state["first_choice"] == "first":
            return "t2" if state["first_picker"] == "t1" else "t1"
        else:
            return state["first_picker"]


def _advance_step(state):
    """记录一次地图操作，并在本轮数量完成后进入下一轮。"""
    step = state["steps"][state["current_step"]]
    progress = state.get("current_step_progress", 0) + 1
    if progress >= step["count"]:
        state["current_step"] += 1
        state["current_step_progress"] = 0
    else:
        state["current_step_progress"] = progress


def _opposite_team(team):
    if team == "t1":
        return "t2"
    if team == "t2":
        return "t1"
    return None


def _bo1_remaining_side_team(state):
    """BO1 最后一张图由未执行最后一次 Ban 的队伍选边。"""
    if state.get("bo") != "BO1":
        return None
    action_log = state.get("action_log") or []
    last_ban_team = next(
        (
            entry.get("team")
            for entry in reversed(action_log)
            if entry.get("action") == "ban" and entry.get("team") in {"t1", "t2"}
        ),
        None,
    )
    return _opposite_team(last_ban_team)


def _finish_map_selection(state):
    """加入唯一剩余地图，并进入选边或直接完成。"""
    remaining = list(state["pool"])
    if len(remaining) != 1:
        return False, f"地图数量异常，应剩 1 张，实际剩 {len(remaining)} 张"

    remaining_pick = {"map": remaining[0], "picked_by": "remaining", "side": None}
    if state.get("bo") == "BO1":
        remaining_pick["side_team"] = _bo1_remaining_side_team(state)
    state["picks"].append(remaining_pick)
    state["map_order"] = [pick["map"] for pick in state["picks"]]
    if len(state["map_order"]) != state["total_maps"]:
        return False, (
            f"选图数量异常，{state['bo']} 应有 {state['total_maps']} 张，"
            f"实际有 {len(state['map_order'])} 张"
        )

    needs_side_selection = any(
        pick.get("side") is None
        and (pick.get("picked_by") != "remaining" or state.get("bo") == "BO1")
        for pick in state["picks"]
    )
    state["status"] = "side_select" if needs_side_selection else "completed"
    return True, "BP 完成，进入选边阶段" if needs_side_selection else "BP 已完成"


def ban_map(state, team, map_name):
    """执行 ban 图操作"""
    if state["status"] != "bp":
        return False, "当前不在 BP 阶段"

    step_idx = state["current_step"]
    if step_idx >= len(state["steps"]):
        return False, "BP 已结束"

    step = state["steps"][step_idx]
    if step["action"] != "ban":
        return False, "当前步骤不是 ban"

    expected_team = get_team_for_step(state, step_idx)
    if team != expected_team:
        return False, "当前轮到对方操作"

    if map_name not in state["pool"]:
        return False, "地图不在池中"
    if map_name in state["bans"]:
        return False, "该地图已被 ban"

    state["bans"].append(map_name)
    state["pool"].remove(map_name)
    state["action_log"].append({"team": team, "action": "ban", "map": map_name, "step": step_idx})

    _advance_step(state)

    # 检查是否完成
    if state["current_step"] >= len(state["steps"]):
        return _finish_map_selection(state)

    return True, "ban 成功"


def pick_map(state, team, map_name):
    """执行 pick 图操作"""
    if state["status"] != "bp":
        return False, "当前不在 BP 阶段"

    step_idx = state["current_step"]
    if step_idx >= len(state["steps"]):
        return False, "BP 已结束"

    step = state["steps"][step_idx]
    if step["action"] != "pick":
        return False, "当前步骤不是 pick"

    expected_team = get_team_for_step(state, step_idx)
    if team != expected_team:
        return False, "当前轮到对方操作"

    if map_name not in state["pool"]:
        return False, "地图不在池中"
    if map_name in state["bans"]:
        return False, "该地图已被 ban"
    if any(p["map"] == map_name for p in state["picks"]):
        return False, "该地图已被选"

    state["picks"].append({"map": map_name, "picked_by": team, "side": None})
    state["pool"].remove(map_name)
    state["action_log"].append({"team": team, "action": "pick", "map": map_name, "step": step_idx})

    _advance_step(state)

    # 检查是否完成
    if state["current_step"] >= len(state["steps"]):
        return _finish_map_selection(state)

    return True, "pick 成功"


def choose_side(state, team, map_name, side):
    """
    选边: 被选图的对手选择 CT/T
    team: 当前操作的队伍
    side: 'CT' 或 'T'
    """
    if state["status"] != "side_select":
        return False, "当前不能选边"

    # 找到这张图的 pick 记录
    pick_entry = None
    for p in state["picks"]:
        if p["map"] == map_name:
            pick_entry = p
            break

    if not pick_entry:
        return False, "地图不在选图中"

    if pick_entry["side"] is not None:
        return False, "该图已选过边"

    if pick_entry["picked_by"] == "remaining":
        if state.get("bo") != "BO1":
            return False, "最后一图无需选边"
        opponent = pick_entry.get("side_team") or _bo1_remaining_side_team(state)
        if opponent is None:
            return False, "无法确定最后一图的选边队伍"
        pick_entry["side_team"] = opponent
    else:
        # 校验选边方必须是选图方的对手
        opponent = _opposite_team(pick_entry["picked_by"])
    if team != opponent:
        return False, "该图由对方选边"

    if side not in ("CT", "T"):
        return False, "无效选边"

    pick_entry["side"] = side
    state.setdefault("sides", {})[map_name] = side

    # BO1 的剩余图也必须选边；BO3/BO5 的决胜图由拼刀字段决定。
    all_sided = all(
        p["side"] is not None
        for p in state["picks"]
        if p["picked_by"] != "remaining" or state.get("bo") == "BO1"
    )
    if all_sided:
        state["status"] = "completed"

    return True, "选边成功"


def get_current_step_info(state):
    """获取当前步骤的描述信息"""
    if state["status"] == "rolling":
        return {
            "phase": "rolling",
            "t1_rolled": state["rolls"]["t1"] is not None,
            "t2_rolled": state["rolls"]["t2"] is not None,
            "t1_value": state["rolls"]["t1"],
            "t2_value": state["rolls"]["t2"],
            "winner": state["first_picker"],
        }

    if state["status"] == "bp":
        if state["first_choice"] is None:
            return {
                "phase": "choose_order",
                "winner": state["first_picker"],
            }

        step_idx = state["current_step"]
        if step_idx >= len(state["steps"]):
            return {"phase": "bp_complete"}

        step = state["steps"][step_idx]
        team = get_team_for_step(state, step_idx)
        return {
            "phase": "bp",
            "step_idx": step_idx,
            "total_steps": len(state["steps"]),
            "action": step["action"],
            "count": step["count"] - state.get("current_step_progress", 0),
            "step_count": step["count"],
            "step_progress": state.get("current_step_progress", 0),
            "team": team,
        }

    if state["status"] == "side_select":
        pending = [
            {
                "map": p["map"],
                "picked_by": p["picked_by"],
                "team": p.get("side_team")
                if p.get("picked_by") == "remaining"
                else _opposite_team(p.get("picked_by")),
            }
            for p in state["picks"]
            if (p["picked_by"] != "remaining" or state.get("bo") == "BO1") and p["side"] is None
        ]
        return {
            "phase": "side_select",
            "pending": pending,
            "picks": state["picks"],
        }

    return {"phase": state["status"]}


def format_bp_log(state):
    """将 BP 状态转为可读文本，用于 bp_process 字段"""
    lines = []

    rolls = state.get("rolls", {})
    t1r = rolls.get("t1")
    t2r = rolls.get("t2")
    first_picker = state.get("first_picker", "")
    first_choice = state.get("first_choice", "")

    if t1r is not None or t2r is not None:
        lines.append(
            f"Roll: T1={'?' if t1r is None else t1r}, T2={'?' if t2r is None else t2r}"
            + (f" → {first_picker.upper()} 胜出" if first_picker else "")
        )

    if first_choice:
        lines.append(f"{first_picker.upper()} 选择{'先手' if first_choice == 'first' else '后手'}")

    # action_log
    action_log = state.get("action_log", [])
    team_names = {"t1": "T1", "t2": "T2"}
    for i, entry in enumerate(action_log):
        act = "Ban" if entry["action"] == "ban" else "Pick"
        lines.append(
            f"{i + 1}. {team_names.get(entry['team'], entry['team'])} {act} {entry['map']}"
        )

    # remaining map
    picks = state.get("picks", [])
    for p in picks:
        if p.get("picked_by") == "remaining":
            lines.append(f"{len(action_log) + 1}. {p['map']} 剩余")

    # side selections
    for p in picks:
        if p.get("side"):
            lines.append(f"选边: {p['map']} → {p['side']} 方")

    return "\n".join(lines)


def save_bp_to_match(conn, match_id, state):
    """
    将 BP 结果保存到 matches 表
    更新 map_pool, map1-5, map*_picked_by, bp_process
    """
    if state["status"] != "completed":
        return False

    map_order = state["map_order"]
    bo = state["bo"].upper()
    expected_count = FORMAT_MAP_COUNTS.get(bo)
    if expected_count is None or len(map_order) != expected_count:
        return False

    # 构建更新数据
    state["status"] = "completed"  # 确保状态为 completed
    updates: dict[str, object] = {
        "bp_process": format_bp_log(state),
        "bp_state": json.dumps(state, ensure_ascii=False),
        "map_pool": json.dumps(state.get("initial_pool", ALL_MAPS), ensure_ascii=False),
    }

    # 先清空旧 BP 留下的地图名和选图方，避免从 BO5 改成 BO1 后残留旧图。
    for i in range(1, 6):
        updates[f"map{i}"] = None
        updates[f"map{i}_picked_by"] = None

    for i, m in enumerate(map_order[:5]):
        col = f"map{i + 1}"
        # BP 页面使用 Dust2/Mirage 等展示名，matches 表和后台表单使用
        # de_dust2/de_mirage 等键；统一写入后，后台再次保存不会丢图。
        updates[col] = _storage_map_name(m)
        if i > 1:
            updates[f"has_map{i + 1}"] = 1

    # 设置 picked_by
    for p in state["picks"]:
        picked_by = p.get("picked_by", "")
        for i, m in enumerate(map_order[:5]):
            if m == p["map"]:
                if picked_by == "t1":
                    updates[f"map{i + 1}_picked_by"] = "t1"
                elif picked_by == "t2":
                    updates[f"map{i + 1}_picked_by"] = "t2"
                elif picked_by == "remaining":
                    updates[f"map{i + 1}_picked_by"] = "decider"
                break

    # 确保 has_map3 等字段正确
    if bo == "BO1":
        updates["has_map3"] = 0
        updates["has_map4"] = 0
        updates["has_map5"] = 0
    elif bo == "BO3":
        updates["has_map3"] = 1
        updates["has_map4"] = 0
        updates["has_map5"] = 0
    elif bo == "BO5":
        updates["has_map3"] = 1
        updates["has_map4"] = 1
        updates["has_map5"] = 1

    set_clauses = ", ".join(f"{k}=?" for k in updates)
    values = list(updates.values()) + [match_id]

    conn.execute(f"UPDATE matches SET {set_clauses} WHERE id=?", values)
    return True
