"""Normalize external URLs, on-site links and slug fragments."""

import re
from urllib.parse import unquote, urlsplit


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
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) > 2048 or re.search(r"[\x00-\x1f\x7f\\]", value):
        return None
    try:
        value.encode("utf-8")
        parsed = urlsplit(value)
        port = parsed.port
    except (ValueError, UnicodeError):
        return None
    if parsed.username or parsed.password or port not in (None, 80, 443):
        return None
    path = parsed.path or "/"
    decoded_path = unquote(path)
    if not path.startswith("/") or decoded_path.startswith("//") or "\\" in decoded_path:
        return None
    if parsed.scheme or parsed.netloc:
        if parsed.scheme.lower() not in ("http", "https"):
            return None
        if (parsed.hostname or "").lower() not in ("80gotv.cn", "www.80gotv.cn"):
            return None
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
