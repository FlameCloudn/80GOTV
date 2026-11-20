"""Match, directory, and comment views shared by front-end JSON endpoints."""

from flask import request, url_for

from src.website.domains.directory.team_names import team_abbr
from src.website.domains.events.event_references import event_abbr, event_path
from src.website.domains.matches.match_utils import (
    get_sql_effective_status,
    get_sql_match_completed,
)
from src.website.domains.statistics.stats_display import optional_number
from src.website.runtime.storage import site_paths
from src.website.runtime.uploads import avatar_static_filename
from src.website.web.presentation.filters import (
    date_display_filter,
    datetime_display_filter,
    time_display_filter,
)
from src.website.web.presentation.pagination import page_params
from src.website.web.presentation.private_remarks import (
    private_player_identity,
    private_user_identity,
)
from src.website.web.presentation.team_logos import team_logo_url
from src.website.web.read_models.news_references import news_path

_SQL_MATCH_COMPLETED = get_sql_match_completed()


_SQL_EFFECTIVE_STATUS = get_sql_effective_status()


def _text(value):
    return "" if value is None else str(value)


def _rounded(value, digits):
    number = optional_number(value)
    return round(number, digits) if number is not None else None


def _user_display_name(username, group_username, user_id=None):
    nickname, group_name = private_user_identity(user_id, username, group_username)
    nickname = _text(nickname).strip()
    group_name = _text(group_name).strip()
    if nickname and group_name:
        return f"{nickname} @{group_name}"
    return nickname or group_name


def _player_display_name(player_id, nickname):
    return _text(private_player_identity(player_id, nickname)[0])


def _keys(row):
    return row.keys() if hasattr(row, "keys") else []


def _has(row, key):
    return key in _keys(row)


def _get(row, key, default=None):
    if row is None:
        return default
    try:
        return row[key] if _has(row, key) else default
    except (KeyError, TypeError, IndexError):
        return default


def _page_params(default=20, maximum=100):
    return page_params(request.args, default, maximum)


def _avatar_url(filename):
    static_filename = avatar_static_filename(site_paths().root, filename, thumbnail=True)
    return url_for("static", filename=static_filename) if static_filename else ""


def _logo_url(filename):
    return team_logo_url(filename, site_paths().root)


def _match_url(match):
    return url_for("match_detail", slug=_get(match, "slug") or match["id"])


def _match_payload(match):
    from src.website.domains.matches.match_display import match_opponents

    return {
        "id": match["id"],
        "url": _match_url(match),
        "event_id": _get(match, "event_id"),
        "event": _text(_get(match, "event_name", "")),
        "team1": _text(_get(match, "team1_name", "TBD") or "TBD"),
        "team2": _text(_get(match, "team2_name", "TBD") or "TBD"),
        "team1_full": _text(_get(match, "team1_name", "TBD")),
        "team2_full": _text(_get(match, "team2_name", "TBD")),
        "team1_short": _text(_get(match, "t1s", "")),
        "team2_short": _text(_get(match, "t2s", "")),
        "team1_logo": _logo_url(_get(match, "team1_logo", "")),
        "team2_logo": _logo_url(_get(match, "team2_logo", "")),
        "opponents": [
            {**opponent, "logo": _logo_url(opponent["logo"])} for opponent in match_opponents(match)
        ],
        "score1": match["team1_score"],
        "score2": match["team2_score"],
        "bo": _text(match["bo_format"] or "BO1"),
        "status": _text(_get(match, "effective_status", "")),
        "time": time_display_filter(match["match_time"]) if match["match_time"] else "TBD",
        "date": date_display_filter(match["match_time"]) if match["match_time"] else "",
        "match_time": _text(_get(match, "match_time", "")),
        "stage": _text(_get(match, "stage", "")),
        "maps": [
            {
                "slot": slot,
                "name": _text(_get(match, f"map{slot}", "")),
                "team1_score": _get(match, f"map{slot}_t1"),
                "team2_score": _get(match, f"map{slot}_t2"),
                "picked_by": _text(_get(match, f"map{slot}_picked_by", "")),
            }
            for slot in range(1, 6)
            if _get(match, f"map{slot}") or _get(match, f"map{slot}_t1") is not None
        ],
    }


def _home_match_payload(match):
    payload = _match_payload(match)
    payload["team1"] = _text(_get(match, "t1s") or payload["team1"])
    payload["team2"] = _text(_get(match, "t2s") or payload["team2"])
    return payload


def _news_payload(row):
    return {
        "id": row["id"],
        "url": news_path(row),
        "title": _text(row["title"]),
        "summary": _text(_get(row, "summary", "")),
        "time": datetime_display_filter(row["publish_time"]) if row["publish_time"] else "",
        "raw_time": _text(_get(row, "publish_time", "")),
        "comments": _get(row, "actual_comment_count", _get(row, "comment_count", 0)) or 0,
    }


def _event_payload(row):
    status = _get(row, "effective_event_status") or _get(row, "status", "")
    return {
        "id": row["id"],
        "url": event_path(row),
        "name": _text(row["name"]),
        "short_name": _text(_get(row, "short_name", "")),
        "abbr": event_abbr(row["name"], _get(row, "short_name", "")),
        "description": _text(_get(row, "description", "")),
        "format": _text(_get(row, "format", "")),
        "status": _text(status),
        "start_date": date_display_filter(_get(row, "start_date"))
        if _get(row, "start_date")
        else "",
        "end_date": date_display_filter(_get(row, "end_date")) if _get(row, "end_date") else "",
        "registration_open": bool(_get(row, "registration_open", 0)),
        "match_count": _get(row, "match_count", 0),
        "team_count": _get(row, "team_count", 0),
    }


def _player_payload(row):
    rating = _get(row, "rating", _get(row, "avg_rating", None))
    school_status = _get(
        row,
        "managed_is_bashizhong_student",
        _get(row, "is_bashizhong_student", None),
    )
    nickname, group_username = private_player_identity(
        row["id"], row["nickname"], _get(row, "group_username", "")
    )
    return {
        "id": row["id"],
        "url": url_for("player_detail", player_id=row["id"]),
        "nickname": _text(nickname),
        "group_username": (_text(group_username) if school_status != 0 else ""),
        "is_bashizhong_student": school_status,
        "origin_symbol": "🌐" if school_status == 0 else "",
        "team_id": _get(row, "team_id"),
        "team": _text(_get(row, "team", _get(row, "team_short", _get(row, "team_name", "")))),
        "avatar": _avatar_url(_get(row, "avatar", "")),
        "rating": _rounded(rating, 2),
        "maps": _get(row, "maps", _get(row, "match_count", 0)),
        "kills": _get(row, "kills"),
        "deaths": _get(row, "deaths"),
        "assists": _get(row, "assists"),
        "adr": _rounded(_get(row, "adr"), 1),
        "hs": _rounded(_get(row, "hs"), 1),
    }


def _team_payload(row):
    return {
        "id": row["id"],
        "url": url_for("team_detail", team_id=row["id"])
        if row["id"]
        else _get(row, "event_url", ""),
        "name": _text(row["name"]),
        "short_name": _text(_get(row, "short_name", "")),
        "abbr": team_abbr(row["name"], _get(row, "short_name", "")),
        "description": _text(_get(row, "description", "")),
        "logo": _logo_url(_get(row, "logo", "")),
        "players": _get(row, "players", 0),
        "rating": _rounded(_get(row, "rating"), 2),
        "maps": _get(row, "maps", 0),
    }


def _comment_payload(row):
    username, group_username = private_user_identity(
        _get(row, "user_id"),
        _get(row, "username", ""),
        _get(row, "group_username", ""),
    )
    username = _text(username)
    group_username = _text(group_username)
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "username": username,
        "group_username": group_username,
        "display_name": _user_display_name(username, group_username),
        "avatar": _avatar_url(_get(row, "avatar", "")),
        "is_cheater": bool(_get(row, "is_cheater", 0)),
        "content": _text(row["content"]),
        "created_at": datetime_display_filter(row["created_at"]) if row["created_at"] else "",
        "parent_id": _get(row, "parent_id"),
        "like_count": _get(row, "like_count", 0),
    }
