"""Canonical map keys and public display names."""

MAP_NAME_MAPPING = {
    "dust2": "Dust2",
    "mirage": "Mirage",
    "inferno": "Inferno",
    "nuke": "Nuke",
    "overpass": "Overpass",
    "ancient": "Ancient",
    "anubis": "Anubis",
    "cache": "Cache",
    "train": "Train",
    "vertigo": "Vertigo",
}


MAP_NAME_CN = {
    "dust2": "炙热沙城Ⅱ",
    "mirage": "荒漠迷城",
    "inferno": "炼狱小镇",
    "nuke": "核子危机",
    "overpass": "死亡游乐园",
    "ancient": "远古遗迹",
    "anubis": "阿努比斯",
    "cache": "死城之谜",
    "train": "列车停放站",
    "vertigo": "殒命大厦",
}


def normalize_map_key(name):
    """地图名 → 归一化 key（小写，去除 de_ 前缀）"""
    if not name:
        return ""
    return name.lower().replace("de_", "").replace(" ", "").strip()


def map_display_name(name):
    """地图名 → 显示名称（首字母大写）"""
    if not name:
        return ""
    key = normalize_map_key(name)
    if key in ("tba", "tbd"):
        return "TBA"
    if key in MAP_NAME_MAPPING:
        return MAP_NAME_MAPPING[key]
    # 去除 de_/cs_ 前缀后首字母大写
    clean = name.lower()
    for prefix in ("de_", "cs_"):
        if clean.startswith(prefix):
            clean = clean[len(prefix) :]
            break
    return clean.replace("_", " ").title()


def map_display_name_cn(name):
    """地图名 → 中文显示名称"""
    if not name:
        return ""
    key = normalize_map_key(name)
    if key in ("tba", "tbd"):
        return "待定"
    if key in MAP_NAME_CN:
        return MAP_NAME_CN[key]
    return map_display_name(name)
