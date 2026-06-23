"""
共享工具函数：XSS 清洗、HTML 安全过滤、评论树构建、地图名称映射、管理员判断等
"""

import html as html_mod
import re
from urllib.parse import urlsplit

from flask import session

# ============ XSS 过滤器 ============

ALLOWED_TAGS = {
    "p",
    "b",
    "i",
    "u",
    "strong",
    "em",
    "a",
    "br",
    "ul",
    "ol",
    "li",
    "h1",
    "h2",
    "h3",
    "h4",
    "blockquote",
    "img",
    "span",
    "div",
    "pre",
    "code",
    "hr",
    "sub",
    "sup",
}
ALLOWED_ATTRS = {"href", "title", "src", "alt", "width", "height", "class", "style"}

_STYLE_SAFE = re.compile(
    r"(?:color|background(?:-color)?|font(?:-size|-weight|-family|-style)?|"
    r"text(?:-align|-decoration|-transform)?|margin(?:-top|-bottom|-left|-right)?|"
    r"padding(?:-top|-bottom|-left|-right)?|border(?:-radius|-color)?|"
    r"width|height|display|float|line-height|letter-spacing|white-space|"
    r"opacity|overflow|vertical-align)\s*:"
)
_URL_FUNC_RE = re.compile(r"url\s*\(", re.IGNORECASE)

_script_re = re.compile(r"<script[\s\S]*?</script>", re.IGNORECASE)
_style_re = re.compile(r"<style[\s\S]*?</style>", re.IGNORECASE)
_onattr_re = re.compile(r'\s+on\w+\s*=\s*["\'][^"\']*["\']', re.IGNORECASE)
_jshref_re = re.compile(r'\s+href\s*=\s*["\']\s*javascript:', re.IGNORECASE)
_tag_re = re.compile(r"</?([a-zA-Z][a-zA-Z0-9]*)\b[^>]*>")


def sanitize_style(value):
    """只保留安全的 CSS 属性（拦截 url() 表达式）"""
    if _URL_FUNC_RE.search(value):
        return ""
    parts = value.split(";")
    safe = []
    for p in parts:
        if _STYLE_SAFE.match(p.strip()):
            safe.append(p.strip())
    return "; ".join(safe)


def sanitize_html_url(value, allow_mailto=False):
    """清洗富文本里的链接和图片地址。"""
    value = html_mod.unescape(value).strip()
    if value.startswith("#") or (value.startswith("/") and not value.startswith("//")):
        return value
    parsed = urlsplit(value)
    if parsed.scheme.lower() in ("http", "https") and parsed.netloc:
        return value
    if allow_mailto and parsed.scheme.lower() == "mailto":
        return value
    return ""


def sanitize_html(content):
    """清洗 HTML，移除危险标签和属性，保留安全格式"""
    if not content:
        return ""
    content = _script_re.sub("", content)
    content = _style_re.sub("", content)
    content = _onattr_re.sub("", content)
    content = _jshref_re.sub(' href="#"', content)

    def _filter_tag(m):
        tag = m.group(1).lower()
        if tag not in ALLOWED_TAGS:
            return html_mod.escape(m.group(0))
        if m.group(0).startswith("</"):
            return f"</{tag}>"
        attrs = m.group(0)[len(tag) + 1 : -1].strip()
        if not attrs:
            return f"<{tag}>"
        filtered = []
        for a in re.findall(r'(\w+)\s*=\s*"([^"]*)"', attrs):
            aname = a[0].lower()
            if aname not in ALLOWED_ATTRS:
                continue
            raw_value = a[1]
            if aname in ("href", "src"):
                raw_value = sanitize_html_url(raw_value, allow_mailto=aname == "href")
                if not raw_value:
                    continue
            aval = html_mod.escape(raw_value, quote=True)
            if aname == "style":
                aval = sanitize_style(aval)
                if not aval:
                    continue
            filtered.append(f'{a[0]}="{aval}"')
        return f"<{tag} {' '.join(filtered)}>" if filtered else f"<{tag}>"

    return _tag_re.sub(_filter_tag, content)


# ============ 地图名称映射 ============

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


def map_image_url(name):
    """地图名 → /resources/maps/xxx.webp"""
    key = normalize_map_key(name)
    if not key or key in ("tba", "tbd"):
        return "/resources/maps/tba.webp"
    fn = MAP_NAME_MAPPING.get(key, key)
    return f"/resources/maps/{fn.lower()}.webp"


def map_background_url(name):
    """地图名 → /resources/map_landscapes/xxx.png（景观图）"""
    key = normalize_map_key(name)
    if not key or key in ("tba", "tbd"):
        return "/resources/maps/tba.webp"
    fn = MAP_NAME_MAPPING.get(key, key)
    return f"/resources/map_landscapes/{fn.lower()}.png"


def normalize_http_url(value):
    """只保留可点击的 http/https 地址。"""
    value = (value or "").strip()
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        return None
    return value


def make_match_slug(team1_name, team2_name, match_time, event_short_name):
    """
    根据队伍名、时间、赛事简称生成 URL 友好的 slug。
    例如: team-a-vs-team-b-2026-spring-major
    中文等非 ASCII 字符会被跳过。
    """
    import re as _re

    parts = []
    for name in (team1_name or "", team2_name or ""):
        # 只保留 ASCII 字母数字和空格
        ascii_only = _re.sub(r"[^a-zA-Z0-9 ]", "", name).strip()
        if ascii_only:
            parts.append(ascii_only.lower().replace(" ", "-"))
    if match_time:
        try:
            parts.append(str(match_time)[:4])  # 年份
        except Exception:
            pass
    if event_short_name:
        short = _re.sub(r"[^a-zA-Z0-9 ]", "", event_short_name).strip()
        if short:
            parts.append(short.lower().replace(" ", "-"))
    slug = "-vs-".join(parts[:2]) if len(parts) >= 2 else "match"
    if len(parts) > 2:
        slug = slug + "-" + "-".join(parts[2:])
    # 去掉多余连字符
    slug = _re.sub(r"-+", "-", slug).strip("-")
    return slug or "match"


def ensure_unique_match_slug(conn, match_id, slug_base):
    """保证 slug 唯一，重名时加 -2、-3 等后缀"""
    slug = slug_base
    counter = 2
    while True:
        existing = conn.execute(
            "SELECT id FROM matches WHERE slug=? AND id!=?", (slug, match_id)
        ).fetchone()
        if not existing:
            return slug
        slug = f"{slug_base}-{counter}"
        counter += 1


# ============ 数据访问辅助 ============


def row_get(row, key, default=None):
    """兼容 sqlite3.Row 和 dict 的安全取值"""
    try:
        return row.get(key, default)
    except AttributeError:
        return row[key] if key in row.keys() else default


# ============ 评论树构建 ============


def build_comment_tree(comments):
    """将扁平评论列表转为嵌套结构，含层级标记"""
    tree = []
    lookup = {}
    for c in comments:
        c = dict(c)
        c["replies"] = []
        lookup[c["id"]] = c

    for c in lookup.values():
        pid = c.get("parent_id")
        if pid and pid in lookup:
            lookup[pid]["replies"].append(c)
        else:
            tree.append(c)

    def _mark_depth(node, depth=0):
        node["depth"] = depth
        for r in node.get("replies", []):
            _mark_depth(r, depth + 1)

    for n in tree:
        _mark_depth(n, 0)
    return tree


# ============ Slug 解析 ============


def resolve_match_slug(slug):
    """将比赛 slug 或数字 ID 统一转为数字 match_id。
    调用方负责管理数据库连接与关闭。"""
    from models import get_db

    conn = get_db()
    try:
        if str(slug).isdigit():
            row = conn.execute("SELECT id FROM matches WHERE id=?", (int(slug),)).fetchone()
        else:
            row = conn.execute("SELECT id FROM matches WHERE slug=?", (slug,)).fetchone()
        return row["id"] if row else None
    finally:
        conn.close()


# ============ 管理员检查 ============


def is_admin():
    """检查当前 session 是否为管理员"""
    return "admin_id" in session
