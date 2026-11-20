"""选手统计和全站数据页共同接受的筛选项。"""

TIME_FILTERS = [
    {"value": "all", "label": "全部", "months": None},
    {"value": "3m", "label": "最近 3 个月", "months": 3},
    {"value": "6m", "label": "最近 6 个月", "months": 6},
    {"value": "12m", "label": "最近 12 个月", "months": 12},
]
TIME_FILTER_MAP = {item["value"]: item for item in TIME_FILTERS}
SIDE_OPTIONS = [
    {"value": "both", "label": "双方"},
    {"value": "ct", "label": "CT 方"},
    {"value": "t", "label": "T 方"},
]
_SIDES = {item["value"] for item in SIDE_OPTIONS}


def stat_filters(args):
    time = args.get("time") or args.get("period") or "all"
    side = (args.get("side") or "both").strip().lower()
    return {
        "time": time if time in TIME_FILTER_MAP else "all",
        "map": (args.get("map") or "all").strip() or "all",
        "side": side if side in _SIDES else "both",
    }
