"""
比赛详细数据页「选手表现总览」：每项数据和平均水平比，算出条的长度和颜色（照 HLTV 的表现图）。

- Rating 的平均就是 1.00；其余几项用全站所有地图数据的平均值（按回合数加权）。
- DPR 越低越好，所以倒过来比：平均 DPR ÷ 选手 DPR，条越长还是越好。
- 全场选手共用一把尺子：根据本场最高比值伸展，平均线的位置随之确定。
"""

import math

from services.performance_service import weighted_average_sql, weighted_rate_sql
from utils.stats_display import optional_number

# 未记录的平均值不能当作实测数据。
DEFAULT_AVERAGES = dict.fromkeys(("kpr", "dpr", "kast", "impact", "rws", "adr"))

# 条的顺序：(显示名, 选手数据里的键, 平均值的键（None = Rating，平均是 1）, 数字格式, 越大越好)
PERF_METRICS = (
    ("KPR", "kpr", "kpr", "{:.2f}", True),
    ("DPR", "dpr", "dpr", "{:.2f}", False),
    ("KAST", "kast", "kast", "{:.1f}%", True),
    ("Impact", "mk_rating", "impact", "{:.2f}", True),
    ("RWS", "rws", "rws", "{:.2f}", True),
    ("ADR", "adr", "adr", "{:.1f}", True),
    ("Rating", "rating", None, "{:.2f}", True),
)

SCALE_MIN = 1.4


def load_metric_averages(conn):
    """按已记录回合加权，跳过历史版本；未知保留 None，实测 0 保留 0。"""
    row = conn.execute(
        f"""
        SELECT CASE WHEN COUNT(CASE WHEN rounds_played > 0 THEN kills END) > 0
                    THEN {weighted_rate_sql("kills", "rounds_played")} END AS kpr,
               CASE WHEN COUNT(CASE WHEN rounds_played > 0 THEN deaths END) > 0
                    THEN {weighted_rate_sql("deaths", "rounds_played")} END AS dpr,
               {weighted_average_sql("kast", "rounds_played")} AS kast,
               {weighted_average_sql("impact", "rounds_played")} AS impact,
               {weighted_average_sql("rws_basic", "rounds_played")} AS rws,
               {weighted_average_sql("adr", "rounds_played")} AS adr
        FROM match_stats
        WHERE COALESCE(data_status, 'final') <> 'superseded'
        """
    ).fetchone()
    averages = dict(DEFAULT_AVERAGES)
    for key in averages:
        value = row[key] if row else None
        averages[key] = optional_number(value)
    return averages


def _ratio(value, average, higher_better):
    """选手数值 ÷ 平均值；越小越好的项倒过来（平均 ÷ 选手），0 死亡直接算满。"""
    if value is None or average is None or average <= 0:
        return None
    if higher_better:
        return value / average
    return average / value if value > 0 else math.inf


def _tier(ratio):
    """条的颜色档位（照 HLTV）：低于平均 / 平均 / 较好 / 很好 / 顶尖。"""
    if ratio < 1.0:
        return "perf-low"
    if ratio < 1.1:
        return "perf-avg"
    if ratio < 1.2:
        return "perf-good"
    if ratio < 1.3:
        return "perf-great"
    return "perf-top"


def _metric_items(row, averages):
    """一名选手的 7 项：(显示名, 显示的数字, 和平均的比值, 是否 Rating)。"""
    items = []
    for label, key, avg_key, number_format, higher_better in PERF_METRICS:
        value = optional_number(row.get(key))
        average = optional_number(averages.get(avg_key)) if avg_key else 1.0
        ratio = _ratio(value, average, higher_better)
        items.append(
            (
                label,
                number_format.format(value) if value is not None else "-",
                ratio,
                avg_key is None,
            )
        )
    return items


def build_perf_overview(rows, averages):
    """给每名选手挂上 perf_bars（7 根条），返回平均线在尺子上的位置（0~1）。"""
    per_row = [(row, _metric_items(row, averages)) for row in rows]
    highest = max(
        (
            item[2]
            for _, items in per_row
            for item in items
            if item[2] is not None and math.isfinite(item[2])
        ),
        default=SCALE_MIN,
    )
    scale = max(SCALE_MIN, highest)
    if any(item[2] == math.inf for _, items in per_row for item in items):
        scale *= 1.05
    for row, items in per_row:
        row["perf_bars"] = [
            {
                "label": label,
                "text": text,
                "pct": round(max(0, min(ratio, scale)) / scale * 100, 1)
                if ratio is not None
                else 0,
                "tier": "perf-rating" if is_rating else _tier(ratio) if ratio is not None else "",
                "fixed": label.isascii(),
            }
            for label, text, ratio, is_rating in items
        ]
    return round(1 / scale, 4)
