"""比赛 BP：操作席、版本、可撤回的每一步，以及相应地图的原子更新。"""

import time
from copy import deepcopy

from src.website.domains.matches import bp_manager as rules
from src.website.domains.matches import bp_match_state as store
from src.website.domains.matches.maps import (
    bp_lock_reason,
    bp_revision_after_reset,
    record_bp_reset,
)
from src.website.runtime.host import HostError, is_managed_match

TURN_ACTIONS = ("start", "roll", "choose_order", "ban", "pick", "choose_side")
SEAT_TIMEOUT_SECONDS = 30


def require_action_window(conn, match, *, check_score):
    if not store.window_is_open(match):
        raise HostError("比赛已结束或取消，BP 已锁定", 403)
    if check_score and store.change_lock_error(match):
        raise HostError("比赛已产生比分，不能继续更改 BP")
    if reason := bp_lock_reason(conn, match):
        raise HostError(reason)


def _take_seat(state, seat, user_id, *, occupied_message=None):
    seats = state.setdefault("controller_seats", {})
    current = seats.get(seat)
    now = time.time()
    if (
        occupied_message
        and current
        and now - float(current.get("last_seen") or 0) <= SEAT_TIMEOUT_SECONDS
        and int(current.get("user_id", -1)) != user_id
    ):
        raise HostError(occupied_message)
    seats[seat] = {"user_id": user_id, "last_seen": now}


def heartbeat(conn, match, seat, user_id):
    state, _ = store.ensure_bp_started(conn, match)
    if state is None:
        raise HostError("BP 尚未开始")
    # 管理心跳可接管管理席；两队心跳不能挤走仍在线的同队选手。
    _take_seat(
        state, seat, user_id, occupied_message=None if seat == "admin" else "本队席位已被占用"
    )
    store.persist_state(conn, match["id"], state)
    return state.get("revision", 0)


def release_seat(conn, match, team, admin_id):
    if str(match["status"] or "") in ("completed", "cancelled"):
        raise HostError("比赛已结束，不能撤销 BP")
    if any(int(match[f"map{slot}_t{side}"] or 0) > 0 for slot in range(1, 6) for side in (1, 2)):
        raise HostError("比赛已产生比分，不能撤销 BP")
    if reason := bp_lock_reason(conn, match):
        raise HostError(reason)
    state, _ = store.ensure_bp_started(conn, match)
    if state is None:
        raise HostError("BP 尚未开始")
    state.setdefault("controller_seats", {}).pop(team, None)
    state["revision"] = int(state.get("revision") or 0) + 1
    state.setdefault("audit_log", []).append(
        {
            "action": "release_seat",
            "team": team,
            "revision": state["revision"],
            "at": time.time(),
            "admin_id": admin_id,
        }
    )
    store.persist_state(conn, match["id"], state)
    return state["revision"]


def _apply_step(state, action, team, data):
    if action == "roll":
        value = rules.roll()
        ok, winner = rules.process_roll(state, team, value)
        if not ok:
            return False, winner
        if winner == "tie":
            return True, "双方点数相同，请重新 Roll"
        if winner:
            return True, f"{team} roll 得 {value}, 先手: {winner}"
        return True, f"{team} roll 得 {value}, 等待对方 roll"
    if action == "choose_order":
        choice = data.get("choice", "")
        if choice not in ("first", "second"):
            raise HostError("无效选择", 200)
        ok, result = rules.set_first_choice(state, team, choice)
        return ok, f"选择{'先手' if choice == 'first' else '后手'}" if ok else result
    name = data.get("map", "")
    if action == "ban":
        return rules.ban_map(state, team, name)
    if action == "pick":
        return rules.pick_map(state, team, name)
    side = data.get("side", "")
    if side not in ("CT", "T"):
        raise HostError("无效选边", 200)
    return rules.choose_side(state, team, name, side)


def play_turn(conn, match, action, team, data, *, seat, actor_id, seat_user_id):
    match_id = match["id"]
    state, _ = store.ensure_bp_started(conn, match)
    if action == "start":
        if state is not None:
            raise HostError("BP 已经开始，请勿重复启动", 200)
        try:
            state = rules.init_bp_state(
                match["bo_format"] or "BO3", store.map_pool(match["map_pool"])
            )
        except ValueError as exc:
            raise HostError(str(exc), 400) from exc
        if is_managed_match(conn, match_id):
            state["revision"] = bp_revision_after_reset(conn, match_id)
        _take_seat(state, seat, int(actor_id or 0))
        store.persist_state(conn, match_id, state)
        return state, None
    if state is None:
        raise HostError("BP 未初始化", 200)

    expected = data.get("bp_revision")
    if expected is not None:
        try:
            expected = int(expected)
        except (TypeError, ValueError) as exc:
            raise HostError("BP 版本号无效", 400) from exc
        if expected != int(state.get("revision", 0)):
            raise HostError("BP 已被另一名操作员更新，请刷新后再操作", params={"state": state})
    _take_seat(
        state,
        seat,
        seat_user_id,
        occupied_message="该操作席已有另一名操作员，请等待掉线或联系管理员释放席位",
    )
    before = deepcopy(
        {key: value for key, value in state.items() if key not in ("state_history", "audit_log")}
    )
    ok, result = _apply_step(state, action, team, data)
    if not ok:
        raise HostError(result, 200, params={"state": state})
    history = state.setdefault("state_history", [])
    history.append(before)
    del history[:-30]
    state["revision"] = int(state.get("revision", 0)) + 1
    state.setdefault("audit_log", []).append(
        {
            "revision": state["revision"],
            "user_id": actor_id,
            "team": team,
            "action": action,
            "map": data.get("map"),
            "at": time.time(),
        }
    )
    if not store.save_action(conn, match_id, state):
        raise HostError("BP 地图保存失败，本次操作未保存", 400)
    return state, result


def _state_for_correction(conn, match):
    if reason := store.change_lock_error(match) or bp_lock_reason(conn, match):
        raise HostError(reason)
    return store.ensure_bp_started(conn, match)[0]


def reset(conn, match):
    state = _state_for_correction(conn, match)
    if state and state.get("status") == "completed":
        store.clear_generated_maps(conn, match["id"], state["bo"])
    if state and is_managed_match(conn, match["id"]):
        record_bp_reset(conn, match["id"], int(state.get("revision", 0)))
    conn.execute("UPDATE matches SET bp_state=NULL WHERE id=?", (match["id"],))


def undo(conn, match, data, admin_id):
    state = _state_for_correction(conn, match)
    if state is None:
        raise HostError("BP 尚未开始")
    history = state.get("state_history") or []
    if not history:
        raise HostError("没有可撤回的 BP 操作")
    if not isinstance(data, dict):
        raise HostError("请求格式无效", 400)
    try:
        count = max(1, min(int(data.get("steps_back", 1)), len(history)))
    except (TypeError, ValueError):
        count = 1
    restored = deepcopy(history[-count])
    restored["state_history"] = history[:-count]
    restored["audit_log"] = [
        *(state.get("audit_log") or []),
        {"action": "undo", "steps_back": count, "at": time.time(), "admin_id": admin_id},
    ]
    restored["revision"] = int(state.get("revision", 0)) + 1
    if state.get("status") == "completed" and restored.get("status") != "completed":
        store.clear_generated_maps(conn, match["id"], str(restored.get("bo") or "BO3").upper())
    if not store.save_action(conn, match["id"], restored):
        raise HostError("BP 地图保存失败，本次撤回未保存", 400)
    return restored
