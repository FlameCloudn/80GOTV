"""Daily and unlimited CS2 map-location quiz routes."""

from flask import abort, flash, redirect, render_template, request, send_file, session, url_for

from models import get_db
from services.map_quiz_service import (
    MAPS,
    MAX_ATTEMPTS,
    SOURCE_COLLECTION,
    create_practice_game,
    get_daily_game_row,
    get_practice_game_row,
    load_game,
    public_spot_options,
    question_image_path,
    submit_guess,
    user_statistics,
)
from utils.rate_limiter import rate_limit
from utils.web_helpers import csrf_required
from web_app import app


def _login_redirect(endpoint="map_quiz_page"):
    return redirect(url_for("user_login", next=url_for(endpoint)))


def _game_row(conn, mode):
    if mode == "practice":
        return get_practice_game_row(conn, session["user_id"])
    return get_daily_game_row(conn, session["user_id"])


def _render(mode):
    if "user_id" not in session:
        return _login_redirect("map_quiz_practice_page" if mode == "practice" else "map_quiz_page")
    conn = get_db()
    try:
        game = load_game(conn, _game_row(conn, mode))
        statistics = user_statistics(conn, session["user_id"]) if mode == "daily" else None
    finally:
        conn.close()
    return render_template(
        "map_quiz.html",
        game=game,
        mode=mode,
        maps=MAPS,
        map_names=dict(MAPS),
        spot_options=public_spot_options(),
        max_attempts=MAX_ATTEMPTS,
        statistics=statistics,
        source_collection=SOURCE_COLLECTION,
    )


@app.route("/map-quiz", methods=["GET"])
def map_quiz_page():
    return _render("daily")


@app.route("/map-quiz/practice", methods=["GET"])
def map_quiz_practice_page():
    return _render("practice")


def _submit(mode):
    if "user_id" not in session:
        return _login_redirect("map_quiz_practice_page" if mode == "practice" else "map_quiz_page")
    if not rate_limit("map_quiz_guess", 60, 60):
        flash("操作太快了，稍等几秒再试", "error")
        return redirect(
            url_for("map_quiz_practice_page" if mode == "practice" else "map_quiz_page")
        )
    conn = get_db()
    try:
        _, error = submit_guess(
            conn,
            _game_row(conn, mode),
            request.form.get("map_name", ""),
            request.form.get("spot_name", ""),
        )
    finally:
        conn.close()
    if error:
        flash(error, "error")
    return redirect(url_for("map_quiz_practice_page" if mode == "practice" else "map_quiz_page"))


@app.route("/map-quiz", methods=["POST"])
@csrf_required
def map_quiz_submit():
    return _submit("daily")


@app.route("/map-quiz/practice", methods=["POST"])
@csrf_required
def map_quiz_practice_submit():
    return _submit("practice")


@app.route("/map-quiz/practice/new", methods=["POST"])
@csrf_required
def map_quiz_practice_new():
    if "user_id" not in session:
        return _login_redirect("map_quiz_practice_page")
    if not rate_limit("map_quiz_new", 30, 60):
        flash("换题太快了，稍等几秒再试", "error")
        return redirect(url_for("map_quiz_practice_page"))
    conn = get_db()
    try:
        create_practice_game(conn, session["user_id"])
    finally:
        conn.close()
    return redirect(url_for("map_quiz_practice_page"))


@app.route("/map-quiz/image/<question_key>", methods=["GET"])
def map_quiz_image(question_key):
    if "user_id" not in session:
        abort(404)
    variant = "mobile" if request.args.get("variant") == "mobile" else None
    image_path = question_image_path(question_key, variant=variant)
    if not image_path:
        abort(404)
    mimetype = {
        ".webp": "image/webp",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
    }.get(image_path.suffix.lower())
    return send_file(
        image_path,
        conditional=True,
        max_age=86400,
        mimetype=mimetype,
    )
