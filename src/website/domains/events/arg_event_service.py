"""Local-only preview event and its encoded display names."""

import base64
import secrets
import string

ARG_EVENT_PATH = "/gtE5geUvi+j="
ARG_EVENT_SLUG = "gte5geuvi-j"
ARG_EVENT_DATE = "202?/0?/??"
ARG_EVENT_STATUS = "???"
ARG_EVENT_FORMAT = "双败淘汰·?·?"


def _shift_letters(value, delta):
    lower = string.ascii_lowercase
    upper = string.ascii_uppercase
    shifted = lower[delta:] + lower[:delta] + upper[delta:] + upper[:delta]
    return value.translate(str.maketrans(lower + upper, shifted))


def _encoded_name(delta):
    value = _shift_letters("2027Winter???", delta)
    return base64.b64encode(value.encode("ascii")).decode("ascii")


ARG_EVENT_FRAMES = tuple(_encoded_name(delta) for delta in range(1, 15))
# 503 页故障时偶尔替换下面那行：先转 Base64，再把字母凯撒位移 7 位
ARG_UNAVAILABLE_ALT = _shift_letters(base64.b64encode(b"NextStage").decode("ascii"), 7)


def ordinary_event_condition(alias=""):
    """Exclude the preview event from ordinary public lists before pagination."""
    prefix = alias + "." if alias else ""
    return (
        f"(COALESCE({prefix}slug, '') <> '{ARG_EVENT_SLUG}' "
        f"AND COALESCE({prefix}name, '') <> '{ARG_EVENT_FRAMES[0]}')"
    )


def event_display_values(previous="", count=32):
    values = []
    for _ in range(count):
        previous = secrets.choice([value for value in ARG_EVENT_FRAMES if value != previous])
        values.append(previous)
    return values


def is_arg_event(event):
    if not hasattr(event, "keys"):
        return False
    keys = event.keys()
    return (
        ("slug" in keys and event["slug"] == ARG_EVENT_SLUG)
        or ("event_slug" in keys and event["event_slug"] == ARG_EVENT_SLUG)
        or ("name" in keys and event["name"] == ARG_EVENT_FRAMES[0])
    )


def ensure_arg_event(conn):
    """Create only the requested event; never update an existing event's details."""
    existing = conn.execute("SELECT id,name FROM events WHERE slug=?", (ARG_EVENT_SLUG,)).fetchone()
    if existing:
        if existing["name"] != ARG_EVENT_FRAMES[0]:
            raise ValueError("赛事地址已被其他赛事使用，未覆盖任何资料。")
        return existing["id"]
    return conn.execute(
        "INSERT INTO events(name,slug,status,format) VALUES(?,?,?,?)",
        (ARG_EVENT_FRAMES[0], ARG_EVENT_SLUG, ARG_EVENT_STATUS, ARG_EVENT_FORMAT),
    ).lastrowid
