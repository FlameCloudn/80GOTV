"""Public JSON endpoint for the live scoreboard embedded in match pages."""

from contextlib import closing

from flask import jsonify

from src.website.runtime.database import get_db
from src.website.web.read_models.live_scoreboard import read_scoreboard
from src.website.web.routing import site_routes


@site_routes.route("/api/live/<int:match_id>")
def api_live_match(match_id):
    with closing(get_db()) as conn:
        scoreboard = read_scoreboard(conn, match_id)
    return jsonify(scoreboard)
