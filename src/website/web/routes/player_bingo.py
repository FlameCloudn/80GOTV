"""Daily and unlimited player Bingo routes."""

from flask import flash, redirect, render_template, request, session, url_for

from src.website.domains.games.player_bingo_service import (
    create_practice_game,
    get_daily_game_row,
    get_practice_game_row,
    load_game,
    player_options,
    submit_player,
    user_statistics,
)
from src.website.runtime.database import get_db
from src.website.runtime.rate_limiter import rate_limit
from src.website.web.access import csrf_required
from src.website.web.localization import t as ui_message
from src.website.web.routing import site_routes

MAX_SQLITE_INTEGER = 9223372036854775807


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
        "public/games/player_bingo.html",
        game=game,
        mode=mode,
        players=players,
        statistics=statistics,
    )


@site_routes.route("/player-bingo", methods=["GET"])
def player_bingo_page():
    return _render("daily")


@site_routes.route("/player-bingo/practice", methods=["GET"])
def player_bingo_practice_page():
    return _render("practice")


def _submit(mode):
    endpoint = "player_bingo_practice_page" if mode == "practice" else "player_bingo_page"
    if "user_id" not in session:
        return _login_redirect(endpoint)
    if not rate_limit("player_bingo_pick", 90, 60):
        flash(ui_message("flash.player_bingo.too_fast_wait_a_few_seconds"), "error")
        return redirect(url_for(endpoint))
    row_value = request.form.get("row_index", "")
    column_value = request.form.get("column_index", "")
    player_value = request.form.get("player_id", "")
    if not (
        row_value in ("0", "1", "2")
        and column_value in ("0", "1", "2")
        and player_value.isascii()
        and player_value.isdigit()
        and len(player_value) <= 19
    ):
        flash(ui_message("flash.player_bingo.click_an_empty_cell_first_then"), "error")
        return redirect(url_for(endpoint))
    player_id = int(player_value)
    if not 0 < player_id <= MAX_SQLITE_INTEGER:
        flash(ui_message("flash.player_bingo.click_an_empty_cell_first_then"), "error")
        return redirect(url_for(endpoint))
    conn = get_db()
    try:
        _, rejection = submit_player(
            conn,
            _game_row(conn, mode),
            int(row_value),
            int(column_value),
            player_id,
        )
    finally:
        conn.close()
    if rejection:
        flash(ui_message(f"flash.player_bingo.{rejection}"), "error")
    return redirect(url_for(endpoint))


@site_routes.route("/player-bingo", methods=["POST"])
@csrf_required
def player_bingo_submit():
    return _submit("daily")


@site_routes.route("/player-bingo/practice", methods=["POST"])
@csrf_required
def player_bingo_practice_submit():
    return _submit("practice")


@site_routes.route("/player-bingo/practice/new", methods=["POST"])
@csrf_required
def player_bingo_practice_new():
    if "user_id" not in session:
        return _login_redirect("player_bingo_practice_page")
    if not rate_limit("player_bingo_new", 30, 60):
        flash(ui_message("flash.player_bingo.too_fast_wait_a_few_seconds_2"), "error")
        return redirect(url_for("player_bingo_practice_page"))
    conn = get_db()
    try:
        create_practice_game(conn, session["user_id"])
    finally:
        conn.close()
    return redirect(url_for("player_bingo_practice_page"))
