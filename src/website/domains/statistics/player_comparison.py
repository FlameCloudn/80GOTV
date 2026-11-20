"""Read and compare two players' performance summaries."""

from src.website.domains.statistics.performance_service import summary_metric_sql
from src.website.domains.statistics.stats_display import optional_number
from src.website.domains.statistics.stats_storage import stats_relation

COMPARE_FIELDS = (
    ("Rating", "rating", 2, "", True),
    ("KPR", "kpr", 2, "", True),
    ("DPR", "dpr", 2, "", False),
    ("KAST", "kast", 1, "%", True),
    ("Impact", "impact", 2, "", True),
    ("ADR", "adr", 1, "", True),
    ("K/D", "kd", 2, "", True),
    ("爆头率", "hs", 1, "%", True),
    ("每回合助攻", "apr", 2, "", True),
    ("每回合首杀", "opk", 2, "", True),
    ("每回合闪光助攻", "fapr", 2, "", True),
)


def _compare_values(summary):
    """把选手的生涯汇总换成对比用的数值；没有数据返回空字典。"""
    if not summary or not summary["maps"]:
        return {}
    rounds = optional_number(summary["rounds_played"])
    kills = optional_number(summary["total_kills"])
    deaths = optional_number(summary["total_deaths"])

    def per_round(total):
        value = optional_number(total)
        return value / rounds if value is not None and rounds is not None and rounds > 0 else None

    return {
        "rating": optional_number(summary["avg_rating"]),
        "kpr": optional_number(summary["avg_kpr"]) if per_round(kills) is not None else None,
        "dpr": optional_number(summary["avg_dpr"]) if per_round(deaths) is not None else None,
        "kast": optional_number(summary["avg_kast"]),
        "impact": optional_number(summary["avg_impact"]),
        "adr": optional_number(summary["avg_adr"]),
        "kd": kills / deaths if kills is not None and deaths is not None and deaths > 0 else None,
        "hs": optional_number(summary["avg_hs"]),
        "apr": per_round(summary["total_assists"]),
        "opk": per_round(summary["first_kills"]),
        "fapr": per_round(summary["flash_assists"]),
    }


def _compare_player(conn, player_id):
    """读一名选手的资料和生涯汇总；没选或选手不存在返回 None。"""
    if not player_id:
        return None
    player = conn.execute(
        """SELECT p.*, t.name AS team_name, t.logo AS team_logo
           FROM players p LEFT JOIN teams t ON p.team_id=t.id
           WHERE p.id=?""",
        (player_id,),
    ).fetchone()
    if not player:
        return None
    summary_metrics = {
        "rounds_played": "rounds_played",
        "avg_rating": "rating",
        "avg_kpr": "kills",
        "avg_dpr": "deaths",
        "avg_kast": "kast",
        "avg_impact": "impact",
        "avg_adr": "adr",
        "avg_hs": "headshot_percentage",
        "total_kills": "kills",
        "total_deaths": "deaths",
        "total_assists": "assists",
        "first_kills": "first_kills",
        "flash_assists": "flash_assists",
    }
    source = stats_relation(conn)
    select_metrics = ", ".join(
        f"{summary_metric_sql(column, raw_column, stats_source=source)} AS {column}"
        for column, raw_column in summary_metrics.items()
    )
    summary = conn.execute(
        f"""SELECT s.maps, {select_metrics}
           FROM player_performance_summary s
           WHERE s.player_id=?""",
        (player_id,),
    ).fetchone()
    maps = (summary["maps"] if summary else 0) or 0
    return {"player": player, "maps": maps, "values": _compare_values(summary)}


def _compare_rows(mine, theirs):
    """一侧的每一行：显示的数字 + 和对面比的结果（better 占优 / worse 落后 / 空 = 一样或没得比）。"""
    rows = []
    for label, key, digits, suffix, higher_better in COMPARE_FIELDS:
        row = {"label": label, "fixed": label.isascii(), "value": "-", "state": ""}
        value = optional_number(mine.get(key))
        other = optional_number(theirs.get(key))
        if value is not None:
            value = round(value, digits)
            row["value"] = f"{value:.{digits}f}{suffix}"
            other = round(other, digits) if other is not None else None
            if other is not None and value != other:
                row["state"] = "better" if (value > other) == higher_better else "worse"
        rows.append(row)
    return rows


def _compare_card(slot, field, mine, theirs):
    """左右两张卡之一：选手、地图数、每项数据，以及两边都有数据时领先了几项。"""
    card = {"slot": slot, "field": field, "player": None, "maps": 0, "rows": [], "lead": None}
    if not mine:
        return card
    other_values = theirs["values"] if theirs else {}
    rows = _compare_rows(mine["values"], other_values)
    card.update(player=mine["player"], maps=mine["maps"], rows=rows)
    if any(
        optional_number(value) is not None and optional_number(other_values.get(key)) is not None
        for key, value in mine["values"].items()
    ):
        card["lead"] = sum(1 for row in rows if row["state"] == "better")
    return card
