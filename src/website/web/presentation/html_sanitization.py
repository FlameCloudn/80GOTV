"""Sanitize stored HTML before rendering it."""

import html as html_mod
import re
from urllib.parse import urlsplit

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
