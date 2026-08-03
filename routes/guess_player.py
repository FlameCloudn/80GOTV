"""Daily and unlimited practice guess-the-professional-player games."""

from flask import flash, jsonify, redirect, render_template, request, session, url_for

from models import get_db
from services.guess_player_service import (
    MAX_GUESSES,
    create_multiplayer_room,
    create_practice_game,
    get_multiplayer_room,
    join_multiplayer_room,
    load_game,
    load_practice_game,
    multiplayer_room_state,
    normalize_pool_mode,
    pool_players,
    submit_multiplayer_guess,
    user_statistics,
)
from utils.rate_limiter import rate_limit
from utils.web_helpers import csrf_required
from web_app import app


def _login_redirect(endpoint="guess_player_page"):
    return redirect(url_for("user_login", next=url_for(endpoint)))


def _player_options(conn, pool_mode="pro"):
    return pool_players(conn, pool_mode, "id, nickname, full_name")


def _resolve_player(conn, pool_mode="pro"):
    pool_mode = normalize_pool_mode(pool_mode)
    extra = " AND noob_eligible=1" if pool_mode == "noob" else ""
    player_id = request.form.get("player_id", "").strip()
    player_query = request.form.get("player_query", "").strip()
    guessed = None
    if player_id.isdigit():
        guessed = conn.execute(
            f"SELECT * FROM guess_players WHERE id=? AND active=1{extra}", (int(player_id),)
        ).fetchone()
    if not guessed and player_query:
        guessed = conn.execute(
            f"""SELECT * FROM guess_players WHERE active=1{extra} AND
               (LOWER(nickname)=LOWER(?) OR LOWER(full_name)=LOWER(?))""",
            (player_query, player_query),
        ).fetchone()
    return guessed


def _render_game(game, mode, pool_mode="pro"):
    pool_mode = normalize_pool_mode(pool_mode)
    conn = get_db()
    try:
        players = _player_options(conn, pool_mode)
        pool_counts = {
            "noob": conn.execute(
                "SELECT COUNT(*) FROM guess_players WHERE active=1 AND noob_eligible=1"
            ).fetchone()[0],
            "pro": conn.execute("SELECT COUNT(*) FROM guess_players WHERE active=1").fetchone()[0],
        }
        statistics = user_statistics(conn, session["user_id"]) if mode == "daily" else None
    finally:
        conn.close()
    return render_template(
        "guess_player.html",
        game=game,
        players=players,
        statistics=statistics,
        max_guesses=MAX_GUESSES,
        mode=mode,
        pool_mode=pool_mode,
        pool_counts=pool_counts,
    )


@app.route("/guess-player", methods=["GET"])
def guess_player_page():
    if "user_id" not in session:
        return _login_redirect()
    conn = get_db()
    try:
        game = load_game(conn, session["user_id"])
    finally:
        conn.close()
    return _render_game(game, "daily", "pro")


@app.route("/guess-player", methods=["POST"])
@csrf_required
def guess_player_submit():
    if "user_id" not in session:
        return _login_redirect()
    if not rate_limit("guess_player_submit", 60, 60):
        flash("操作太快了，稍等几秒再试", "error")
        return redirect(url_for("guess_player_page"))

    conn = get_db()
    try:
        game = load_game(conn, session["user_id"])
        if game["finished"]:
            flash("今天的猜选手已经结束，明天再来吧", "info")
            return redirect(url_for("guess_player_page"))
        guessed = _resolve_player(conn)
        if not guessed:
            flash("请从候选列表中选择一名选手", "error")
            return redirect(url_for("guess_player_page"))

        duplicate = conn.execute(
            """SELECT 1 FROM guess_player_attempts
               WHERE user_id=? AND game_date=? AND guessed_player_id=?""",
            (session["user_id"], game["date"], guessed["id"]),
        ).fetchone()
        if duplicate:
            flash("这名选手今天已经猜过了", "error")
            return redirect(url_for("guess_player_page"))

        attempt_number = len(game["results"]) + 1
        is_correct = int(guessed["id"] == game["answer_row"]["id"])
        conn.execute(
            """INSERT INTO guess_player_attempts(
                   user_id, game_date, guessed_player_id, attempt_number, is_correct
               ) VALUES(?,?,?,?,?)""",
            (session["user_id"], game["date"], guessed["id"], attempt_number, is_correct),
        )
        conn.commit()
        if is_correct:
            flash(f"猜对了！你用了 {attempt_number} 次", "success")
        elif attempt_number >= MAX_GUESSES:
            flash("今天的 8 次机会已经用完", "info")
    finally:
        conn.close()
    return redirect(url_for("guess_player_page"))


@app.route("/guess-player/practice", methods=["GET"])
def guess_player_practice_page():
    if "user_id" not in session:
        return _login_redirect("guess_player_practice_page")
    pool_mode = normalize_pool_mode(request.args.get("difficulty", "noob"))
    conn = get_db()
    try:
        game = load_practice_game(conn, session["user_id"], pool_mode)
    finally:
        conn.close()
    return _render_game(game, "practice", pool_mode)


@app.route("/guess-player/practice", methods=["POST"])
@csrf_required
def guess_player_practice_submit():
    if "user_id" not in session:
        return _login_redirect("guess_player_practice_page")
    pool_mode = normalize_pool_mode(request.form.get("pool_mode", "noob"))
    if not rate_limit("guess_player_practice_submit", 60, 60):
        flash("操作太快了，稍等几秒再试", "error")
        return redirect(url_for("guess_player_practice_page", difficulty=pool_mode))
    conn = get_db()
    try:
        game = load_practice_game(conn, session["user_id"], pool_mode)
        if game["finished"]:
            flash("本局已经结束，可以再开一局", "info")
            return redirect(url_for("guess_player_practice_page", difficulty=pool_mode))
        guessed = _resolve_player(conn, pool_mode)
        if not guessed:
            flash("请从候选列表中选择一名选手", "error")
            return redirect(url_for("guess_player_practice_page", difficulty=pool_mode))
        duplicate = conn.execute(
            """SELECT 1 FROM guess_player_practice_attempts
               WHERE game_id=? AND guessed_player_id=?""",
            (game["id"], guessed["id"]),
        ).fetchone()
        if duplicate:
            flash("这名选手本局已经猜过了", "error")
            return redirect(url_for("guess_player_practice_page", difficulty=pool_mode))

        attempt_number = len(game["results"]) + 1
        is_correct = int(guessed["id"] == game["answer_row"]["id"])
        conn.execute(
            """INSERT INTO guess_player_practice_attempts(
                   game_id, guessed_player_id, attempt_number, is_correct
               ) VALUES(?,?,?,?)""",
            (game["id"], guessed["id"], attempt_number, is_correct),
        )
        conn.commit()
        if is_correct:
            flash(f"猜对了！你用了 {attempt_number} 次", "success")
        elif attempt_number >= MAX_GUESSES:
            flash("本局 8 次机会已经用完", "info")
    finally:
        conn.close()
    return redirect(url_for("guess_player_practice_page", difficulty=pool_mode))


@app.route("/guess-player/practice/new", methods=["POST"])
@csrf_required
def guess_player_practice_new():
    if "user_id" not in session:
        return _login_redirect("guess_player_practice_page")
    pool_mode = normalize_pool_mode(request.form.get("pool_mode", "noob"))
    if not rate_limit("guess_player_practice_new", 30, 60):
        flash("换题太快了，稍等几秒再试", "error")
        return redirect(url_for("guess_player_practice_page", difficulty=pool_mode))
    conn = get_db()
    try:
        create_practice_game(conn, session["user_id"], pool_mode)
    finally:
        conn.close()
    return redirect(url_for("guess_player_practice_page", difficulty=pool_mode))


@app.route("/guess-player/multiplayer", methods=["GET"])
def guess_player_multiplayer_page():
    if "user_id" not in session:
        return _login_redirect("guess_player_multiplayer_page")
    return render_template("guess_player_multiplayer.html")


@app.route("/guess-player/multiplayer/create", methods=["POST"])
@csrf_required
def guess_player_multiplayer_create():
    if "user_id" not in session:
        return _login_redirect("guess_player_multiplayer_page")
    if not rate_limit("guess_player_room_create", 10, 60):
        flash("创建房间太快了，稍等一会再试", "error")
        return redirect(url_for("guess_player_multiplayer_page"))
    pool_mode = normalize_pool_mode(request.form.get("pool_mode", "noob"))
    conn = get_db()
    try:
        _, room_code = create_multiplayer_room(conn, session["user_id"], pool_mode)
    finally:
        conn.close()
    return redirect(url_for("guess_player_multiplayer_room", room_code=room_code))


@app.route("/guess-player/multiplayer/join", methods=["POST"])
@csrf_required
def guess_player_multiplayer_join():
    if "user_id" not in session:
        return _login_redirect("guess_player_multiplayer_page")
    if not rate_limit("guess_player_room_join", 30, 60):
        flash("加入房间太快了，稍等一会再试", "error")
        return redirect(url_for("guess_player_multiplayer_page"))
    room_code = request.form.get("room_code", "").strip().upper()
    conn = get_db()
    try:
        room, error = join_multiplayer_room(conn, room_code, session["user_id"])
    finally:
        conn.close()
    if error:
        flash(error, "error")
        return redirect(url_for("guess_player_multiplayer_page"))
    return redirect(url_for("guess_player_multiplayer_room", room_code=room["room_code"]))


@app.route("/guess-player/multiplayer/<room_code>", methods=["GET"])
def guess_player_multiplayer_room(room_code):
    if "user_id" not in session:
        return _login_redirect("guess_player_multiplayer_page")
    conn = get_db()
    try:
        room = get_multiplayer_room(conn, room_code)
        if not room or session["user_id"] not in (room["host_user_id"], room["guest_user_id"]):
            flash("请先通过房间码加入比赛", "error")
            return redirect(url_for("guess_player_multiplayer_page"))
        state = multiplayer_room_state(conn, room_code, session["user_id"])
        players = _player_options(conn, room["pool_mode"])
    finally:
        conn.close()
    return render_template(
        "guess_player_room.html",
        room_code=room["room_code"],
        pool_mode=normalize_pool_mode(room["pool_mode"]),
        state=state,
        players=players,
        max_guesses=MAX_GUESSES,
    )


@app.route("/api/guess-player/multiplayer/<room_code>/state", methods=["GET"])
def guess_player_multiplayer_state(room_code):
    if "user_id" not in session:
        return jsonify({"success": False, "error": "请先登录"}), 401
    conn = get_db()
    try:
        state = multiplayer_room_state(conn, room_code, session["user_id"])
    finally:
        conn.close()
    if not state:
        return jsonify({"success": False, "error": "房间不存在或你不在房间内"}), 404
    return jsonify({"success": True, "state": state})


@app.route("/api/guess-player/multiplayer/<room_code>/guess", methods=["POST"])
@csrf_required
def guess_player_multiplayer_guess(room_code):
    if "user_id" not in session:
        return jsonify({"success": False, "error": "请先登录"}), 401
    if not rate_limit("guess_player_room_guess", 60, 60):
        return jsonify({"success": False, "error": "操作太快了，请稍后再试"}), 429
    payload = request.get_json(silent=True) or {}
    player_id = str(payload.get("player_id", ""))
    if not player_id.isdigit():
        return jsonify({"success": False, "error": "请选择一名选手"}), 400
    conn = get_db()
    try:
        error = submit_multiplayer_guess(conn, room_code, session["user_id"], int(player_id))
        state = multiplayer_room_state(conn, room_code, session["user_id"])
    finally:
        conn.close()
    if error:
        return jsonify({"success": False, "error": error, "state": state}), 400
    return jsonify({"success": True, "state": state})
