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


def normalize_internal_path(value):
    """保存新闻跳转地址，只允许本站路径或 80gotv.cn 完整地址。"""
    value = (value or "").strip()
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        if parsed.scheme.lower() not in ("http", "https"):
            return None
        if (parsed.hostname or "").lower() not in ("80gotv.cn", "www.80gotv.cn"):
            return None
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        if parsed.fragment:
            path += "#" + parsed.fragment
        return path
    if not value.startswith("/") or value.startswith("//"):
        return None
    return value


def slugify_url_part(value, fallback=""):
    """把可读名称转换成稳定的 ASCII 网址片段。"""
    import re as _re

    value = _re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower())
    value = _re.sub(r"-+", "-", value).strip("-")
    return value or fallback


def make_event_slug(value, fallback="event"):
    return slugify_url_part(value, fallback)[:80].rstrip("-") or fallback


def ensure_unique_event_slug(conn, event_id, slug_base):
    slug_base = make_event_slug(slug_base)
    slug = slug_base
    counter = 2
    while True:
        existing = conn.execute(
            "SELECT id FROM events WHERE slug=? AND id<>?", (slug, event_id or -1)
        ).fetchone()
        if not existing:
            return slug
        suffix = f"-{counter}"
        slug = slug_base[: 80 - len(suffix)].rstrip("-") + suffix
        counter += 1


def make_match_slug(team1_name, team2_name, match_time, event_short_name):
    """
    生成“赛事-队伍1-vs-队伍2-年-月-日”格式的网址名称。
    """
    event_part = slugify_url_part(event_short_name, "event")
    team1_part = slugify_url_part(team1_name, "team1")
    team2_part = slugify_url_part(team2_name, "team2")
    date_part = "date-tbd"
    if match_time:
        try:
            year, month, day = str(match_time)[:10].split("-")
            date_part = f"{int(year)}-{int(month)}-{int(day)}"
        except (TypeError, ValueError):
            pass
    return f"{event_part}-{team1_part}-vs-{team2_part}-{date_part}"[:180].rstrip("-")


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
    """将按发布时间排列的评论转为嵌套结构，并标记楼层和层级。"""
    tree = []
    lookup = {}
    for floor_number, c in enumerate(comments, start=1):
        c = dict(c)
        c["replies"] = []
        c["floor_number"] = floor_number
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
            if not row:
                row = conn.execute(
                    "SELECT match_id AS id FROM match_slug_aliases WHERE slug=?", (slug,)
                ).fetchone()
        return row["id"] if row else None
    finally:
        conn.close()


def resolve_event_ref(conn, event_ref):
    """用数字 ID 或赛事网址名称查找赛事。"""
    value = str(event_ref or "").strip().lower()
    if value.isdigit():
        return conn.execute("SELECT * FROM events WHERE id=?", (int(value),)).fetchone()
    event = conn.execute("SELECT * FROM events WHERE slug=?", (value,)).fetchone()
    if event:
        return event
    return conn.execute(
        """SELECT e.* FROM event_slug_aliases a
           JOIN events e ON e.id=a.event_id WHERE a.slug=?""",
        (value,),
    ).fetchone()


def event_path(event):
    """模板和接口共用的赛事详情地址。"""
    if hasattr(event, "keys") or isinstance(event, dict):
        event_slug = row_get(event, "event_slug")
        if event_slug or row_get(event, "event_id") is not None:
            slug = event_slug
            event_id = row_get(event, "event_id")
        else:
            slug = row_get(event, "slug")
            event_id = row_get(event, "id")
    else:
        slug = None
        event_id = event
    return f"/events/{slug or event_id}"


def news_path(news):
    """新闻配置跳转页时优先使用该地址。"""
    if hasattr(news, "keys") or isinstance(news, dict):
        return row_get(news, "redirect_url") or f"/news/{row_get(news, 'id')}"
    return f"/news/{news}"


# ============ 管理员检查 ============


def is_admin():
    """检查当前 session 是否为管理员"""
    return "admin_id" in session
