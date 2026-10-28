"""模板过滤器：日期格式化、地图名称映射、Rating 分色、B站链接等。"""

import json
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

from utils.helpers import (
    map_background_url,
    map_display_name,
    map_display_name_cn,
    map_image_url,
    row_get,
    team_abbr,
)
from utils.stats_display import optional_number


def _parse_display_datetime(value):
    """解析日期时间字符串，转换为东八区 datetime 对象。"""
    if not value:
        return None
    try:
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return None
            dt_val = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        else:
            dt_val = value
        if dt_val.tzinfo is not None:
            dt_val = dt_val.astimezone(timezone(timedelta(hours=8)))
        return dt_val
    except (ValueError, TypeError, AttributeError):
        return None


def json_loads_filter(value):
    """安全 JSON 反序列化。"""
    try:
        return json.loads(value) if value else None
    except (json.JSONDecodeError, TypeError):
        return None


def cn_time_filter(value):
    """将 ISO 时间字符串转为中文日期时间。"""
    return datetime_display_filter(value)


def date_display_filter(value):
    """页面展示用日期：2026年6月3日。"""
    dt_val = _parse_display_datetime(value)
    if not dt_val:
        return str(value or "")[:10]
    return f"{dt_val.year}年{dt_val.month}月{dt_val.day}日"


def date_range_display_filter(start, end=None):
    """赛事起止日期：同一天只写一天（2026年5月2日），否则写“2026年5月2日 ~ 2026年5月4日”；只有一头就写那一头。"""
    start_day = date_display_filter(start) if start else ""
    end_day = date_display_filter(end) if end else ""
    if not start_day or not end_day or start_day == end_day:
        return start_day or end_day
    return f"{start_day} ~ {end_day}"


def compact_date_display_filter(value):
    """紧凑日期：2026/06/03。"""
    dt_val = _parse_display_datetime(value)
    if not dt_val:
        raw = str(value or "").strip()
        date_match = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})", raw)
        if date_match:
            year, month, day = (int(part) for part in date_match.groups())
            return f"{year:04d}/{month:02d}/{day:02d}"
        return raw[:10].replace("-", "/")
    return f"{dt_val.year:04d}/{dt_val.month:02d}/{dt_val.day:02d}"


def relative_date_display_filter(value, today=None):
    """相对日期：今天、3天前、5天后。"""
    dt_val = _parse_display_datetime(value)
    if not dt_val:
        return ""
    if today is None:
        reference_date = date.today()
    elif isinstance(today, datetime):
        reference_date = today.date()
    elif isinstance(today, date):
        reference_date = today
    else:
        reference_date = _parse_display_datetime(today)
        reference_date = reference_date.date() if reference_date else date.today()

    days = (dt_val.date() - reference_date).days
    if days == 0:
        return "今天"
    if days > 0:
        return f"{days}天后"
    return f"{-days}天前"


def datetime_display_filter(value):
    """页面展示用日期时间：2026年6月3日 20:57。"""
    dt_val = _parse_display_datetime(value)
    if not dt_val:
        return str(value or "")[:16].replace("T", " ")
    return f"{dt_val.year}年{dt_val.month}月{dt_val.day}日 {dt_val.hour:02d}:{dt_val.minute:02d}"


def time_display_filter(value):
    """页面展示用时间：20:57。"""
    dt_val = _parse_display_datetime(value)
    if not dt_val:
        text = str(value or "")
        return text[11:16] if len(text) >= 16 else ""
    return f"{dt_val.hour:02d}:{dt_val.minute:02d}"


def map_image_filter(name):
    """地图名 → 缩略图 URL。"""
    return map_image_url(name)


def map_background_filter(name):
    """地图名 → 景观图 URL。"""
    return map_background_url(name)


def map_display_filter(name):
    """地图名 → 英文显示名称。"""
    return map_display_name(name)


def map_display_cn_filter(name):
    """地图名 → 中文显示名称。"""
    return map_display_name_cn(name)


def map_pool_label_filter(name):
    """图池里的地图统一显示成“英文 (中文)”。

    比赛设置里可能存 “de_mirage”，默认图池存的是 “Mirage (荒漠迷城)”，这里先取括号前的英文名再换算。
    """
    raw = str(name or "").strip()
    base = re.split(r"[（(]", raw, maxsplit=1)[0].strip()
    english = map_display_name(base)
    if not english:
        return raw
    chinese = map_display_name_cn(base)
    return f"{english} ({chinese})" if chinese and chinese != english else english


def rating_class_filter(value):
    """RATING 统一分色：>=1.05 绿，0.95~1.05 常规，<0.95 红。"""
    rating = optional_number(value)
    if rating is None:
        return ""
    if rating >= 1.05:
        return "rt-4"
    if rating >= 0.95:
        return "rt-3"
    return "rt-1"


def rating_desc_filter(players):
    """Sort a display copy without changing the saved player slots."""

    def sort_key(player):
        rating = optional_number(row_get(player, "rating"))
        return rating if rating is not None else float("-inf")

    return sorted(players or [], key=sort_key, reverse=True)


def registration_team_abbr_filter(value):
    """报名队伍名 -> 缩写（和全站队伍占位缩写同一套规则，见 utils.helpers.team_abbr）。"""
    return team_abbr(value)


def _parse_bilibili_url(url):
    """解析 B 站链接为嵌入播放器 URL。"""
    if not url:
        return None
    url = url.strip()
    live_match = re.fullmatch(r"https?://live\.bilibili\.com/(\d+)(?:[/?#].*)?", url, re.IGNORECASE)
    if live_match:
        return (
            f"https://live.bilibili.com/blackboard/live/live-activity-player.html"
            f"?cid={live_match.group(1)}&quality=0"
        )
    parsed = urlsplit(url)
    is_bilibili_url = parsed.scheme in ("http", "https") and (
        parsed.netloc.lower() == "bilibili.com" or parsed.netloc.lower().endswith(".bilibili.com")
    )
    bv_match = re.fullmatch(r"(BV[a-zA-Z0-9]+)", url)
    if not bv_match and is_bilibili_url:
        bv_match = re.search(r"(BV[a-zA-Z0-9]+)", parsed.path, re.IGNORECASE)
    if bv_match:
        return (
            f"https://player.bilibili.com/player.html"
            f"?bvid={bv_match.group(1)}&page=1&high_quality=1"
        )
    return None


def bilibili_embed_filter(url):
    """B站链接 → 嵌入播放器 URL。"""
    return _parse_bilibili_url(url)
