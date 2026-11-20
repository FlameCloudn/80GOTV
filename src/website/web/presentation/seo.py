from urllib.parse import quote, urlsplit

from flask import current_app, request

DEFAULT_SITE_URL = "https://80gotv.cn"


def public_site_url(path="/"):
    configured = str(current_app.config.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    try:
        parts = urlsplit(configured)
        valid = (
            parts.scheme in {"http", "https"}
            and bool(parts.hostname)
            and parts.username is None
            and parts.password is None
            and not parts.query
            and not parts.fragment
            and not any(character.isspace() or character == "\\" for character in configured)
            and (parts.port is None or 1 <= parts.port <= 65535)
        )
    except ValueError:
        valid = False
    origin = configured if valid else DEFAULT_SITE_URL
    return origin + quote("/" + str(path).lstrip("/"), safe="/%:@!$&'()*+,;=-._~")


def canonical_page_url(page=None):
    url = public_site_url(request.path)
    if page is None:
        page = request.args.get("page", type=int)
    if (
        page
        and page > 1
        and request.endpoint in {"news_list", "matches_list", "results_list", "players_list"}
    ):
        url += f"?page={page}"
    return url
