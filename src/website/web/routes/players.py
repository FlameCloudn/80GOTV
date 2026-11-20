"""Player directory, profile and statistics pages."""

import json
from contextlib import closing

from flask import flash, redirect, render_template, request, session, url_for

from src.website.domains.awards.player_awards_service import build_award_page, build_top10_page
from src.website.domains.directory.player_directory import player_profile
from src.website.domains.directory.player_page_queries import (
    load_player_directory,
    player_achievements,
    player_profile_relations,
    with_effective_school_status,
)
from src.website.domains.directory.player_remark_service import (
    MAX_PLAYER_REMARK_LENGTH,
    change_private_remark,
    remark_target,
    validate_player_remark,
)
from src.website.domains.identity.steam_profile_service import enrich_player_from_steam
from src.website.domains.statistics.player_page_stats import load_player_page_stats
from src.website.domains.statistics.stat_filters import SIDE_OPTIONS, TIME_FILTERS, stat_filters
from src.website.runtime.database import get_db
from src.website.runtime.rate_limiter import rate_limit
from src.website.runtime.storage import site_paths
from src.website.web.access import csrf_required, safe_redirect_target, user_required
from src.website.web.localization import t as ui_message
from src.website.web.presentation.filters import date_display_filter
from src.website.web.presentation.player_stats import _build_player_blocks
from src.website.web.routing import site_routes


def _chart_data(rows):
    return json.dumps(
        {
            "labels": [date_display_filter(row["match_time"]) for row in rows],
            "rating": [
                round(row["rating"], 2) if row["rating"] is not None else None for row in rows
            ],
            "adr": [round(row["adr"], 1) if row["adr"] is not None else None for row in rows],
        },
        ensure_ascii=False,
    )


@site_routes.route("/players")
def players_list():
    """选手列表"""
    team_filter = request.args.get("team", "")
    filter_type = request.args.get("filter", "")
    initial_filter = request.args.get("initial", "all").strip().lower()
    valid_initials = {"all", "123", "other", *(chr(code) for code in range(ord("a"), ord("z") + 1))}
    if initial_filter not in valid_initials:
        initial_filter = "all"
    if filter_type == "top20":
        return redirect(url_for("players_list", filter="top10"))

    with closing(get_db()) as conn:
        award_page = None
        top10_page = None
        if filter_type in {"mvps", "evps"}:
            award_page = build_award_page(conn, "MVP" if filter_type == "mvps" else "EVP")
        elif filter_type == "top10":
            top10_page = build_top10_page(conn)
        players, teams = load_player_directory(
            conn, team_filter=team_filter, filter_type=filter_type, initial=initial_filter
        )

    return render_template(
        "public/players/players.html",
        players=players,
        teams=teams,
        team_filter=team_filter,
        filter_type=filter_type,
        initial_filter=initial_filter,
        award_page=award_page,
        top10_page=top10_page,
    )


@site_routes.route("/players/<int:player_id>/remark", methods=["POST"])
@csrf_required
@user_required
def player_private_remark(player_id):
    """Save a nickname visible only to the current viewer."""
    if not rate_limit("player_private_remark", 20, 60):
        flash(ui_message("flash.players.too_many_note_changes_please_try"), "error")
        return redirect(safe_redirect_target(url_for("player_detail", player_id=player_id)))

    conn = get_db()
    target = remark_target(conn, player_id)
    if not target:
        conn.close()
        flash(ui_message("flash.players.this_player_has_no_site_account"), "error")
        return redirect(safe_redirect_target(url_for("player_detail", player_id=player_id)))
    if int(target["user_id"]) == int(session["user_id"]):
        conn.close()
        flash(ui_message("flash.players.you_cannot_set_a_private_note"), "error")
        return redirect(url_for("player_detail", player_id=player_id))

    action = request.form.get("action", "save").strip().lower()
    remark, error = validate_player_remark(request.form.get("remark", ""))
    if error:
        conn.close()
        flash(ui_message(f"flash.players.{error}", limit=MAX_PLAYER_REMARK_LENGTH), "error")
        return redirect(safe_redirect_target(url_for("player_detail", player_id=player_id)))

    if action == "delete" or not remark:
        change_private_remark(conn, session["user_id"], target["user_id"], "")
        message = ui_message("flash.players.note_deleted")
    else:
        change_private_remark(conn, session["user_id"], target["user_id"], remark)
        message = ui_message("flash.players.note_saved", player=target["nickname"], remark=remark)
    conn.commit()
    conn.close()
    flash(message, "success")
    return redirect(url_for("player_detail", player_id=player_id))


@site_routes.route("/players/<int:player_id>")
def player_detail(player_id):
    """选手详情"""
    period = request.args.get("period", "all")
    event_filter = request.args.get("event", "")
    filters = {"time": period if period in ("3m", "6m") else "all", "map": "all", "side": "both"}

    with closing(get_db()) as conn:
        player = player_profile(conn, player_id)
        if not player:
            return ui_message("public.players.not_found"), 404
        if enrich_player_from_steam(conn, player, site_paths().root):
            conn.commit()
            player = player_profile(conn, player_id)
            if player is None:
                return ui_message("public.players.not_found"), 404

        player = with_effective_school_status(player)
        stats = load_player_page_stats(
            conn, player_id, filters, profile=True, event_filter=event_filter
        )
        medals, championships = player_achievements(conn, player_id)
        relations = player_profile_relations(conn, player)

    chart_data = _chart_data(stats.pop("chart_rows"))
    player_summary, player_category_cards, player_statistics = _build_player_blocks(
        stats["overall"]
    )
    return render_template(
        "public/players/player_detail.html",
        player=player,
        medals=medals,
        championships=championships,
        chart_data=chart_data,
        period=period,
        event_filter=event_filter,
        player_summary=player_summary,
        player_category_cards=player_category_cards,
        player_statistics=player_statistics,
        achievement_count=len(medals) + len(championships),
        **stats,
        **relations,
    )


@site_routes.route("/stats/players/<int:player_id>")
def player_stats_detail(player_id):
    """选手详细数据页。"""
    filters = stat_filters(request.args)
    with closing(get_db()) as conn:
        player = player_profile(conn, player_id)
        if not player:
            return ui_message("public.players.not_found"), 404
        player = with_effective_school_status(player)
        stats = load_player_page_stats(conn, player_id, filters)
        medals, championships = player_achievements(conn, player_id)

    chart_rows = stats.pop("chart_rows")
    chart_data = _chart_data(chart_rows) if chart_rows else None
    player_summary, player_category_cards, player_statistics = _build_player_blocks(
        stats["overall"]
    )
    return render_template(
        "public/players/player_stats.html",
        player=player,
        medals=medals,
        championships=championships,
        chart_data=chart_data,
        filters=filters,
        time_options=TIME_FILTERS,
        side_options=SIDE_OPTIONS,
        player_summary=player_summary,
        player_category_cards=player_category_cards,
        player_statistics=player_statistics,
        **stats,
    )
