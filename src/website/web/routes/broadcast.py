"""Public JSON endpoints for the local broadcast HUD and desktop manager."""

from contextlib import closing
from datetime import datetime

from flask import jsonify

from src.website.runtime.database import get_db
from src.website.web.read_models import director_catalog
from src.website.web.routing import site_routes


def _broadcast_response(payload, status=200):
    response = jsonify(payload)
    response.status_code = status
    # The HUD runs locally in LHM/OBS. These endpoints contain public match data only.
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, HEAD, OPTIONS"
    return response


def _catalog_response(ok=True, **payload):
    return _broadcast_response(
        {"ok": ok, **payload, "generated_at": datetime.now().isoformat(timespec="seconds")}
    )


@site_routes.route("/api/broadcast/matches")
def api_broadcast_matches():
    with closing(get_db()) as conn:
        matches = director_catalog.list_matches(conn)
    return _catalog_response(matches=matches)


@site_routes.route("/api/broadcast/events")
def api_broadcast_events():
    with closing(get_db()) as conn:
        events = director_catalog.list_events(conn)
    return _catalog_response(events=events)


@site_routes.route("/api/broadcast/events/<int:event_id>")
def api_broadcast_event(event_id):
    with closing(get_db()) as conn:
        event = director_catalog.event_detail(conn, event_id)
    if event is None:
        return _broadcast_response({"ok": False, "event": None, "error": "赛事不存在"}, 404)
    return _catalog_response(event=event)


@site_routes.route("/api/broadcast/current")
def api_broadcast_current():
    with closing(get_db()) as conn:
        match = director_catalog.current_match(conn)
    return _catalog_response(ok=match is not None, match=match)


@site_routes.route("/api/broadcast/matches/<int:match_id>")
def api_broadcast_match(match_id):
    with closing(get_db()) as conn:
        match = director_catalog.match_detail(conn, match_id)
    if match is None:
        return _broadcast_response({"ok": False, "error": "比赛不存在"}, 404)
    return _catalog_response(match=match)
