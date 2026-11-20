"""Rules with the site's original, unprefixed endpoint names."""

from flask import Blueprint, redirect, request, url_for

site_routes = Blueprint("site", __name__)


def canonical_match_redirect(endpoint, requested_slug, match, *, suffix=""):
    canonical_slug = match["slug"] or str(match["id"])
    if str(requested_slug) == str(canonical_slug):
        return None
    target = url_for(endpoint, slug=canonical_slug) + suffix
    if request.query_string:
        target += "?" + request.query_string.decode("latin-1")
    return redirect(target, code=301)
