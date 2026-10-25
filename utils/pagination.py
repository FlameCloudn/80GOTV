"""Shared pagination bounds for SQLite-backed lists."""

from werkzeug.exceptions import BadRequest


def page_params(args, default=20, maximum=100):
    def integer(name, fallback):
        try:
            return int(args.get(name, fallback))
        except (TypeError, ValueError, OverflowError):
            return fallback

    page = max(1, integer("page", 1))
    per_page = max(1, min(maximum, integer("per_page", default) or default))
    offset = (page - 1) * per_page
    if offset > 2**63 - 1:
        raise BadRequest("页码过大，请使用有效的页码")
    return page, per_page, offset
