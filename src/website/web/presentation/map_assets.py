"""Resolve a map's reusable image and landscape URLs."""

import os
from functools import lru_cache

from config import BASE_DIR
from src.website.domains.matches.map_names import MAP_NAME_MAPPING, normalize_map_key


def map_image_url(name):
    """地图名 → /resources/maps/xxx.webp"""
    key = normalize_map_key(name)
    if not key or key in ("tba", "tbd"):
        return "/resources/maps/tba.webp"
    fn = MAP_NAME_MAPPING.get(key, key)
    fn_str = str(fn or "").lower()
    if not fn_str:
        return "/resources/maps/tba.webp"
    return f"/resources/maps/{fn_str}.webp"


_LANDSCAPE_SMALL_DIR = os.path.join(
    BASE_DIR,
    "resources",
    "map_landscapes",
    "small",
)


@lru_cache(maxsize=64)
def _has_small_landscape(file_stem):
    """有没有压缩过的小景观图（800 宽、几十 KB，网页背景用它就够了）。"""
    return os.path.isfile(os.path.join(_LANDSCAPE_SMALL_DIR, f"{file_stem}.webp"))


def map_background_url(name):
    """地图名 → 景观图地址：优先用小图 /resources/map_landscapes/small/xxx.webp，没有再用原图 png。"""
    key = normalize_map_key(name)
    if not key or key in ("tba", "tbd"):
        return "/resources/maps/tba.webp"
    fn = MAP_NAME_MAPPING.get(key, key)
    fn_str = str(fn or "").lower()
    if not fn_str:
        return "/resources/maps/tba.webp"
    if _has_small_landscape(fn_str):
        return f"/resources/map_landscapes/small/{fn_str}.webp"
    return f"/resources/map_landscapes/{fn_str}.png"
