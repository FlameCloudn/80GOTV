"""Daily and unlimited player Bingo routes."""

from flask import flash, redirect, render_template, request, session, url_for

from models import get_db
from services.player_bingo_service import (
    create_practice_game,
    get_daily_game_row,
    get_practice_game_row,
    load_game,
    player_options,
    submit_player,
    user_statistics,
)
from utils.rate_limiter import rate_limit
from utils.web_helpers import csrf_required
from web_app import app


def _login_redirect(endpoint="player_bingo_page"):
    return redirect(url_for("user_login", next=url_for(endpoint)))


def _game_row(conn, mode):
    if mode == "practice":
        return get_practice_game_row(conn, session["user_id"])
    return get_daily_game_row(conn, session["user_id"])


def _render(mode):
    if "user_id" not in session:
        return _login_redirect(
            "player_bingo_practice_page" if mode == "practice" else "player_bingo_page"
        )
    conn = get_db()
    try:
        game = load_game(conn, _game_row(conn, mode))
        players = player_options(conn)
        statistics = user_statistics(conn, session["user_id"]) if mode == "daily" else None
    finally:
        conn.close()
    return render_template(
        "player_bingo.html",
        game=game,
        mode=mode,
        players=players,
        statistics=statistics,
    )


@app.route("/player-bingo", methods=["GET"])
def player_bingo_page():
    return _render("daily")


@app.route("/player-bingo/practice", methods=["GET"])
def player_bingo_practice_page():
    return _render("practice")


def _submit(mode):
    endpoint = "player_bingo_practice_page" if mode == "practice" else "player_bingo_page"
    if "user_id" not in session:
        return _login_redirect(endpoint)
    if not rate_limit("player_bingo_pick", 90, 60):
        flash("操作太快了，稍等几秒再试", "error")
        return redirect(url_for(endpoint))
    row_value = request.form.get("row_index", "")
    column_value = request.form.get("column_index", "")
    player_value = request.form.get("player_id", "")
    if not (row_value.isdigit() and column_value.isdigit() and player_value.isdigit()):
        flash("请先点一个空格，再从候选列表中选择选手", "error")
        return redirect(url_for(endpoint))
    conn = get_db()
    try:
        _, error = submit_player(
            conn,
            _game_row(conn, mode),
            int(row_value),
            int(column_value),
            int(player_value),
        )
    finally:
        conn.close()
    if error:
        flash(error, "error")
    return redirect(url_for(endpoint))


@app.route("/player-bingo", methods=["POST"])
@csrf_required
def player_bingo_submit():
    return _submit("daily")


@app.route("/player-bingo/practice", methods=["POST"])
@csrf_required
def player_bingo_practice_submit():
    return _submit("practice")


@app.route("/player-bingo/practice/new", methods=["POST"])
@csrf_required
def player_bingo_practice_new():
    if "user_id" not in session:
        return _login_redirect("player_bingo_practice_page")
    if not rate_limit("player_bingo_new", 30, 60):
        flash("换题太快了，稍等几秒再试", "error")
        return redirect(url_for("player_bingo_practice_page"))
    conn = get_db()
    try:
        create_practice_game(conn, session["user_id"])
    finally:
        conn.close()
    return redirect(url_for("player_bingo_practice_page"))
