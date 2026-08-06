# 统计数据计算函数


def calculate_rating(kills, deaths, rounds_played, adr=None, kast=None, impact=None):
    """
    计算 HLTV Rating 2.0

    公式: 0.0073*KAST + 0.3591*KPR - 0.5329*DPR + 0.2372*Impact + 0.0032*ADR + 0.2698
    返回 (rating, kpr, dpr)
    """
    if rounds_played == 0:
        return 0.0, 0.0, 0.0

    rounds_played = max(0, float(rounds_played or 0))
    kpr = kills / rounds_played
    # Zero deaths is a real value, not a missing value. The old 0.01 floor
    # made perfect maps look worse and caused director/site differences.
    dpr = deaths / rounds_played

    # ``None`` means unavailable; an explicit zero Impact must remain zero.
    if impact is None:
        impact = kpr * 0.5 + (adr or 0) / 200.0

    rating = (
        0.0073 * (kast or 0)
        + 0.3591 * kpr
        - 0.5329 * dpr
        + 0.2372 * impact
        + 0.0032 * (adr or 0)
        + 0.2698
    )

    return round(max(0.0, min(3.0, rating)), 2), round(kpr, 2), round(dpr, 2)


def calculate_kd_ratio(kills, deaths):
    """计算 K/D 比"""
    if deaths == 0:
        return kills
    return round(kills / deaths, 2)


def calculate_kast(kills, assists, survived, traded, rounds_played):
    """
    计算 KAST (Kills, Assists, Survived, Traded)

    KAST% = (回合中有击杀 + 有助攻 + 存活 + 被交易) / 总回合数 * 100
    """
    if rounds_played == 0:
        return 0.0

    # Callers that only have totals can still get a bounded estimate. When
    # round-number sets/lists are supplied, count the union instead of adding
    # overlapping K/A/S/T flags from the same round.
    if all(isinstance(value, (set, list, tuple)) for value in (kills, assists, survived, traded)):
        kast_rounds = len(set(kills) | set(assists) | set(survived) | set(traded))
    else:
        kast_rounds = min(kills + assists + survived + traded, rounds_played)
    kast_rounds = min(kast_rounds, rounds_played)
    return round((kast_rounds / rounds_played) * 100, 1)


def calculate_adr(total_damage, rounds_played):
    """计算 ADR (Average Damage per Round)"""
    if rounds_played == 0:
        return 0.0
    return round(total_damage / rounds_played, 1)


def calculate_impact(entry_kills, entry_deaths, multi_kills, clutches_won, rounds_played):
    """
    计算 Impact 评分

    简化版，考虑首杀、多杀、残局等关键表现
    """
    if rounds_played == 0:
        return 0.0

    impact = (
        entry_kills * 1.5 - entry_deaths * 0.7 + multi_kills * 0.5 + clutches_won * 2.0
    ) / rounds_played
    return round(max(0, impact), 2)


def calculate_headshot_percentage(headshot_kills, total_kills):
    """计算爆头率"""
    if total_kills == 0:
        return 0.0
    return round((headshot_kills / total_kills) * 100, 1)


def aggregate_player_stats(match_stats_list):
    """
    聚合选手在多场比赛中的数据

    参数:
        match_stats_list: 选手在多场比赛的数据列表

    返回:
        dict: 聚合后的统计数据
    """
    if not match_stats_list:
        return {}

    total_kills = sum(s["kills"] for s in match_stats_list)
    total_deaths = sum(s["deaths"] for s in match_stats_list)
    total_assists = sum(s["assists"] for s in match_stats_list)
    matches = len(match_stats_list)
    total_rounds = sum(max(0, float(s.get("rounds_played", 0) or 0)) for s in match_stats_list)
    weight = total_rounds or float(matches)

    avg_adr = (
        sum(
            float(s.get("adr", 0) or 0) * (float(s.get("rounds_played", 0) or 0) or 1)
            for s in match_stats_list
        )
        / weight
    )
    avg_rating = (
        sum(
            float(s.get("rating", 0) or 0) * (float(s.get("rounds_played", 0) or 0) or 1)
            for s in match_stats_list
        )
        / weight
    )
    avg_kast = (
        sum(
            float(s.get("kast", 0) or 0) * (float(s.get("rounds_played", 0) or 0) or 1)
            for s in match_stats_list
        )
        / weight
    )
    avg_hs = sum(
        float(s.get("headshot_percentage", 0) or 0) * (float(s.get("kills", 0) or 0) or 1)
        for s in match_stats_list
    ) / sum((float(s.get("kills", 0) or 0) or 1) for s in match_stats_list)

    return {
        "matches": matches,
        "total_kills": total_kills,
        "total_deaths": total_deaths,
        "total_assists": total_assists,
        "kd_ratio": calculate_kd_ratio(total_kills, total_deaths),
        "avg_adr": round(avg_adr, 1),
        "avg_rating": round(avg_rating, 2),
        "avg_kast": round(avg_kast, 1),
        "avg_headshot_percentage": round(avg_hs, 1),
    }
