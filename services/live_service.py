"""Helpers for turning raw GSI data into website live-match data."""

import json
import time
from datetime import datetime, timezone

# 与网页雷达图使用同一套坐标换算。包点中心来自 resources/radars/*.svg
# 中的红色斜线区域，只用于游戏没有直接返回 A / B 时的兜底判断。
_RADAR_SIZE = 708
_MAP_OVERVIEWS = {
    "dust2": {"x": -2476, "y": 3239, "scale": 4.4},
    "mirage": {"x": -3230, "y": 1713, "scale": 5},
    "inferno": {"x": -2087, "y": 3870, "scale": 4.9},
    "nuke": {"x": -3453, "y": 2887, "scale": 7},
    "overpass": {"x": -4831, "y": 1781, "scale": 5.2},
    "ancient": {"x": -2953, "y": 2164, "scale": 5},
    "anubis": {"x": -2796, "y": 3328, "scale": 5.22},
    "vertigo": {"x": -3168, "y": 1762, "scale": 4},
    "cache": {"x": -2000, "y": 3250, "scale": 5.5},
    "train": {"x": -2477, "y": 2392, "scale": 4.7},
}
_MAP_BOUNDS = {
    "ancient": {"x0": -3200, "y0": -3800, "x1": 4200, "y1": 3700},
    "anubis": {"x0": -2900, "y0": -2500, "x1": 3200, "y1": 3200},
}
_BOMB_SITE_RADAR_POINTS = {
    "dust2": {"A": (116, 143), "B": (85, 565)},
    "mirage": {"A": (380, 573), "B": (116, 168)},
    "inferno": {"A": (371, 561), "B": (125, 209)},
    "ancient": {"A": (125, 521), "B": (260, 135)},
    "anubis": {"A": (358, 488), "B": (188, 168)},
    "overpass": {"A": (141, 385), "B": (223, 239)},
    "vertigo": {"A": (501, 356), "B": (292, 643)},
    "train": {"A": (353, 244), "B": (554, 326)},
    "cache": {"A": (589, 530), "B": (162, 554)},
}


def _normalize_map_key(value):
    value = str(value or "").strip().lower()
    return value[3:] if value.startswith("de_") else value


def remove_stored_gsi_auth(conn):
    """Remove old GSI credentials from already stored live-state rows."""
    changed = 0
    rows = conn.execute("SELECT match_id, live_state FROM live_match_data").fetchall()
    for row in rows:
        try:
            state = json.loads(row["live_state"] or "{}")
        except (TypeError, ValueError):
            continue
        gsi = state.get("gsi") if isinstance(state, dict) else None
        if not isinstance(gsi, dict) or "auth" not in gsi:
            continue
        clean_gsi = dict(gsi)
        clean_gsi.pop("auth", None)
        state["gsi"] = clean_gsi
        conn.execute(
            "UPDATE live_match_data SET live_state=? WHERE match_id=?",
            (json.dumps(state, ensure_ascii=False), row["match_id"]),
        )
        changed += 1
    return changed


def _parse_gsi_coordinates(value):
    """将 GSI 的 "x, y, z" 坐标转成数字列表。"""
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        result = [float(value[0]), float(value[1])]
        if len(value) >= 3:
            result.append(float(value[2]))
        return result
    except (TypeError, ValueError):
        return None


def _parse_gsi_position(value):
    """将 GSI 的 "x, y, z" 坐标转成数字列表。"""
    coords = _parse_gsi_coordinates(value)
    return [round(coords[0], 1), round(coords[1], 1)] if coords else None


def _is_recent_iso_timestamp(value, max_age_seconds=45):
    """判断 GSI 最近是否仍在持续推送。"""
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()
        return age <= max_age_seconds
    except (TypeError, ValueError):
        return False


def _active_gsi_weapon(player):
    """读取击杀发生时正在使用的武器；没有可靠数据时留空。"""
    weapons = (player or {}).get("weapons", {}) or {}
    for weapon in weapons.values():
        if weapon.get("state") == "active":
            return weapon.get("name", "")
    return ""


def _count_alive_gsi_players(players):
    """统计双方当前仍然存活的人数。"""
    alive = {"ct": 0, "t": 0}
    for player in (players or {}).values():
        team = str(player.get("team", "")).lower()
        if team not in alive:
            continue
        if int((player.get("state", {}) or {}).get("health", 0) or 0) > 0:
            alive[team] += 1
    return alive


def _resolve_gsi_player_name(steamid, *player_sets):
    """根据 SteamID 找到 GSI 中的选手名。"""
    steamid = str(steamid or "")
    if not steamid:
        return ""
    for players in player_sets:
        player = (players or {}).get(steamid)
        if player:
            return player.get("name", "")
    return ""


def _normalize_bombsite(value):
    """把游戏可能返回的包点字段统一成 A / B。"""
    value = str(value or "").strip().upper()
    if value in ("A", "B"):
        return value
    if value.endswith("_A") or value.endswith("SITEA"):
        return "A"
    if value.endswith("_B") or value.endswith("SITEB"):
        return "B"
    return "?"


def _position_to_radar(map_name, position):
    """将游戏坐标换算为雷达 SVG 坐标。"""
    key = _normalize_map_key(map_name)
    overview = _MAP_OVERVIEWS.get(key)
    if overview:
        return (
            (position[0] - overview["x"]) / (overview["scale"] * 1024) * _RADAR_SIZE,
            (overview["y"] - position[1]) / (overview["scale"] * 1024) * _RADAR_SIZE,
        )
    bounds = _MAP_BOUNDS.get(key)
    if bounds:
        return (
            (position[0] - bounds["x0"]) / (bounds["x1"] - bounds["x0"]) * _RADAR_SIZE,
            (1 - (position[1] - bounds["y0"]) / (bounds["y1"] - bounds["y0"])) * _RADAR_SIZE,
        )
    return None


def _infer_bombsite(map_name, bomb, players=None):
    """优先使用游戏字段；缺少字段时按下包坐标推断 A / B。"""
    direct = _normalize_bombsite(
        (bomb or {}).get("site") or (bomb or {}).get("bombsite") or (bomb or {}).get("location")
    )
    if direct != "?":
        return direct

    position = _parse_gsi_coordinates((bomb or {}).get("position"))
    if not position:
        planter = str((bomb or {}).get("player") or "")
        player = (players or {}).get(planter, {}) or {}
        position = _parse_gsi_coordinates(player.get("position"))
    if not position:
        return "?"

    key = _normalize_map_key(map_name)
    # Nuke 两个包点处于不同楼层，XY 很接近，用高度判断更可靠。
    if key == "nuke" and len(position) >= 3:
        return "B" if position[2] < -600 else "A"

    radar_position = _position_to_radar(key, position)
    sites = _BOMB_SITE_RADAR_POINTS.get(key)
    if not radar_position or not sites:
        return "?"
    return min(
        sites,
        key=lambda site: (
            (radar_position[0] - sites[site][0]) ** 2 + (radar_position[1] - sites[site][1]) ** 2
        ),
    )


def _load_live_player_profiles(conn, steamids):
    """按 SteamID 读取网站保存的昵称和头像。"""
    steamids = sorted({str(steamid) for steamid in steamids if steamid})
    if not steamids:
        return {}
    placeholders = ",".join("?" for _ in steamids)
    rows = conn.execute(
        f"SELECT steam_id, nickname, avatar FROM players WHERE steam_id IN ({placeholders})",
        steamids,
    ).fetchall()
    return {
        str(player["steam_id"]): {
            "name": player["nickname"],
            "avatar": f"/static/avatars/{player['avatar']}" if player["avatar"] else "",
        }
        for player in rows
    }


def _record_gsi_bomb_events(merged, data):
    """在炸弹首次安放时记录一条 Game Log。"""
    previous_gsi = merged.get("gsi", {}) or {}
    previous_bomb = previous_gsi.get("bomb", {}) or {}
    current_bomb = data.get("bomb", {}) or {}
    if current_bomb.get("state") != "planted" or previous_bomb.get("state") == "planted":
        return

    current_players = data.get("allplayers", {}) or {}
    previous_players = previous_gsi.get("allplayers", {}) or {}
    planter_id = current_bomb.get("player") or previous_bomb.get("player")
    alive = _count_alive_gsi_players(current_players)
    round_num = (data.get("map", {}) or {}).get("round", 0)
    events = merged.get("bomb_events", [])
    if not isinstance(events, list):
        events = []
    now = time.time()
    events.append(
        {
            "id": f"plant-{round_num}-{int(now * 1000)}",
            "round": round_num,
            "player_steamid": str(planter_id or ""),
            "player": _resolve_gsi_player_name(planter_id, current_players, previous_players),
            "player_side": "T",
            "site": _infer_bombsite(
                (data.get("map", {}) or {}).get("name", ""),
                current_bomb,
                current_players,
            ),
            "alive_t": alive["t"],
            "alive_ct": alive["ct"],
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "captured_at_epoch": now,
        }
    )
    merged["bomb_events"] = events[-24:]


def _latest_round_win_code(data):
    round_wins = (data.get("map", {}) or {}).get("round_wins", {}) or {}
    if not isinstance(round_wins, dict) or not round_wins:
        return ""

    def round_index(item):
        try:
            return int(item[0])
        except (TypeError, ValueError):
            return -1

    return str(max(round_wins.items(), key=round_index)[1] or "").lower()


def _round_win_reason_code(data, previous_gsi, winner):
    """返回稳定的回合结束原因代码，供前端选择图标和颜色。"""
    current_map = data.get("map", {}) or {}
    latest_code = _latest_round_win_code(data)
    if "bomb" in latest_code and ("explode" in latest_code or latest_code.endswith("_bomb")):
        return "bomb_exploded"
    if "defus" in latest_code:
        return "bomb_defused"
    if "time" in latest_code:
        return "time_expired"
    if "elimination" in latest_code or "elim" in latest_code:
        return "elimination"

    bomb_states = {
        str((data.get("bomb", {}) or {}).get("state", "")).lower(),
        str(((data.get("previously", {}) or {}).get("bomb", {}) or {}).get("state", "")).lower(),
        str((previous_gsi.get("bomb", {}) or {}).get("state", "")).lower(),
    }
    if "exploded" in bomb_states:
        return "bomb_exploded"
    if "defused" in bomb_states:
        return "bomb_defused"

    alive = _count_alive_gsi_players(data.get("allplayers", {}) or {})
    if winner == "CT":
        return "elimination" if alive["t"] == 0 else "time_expired"
    if winner == "T" and alive["ct"] == 0:
        return "elimination"
    return "completed"


def _round_win_reason(data, previous_gsi, winner):
    """尽量从 GSI 返回值中识别本回合获胜原因。"""
    labels = {
        "bomb_exploded": "Target bombed",
        "bomb_defused": "Bomb defused",
        "time_expired": "Target saved",
        "elimination": "Enemy eliminated",
        "completed": "Round completed",
    }
    return labels[_round_win_reason_code(data, previous_gsi, winner)]


def _record_gsi_deaths(merged, data):
    """记录本回合阵亡位置，并尽量拼出可展示的击杀信息。"""
    previous_gsi = merged.get("gsi", {}) or {}
    previous_players = previous_gsi.get("allplayers", {}) or {}
    current_players = data.get("allplayers", {}) or {}
    current_map = (data.get("map", {}) or {}).get("name", "")
    previous_map = (previous_gsi.get("map", {}) or {}).get("name", "")
    map_changed = previous_map and previous_map != current_map
    round_num = (data.get("map", {}) or {}).get("round", 0)
    previous_round = (previous_gsi.get("map", {}) or {}).get("round")
    round_changed = previous_round is not None and previous_round != round_num
    markers = [] if map_changed or round_changed else merged.get("kill_markers", [])
    events = [] if map_changed else merged.get("kill_events", [])
    if not isinstance(markers, list):
        markers = []
    if not isinstance(events, list):
        events = []
    if map_changed:
        merged["round_history"] = []

    now = time.time()
    killer_candidates = []
    assist_candidates = []
    for steamid, player in current_players.items():
        old_player = previous_players.get(steamid, {}) or {}
        stats = player.get("match_stats", {}) or {}
        old_stats = old_player.get("match_stats", {}) or {}
        kill_delta = int(stats.get("kills", 0) or 0) - int(old_stats.get("kills", 0) or 0)
        assist_delta = int(stats.get("assists", 0) or 0) - int(old_stats.get("assists", 0) or 0)
        killer_candidates.extend([(steamid, player)] * max(kill_delta, 0))
        assist_candidates.extend([(steamid, player)] * max(assist_delta, 0))

    for steamid, player in current_players.items():
        old_player = previous_players.get(steamid, {}) or {}
        old_health = (old_player.get("state", {}) or {}).get("health", 0)
        new_health = (player.get("state", {}) or {}).get("health", 0)
        if old_health <= 0 or new_health > 0:
            continue
        # 阵亡包里的当前位置偶尔已经跳变，优先使用上一帧仍存活时的坐标。
        position = _parse_gsi_position(old_player.get("position") or player.get("position"))
        if not position:
            continue
        victim_side = player.get("team", "")
        killer = next(
            (
                candidate
                for candidate in killer_candidates
                if candidate[0] != steamid and candidate[1].get("team", "") != victim_side
            ),
            None,
        )
        if killer:
            killer_candidates.remove(killer)
        assister = next(
            (
                candidate
                for candidate in assist_candidates
                if candidate[0] != steamid
                and (not killer or candidate[0] != killer[0])
                and candidate[1].get("team", "") != victim_side
            ),
            None,
        )
        if assister:
            assist_candidates.remove(assister)
        markers.append(
            {
                "id": f"{round_num}-{steamid}-{int(now * 1000)}",
                "steamid": str(steamid),
                "name": player.get("name", ""),
                "side": player.get("team", ""),
                "round": round_num,
                "x": position[0],
                "y": position[1],
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "captured_at_epoch": now,
            }
        )
        events.append(
            {
                "id": f"{round_num}-{steamid}-{int(now * 1000)}",
                "round": round_num,
                "killer": killer[1].get("name", "") if killer else "",
                "killer_steamid": str(killer[0]) if killer else "",
                "killer_side": killer[1].get("team", "") if killer else "",
                "assister": assister[1].get("name", "") if assister else "",
                "assister_steamid": str(assister[0]) if assister else "",
                "assister_side": assister[1].get("team", "") if assister else "",
                "victim": player.get("name", ""),
                "victim_steamid": str(steamid),
                "victim_side": victim_side,
                "weapon": _active_gsi_weapon(killer[1]) if killer else "",
                "headshot": False,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "captured_at_epoch": now,
            }
        )

    # 雷达只保留当前回合；击杀列表保留当前地图最近的记录。
    merged["kill_markers"] = markers[-10:]
    merged["kill_events"] = events[-24:]
