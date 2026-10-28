# 统计数据计算函数

import math

HLTV2_ESTIMATE_METHOD = "csda_hltv2_regression_v1"
HLTV2_ESTIMATE_SOURCE = "https://github.com/akiver/cs-demo-analyzer/blob/main/pkg/api/player.go"


def _rounds(value):
    try:
        value = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return value if math.isfinite(value) and value > 0 else 0.0


def estimate_hltv2_impact(kills, assists, rounds_played):
    """CSDA 使用的公开回归近似，不是 HLTV 保密的精确 Impact 公式。

    来源：Dave 的 reverse-engineering-hltv-rating，CSDA player.go 同样使用此式。
    未记录的助攻不能当作零；负估值也保留，以便与 CSDA Rating 的输入一致。
    """
    rounds_played = _rounds(rounds_played)
    if not rounds_played or kills is None or assists is None:
        return None
    return 2.13 * kills / rounds_played + 0.42 * assists / rounds_played - 0.41


def non_negative_impact(value):
    """保存和展示用的 Impact：最低记 0。

    上面的回归近似在击杀、助攻很少时会算出负数（0 杀 0 助攻得 -0.41），这只是直线公式往外推的结果；
    HLTV 的 Impact 由多杀、首杀、残局获胜等加分项构成，不会是负数。Rating 仍用回归原值计算，和 CSDA 一致。
    """
    if value is None:
        return None
    return max(0.0, float(value))


def impact_calculation_metadata(stat):
    """保存 Rating 实际使用的 Impact，和最低为零的显示值分开。

    旧导入记录仅在来源与显示值都符合回归公式时补认计算口径，手工 Impact 不重解释。
    """
    stat = dict(stat)
    method = stat.get("impact_method")
    raw = stat.get("rating_impact")
    estimate = estimate_hltv2_impact(
        stat.get("kills"), stat.get("assists"), stat.get("rounds_played")
    )
    if method == HLTV2_ESTIMATE_METHOD:
        return method, raw if raw is not None else estimate
    if method == "manual":
        return method, raw if raw is not None else stat.get("impact")
    source = stat.get("_data_source") or stat.get("data_source")
    displayed = stat.get("impact")
    if source in {"demo", "demo_review", "director_final", "director_live", "gotv_relay"}:
        if (
            estimate is not None
            and displayed is not None
            and math.isclose(float(displayed), max(0.0, estimate), rel_tol=0, abs_tol=0.005001)
        ):
            return HLTV2_ESTIMATE_METHOD, estimate
    return "manual", displayed


def calculate_rating(kills, deaths, rounds_played, adr=None, kast=None, impact=None):
    """
    计算与 CSDA 同口径的 Rating 2.0 回归近似，非 HLTV 官方精确公式。

    来源：https://dave.xn--tckwe/posts/reverse-engineering-hltv-rating/
    缺少必要指标时不猜测评分，返回 None。
    返回 (rating, kpr, dpr)
    """
    rounds_played = _rounds(rounds_played)
    if not rounds_played:
        return 0.0, 0.0, 0.0

    kpr = kills / rounds_played if kills is not None else None
    # Zero deaths is a real value, not a missing value. The old 0.01 floor
    # made perfect maps look worse and caused director/site differences.
    dpr = deaths / rounds_played if deaths is not None else None

    if kpr is None or dpr is None or adr is None or kast is None or impact is None:
        return (
            None,
            round(kpr, 2) if kpr is not None else None,
            round(dpr, 2) if dpr is not None else None,
        )

    rating = (
        0.0073 * (kast or 0)
        + 0.3591 * kpr
        - 0.5329 * dpr
        + 0.2372 * impact
        + 0.0032 * (adr or 0)
        + 0.1587
    )

    return round(max(0.0, rating), 2), round(kpr, 2), round(dpr, 2)


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

    旧版站内自定义指标，仅为旧调用保留；不是 HLTV Impact。
    新的 Rating 2.0 近似输入使用 estimate_hltv2_impact。
    """
    rounds_played = _rounds(rounds_played)
    if not rounds_played:
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

    total_kills = sum(s.get("kills") or 0 for s in match_stats_list)
    total_deaths = sum(s.get("deaths") or 0 for s in match_stats_list)
    total_assists = sum(s.get("assists") or 0 for s in match_stats_list)
    matches = len(match_stats_list)

    def weighted(field, weight_field, digits):
        recorded = [s for s in match_stats_list if s.get(field) is not None]
        known_weights = [(s[field], _rounds(s.get(weight_field))) for s in recorded]
        denominator = sum(weight for _, weight in known_weights)
        if denominator:
            average = sum(value * weight for value, weight in known_weights) / denominator
        elif recorded:
            average = sum(s[field] for s in recorded) / len(recorded)
        else:
            return None
        return round(average, digits)

    return {
        "matches": matches,
        "total_kills": total_kills,
        "total_deaths": total_deaths,
        "total_assists": total_assists,
        "kd_ratio": calculate_kd_ratio(total_kills, total_deaths),
        "avg_adr": weighted("adr", "rounds_played", 1),
        "avg_rating": weighted("rating", "rounds_played", 2),
        "avg_kast": weighted("kast", "rounds_played", 1),
        "avg_headshot_percentage": weighted("headshot_percentage", "kills", 1),
    }
