"""Parse the administrator's submitted match settings and retain invalid input."""

import json
import re

from src.website.domains.matches import setup
from src.website.runtime.urls import normalize_http_url
from src.website.web.access import hash_bp_password


def _int_form(form, name, default=0):
    try:
        return int(form.get(name, default) or default)
    except (TypeError, ValueError):
        return default


def parse_match_form(form, include_results=False):
    f = {}
    for i in range(1, 6):
        f[f"map{i}"] = form.get(f"map{i}", "")
        f[f"map{i}_t1"] = _int_form(form, f"map{i}_t1") if include_results else 0
        f[f"map{i}_t2"] = _int_form(form, f"map{i}_t2") if include_results else 0
        f[f"map{i}_pb"] = form.get(f"map{i}_picked_by", "") or None if include_results else None
    f["event_id"] = form.get("event_id")
    f["match_time"] = form.get("match_time")
    f["bo_format"] = form.get("bo_format", "BO3")
    f["stage"] = form.get("stage", "").strip() or None
    f["is_test_mode"] = 1 if form.get("is_test_mode") == "1" else 0
    f["team1_score"] = _int_form(form, "team1_score") if include_results else 0
    f["team2_score"] = _int_form(form, "team2_score") if include_results else 0
    f["has_map3"] = 0 if include_results and form.get("no_map3") == "1" else 1
    f["has_map4"] = 0 if include_results and form.get("no_map4") == "1" else 1
    f["has_map5"] = 0 if include_results and form.get("no_map5") == "1" else 1
    f["bp_password"] = hash_bp_password(form.get("bp_password", "").strip())
    f["bp_process"] = form.get("bp_process", "") if include_results else ""
    f["decider_knife_winner"] = (
        form.get("decider_knife_winner", "").strip() or None if include_results else None
    )
    f["decider_start_side"] = (
        form.get("decider_start_side", "").strip().upper() or None if include_results else None
    )
    f["stream_url"] = form.get("stream_url", "").strip() or None
    f["map_halves"] = form.get("map_halves", "").strip() or None
    watch_urls = []
    idx = 0
    while True:
        name = form.get(f"watch_name_{idx}", "").strip()
        url = normalize_http_url(form.get(f"watch_url_{idx}", ""))
        if name and url:
            watch_urls.append({"name": name, "url": url})
            idx += 1
        elif form.get(f"watch_name_{idx}") is not None or form.get(f"watch_url_{idx}") is not None:
            idx += 1
        else:
            break
    f["watch_urls"] = json.dumps(watch_urls, ensure_ascii=False) if watch_urls else None
    f["status"] = form.get("status", "upcoming") if include_results else "upcoming"
    if f["status"] == "ongoing":
        f["status"] = "live"
    if f["status"] not in ("upcoming", "live", "completed", "cancelled"):
        f["status"] = "upcoming"
    f["server_address"], f["server_password"] = _parse_server_connect(
        form.get("server_address", "").strip()
    )
    provided = set(form).intersection(
        (*setup.LOCKED_AFTER_START_FIELDS, "server_address", "stream_url")
    )
    provided.update(f"{key}_pb" for key in setup.MAP_FIELDS if f"{key}_picked_by" in form)
    provided.update(f"has_map{slot}" for slot in (3, 4, 5) if f"no_map{slot}" in form)
    if "watch_name_0" in form or "watch_url_0" in form:
        provided.add("watch_urls")
    return setup.MatchSetupInput(
        values=f,
        provided=frozenset(provided),
        sides=(_parse_side(form, 1), _parse_side(form, 2)),
        requested_status=form.get("status"),
        result_entries={
            field: form.get(field, "").strip()
            for field in setup.PREMATCH_RESULT_FIELDS
            if field in form
        },
        clear_bp_password=form.get("clear_bp_password") == "1",
        freeze_rosters=form.get("freeze_rosters") == "1",
    )


_CONNECT_PART = re.compile(r"^connect\s+(\S+)$", re.IGNORECASE)


_PASSWORD_PART = re.compile(r"^password\s+(\S+)$", re.IGNORECASE)


def _parse_server_connect(raw):
    """把粘贴的进服串拆成（地址, 密码）。

    支持原来的 “password 密码;connect IP:端口”，也支持 “connect IP:端口; password 密码”
    和只有 “connect IP:端口”（以前这两种会把 “connect ” 一起存进地址，复制出来变成
    “connect connect …”，直播轮询也解析不了地址）。认不出的写法仍原样当地址保存。
    """
    if not raw:
        return None, None
    address, password = None, None
    for part in (piece.strip() for piece in raw.split(";")):
        connect = _CONNECT_PART.match(part)
        secret = _PASSWORD_PART.match(part)
        if connect:
            address = connect.group(1)
        elif secret:
            password = secret.group(1)
    if address is None:
        return raw, None
    return address, password


def _parse_side(form, side):
    prefix = f"side{side}"
    roster_fields = [f"match_team{side}_p{slot}" for slot in range(5)]
    roster = (
        tuple(form.get(field, "").strip() for field in roster_fields)
        if any(field in form for field in roster_fields)
        else None
    )
    return setup.MatchSideInput(
        kind=form.get(f"{prefix}_type", "team"),
        choice=form.get(f"{prefix}_id", "").strip(),
        players=tuple(form.get(f"{prefix}_p{slot}", "").strip() for slot in range(5)),
        roster=roster,
        provided=f"{prefix}_type" in form,
    )


def form_state(current, values=None, sides=None):
    """Keep the submitted fields on the page when rejecting an edit."""
    state = dict(current) if current else {}
    state["_setup_editable"] = bool(current and setup.setup_editable(current))
    for key, value in (values or {}).items():
        state[key[:-3] + "_picked_by" if key.endswith("_pb") else key] = value
    for side, choice in enumerate(sides or (), start=1):
        if choice.team_id is not None:
            state[f"team{side}_id"] = choice.team_id
        if choice.players is not None:
            state[f"team{side}_players"] = choice.players
    state.setdefault("team1_players", None)
    state.setdefault("team2_players", None)
    if not current:
        state["_is_new_form"] = True
    return state
