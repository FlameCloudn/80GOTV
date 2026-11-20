"""Publish championships, player awards, and the yearly Top 10."""

import sqlite3
from contextlib import closing
from datetime import date
from typing import cast

from flask import (
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from config import BASE_DIR
from src.website.domains.awards.championship import award_championship, championship_status
from src.website.domains.awards.player_awards_service import (
    FIRST_AWARD_YEAR,
    event_medal_selections,
    managed_event_medals,
    save_legacy_event_awards,
    save_managed_event_medals,
    save_yearly_top10,
    yearly_top10_editor,
)
from src.website.runtime.database import db, get_db
from src.website.runtime.host import HostError, write
from src.website.web.access import admin_required as login_required
from src.website.web.access import csrf_required
from src.website.web.admin.admin import admin_bp
from src.website.web.admin.event_forms import _form_number
from src.website.web.localization import t as ui_message
from src.website.web.presentation.event_awards import award_poster_choices, build_event_award_poster


def _submit_event_awards(conn, event_id):
    champion_team_id = request.form.get("champion_team_id", "")
    mvp_player_id = request.form.get("mvp_player_id", "")
    save_legacy_event_awards(
        conn,
        event_id,
        champion_team_id=_form_number(champion_team_id) if champion_team_id else None,
        mvp_player_id=_form_number(mvp_player_id) if mvp_player_id else None,
        evp_player_ids=tuple(
            _form_number(player_id)
            for player_id in request.form.getlist("evp_player_ids")
            if player_id
        ),
    )


def _event_award_options(conn, event_id):
    champion_team = conn.execute(
        "SELECT t.* FROM event_champions ec JOIN teams t ON ec.team_id=t.id WHERE ec.event_id=?",
        (event_id,),
    ).fetchone()
    teams = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
    players = conn.execute("""SELECT p.*, t.name AS team_name
        FROM players p LEFT JOIN teams t ON p.team_id=t.id ORDER BY p.nickname""").fetchall()
    mvp_player, evp_players = event_medal_selections(conn, event_id)
    return teams, players, champion_team, mvp_player, evp_players


@admin_bp.route("/events/<int:event_id>/operations/championship", methods=["GET", "POST"])
@csrf_required
@login_required
def managed_championship(event_id):
    with closing(get_db()) as conn:
        try:
            if request.method == "GET":
                conn.execute("BEGIN")
                return jsonify(ok=True, **championship_status(conn, event_id))
            body = request.get_json(silent=True)
            if not isinstance(body, dict):
                raise HostError("请提交已核对的决赛、正式结算和获奖五人", 400)
            match_id, settlement_id, players = (
                body.get("match_id"),
                body.get("settlement_id"),
                body.get("player_ids"),
            )
            if (
                not isinstance(players, list)
                or len(players) != 5
                or any(
                    type(value) is not int or not 1 <= value <= 2**63 - 1
                    for value in (match_id, settlement_id, *players)
                )
                or len(set(players)) != 5
            ):
                raise HostError("请提供有效的决赛、正式结算编号和五名不同的选手", 400)
            with write(conn):
                result = award_championship(
                    conn,
                    event_id,
                    match_id=cast(int, match_id),
                    settlement_id=cast(int, settlement_id),
                    player_ids=tuple(players),
                    admin_id=session["admin_id"],
                )
            return jsonify(ok=True, **result), 200 if result["duplicate"] else 201
        except HostError as exc:
            return jsonify(ok=False, error=exc.message), exc.status


@admin_bp.route("/events/<int:event_id>/operations/player-awards", methods=["GET", "POST"])
@csrf_required
@login_required
def managed_player_awards(event_id):
    with closing(get_db()) as conn:
        try:
            if request.method == "GET":
                conn.execute("BEGIN")
                return jsonify(ok=True, **managed_event_medals(conn, event_id))
            body = request.get_json(silent=True)
            if not isinstance(body, dict) or not {"mvp_player_id", "evp_player_ids"} <= body.keys():
                raise HostError("请明确提交赛事 MVP 和 EVP 名单", 400)
            mvp = body["mvp_player_id"]
            evps = body["evp_player_ids"]
            if not isinstance(evps, list) or any(
                type(value) is not int or not 1 <= value <= 2**63 - 1
                for value in ([*evps, mvp] if mvp is not None else evps)
            ):
                raise HostError("获奖人编号必须是正整数，EVP 须按公布顺序提交", 400)
            with write(conn):
                result = save_managed_event_medals(
                    conn,
                    event_id,
                    mvp_player_id=mvp,
                    evp_player_ids=tuple(evps),
                    admin_id=session["admin_id"],
                )
            return jsonify(ok=True, **result)
        except HostError as exc:
            return jsonify(ok=False, error=exc.message), exc.status


@admin_bp.route("/top10")
@login_required
def admin_top10():
    """Manage the manually published yearly TOP 10 list."""
    current_year = date.today().year
    year = request.args.get("year", type=int) or current_year
    if year < FIRST_AWARD_YEAR or year > current_year:
        year = current_year

    with closing(get_db()) as conn:
        players, existing, published_years = yearly_top10_editor(conn, year)
    return render_template(
        "admin/catalog/top10.html",
        year=year,
        current_year=current_year,
        players=players,
        existing=existing,
        published_years=published_years,
    )


@admin_bp.route("/top10/save", methods=["POST"])
@csrf_required
@login_required
def admin_top10_save():
    """Replace or explicitly clear one year's published TOP 10 list."""
    current_year = date.today().year
    year_text = request.form.get("year", "").strip()
    if not year_text.isdecimal() or len(year_text) > 19:
        flash(ui_message("flash.admin_operations.invalid_year"), "error")
        return redirect(url_for("admin.admin_top10"))
    year = int(year_text)
    if year < FIRST_AWARD_YEAR or year > current_year:
        flash(
            ui_message(
                "flash.admin_operations.rankings_can_only_be_managed_from",
                FIRST_AWARD_YEAR=FIRST_AWARD_YEAR,
            ),
            "error",
        )
        return redirect(url_for("admin.admin_top10", year=current_year))

    clear = request.form.get("action") == "clear"
    try:
        player_ids = []
        if not clear:
            for rank in range(1, 11):
                value = request.form.get(f"rank_{rank}", "").strip()
                if not value.isdecimal() or len(value) > 19:
                    raise ValueError("必须完整选择第 1 至第 10 名")
                player_id = int(value)
                if not 1 <= player_id <= 2**63 - 1:
                    raise ValueError("所选选手中存在无效档案")
                player_ids.append(player_id)
        with db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            save_yearly_top10(
                conn, year, None if clear else tuple(player_ids), admin_id=session["admin_id"]
            )
    except ValueError as exc:
        flash(str(exc), "error")
    except sqlite3.Error:
        current_app.logger.exception("保存年度 TOP 10 失败")
        flash(ui_message("flash.admin_operations.could_not_save_please_try_again"), "error")
    else:
        flash(
            ui_message(
                "flash.admin.top10_cleared" if clear else "flash.admin.top10_published", year=year
            ),
            "success",
        )
    return redirect(url_for("admin.admin_top10", year=year))


@admin_bp.route("/awards/poster")
@login_required
def admin_award_poster():
    """Award-card form and preview."""
    with closing(get_db()) as conn:
        events, players = award_poster_choices(conn)
    selected_event = request.args.get("event_id", type=int)
    selected_player = request.args.get("player_id", type=int)
    award_type = "EVP" if request.args.get("award_type", "").upper() == "EVP" else "MVP"
    return render_template(
        "admin/events/award_poster.html",
        events=events,
        players=players,
        selected_event=selected_event,
        selected_player=selected_player,
        award_type=award_type,
    )


@admin_bp.route("/awards/poster.png")
@login_required
def admin_award_poster_image():
    """Generate a shareable MVP / EVP image from saved event stats."""
    event_id = request.args.get("event_id", type=int)
    player_id = request.args.get("player_id", type=int)
    award_type = "EVP" if request.args.get("award_type", "").upper() == "EVP" else "MVP"
    if not event_id or not player_id:
        return "请选择赛事和选手", 400
    conn = get_db()
    buffer = build_event_award_poster(conn, BASE_DIR, event_id, player_id, award_type)
    conn.close()
    if not buffer:
        return "赛事或选手不存在", 404
    filename = f"{award_type.lower()}_{event_id}_{player_id}.png"
    return send_file(buffer, mimetype="image/png", as_attachment=True, download_name=filename)
