"""Prediction leaderboard, public JSON, and ballot submission endpoints."""

from flask import jsonify, render_template, request, session

from src.website.domains.matches.match_references import resolve_match_slug
from src.website.domains.predictions.scoring import get_prediction_leaderboard
from src.website.domains.predictions.votes import cast_vote, get_prediction_upcoming_matches
from src.website.runtime.database import db, get_db
from src.website.runtime.host import HostError
from src.website.runtime.rate_limiter import rate_limit
from src.website.web.access import csrf_required
from src.website.web.presentation.filters import datetime_display_filter
from src.website.web.read_models.front_payloads import (
    _avatar_url,
    _get,
    _match_url,
    _text,
    _user_display_name,
)
from src.website.web.routing import site_routes


@site_routes.route("/predictions")
def predictions_page():
    """预测排行榜"""
    conn = get_db()

    points_rows = get_prediction_leaderboard(conn)

    upcoming_matches = get_prediction_upcoming_matches(conn)

    conn.close()

    return render_template(
        "public/account/predictions.html",
        predictions=points_rows,
        upcoming_matches=upcoming_matches,
    )


@site_routes.route("/api/front/predictions")
def api_front_predictions():
    """Prediction leaderboard and voted upcoming matches."""
    conn = get_db()
    leaderboard = get_prediction_leaderboard(conn)
    upcoming = get_prediction_upcoming_matches(conn)
    conn.close()
    return jsonify(
        {
            "ok": True,
            "leaderboard": [
                {
                    "user_id": row["user_id"],
                    "username": _user_display_name(row["username"], "", row["user_id"]),
                    "avatar": _avatar_url(_get(row, "avatar", "")),
                    "is_cheater": bool(_get(row, "is_cheater", 0)),
                    "votes": row["total_votes"],
                    "correct": row["correct_votes"] or 0,
                    "points": row["total_points"] or 0,
                }
                for row in leaderboard
            ],
            "upcoming_matches": [
                {
                    "id": row["id"],
                    "url": _match_url(row),
                    "time": datetime_display_filter(row["match_time"]) if row["match_time"] else "",
                    "bo": _text(row["bo_format"]),
                    "team1": _text(row["team1_name"]),
                    "team2": _text(row["team2_name"]),
                    "event": _text(row["event_name"]),
                    "votes": row["vote_count"],
                    "team1_votes": row["t1_votes"] or 0,
                    "team2_votes": row["t2_votes"] or 0,
                }
                for row in upcoming
            ],
        }
    )


@site_routes.route("/matches/<slug>/vote", methods=["POST"])
@csrf_required
def match_vote(slug):
    """赛前投票"""
    match_id = resolve_match_slug(slug)
    if not match_id:
        return jsonify({"ok": False, "msg": "比赛不存在"})
    if "user_id" not in session:
        return jsonify({"ok": False, "msg": "请先登录"})
    if not rate_limit("vote", 20, 60):
        return jsonify({"ok": False, "msg": "操作过于频繁，请稍后再试"})
    user_id = session["user_id"]
    voted_for = request.form.get("voted_for", "").strip()
    if voted_for not in ("t1", "t2"):
        return jsonify({"ok": False, "msg": "无效的投票选项"})

    score1 = request.form.get("score1", "").strip()
    score2 = request.form.get("score2", "").strip()
    try:
        score1_guess = int(score1) if score1 else None
        score2_guess = int(score2) if score2 else None
    except ValueError:
        return jsonify({"ok": False, "msg": "比分格式错误"})
    if any(score is not None and not 0 <= score <= 99 for score in (score1_guess, score2_guess)):
        return jsonify({"ok": False, "msg": "比分范围应为 0-99"})

    try:
        with db() as conn:
            counts = cast_vote(conn, match_id, user_id, voted_for, score1_guess, score2_guess)
    except HostError as exc:
        return jsonify({"ok": False, "msg": exc.message}), exc.status
    return jsonify({"ok": True, **counts})
