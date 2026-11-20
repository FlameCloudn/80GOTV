"""Resolve historic event slugs and build canonical event URLs."""

import re

from src.website.domains.events.arg_event_service import ARG_EVENT_PATH, is_arg_event
from src.website.runtime.database import row_get
from src.website.runtime.urls import slugify_url_part

_EVENT_YEAR_RE = re.compile(r"^(?:19|20)(\d{2})$")


_EVENT_EDITION_RE = re.compile(r"^S(\d{1,2})$", re.IGNORECASE)


def event_abbr(name, short_name=""):
    """赛事占位缩写：有 4 个字以内的简称就用简称；否则取名字里第一个词的前两个字母
    + 年份后两位（没有年份就用届数），如 2026 Summer 80 Major → SU26、80CS Challenge S1 → CH1。"""
    short = str(short_name or "").strip()
    if short and len(short) <= 4:
        return short.upper()
    word, year, edition = "", "", ""
    for token in str(name or "").split():
        year_match = _EVENT_YEAR_RE.match(token)
        edition_match = _EVENT_EDITION_RE.match(token)
        if year_match:
            year = year or year_match.group(1)
        elif edition_match:
            edition = edition or edition_match.group(1)
        elif not word and token.isalpha():
            word = token
    if not word:
        word = re.sub(r"[\d\s_]+", "", str(name or "")) or "?"
    return word[:2].upper() + (year or edition)


def make_event_slug(value, fallback="event"):
    return slugify_url_part(value, fallback)[:80].rstrip("-") or fallback


def event_short_slug(short_name):
    part = re.sub(r"[\W_]+", "-", (short_name or "").strip().lower()).strip("-")[:80].rstrip("-")
    # 纯数字网址已经用于按旧赛事 ID 访问。
    return f"event-{part}" if part.isdecimal() else part


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
    if is_arg_event(event):
        return ARG_EVENT_PATH
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
