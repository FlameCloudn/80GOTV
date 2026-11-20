"""界面语言选择、词条及语言切换表单。"""

import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

from flask import abort, current_app, g, has_request_context, redirect, request

from src.website.domains.matches.bracket_formats import FORMAT_SPECS
from src.website.web.access import csrf_required

LANGUAGES = ("zh", "en")
LANGUAGE_MODES = (*LANGUAGES, "auto")
LANGUAGE_COOKIE = "site_locale"
LANGUAGE_PATH = "/preferences/language"


def _load_messages():
    messages = {}
    for path in sorted(Path(__file__).with_name("messages").glob("*.json")):
        group = json.loads(path.read_text(encoding="utf-8"))
        duplicate = messages.keys() & group.keys()
        if duplicate:
            raise ValueError(f"重复的界面文案键：{', '.join(sorted(duplicate))}")
        messages.update(group)
    return messages


MESSAGES = _load_messages()


def _saved_language():
    saved = request.cookies.get(LANGUAGE_COOKIE)
    return saved if saved in LANGUAGE_MODES else None


def current_language():
    if not has_request_context():
        return "zh"
    if "site_locale" not in g:
        saved = _saved_language()
        g.site_locale = (
            saved
            if saved in LANGUAGES
            else request.accept_languages.best_match(LANGUAGES, default="zh")
        )
    return g.site_locale


def t(key, **values):
    return MESSAGES[key][current_language()].format_map(values)


def event_format_label(event):
    original = event["format"]
    try:
        data = json.loads(event["bracket_data"] or "{}")
    except (TypeError, ValueError):
        return original
    tournament = data.get("tournament") if isinstance(data, dict) else None
    if not isinstance(tournament, dict):
        return original
    format_key = tournament.get("format_key")
    if "format_key" not in tournament:
        # Older brackets recorded the system format as an exact type and team count.
        bracket_type = tournament.get("type")
        team_count = tournament.get("total_teams")
        if type(team_count) is int:
            format_key = next(
                (
                    key
                    for key, spec in FORMAT_SPECS.items()
                    if spec["type"] == bracket_type and spec["total_teams"] == team_count
                ),
                None,
            )
    spec = FORMAT_SPECS.get(format_key) if isinstance(format_key, str) else None
    if spec and original == spec["name"]:
        return t(f"event.bracket.format.{format_key}")
    return original


def client_messages(*groups, keys=()):
    """只把页面声明的动态文案传给浏览器。"""
    language = current_language()
    prefixes = tuple(f"client.{group}." for group in groups)
    messages = {key: item[language] for key, item in MESSAGES.items() if key.startswith(prefixes)}
    messages.update((key, MESSAGES[key][language]) for key in keys)
    return messages


def _return_path(target):
    # 浏览器会把反斜线当分隔符，转义后的分隔符也不允许改变开头的路径。
    try:
        path = urlsplit(target).path
        while True:
            if not path.startswith("/") or path.startswith("//") or "\\" in path:
                return "/"
            if any(ord(character) < 32 or ord(character) == 127 for character in path):
                return "/"
            decoded = unquote(path, errors="strict")
            if decoded == path:
                break
            path = decoded
    except (UnicodeError, ValueError):
        return "/"
    if not target.startswith("/") or target.startswith("//") or target != target.strip():
        return "/"
    if any(ord(character) < 32 or ord(character) == 127 for character in target):
        return "/"
    return target


@csrf_required
def set_site_language():
    mode = request.form.get("language")
    if mode not in LANGUAGE_MODES:
        abort(400)

    if request.form.get("legacy") == "1":
        if _saved_language() is not None:
            return "", 204
        response = current_app.make_response(("", 204))
    else:
        response = redirect(_return_path(request.form.get("next", "")), code=303)

    response.set_cookie(
        LANGUAGE_COOKIE,
        mode,
        max_age=365 * 24 * 60 * 60,
        secure=bool(current_app.config.get("SESSION_COOKIE_SECURE")),
        httponly=True,
        samesite="Lax",
    )
    return response


def register_localization(app):
    app.add_url_rule(LANGUAGE_PATH, view_func=set_site_language, methods=("POST",))
    app.jinja_env.globals.update(
        msg=t, client_messages=client_messages, event_format_label=event_format_label
    )

    @app.context_processor
    def language_context():
        language = current_language()
        saved = _saved_language() if has_request_context() else None
        return {
            "site_locale": language,
            "site_language_mode": saved or "auto",
            "site_language_is_saved": saved is not None,
            "site_language_tag": "zh-CN" if language == "zh" else "en",
        }

    @app.after_request
    def language_headers(response):
        if (
            response.mimetype == "text/html"
            and request.endpoint not in {"static", "serve_resource", "arg_unavailable"}
            and not 300 <= response.status_code < 400
        ):
            language = current_language()
            response.headers["Content-Language"] = "zh-CN" if language == "zh" else "en"
            response.vary.update(("Cookie", "Accept-Language"))
        return response
