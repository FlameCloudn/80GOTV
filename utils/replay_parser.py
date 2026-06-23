"""
2D Demo 回放解析器：使用 demoparser2 提取选手坐标和击杀事件。
"""

import logging
import math
import os

logger = logging.getLogger("80gotv")


def _value(row, *names, default=None):
    _missing = object()  # 哨兵值，区分「字段不存在」和「值为 None」
    for name in names:
        try:
            value = row.get(name, _missing)
        except AttributeError:
            continue
        if value is not _missing:
            return value
    return default


def _number(value, default=0.0):
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _integer(value, default=0):
    return int(_number(value, default))


def _text(value):
    if value is None:
        return ""
    try:
        if isinstance(value, float) and math.isnan(value):
            return ""
    except TypeError:
        pass
    text = str(value)
    return "" if text.lower() == "nan" else text


def _event_round_number(row):
    total_rounds = _integer(_value(row, "total_rounds_played", "round_num", default=0))
    return total_rounds + 1 if total_rounds >= 0 else 0


def _primary_weapon(inventory):
    if not isinstance(inventory, list):
        return ""
    primary_types = {"Rifle", "SniperRifle", "Machine Gun", "Shotgun", "Submachine Gun"}
    for item in inventory:
        if isinstance(item, dict) and item.get("weapon_type") in primary_types:
            return str(item.get("weapon_name", ""))
    return ""


def parse_demo_replay(demo_path, tick_sample=8):
    """
    解析 demo 为 2D 回放数据。

    tick_sample 表示每隔多少个时间点保留一帧。
    """
    try:
        from demoparser2 import DemoParser
    except ImportError:
        logger.error("demoparser2 未安装。请运行: pip install demoparser2")
        return None

    if not os.path.isfile(demo_path):
        logger.error("Demo 文件不存在: %s", demo_path)
        return None

    try:
        parser = DemoParser(demo_path)
        header = parser.parse_header() or {}
        tick_rate = (
            _integer(
                header.get("tickrate", header.get("tick_rate", header.get("tickRate", 64))),
                64,
            )
            or 64
        )
        from utils.demo_parser import normalize_map_name

        map_name = normalize_map_name(header.get("map_name", header.get("mapName", "")) or "")

        fields = [
            "X",
            "Y",
            "Z",
            "health",
            "team_name",
            "is_alive",
            "total_rounds_played",
            "inventory",
            "name",
            "steamid",
        ]
        try:
            df_ticks = parser.parse_ticks(fields)
        except Exception:
            # Older demoparser2 builds may not expose inventory on every demo.
            fields.remove("inventory")
            df_ticks = parser.parse_ticks(fields)

        df_kills = parser.parse_event(
            "player_death",
            player=["name", "steamid", "X", "Y", "team_name"],
            other=[
                "weapon",
                "headshot",
                "attackerblind",
                "noscope",
                "penetrated",
                "thrusmoke",
                "distance",
                "total_rounds_played",
                "attacker_X",
                "attacker_Y",
            ],
        )
        try:
            df_hurts = parser.parse_event(
                "player_hurt",
                player=["name", "steamid", "team_name"],
                other=[
                    "weapon",
                    "dmg_health",
                    "dmg_armor",
                    "health",
                    "hitgroup",
                    "total_rounds_played",
                ],
            )
        except Exception:
            df_hurts = None
        try:
            df_round_end = parser.parse_event("round_end", other=["total_rounds_played"])
        except Exception:
            df_round_end = None

        ticks_data = []
        team_names = {}
        if df_ticks is not None and not df_ticks.empty and "tick" in df_ticks:
            unique_ticks = sorted({_integer(value) for value in df_ticks["tick"].tolist()})
            sample_step = max(1, int(tick_sample or 1))
            keep_ticks = set(unique_ticks[::sample_step])
            sampled = df_ticks[df_ticks["tick"].map(_integer).isin(keep_ticks)]
            for tick, group in sampled.groupby(sampled["tick"].map(_integer), sort=True):
                players = []
                round_num = 0
                for _, row in group.iterrows():
                    health = _integer(_value(row, "health", default=100), 100)
                    alive = bool(_value(row, "is_alive", default=health > 0))
                    if not alive:
                        continue
                    team = _text(_value(row, "team_name", default=""))
                    name = _text(_value(row, "name", "player_name", default=""))
                    if team and name:
                        team_names.setdefault(team, team)
                    round_num = _integer(
                        _value(row, "total_rounds_played", "round_num", default=round_num)
                    )
                    players.append(
                        {
                            "name": name,
                            "steamid": _text(_value(row, "steamid", "steam_id", default="")),
                            "x": round(_number(_value(row, "X", default=0)), 1),
                            "y": round(_number(_value(row, "Y", default=0)), 1),
                            "hp": health,
                            "team": team,
                            "primary": _primary_weapon(_value(row, "inventory", default=None)),
                            "alive": True,
                        }
                    )
                if players:
                    ticks_data.append(
                        {
                            "tick": int(tick),
                            "round": round_num,
                            "round_number": round_num + 1 if round_num >= 0 else 0,
                            "players": players,
                        }
                    )

        kills_data = []
        if df_kills is not None and not df_kills.empty:
            for _, row in df_kills.iterrows():
                kills_data.append(
                    {
                        "tick": _integer(_value(row, "tick", default=0)),
                        "round": _integer(
                            _value(row, "total_rounds_played", "round_num", default=0)
                        ),
                        "round_number": _event_round_number(row),
                        "killer": _text(_value(row, "attacker_name", default="")),
                        "killer_steamid": _text(_value(row, "attacker_steamid", default="")),
                        "killer_side": _text(_value(row, "attacker_team_name", default="")),
                        "assister": _text(_value(row, "assister_name", default="")),
                        "assister_steamid": _text(_value(row, "assister_steamid", default="")),
                        "assister_side": _text(_value(row, "assister_team_name", default="")),
                        "victim": _text(_value(row, "user_name", default="")),
                        "victim_steamid": _text(_value(row, "user_steamid", default="")),
                        "victim_side": _text(_value(row, "user_team_name", default="")),
                        "killer_x": round(_number(_value(row, "attacker_X", default=0)), 1),
                        "killer_y": round(_number(_value(row, "attacker_Y", default=0)), 1),
                        "victim_x": round(
                            _number(_value(row, "user_X", "victim_X", "X", default=0)), 1
                        ),
                        "victim_y": round(
                            _number(_value(row, "user_Y", "victim_Y", "Y", default=0)), 1
                        ),
                        "weapon": _text(_value(row, "weapon", default="")),
                        "headshot": bool(_value(row, "headshot", default=False)),
                        "thrusmoke": bool(_value(row, "thrusmoke", default=False)),
                        "penetrated": bool(_value(row, "penetrated", default=False)),
                        "noscope": bool(_value(row, "noscope", default=False)),
                        "distance": round(_number(_value(row, "distance", default=0)), 1),
                    }
                )

        damages_data = []
        if df_hurts is not None and not df_hurts.empty:
            for _, row in df_hurts.iterrows():
                damages_data.append(
                    {
                        "tick": _integer(_value(row, "tick", default=0)),
                        "round": _integer(
                            _value(row, "total_rounds_played", "round_num", default=0)
                        ),
                        "round_number": _event_round_number(row),
                        "attacker": _text(_value(row, "attacker_name", default="")),
                        "attacker_steamid": _text(_value(row, "attacker_steamid", default="")),
                        "attacker_side": _text(_value(row, "attacker_team_name", default="")),
                        "victim": _text(_value(row, "user_name", default="")),
                        "victim_steamid": _text(_value(row, "user_steamid", default="")),
                        "victim_side": _text(_value(row, "user_team_name", default="")),
                        "damage": _integer(_value(row, "dmg_health", default=0)),
                        "armor_damage": _integer(_value(row, "dmg_armor", default=0)),
                        "weapon": _text(_value(row, "weapon", default="")),
                    }
                )

        round_results = []
        if df_round_end is not None and not df_round_end.empty:
            for index, row in df_round_end.iterrows():
                round_number = _integer(_value(row, "total_rounds_played", default=0), 0)
                if round_number <= 0:
                    round_number = index + 1
                round_results.append(
                    {
                        "round_number": round_number,
                        "tick": _integer(_value(row, "tick", default=0)),
                        "winner": _text(_value(row, "winner", default="")).upper(),
                        "reason": _text(_value(row, "reason", default="")),
                    }
                )

        # ---- 炸弹事件 ----
        bomb_events = []
        for evt_name in (
            "bomb_planted",
            "bomb_defused",
            "bomb_exploded",
            "bomb_beginplant",
            "bomb_begindefuse",
        ):
            try:
                df_evt = parser.parse_event(evt_name)
                if df_evt is not None and not df_evt.empty:
                    for _, row in df_evt.iterrows():
                        site_raw = _value(row, "site", default="")
                        site_str = str(site_raw) if site_raw is not None and site_raw != "" else ""
                        bomb_events.append(
                            {
                                "type": evt_name,
                                "tick": _integer(_value(row, "tick", default=0)),
                                "player": _text(_value(row, "user_name", default="")),
                                "site": site_str,
                            }
                        )
            except Exception:
                pass
        bomb_events.sort(key=lambda e: e["tick"])

        # ---- 回合边界事件 ----
        round_ends = []
        for evt_name in ("round_officially_ended",):
            try:
                df_evt = parser.parse_event(evt_name)
                if df_evt is not None and not df_evt.empty:
                    ticks_raw = [
                        _integer(_value(row, "tick", default=0)) for _, row in df_evt.iterrows()
                    ]
                    # round_officially_ended 可能同一 tick 触发多次，去重并合并相近 tick(<50)
                    ticks_dedup = sorted(set(ticks_raw))
                    for t in ticks_dedup:
                        if not round_ends or t - round_ends[-1] > 50:
                            round_ends.append(t)
            except Exception:
                pass

        return {
            "ticks": ticks_data,
            "kills": kills_data,
            "damages": damages_data,
            "round_results": round_results,
            "bomb_events": bomb_events,
            "round_ends": round_ends,
            "map_name": map_name,
            "tick_rate": tick_rate,
            "team_names": team_names,
        }
    except Exception:
        logger.exception("Demo 回放解析失败")
        return None
