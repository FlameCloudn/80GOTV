"""Build player metric blocks for profile and statistics views."""

from src.website.domains.statistics.stats_display import optional_number
from src.website.web.localization import t


def _num(value):
    return float(value or 0)


def _pct(value, target):
    if target <= 0:
        return 0
    return max(0, min(100, round(_num(value) / target * 100)))


def _rating_gauge_pct(value):
    if value is None:
        return 0
    return min(100, max(0, (float(value) - 0.5) / 1.5 * 100))


def _fmt(value, digits=2, suffix=""):
    if value is None:
        return "-"
    return f"{float(value):.{digits}f}{suffix}"


def _build_player_blocks(overall):
    rounds = _num(overall["rounds_played"])
    maps = int(overall["maps"] or 0)
    kills = _num(overall["total_kills"])
    deaths = _num(overall["total_deaths"])
    assists = _num(overall["total_assists"])
    first_kills = _num(overall["first_kills"])
    first_deaths = _num(overall["first_deaths"])
    trade_kills = _num(overall["trade_kills"])
    trade_deaths = _num(overall["trade_deaths"])
    utility_damage = _num(overall["utility_damage"])
    kd_ratio = kills / deaths if deaths else None
    assists_per_round = assists / rounds if rounds else 0
    multi_total = (
        _num(overall["multi2k"])
        + _num(overall["multi3k"])
        + _num(overall["multi4k"])
        + _num(overall["multi5k"])
    )
    rating_val = optional_number(overall["avg_rating"])
    if rating_val is None:
        rating_label = "Unknown"
    elif rating_val >= 1.15:
        rating_label = "Good"
    elif rating_val >= 0.95:
        rating_label = "Average"
    else:
        rating_label = "Bad"
    player_summary = {
        "matches": int(overall["matches"] or 0),
        "maps": maps,
        "rounds": int(rounds),
        "rating": rating_val,
        "rating_pct": _rating_gauge_pct(overall["avg_rating"]),
        "rating_label": rating_label,
        "rating_label_cn": t(f"stats.player.rating.{rating_label.lower()}"),
        "t_rating": overall["avg_t_rating"],
        "t_rating_pct": _rating_gauge_pct(overall["avg_t_rating"]),
        "ct_rating": overall["avg_ct_rating"],
        "ct_rating_pct": _rating_gauge_pct(overall["avg_ct_rating"]),
        "impact": overall["avg_impact"],
        "impact_pct": _pct(overall["avg_impact"], 1.5),
        "dpr": overall["avg_dpr"],
        "kast": overall["avg_kast"],
        "multi_kill": (multi_total / rounds * 100) if rounds else 0,
        "adr": overall["avg_adr"],
        "kpr": overall["avg_kpr"],
    }
    # HLTV 风格 7 分类
    trade_pct = trade_kills / kills * 100 if kills else 0
    trade_death_pct = trade_deaths / deaths * 100 if deaths else 0
    opening_attempts = first_kills + first_deaths
    opening_success_rate = first_kills / opening_attempts * 100 if opening_attempts else 0
    multi_round_pct = multi_total / rounds * 100 if rounds else 0
    clutch_per_round = _num(overall["clutches_won"]) / rounds if rounds else 0

    player_category_cards = [
        {
            "title": "stats.player.firepower",
            "desc": "stats.player.firepower_desc",
            "score": _pct(
                _num(rating_val) * 0.4
                + (overall["avg_kpr"] or 0) * 0.3
                + (overall["avg_adr"] or 0) / 120 * 0.3,
                1.5,
            ),
            "items": [
                {
                    "label": "stats.metric.kills_per_round",
                    "value": _fmt(overall["avg_kpr"]),
                    "pct": _pct(overall["avg_kpr"], 1.0),
                },
                {
                    "label": "stats.metric.damage_per_round",
                    "value": _fmt(overall["avg_adr"], 1),
                    "pct": _pct(overall["avg_adr"], 120),
                },
                {
                    "label": "stats.metric.multi_kill_rounds",
                    "value": _fmt(multi_round_pct, 1, "%"),
                    "pct": _pct(multi_round_pct, 30),
                },
                {
                    "label": "Impact",
                    "value": _fmt(overall["avg_impact"]),
                    "pct": _pct(overall["avg_impact"], 1.5),
                },
                {"label": "RATING 2.0", "value": _fmt(rating_val), "pct": _pct(rating_val, 1.5)},
            ],
        },
        {
            "title": "stats.player.trading",
            "desc": "stats.player.trading_desc",
            "score": _pct(trade_kills / max(trade_kills + trade_deaths, 1) * 100, 60),
            "items": [
                {
                    "label": "stats.metric.trade_kills_per_round",
                    "value": _fmt(trade_kills / rounds if rounds else 0),
                    "pct": _pct(trade_kills / rounds if rounds else 0, 0.25),
                },
                {
                    "label": "stats.metric.trade_kill_share",
                    "value": _fmt(trade_pct, 1, "%"),
                    "pct": _pct(trade_pct, 35),
                },
                {
                    "label": "stats.metric.traded_deaths_per_round",
                    "value": _fmt(trade_deaths / rounds if rounds else 0),
                    "pct": _pct(trade_deaths / rounds if rounds else 0, 0.25),
                },
                {
                    "label": "stats.metric.traded_death_share",
                    "value": _fmt(trade_death_pct, 1, "%"),
                    "pct": _pct(trade_death_pct, 35),
                },
                {
                    "label": "stats.metric.assists_per_round",
                    "value": _fmt(assists / rounds if rounds else 0),
                    "pct": _pct(assists / rounds if rounds else 0, 0.35),
                },
            ],
        },
        {
            "title": "stats.player.entry",
            "desc": "stats.player.entry_desc",
            "score": _pct(
                opening_success_rate * 0.5 + first_kills / rounds * 100 if rounds else 0, 60
            ),
            "items": [
                {
                    "label": "stats.metric.opening_attempt_share",
                    "value": _fmt(opening_attempts / rounds * 100 if rounds else 0, 1, "%"),
                    "pct": _pct(opening_attempts / rounds * 100 if rounds else 0, 35),
                },
                {
                    "label": "stats.metric.traded_death_share",
                    "value": _fmt(trade_death_pct, 1, "%"),
                    "pct": _pct(trade_death_pct, 35),
                },
                {
                    "label": "stats.metric.trade_kills_per_round",
                    "value": _fmt(trade_kills / rounds if rounds else 0),
                    "pct": _pct(trade_kills / rounds if rounds else 0, 0.25),
                },
                {
                    "label": "stats.metric.traded_deaths_per_round",
                    "value": _fmt(trade_deaths / rounds if rounds else 0),
                    "pct": _pct(trade_deaths / rounds if rounds else 0, 0.25),
                },
            ],
        },
        {
            "title": "stats.player.opening",
            "desc": "stats.player.opening_desc",
            "score": _pct(opening_success_rate, 75),
            "items": [
                {
                    "label": "stats.metric.opening_success",
                    "value": _fmt(opening_success_rate, 1, "%"),
                    "pct": _pct(opening_success_rate, 75),
                },
                {
                    "label": "stats.metric.opening_kills_per_round",
                    "value": _fmt(first_kills / rounds if rounds else 0),
                    "pct": _pct(first_kills / rounds if rounds else 0, 0.25),
                },
                {
                    "label": "stats.metric.opening_deaths_per_round",
                    "value": _fmt(first_deaths / rounds if rounds else 0),
                    "pct": _pct(first_deaths / rounds if rounds else 0, 0.25),
                },
                {
                    "label": "stats.metric.opening_kd",
                    "value": _fmt(first_kills / first_deaths if first_deaths else 0),
                    "pct": _pct(first_kills / first_deaths if first_deaths else 0, 2),
                },
            ],
        },
        {
            "title": "stats.player.clutches",
            "desc": "stats.player.clutches_desc",
            "score": _pct(clutch_per_round * 100, 8),
            "items": [
                {
                    "label": "stats.metric.clutches_won",
                    "value": str(int(_num(overall["clutches_won"]))),
                    "pct": _pct(overall["clutches_won"], max(maps, 1)),
                },
                {
                    "label": "stats.metric.clutch_points_per_round",
                    "value": _fmt(clutch_per_round),
                    "pct": _pct(clutch_per_round * 100, 6),
                },
                {
                    "label": "stats.metric.bomb_plants",
                    "value": str(int(_num(overall["bomb_plants"]))),
                    "pct": _pct(overall["bomb_plants"], max(maps * 2, 1)),
                },
                {
                    "label": "stats.metric.bomb_defuses",
                    "value": str(int(_num(overall["bomb_defuses"]))),
                    "pct": _pct(overall["bomb_defuses"], max(maps, 1)),
                },
            ],
        },
        {
            "title": "stats.player.utility",
            "desc": "stats.player.utility_desc",
            "score": _pct(
                (overall["utility_damage_per_round"] or 0) * 8
                + (_num(overall["enemies_flashed"]) / max(_num(overall["flash_count"]), 1)) * 20,
                12,
            ),
            "items": [
                {
                    "label": "stats.metric.utility_damage_per_round",
                    "value": _fmt(overall["utility_damage_per_round"]),
                    "pct": _pct(overall["utility_damage_per_round"], 10),
                },
                {
                    "label": "stats.metric.utility_damage_total",
                    "value": str(int(utility_damage)),
                    "pct": _pct(utility_damage, max(rounds * 8, 1)),
                },
                {
                    "label": "stats.metric.enemies_flashed_per_round",
                    "value": _fmt(_num(overall["enemies_flashed"]) / rounds if rounds else 0),
                    "pct": _pct(_num(overall["enemies_flashed"]) / rounds if rounds else 0, 0.9),
                },
                {
                    "label": "stats.metric.flash_success",
                    "value": _fmt(
                        _num(overall["enemies_flashed"])
                        / max(_num(overall["flash_count"]), 1)
                        * 100,
                        1,
                        "%",
                    ),
                    "pct": _pct(
                        _num(overall["enemies_flashed"])
                        / max(_num(overall["flash_count"]), 1)
                        * 100,
                        100,
                    ),
                },
            ],
        },
    ]
    player_statistics = [
        {"label": "stats.metric.kills", "value": str(int(kills))},
        {"label": "stats.metric.rounds", "value": str(int(rounds))},
        {"label": "HS%", "value": _fmt(overall["avg_hs"], 1, "%")},
        {"label": "stats.metric.kills_per_round", "value": _fmt(overall["avg_kpr"])},
        {"label": "stats.metric.deaths", "value": str(int(deaths))},
        {"label": "stats.metric.assists_per_round", "value": _fmt(assists_per_round)},
        {"label": "K/D", "value": _fmt(kd_ratio)},
        {"label": "stats.metric.deaths_per_round", "value": _fmt(overall["avg_dpr"])},
        {"label": "stats.metric.damage_per_round", "value": _fmt(overall["avg_adr"], 1)},
        {
            "label": "stats.metric.traded_by_teammates_per_round",
            "value": _fmt(trade_deaths / rounds if rounds else 0),
        },
        {
            "label": "stats.metric.utility_damage_per_round",
            "value": _fmt(overall["utility_damage_per_round"]),
        },
        {
            "label": "stats.metric.trades_for_teammates_per_round",
            "value": _fmt(trade_kills / rounds if rounds else 0),
        },
        {"label": "stats.metric.maps_played", "value": str(maps)},
        {"label": "Impact", "value": _fmt(overall["avg_impact"])},
    ]

    def missing(*fields):
        return any(optional_number(overall[field]) is None for field in fields)

    # Keep the established formulas for known inputs; a display fallback is
    # not evidence that a missing input was measured as zero.
    multi_inputs = ("multi2k", "multi3k", "multi4k", "multi5k", "rounds_played")
    summary_inputs = {
        "rounds": ("rounds_played",),
        "multi_kill": multi_inputs,
        "kpr": ("total_kills", "rounds_played", "avg_kpr"),
        "dpr": ("total_deaths", "rounds_played", "avg_dpr"),
    }
    for field, inputs in summary_inputs.items():
        if missing(*inputs):
            player_summary[field] = None

    category_inputs = {
        "stats.player.firepower": (
            "avg_rating",
            "avg_kpr",
            "total_kills",
            "rounds_played",
            "avg_adr",
        ),
        "stats.player.trading": ("trade_kills", "trade_deaths"),
        "stats.player.entry": ("first_kills", "first_deaths", "rounds_played"),
        "stats.player.opening": ("first_kills", "first_deaths"),
        "stats.player.clutches": ("clutches_won", "rounds_played"),
        "stats.player.utility": (
            "utility_damage_per_round",
            "utility_damage",
            "rounds_played",
            "enemies_flashed",
            "flash_count",
        ),
    }
    item_inputs = {
        "stats.metric.kills_per_round": ("total_kills", "rounds_played", "avg_kpr"),
        "stats.metric.damage_per_round": ("avg_adr",),
        "stats.metric.multi_kill_rounds": multi_inputs,
        "Impact": ("avg_impact",),
        "RATING 2.0": ("avg_rating",),
        "stats.metric.trade_kill_share": ("trade_kills", "total_kills"),
        "stats.metric.traded_deaths_per_round": ("trade_deaths", "rounds_played"),
        "stats.metric.traded_death_share": ("trade_deaths", "total_deaths"),
        "stats.metric.assists_per_round": ("total_assists", "rounds_played"),
        "stats.metric.opening_attempt_share": ("first_kills", "first_deaths", "rounds_played"),
        "stats.metric.trade_kills_per_round": ("trade_kills", "rounds_played"),
        "stats.metric.opening_success": ("first_kills", "first_deaths"),
        "stats.metric.opening_kills_per_round": ("first_kills", "rounds_played"),
        "stats.metric.opening_deaths_per_round": ("first_deaths", "rounds_played"),
        "stats.metric.opening_kd": ("first_kills", "first_deaths"),
        "stats.metric.clutches_won": ("clutches_won",),
        "stats.metric.clutch_points_per_round": ("clutches_won", "rounds_played"),
        "stats.metric.bomb_plants": ("bomb_plants",),
        "stats.metric.bomb_defuses": ("bomb_defuses",),
        "stats.metric.utility_damage_per_round": (
            "utility_damage",
            "rounds_played",
            "utility_damage_per_round",
        ),
        "stats.metric.utility_damage_total": ("utility_damage",),
        "stats.metric.enemies_flashed_per_round": ("enemies_flashed", "rounds_played"),
        "stats.metric.flash_success": ("enemies_flashed", "flash_count"),
    }
    for card in player_category_cards:
        if missing(*category_inputs[card["title"]]):
            card["score"] = None
        for item in card["items"]:
            if missing(*item_inputs[item["label"]]):
                item["value"] = "-"
                item["pct"] = 0
            if item["label"].startswith("stats.metric."):
                item["label"] = t(item["label"])
        card["kind"] = card["title"].rsplit(".", 1)[1]
        card["title"] = t(card["title"])
        card["desc"] = t(card["desc"])

    statistic_inputs = {
        "stats.metric.kills": ("total_kills",),
        "stats.metric.rounds": ("rounds_played",),
        "HS%": ("avg_hs",),
        "stats.metric.kills_per_round": ("total_kills", "rounds_played", "avg_kpr"),
        "stats.metric.deaths": ("total_deaths",),
        "stats.metric.assists_per_round": ("total_assists", "rounds_played"),
        "K/D": ("total_kills", "total_deaths"),
        "stats.metric.deaths_per_round": ("total_deaths", "rounds_played", "avg_dpr"),
        "stats.metric.damage_per_round": ("avg_adr",),
        "stats.metric.traded_by_teammates_per_round": ("trade_deaths", "rounds_played"),
        "stats.metric.utility_damage_per_round": (
            "utility_damage",
            "rounds_played",
            "utility_damage_per_round",
        ),
        "stats.metric.trades_for_teammates_per_round": ("trade_kills", "rounds_played"),
        "Impact": ("avg_impact",),
    }
    for item in player_statistics:
        if missing(*statistic_inputs.get(item["label"], ())):
            item["value"] = "-"
        if item["label"].startswith("stats.metric."):
            item["label"] = t(item["label"])
    return player_summary, player_category_cards, player_statistics
