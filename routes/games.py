"""Games index."""

from flask import render_template

from web_app import app


@app.route("/games")
def games_page():
    return render_template("games.html")
