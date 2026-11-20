"""Convert CSDA data into the website's player and map statistics."""

import math
from collections import defaultdict

from src.website.domains.demos.demo_rounds import (
    _empty_event_stats,
    _event_int,
    _extract_halftime_scores,
    _kill_is_in_round_window,
    _steam_id,
    calculate_event_player_stats,
)


def parse_player_stats(match_data):
    """
    从 csda JSON 解析所有选手统计数据（含 T/CT 侧数据）

    csda → DB 映射:
        name → nickname, steamId → steam_id, killCount → kills,
        deathCount → deaths, assistCount → assists,
        averageDamagePerRound → adr, averageKillPerRound → kpr,
        averageDeathPerRound → dpr, kast → kast,
        headshotPercent → headshot_percentage, hltvRating2 → rating

    T/CT stats: csda does NOT provide per-player side stats natively.
    We calculate them from kills/damages/rounds data.

    返回: list[dict]
    """
    players_data = match_data.get("players", {}) or {}
    if not isinstance(players_data, dict):
        return []
    players_data = {
        _steam_id(sid): player
        for sid, player in players_data.items()
        if _steam_id(sid) and isinstance(player, dict)
    }
    team_a = match_data.get("teamA", {}) or {}
    team_b = match_data.get("teamB", {}) or {}
    rounds = match_data.get("rounds", [])
    if not isinstance(rounds, list):
        rounds = []
    rounds = [row for row in rounds if isinstance(row, dict)]
    rounds_count = len(rounds)
    rounds_by_number = {
        _event_int(row, "number", index): row for index, row in enumerate(rounds, 1)
    }
    event_player_stats = calculate_event_player_stats(match_data)

    def metric(player, key, digits=None):
        value = player.get(key)
        if value is None:
            return None
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value):
            return None
        return round(value, digits) if digits is not None else int(value)

    def grenade_count(player, key, event_key, steam_id):
        recorded = metric(player, key)
        if recorded is not None:
            return recorded
        events = match_data.get(event_key)
        if not isinstance(events, list):
            return None
        if any(not isinstance(event, dict) for event in events):
            raise ValueError("Demo 的投掷物事件格式无效，未保存统计数据")
        return sum(_steam_id(event.get("throwerSteamId")) == steam_id for event in events)

    # ---- Calculate T/CT side stats from kills, damages, rounds ----
    # csda provides killerSide/attackerSide directly in kills/damages (2=T, 3=CT)
    side_kills = {}  # steam_id_str -> {'T': int, 'CT': int}
    side_deaths = {}
    side_damage = {}  # steam_id_str -> {'T': int, 'CT': int}  (total damage)
    side_rounds = {}  # steam_id_str -> {'T': int, 'CT': int}
    side_assists = {}
    side_kast_rounds = {}
    deaths_by_round = defaultdict(set)
    damage_received = {}
    rws_points = {}

    # Map steam_id -> team letter
    player_team_map = {}
    for sid, p in players_data.items():
        if not isinstance(p, dict):
            continue
        letter = (p.get("team") or {}).get("letter", "")
        player_team_map[sid] = letter

    # Initialize accumulators
    for sid in players_data:
        side_kills[sid] = {"T": 0, "CT": 0}
        side_deaths[sid] = {"T": 0, "CT": 0}
        side_damage[sid] = {"T": 0, "CT": 0}
        side_rounds[sid] = {"T": 0, "CT": 0}
        side_assists[sid] = {"T": 0, "CT": 0}
        side_kast_rounds[sid] = {"T": set(), "CT": set()}
        damage_received[sid] = 0
        rws_points[sid] = 0.0

    def _side_label(v):
        """2=T, 3=CT in demoinfocs common.Team"""
        return "T" if v == 2 else "CT"

    # Count rounds per side for each player (from rounds data)
    for r in rounds:
        a_side = _event_int(r, "teamASide")
        b_side = _event_int(r, "teamBSide")
        for sid, letter in player_team_map.items():
            side_val = a_side if letter == "A" else b_side if letter == "B" else 0
            if side_val in (2, 3):
                if sid in side_rounds:
                    side_rounds[sid][_side_label(side_val)] += 1

    # Count kills/deaths by side (using killerSide/victimSide directly)
    kills_list = match_data.get("kills", [])
    if isinstance(kills_list, list):
        for kill in kills_list:
            if not isinstance(kill, dict):
                continue
            round_number = _event_int(kill, "roundNumber")
            if round_number not in rounds_by_number or not _kill_is_in_round_window(
                kill, rounds_by_number[round_number]
            ):
                continue
            killer_sid = _steam_id(kill.get("killerSteamId", kill.get("killerSteamId64")))
            victim_sid = _steam_id(kill.get("victimSteamId", kill.get("victimSteamId64")))
            assister_sid = _steam_id(kill.get("assisterSteamId", kill.get("assisterSteamId64")))
            killer_side = _event_int(kill, "killerSide")
            victim_side = _event_int(kill, "victimSide")
            enemy_kill = (
                killer_side in (2, 3) and victim_side in (2, 3) and killer_side != victim_side
            )

            if enemy_kill and killer_sid in side_kills and not kill.get("isKillerControllingBot"):
                side_kills[killer_sid][_side_label(killer_side)] += 1
                side_kast_rounds[killer_sid][_side_label(killer_side)].add(round_number)
            if (
                enemy_kill
                and assister_sid in side_assists
                and not kill.get("isAssisterControllingBot")
            ):
                assister_side = _event_int(kill, "assisterSide", killer_side)
                if assister_side in (2, 3):
                    side_assists[assister_sid][_side_label(assister_side)] += 1
                    side_kast_rounds[assister_sid][_side_label(assister_side)].add(round_number)

            if victim_sid in side_deaths and not kill.get("isVictimControllingBot"):
                if victim_side in (2, 3):
                    side_deaths[victim_sid][_side_label(victim_side)] += 1
                    deaths_by_round[victim_sid].add(round_number)
                    if kill.get("isTradeDeath"):
                        side_kast_rounds[victim_sid][_side_label(victim_side)].add(round_number)

    for number, round_data in rounds_by_number.items():
        for sid, letter in player_team_map.items():
            side = (
                _event_int(round_data, "teamASide" if letter == "A" else "teamBSide")
                if letter in ("A", "B")
                else 0
            )
            if side in (2, 3) and number not in deaths_by_round[sid]:
                side_kast_rounds[sid][_side_label(side)].add(number)

    # Count damage by side (using attackerSide directly)
    damages_list = match_data.get("damages")
    winning_rounds = {
        int(r.get("number", 0) or 0): {
            "name": str(r.get("winnerName", "") or ""),
            "side": int(r.get("winnerSide", 0) or 0),
        }
        for r in rounds
    }
    winning_round_damage = {}
    if isinstance(damages_list, list):
        for dmg in damages_list:
            if not isinstance(dmg, dict):
                continue
            attacker_sid = str(dmg.get("attackerSteamId", dmg.get("attackerSteamId64", "")))
            victim_sid = str(dmg.get("victimSteamId", dmg.get("victimSteamId64", "")))
            amount = int(dmg.get("healthDamage", 0) or 0)
            attacker_side = int(dmg.get("attackerSide", 0))
            victim_side = int(dmg.get("victimSide", 0))

            is_enemy_damage = (
                attacker_sid
                and victim_sid
                and attacker_sid != victim_sid
                and attacker_side in (2, 3)
                and victim_side in (2, 3)
                and attacker_side != victim_side
                and amount > 0
            )
            if is_enemy_damage and attacker_sid in side_damage:
                side_damage[attacker_sid][_side_label(attacker_side)] += amount
            if is_enemy_damage and victim_sid in damage_received:
                damage_received[victim_sid] += amount

            round_num = int(dmg.get("roundNumber", 0) or 0)
            winner = winning_rounds.get(round_num, {})
            attacker_team = str(dmg.get("attackerTeamName", "") or "")
            if (
                is_enemy_damage
                and attacker_sid in rws_points
                and (
                    (winner.get("name") and attacker_team == winner.get("name"))
                    or (winner.get("side") and attacker_side == winner.get("side"))
                )
            ):
                round_damage = winning_round_damage.setdefault(round_num, {})
                round_damage[attacker_sid] = round_damage.get(attacker_sid, 0) + amount

    # Basic RWS: share 100 points between the winning side by damage in each won round.
    for round_damage in winning_round_damage.values():
        total_damage = sum(round_damage.values())
        if total_damage <= 0:
            continue
        for sid, amount in round_damage.items():
            rws_points[sid] += amount * 100.0 / total_damage

    # Build results
    results = []
    if not isinstance(players_data, dict):
        return results
    for steam_id, player in players_data.items():
        name = player.get("name", "")
        if not name:
            continue

        team_letter = (player.get("team") or {}).get("letter", "")
        team_name = ""
        if team_letter == "A":
            team_name = team_a.get("name", "")
        elif team_letter == "B":
            team_name = team_b.get("name", "")

        entry_kills = metric(player, "firstKillCount")
        entry_deaths = metric(player, "firstDeathCount")
        event_stats = event_player_stats.get(str(steam_id), _empty_event_stats())
        events_available = isinstance(match_data.get("kills"), list) and rounds_count > 0
        if not events_available:
            event_stats = {key: None for key in event_stats}
        clutches_won = event_stats["clutches_won"]

        from src.website.domains.statistics.stats_calc import (
            HLTV2_ESTIMATE_METHOD,
            estimate_hltv2_impact,
            non_negative_impact,
        )

        impact = estimate_hltv2_impact(
            metric(player, "killCount"),
            metric(player, "assistCount"),
            rounds_count,
        )
        # Rating 取自 CSDA（按回归原值算）；保存的 Impact 最低记 0
        shown_impact = non_negative_impact(impact)

        sk = side_kills.get(steam_id, {"T": 0, "CT": 0})
        sd = side_deaths.get(steam_id, {"T": 0, "CT": 0})
        sdm = side_damage.get(steam_id, {"T": 0, "CT": 0})
        sr = side_rounds.get(steam_id, {"T": 0, "CT": 0})

        side_rounds_complete = rounds_count > 0 and sr["T"] + sr["CT"] == rounds_count
        kills_total = metric(player, "killCount")
        deaths_total = metric(player, "deathCount")
        side_kills_complete = sk["T"] + sk["CT"] == kills_total
        side_deaths_complete = sd["T"] + sd["CT"] == deaths_total
        side_stats_complete = (
            events_available
            and side_rounds_complete
            and side_kills_complete
            and side_deaths_complete
        )
        side_damage_complete = isinstance(damages_list, list) and metric(
            player, "healthDamage"
        ) == sum(sdm.values())
        side_assists_complete = metric(player, "assistCount") == sum(
            side_assists[steam_id].values()
        )

        t_rounds = sr["T"]
        ct_rounds = sr["CT"]
        t_k = sk["T"] if side_stats_complete else None
        ct_k = sk["CT"] if side_stats_complete else None
        t_d = sd["T"] if side_stats_complete else None
        ct_d = sd["CT"] if side_stats_complete else None

        t_adr_val = (
            round(sdm["T"] / t_rounds, 1)
            if side_stats_complete and side_damage_complete and t_rounds
            else None
        )
        ct_adr_val = (
            round(sdm["CT"] / ct_rounds, 1)
            if side_stats_complete and side_damage_complete and ct_rounds
            else None
        )
        t_kast = (
            len(side_kast_rounds[steam_id]["T"]) / t_rounds * 100
            if side_stats_complete and side_assists_complete and t_rounds
            else None
        )
        ct_kast = (
            len(side_kast_rounds[steam_id]["CT"]) / ct_rounds * 100
            if side_stats_complete and side_assists_complete and ct_rounds
            else None
        )

        # Approximate T/CT rating from side-specific stats
        from src.website.domains.statistics.stats_calc import calculate_rating as _calc_rtg

        if side_stats_complete:
            t_rating, _, _ = _calc_rtg(
                kills=t_k,
                deaths=t_d,
                rounds_played=t_rounds,
                adr=t_adr_val,
                kast=t_kast,
                impact=estimate_hltv2_impact(t_k, side_assists[steam_id]["T"], t_rounds)
                if side_assists_complete
                else None,
            )
            ct_rating, _, _ = _calc_rtg(
                kills=ct_k,
                deaths=ct_d,
                rounds_played=ct_rounds,
                adr=ct_adr_val,
                kast=ct_kast,
                impact=estimate_hltv2_impact(ct_k, side_assists[steam_id]["CT"], ct_rounds)
                if side_assists_complete
                else None,
            )
        else:
            t_rating = ct_rating = None
        if not t_rounds:
            t_rating = None
        if not ct_rounds:
            ct_rating = None

        results.append(
            {
                "steam_id": int(steam_id) if steam_id.isdigit() else steam_id,
                "name": name,
                "team_name": team_name,
                "team_letter": team_letter,
                "kills": kills_total,
                "deaths": deaths_total,
                "assists": metric(player, "assistCount"),
                "adr": metric(player, "averageDamagePerRound", 1),
                "kpr": metric(player, "averageKillPerRound", 2),
                "dpr": metric(player, "averageDeathPerRound", 2),
                "kast": metric(player, "kast", 1),
                "headshot_percentage": metric(player, "headshotPercent", 1),
                "headshot_count": metric(player, "headshotCount"),
                "rating": metric(player, "hltvRating2", 2),
                "impact": round(shown_impact, 2) if shown_impact is not None else None,
                "impact_method": HLTV2_ESTIMATE_METHOD,
                "rating_method": HLTV2_ESTIMATE_METHOD,
                "mvp_count": metric(player, "mvpCount"),
                "first_kill_count": entry_kills,
                "first_death_count": entry_deaths,
                "clutches_won": clutches_won,
                "clutch_1v1": event_stats["clutch_1v1"],
                "clutch_1v2": event_stats["clutch_1v2"],
                "clutch_1v3": event_stats["clutch_1v3"],
                "clutch_1v4": event_stats["clutch_1v4"],
                "clutch_1v5": event_stats["clutch_1v5"],
                # 多杀细分
                "multi1k": event_stats["multi1k"],
                "multi2k": event_stats["multi2k"],
                "multi3k": event_stats["multi3k"],
                "multi4k": event_stats["multi4k"],
                "multi5k": event_stats["multi5k"],
                # 投掷物统计
                "utility_damage": metric(player, "utilityDamage", 1),
                "utility_damage_per_round": metric(player, "utilityDamagePerRound", 2),
                "enemies_flashed": metric(player, "enemyFlashCount"),
                "flash_count": grenade_count(
                    player, "flashbangCount", "flashbangsExplode", steam_id
                ),
                "he_count": grenade_count(player, "heGrenadeCount", "heGrenadesExplode", steam_id),
                "smoke_count": grenade_count(player, "smokeCount", "smokesStart", steam_id),
                "molotov_count": metric(player, "molotovCount"),
                # 交换击杀与目标相关数据
                "trade_kills": metric(player, "tradeKillCount"),
                "trade_deaths": metric(player, "tradeDeathCount"),
                "bomb_plants": metric(player, "bombPlantedCount"),
                "bomb_defuses": metric(player, "bombDefusedCount"),
                "rounds_played": rounds_count,
                "damage_delta_per_round": round(
                    (player.get("healthDamage", 0) - damage_received.get(steam_id, 0))
                    / rounds_count,
                    2,
                )
                if rounds_count
                and isinstance(damages_list, list)
                and metric(player, "healthDamage") is not None
                else None,
                "rws_basic": round(rws_points.get(steam_id, 0) / rounds_count, 2)
                if rounds_count and isinstance(damages_list, list)
                else None,
                # T/CT 侧数据
                "t_rating": t_rating,
                "ct_rating": ct_rating,
                "t_kills": t_k,
                "ct_kills": ct_k,
                "t_deaths": t_d,
                "ct_deaths": ct_d,
                "t_adr": t_adr_val,
                "ct_adr": ct_adr_val,
                "t_rounds": t_rounds if side_rounds_complete else None,
                "ct_rounds": ct_rounds if side_rounds_complete else None,
                "t_assists": side_assists[steam_id]["T"]
                if side_stats_complete and side_assists_complete
                else None,
                "ct_assists": side_assists[steam_id]["CT"]
                if side_stats_complete and side_assists_complete
                else None,
                "t_kast": round(t_kast, 1) if t_kast is not None else None,
                "ct_kast": round(ct_kast, 1) if ct_kast is not None else None,
                "side_stats_complete": side_stats_complete,
            }
        )

    from src.website.domains.demos.demo_side_parser import parse_side_stats

    side_stats = parse_side_stats(match_data)
    for result in results:
        result["side_stats"] = side_stats.get(str(result["steam_id"]), {})
    return results


def get_match_info(match_data):
    """提取比赛基本信息（含半场比分）"""
    team_a = match_data.get("teamA", {})
    team_b = match_data.get("teamB", {})

    rounds = match_data.get("rounds", [])
    if not isinstance(rounds, list):
        rounds = []

    halftime = _extract_halftime_scores(match_data)

    return {
        "map_name": match_data.get("mapName", ""),
        "date": match_data.get("date", ""),
        "duration_seconds": int(match_data.get("duration", 0) / 1_000_000_000)
        if match_data.get("duration")
        else 0,
        "team_a_name": (team_a or {}).get("name", ""),
        "team_b_name": (team_b or {}).get("name", ""),
        "team_a_score": (team_a or {}).get("score"),
        "team_b_score": (team_b or {}).get("score"),
        "rounds_count": len(rounds),
        "tick_rate": match_data.get("tickrate", 0),
        "source": match_data.get("source", ""),
        "halftime": halftime,
    }


def normalize_map_name(name):
    """标准化地图名称：去掉 de_/cs_ 前缀，统一小写"""
    n = name.lower().replace(" ", "_")
    for prefix in ("de_", "cs_"):
        if n.startswith(prefix):
            n = n[len(prefix) :]
            break
    return n


def match_map_slot(demo_map_name, match_map_names):
    """
    将 demo 中的地图名匹配到比赛的图槽

    参数:
        demo_map_name: demo 中解析出的地图名（如 'de_mirage'）
        match_map_names: list，比赛的三张图名（如 ['Mirage', None, None]）

    返回:
        int: 匹配到的 slot 索引；匹配不到返回 -1，不自动占用其他地图。
    """
    demo_norm = normalize_map_name(demo_map_name)
    for i, map_name in enumerate(match_map_names):
        if map_name and normalize_map_name(map_name) == demo_norm:
            return i
    return -1
