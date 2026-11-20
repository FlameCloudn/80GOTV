"""Games index."""

from flask import render_template

from src.website.web.routing import site_routes


@site_routes.route("/games")
def games_page():
    return render_template("public/games/games.html")
