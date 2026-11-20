"""Parse event settings and determine permitted values."""

from flask import request

from src.website.domains.events.event_references import event_short_slug
from src.website.runtime.host import HostError


def _event_form_values(event=None):
    short_name = request.form.get("short_name", "").strip()
    name = request.form.get("name", "").strip()
    slug = event_short_slug(short_name)
    if event is not None and short_name == event["short_name"] and event["slug"]:
        slug = event["slug"]  # 修改描述等无关字段时，不重写已经发布的历史网址。
    status = request.form.get("status", "upcoming") if event is not None else "upcoming"
    registration_open = (
        1 if request.form.get("registration_open") == "1" and status != "completed" else 0
    )
    return (
        name,
        short_name,
        slug,
        request.form.get("description", "").strip(),
        request.form.get("start_date", "").strip(),
        request.form.get("end_date", "").strip(),
        request.form.get("format", "").strip(),
        status,
        request.form.get("stream_url", "").strip() or None,
        registration_open,
    )


def _form_number(raw, *, minimum=1):
    value = str(raw)
    if (
        not value.isascii()
        or not value.isdecimal()
        or len(value) > 19
        or not minimum <= int(value) <= 2**63 - 1
    ):
        raise HostError("编号、版本或时间格式不正确", 400)
    return int(value)


def _event_validation_error(conn, values, exclude_id=None):
    name, short_name, slug, _, start_date, end_date, _, status, _, _ = values
    if not name or not short_name:
        return "赛事名和简称不能为空"
    if not slug:
        return "赛事简称至少需要一个汉字、字母或数字"
    if not start_date or not end_date:
        return "开始时间和结束时间不能为空"
    if end_date < start_date:
        return "结束时间不能早于开始时间"
    if status not in ("upcoming", "ongoing", "completed"):
        return "赛事状态无效"
    for column, value, message in (
        ("name", name, "已存在同名赛事"),
        ("short_name", short_name, "已存在相同简称的赛事"),
        ("slug", slug, "该网址名称已被其他赛事使用"),
    ):
        sql = f"SELECT id FROM events WHERE LOWER(TRIM({column}))=LOWER(TRIM(?))"
        params = [value]
        if exclude_id is not None:
            sql += " AND id<>?"
            params.append(exclude_id)
        if conn.execute(sql, params).fetchone():
            return message
    alias = conn.execute("SELECT event_id FROM event_slug_aliases WHERE slug=?", (slug,)).fetchone()
    if alias and (exclude_id is None or alias["event_id"] != exclude_id):
        return "该网址名称是其他赛事使用过的旧地址"
    return None


def _event_dict(values, event_id=None):
    keys = (
        "name",
        "short_name",
        "slug",
        "description",
        "start_date",
        "end_date",
        "format",
        "status",
        "stream_url",
        "registration_open",
    )
    result: dict[str, object] = dict(zip(keys, values))
    if event_id is not None:
        result["id"] = event_id
    return result
