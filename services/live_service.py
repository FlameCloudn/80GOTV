"""Helpers for turning raw GSI data into website live-match data."""

import json
import math
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, overload

from utils.stats_calc import calculate_rating, estimate_hltv2_impact, non_negative_impact


class IngestValidationError(ValueError):
    """An authenticated live-data request contains an invalid value."""


def update_unconfirmed_map_slots(conn, match_id, map_slot, confirmed=True):
    """Update only result-confirmation metadata inside the caller's transaction."""
    row = conn.execute(
        "SELECT live_state FROM live_match_data WHERE match_id=?", (match_id,)
    ).fetchone()
    try:
        state = json.loads(row["live_state"] or "{}") if row else {}
    except (ValueError, TypeError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    raw_slots = state.get("unconfirmed_map_slots", [])
    slots = (
        {
            slot
            for slot in raw_slots
            if isinstance(slot, int) and not isinstance(slot, bool) and 0 <= slot < 5
        }
        if isinstance(raw_slots, list)
        else set()
    )
    previous = set(slots)
    if confirmed:
        slots.discard(map_slot)
    else:
        slots.add(map_slot)
    if slots != previous:
        state["unconfirmed_map_slots"] = sorted(slots)
        if isinstance(state.get("gsi"), dict):
            state["gsi"] = {key: value for key, value in state["gsi"].items() if key != "auth"}
        conn.execute(
            """INSERT INTO live_match_data(match_id,live_state) VALUES(?,?)
               ON CONFLICT(match_id) DO UPDATE SET live_state=excluded.live_state,updated_at=CURRENT_TIMESTAMP""",
            (match_id, json.dumps(state, ensure_ascii=False, allow_nan=False)),
        )
    return slots


def has_nonfinite_number(value):
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(has_nonfinite_number(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(has_nonfinite_number(item) for item in value)
    return False


@overload
def read_ingest_number(
    payload: Mapping[str, object],
    key: str,
    minimum: float = 0,
    maximum: float = 100000,
    *,
    integer: Literal[True],
    default: int | float | str | None = None,
) -> int | None: ...


@overload
def read_ingest_number(
    payload: Mapping[str, object],
    key: str,
    minimum: float = 0,
    maximum: float = 100000,
    integer: Literal[False] = False,
    default: int | float | str | None = None,
) -> float | None: ...


@overload
def read_ingest_number(
    payload: Mapping[str, object],
    key: str,
    minimum: float = 0,
    maximum: float = 100000,
    integer: bool = False,
    default: int | float | str | None = None,
) -> int | float | None: ...


def read_ingest_number(
    payload: Mapping[str, object],
    key: str,
    minimum: float = 0,
    maximum: float = 100000,
    integer: bool = False,
    default: int | float | str | None = None,
) -> int | float | None:
    value = payload.get(key, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise IngestValidationError(f"{key} 必须是有效数字")
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        raise IngestValidationError(f"{key} 必须是有效数字") from None
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise IngestValidationError(f"{key} 超出允许范围")
    if integer and not value.is_integer():
        raise IngestValidationError(f"{key} 必须是整数")
    return int(value) if integer else value


def _live_side_stat(payload):
    if payload is None or payload == {}:
        return None
    if not isinstance(payload, dict):
        raise IngestValidationError("分阵营统计格式错误")
    rounds = read_ingest_number(payload, "roundsPlayed", 0, 100, integer=True)
    kills = read_ingest_number(payload, "kills", 0, 500, integer=True)
    deaths = read_ingest_number(payload, "deaths", 0, 500, integer=True)
    assists = read_ingest_number(payload, "assists", 0, 500, integer=True)
    damage = read_ingest_number(payload, "damage", 0, 100000)
    kast_rounds = read_ingest_number(payload, "kastRounds", 0, 100, integer=True)
    if rounds is not None and kast_rounds is not None and kast_rounds > rounds:
        raise IngestValidationError("KAST 回合数不能大于参赛回合数")
    adr = (
        round(damage / rounds, 1)
        if rounds and damage is not None
        else read_ingest_number(payload, "adr", 0, 10000)
    )
    kast = (
        round(kast_rounds * 100 / rounds, 1)
        if rounds and kast_rounds is not None
        else read_ingest_number(payload, "kast", 0, 100)
    )
    impact = estimate_hltv2_impact(kills, assists, rounds)
    rating, _, _ = calculate_rating(kills, deaths, rounds, adr=adr, kast=kast, impact=impact)
    return {
        "kills": kills,
        "deaths": deaths,
        "assists": assists,
        "damage": damage,
        "rounds": rounds,
        "adr": adr,
        "kast": kast,
        "rating": rating if rounds else None,
    }


def parse_director_player_stat(payload):
    rounds = read_ingest_number(payload, "roundsPlayed", 0, 100, integer=True)
    kills = read_ingest_number(payload, "kills", 0, 500, integer=True)
    deaths = read_ingest_number(payload, "deaths", 0, 500, integer=True)
    assists = read_ingest_number(payload, "assists", 0, 500, integer=True)
    damage = read_ingest_number(payload, "damage", 0, 100000)
    damage_taken = read_ingest_number(payload, "damageTaken", 0, 100000)
    headshots = read_ingest_number(payload, "headshots", 0, 500, integer=True)
    kast_rounds = read_ingest_number(payload, "kastRounds", 0, 100, integer=True)
    if headshots is not None and kills is not None and headshots > kills:
        raise IngestValidationError("爆头击杀数不能大于总击杀数")
    if kast_rounds is not None and rounds is not None and kast_rounds > rounds:
        raise IngestValidationError("KAST 回合数不能大于参赛回合数")
    multi = [
        read_ingest_number(payload, f"multi{size}k", 0, 100, integer=True) for size in range(1, 6)
    ]
    clutches = [
        read_ingest_number(payload, f"clutch1v{size}", 0, 100, integer=True) for size in range(1, 6)
    ]
    clutches_won = read_ingest_number(payload, "clutchesWon", 0, 100, integer=True)
    if clutches_won is None and all(value is not None for value in clutches):
        clutches_won = sum(value for value in clutches if value is not None)
    adr = (
        round(damage / rounds, 1)
        if rounds and damage is not None
        else read_ingest_number(payload, "adr", 0, 10000)
    )
    kast = (
        round(kast_rounds * 100 / rounds, 1)
        if rounds and kast_rounds is not None
        else read_ingest_number(payload, "kast", 0, 100)
    )
    impact = estimate_hltv2_impact(kills, assists, rounds)
    rating, kpr, dpr = calculate_rating(kills, deaths, rounds, adr=adr, kast=kast, impact=impact)
    t_stats = _live_side_stat(payload.get("tStats"))
    ct_stats = _live_side_stat(payload.get("ctStats"))
    utility_damage = read_ingest_number(payload, "utilityDamage", 0, 100000)
    stat = {
        "steam_id": str(payload.get("steam_id") or "").strip(),
        "name": str(payload.get("name") or "").strip(),
        "team_side": payload.get("team_side"),
        "kills": kills,
        "deaths": deaths,
        "assists": assists,
        "adr": adr,
        "kast": kast,
        "rating": rating if rounds else None,
        "kpr": kpr if rounds else None,
        "dpr": dpr if rounds else None,
        # Rating 按回归原值算（和 CSDA 一致）；保存的 Impact 最低记 0
        "impact": non_negative_impact(impact),
        "headshot_percentage": (round(headshots * 100 / kills, 1) if kills else 0)
        if headshots is not None and kills is not None
        else None,
        "clutches_won": clutches_won,
        "first_kill_count": read_ingest_number(payload, "firstKills", 0, 100, integer=True),
        "first_death_count": read_ingest_number(payload, "firstDeaths", 0, 100, integer=True),
        "mvp_count": read_ingest_number(payload, "mvpCount", 0, 100, integer=True),
        "utility_damage": utility_damage,
        "trade_kills": read_ingest_number(payload, "tradeKills", 0, 500, integer=True),
        "trade_deaths": read_ingest_number(payload, "tradeDeaths", 0, 500, integer=True),
        "bomb_plants": read_ingest_number(payload, "bombPlants", 0, 100, integer=True),
        "bomb_defuses": read_ingest_number(payload, "bombDefuses", 0, 100, integer=True),
        "utility_damage_per_round": round(utility_damage / rounds, 1)
        if rounds and utility_damage is not None
        else None,
        "rounds_played": rounds,
        "damage_delta_per_round": round((damage - damage_taken) / rounds, 1)
        if rounds and damage is not None and damage_taken is not None
        else None,
        "rws_basic": read_ingest_number(payload, "rwsBasic", 0, 100),
        "flash_assists": read_ingest_number(payload, "flashAssists", 0, 500, integer=True),
    }
    for side, values in (("t", t_stats), ("ct", ct_stats)):
        for field in ("rating", "kills", "deaths", "adr"):
            stat[f"{side}_{field}"] = values[field] if values else None
    for index, value in enumerate(multi, 1):
        stat[f"multi{index}k"] = value
    for index, value in enumerate(clutches, 1):
        stat[f"clutch_1v{index}"] = value
    return stat


# 与网页雷达图使用同一套坐标换算。包点中心来自 resources/radars/*.svg
# 中的红色斜线区域，只用于游戏没有直接返回 A / B 时的兜底判断。
_RADAR_SIZE = 708
_RADAR_META_PATH = (
    Path(__file__).resolve().parents[1] / "resources" / "radars" / "map-metadata.json"
)
try:
    _RADAR_METADATA = json.loads(_RADAR_META_PATH.read_text(encoding="utf-8"))
except (OSError, ValueError, TypeError):
    _RADAR_METADATA = {"radar_size": 1024, "maps": {}}
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
        return result if all(math.isfinite(number) for number in result) else None
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
    position = _parse_gsi_coordinates(position)
    if position is None:
        return None
    key = _normalize_map_key(map_name)
    metadata = (_RADAR_METADATA.get("maps", {}) or {}).get(key)
    if metadata and len(position) >= 2:
        resolution = float(metadata.get("resolution") or 0)
        offset = metadata.get("offset", {}) or {}
        if resolution > 0:
            x = (float(position[0]) + float(offset.get("x", 0))) / resolution
            y = float(_RADAR_METADATA.get("radar_size", 1024)) - (
                (float(position[1]) + float(offset.get("y", 0))) / resolution
            )
            return (x / 1024 * _RADAR_SIZE, y / 1024 * _RADAR_SIZE)
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
    raw_round = int((data.get("map", {}) or {}).get("round", 0) or 0)
    round_num = max(1, raw_round + 1)
    events = merged.get("bomb_events", [])
    if not isinstance(events, list):
        events = []
    now = time.time()
    events.append(
        {
            "id": f"plant-{round_num}-{int(now * 1000)}",
            "round": round_num,
            "round_number": round_num,
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
    """记录本回合阵亡位置；击杀者由 GSI 帧推断不可靠，因此不再生成即时击杀列表。"""
    previous_gsi = merged.get("gsi", {}) or {}
    previous_players = previous_gsi.get("allplayers", {}) or {}
    current_players = data.get("allplayers", {}) or {}
    current_map = (data.get("map", {}) or {}).get("name", "")
    previous_map = (previous_gsi.get("map", {}) or {}).get("name", "")
    map_changed = previous_map and previous_map != current_map
    round_num = (data.get("map", {}) or {}).get("round", 0)
    previous_round = (previous_gsi.get("map", {}) or {}).get("round")
    round_changed = previous_round is not None and previous_round != round_num
    markers = (
        []
        if map_changed or round_changed
        else merged.get("death_markers", merged.get("kill_markers", []))
    )
    if not isinstance(markers, list):
        markers = []
    if map_changed:
        merged["round_history"] = []

    now = time.time()
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
        marker_id = f"{round_num + 1}-{steamid}-{int(now * 1000)}"
        markers.append(
            {
                "id": marker_id,
                "steamid": str(steamid),
                "name": player.get("name", ""),
                "side": victim_side,
                "round": round_num + 1,
                "round_number": round_num + 1,
                "x": position[0],
                "y": position[1],
                "z": position[2] if len(position) > 2 else None,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "captured_at_epoch": now,
            }
        )

    # 雷达只保留当前回合；旧字段保留但不再生成/展示即时击杀列表。
    merged["death_markers"] = markers[-10:]
    merged["kill_markers"] = merged["death_markers"]
    merged["kill_events"] = []
