"""
比赛详细数据页「选手表现总览」：每项数据和平均水平比，算出条的长度和颜色（照 HLTV 的表现图）。

- Rating 的平均就是 1.00；其余几项用全站所有地图数据的平均值（按回合数加权）。
- DPR 越低越好，所以倒过来比：平均 DPR ÷ 选手 DPR，条越长还是越好。
- 全场选手共用一把尺子：尺子长度 = 全场最高的比值（限制在 1.4 ~ 2.0 之间），平均线的位置随之确定。
"""

from services.performance_service import weighted_average_sql, weighted_rate_sql

# 全站还没有数据时用的平均值
DEFAULT_AVERAGES = {
    "kpr": 0.70,
    "dpr": 0.70,
    "kast": 70.0,
    "impact": 0.20,
    "rws": 10.0,
    "adr": 75.0,
}

# 条的顺序：(显示名, 选手数据里的键, 平均值的键（None = Rating，平均是 1）, 数字格式, 越大越好)
PERF_METRICS = (
    ("KPR", "kpr", "kpr", "{:.2f}", True),
    ("DPR", "dpr", "dpr", "{:.2f}", False),
    ("KAST", "kast", "kast", "{:.1f}%", True),
    ("影响力", "mk_rating", "impact", "{:.2f}", True),
    ("RWS", "rws", "rws", "{:.2f}", True),
    ("ADR", "adr", "adr", "{:.1f}", True),
    ("Rating", "rating", None, "{:.2f}", True),
)

SCALE_MIN = 1.4
SCALE_MAX = 2.0


def load_metric_averages(conn):
    """读全站平均值（按回合数加权，跳过已被替换的旧数据）；没有数据的项用默认值。"""
    row = conn.execute(
        f"""
        SELECT {weighted_rate_sql("kills", "rounds_played")} AS kpr,
               {weighted_rate_sql("deaths", "rounds_played")} AS dpr,
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
        if value and float(value) > 0:
            averages[key] = float(value)
    return averages


def _ratio(value, average, higher_better):
    """选手数值 ÷ 平均值；越小越好的项倒过来（平均 ÷ 选手），0 死亡直接算满。"""
    if average <= 0:
        return 0.0
    if higher_better:
        return value / average
    return average / value if value > 0 else SCALE_MAX


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
        value = float(row.get(key) or 0)
        average = averages[avg_key] if avg_key else 1.0
        ratio = _ratio(value, average, higher_better)
        items.append((label, number_format.format(value), ratio, avg_key is None))
    return items


def build_perf_overview(rows, averages):
    """给每名选手挂上 perf_bars（7 根条），返回平均线在尺子上的位置（0~1）。"""
    per_row = [(row, _metric_items(row, averages)) for row in rows]
    highest = max((item[2] for _, items in per_row for item in items), default=SCALE_MIN)
    scale = min(SCALE_MAX, max(SCALE_MIN, highest))
    for row, items in per_row:
        row["perf_bars"] = [
            {
                "label": label,
                "text": text,
                "pct": round(min(ratio, scale) / scale * 100, 1),
                "tier": "perf-rating" if is_rating else _tier(ratio),
                "fixed": label.isascii(),
            }
            for label, text, ratio, is_rating in items
        ]
    return round(1 / scale, 4)
