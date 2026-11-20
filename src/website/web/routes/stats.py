"""HTTP entry points for the website's stats and comparison tabs."""

from flask import abort, render_template, request

from src.website.domains.statistics.comparison_queries import (
    _comparison_players,
    _comparison_profile,
)
from src.website.domains.statistics.map_history import _map_statistics, _match_statistics
from src.website.domains.statistics.public_stat_evidence import pistol_rankings
from src.website.domains.statistics.query_filters import _available_events, _available_maps
from src.website.domains.statistics.ranking_queries import (
    _flash_rankings,
    _overview_context,
    _player_rankings,
    _top_events,
)
from src.website.domains.statistics.stat_filters import (
    SIDE_OPTIONS,
    TIME_FILTER_MAP,
    TIME_FILTERS,
    stat_filters,
)
from src.website.domains.statistics.stats_display import format_stat
from src.website.runtime.database import get_db
from src.website.runtime.storage import site_paths
from src.website.web.read_models.home_service import load_home_feed
from src.website.web.routing import site_routes

RANKING_OPTIONS = [
    {"value": "rating", "label": "RATING"},
    {"value": "kd", "label": "K/D"},
    {"value": "adr", "label": "ADR"},
    {"value": "maps", "label": "地图数"},
]


RANKING_VALUES = {item["value"] for item in RANKING_OPTIONS}


STATS_TABS = ("overview", "players", "matches", "events", "maps", "compare")


OVERVIEW_DETAIL_SECTIONS = {
    "best-players": {"title": "最佳选手", "kind": "players", "order": "rating"},
    "top-events": {"title": "冠军赛事", "kind": "events", "order": "matches"},
    "kd": {"title": "K/D", "kind": "players", "order": "kd"},
    "pistol-rounds": {"title": "手枪局", "kind": "pistol", "order": "pistol"},
    "flashes": {"title": "闪光弹", "kind": "flashes", "order": "success"},
}


def _current_filters():
    event_id = request.args.get("event", type=int)
    ranking = (request.args.get("ranking") or "rating").strip().lower()
    if ranking not in RANKING_VALUES:
        ranking = "rating"
    return {
        **stat_filters(request.args),
        "event": event_id,
        "ranking": ranking,
    }


def _comparison_context(conn, filters):
    players = _comparison_players(conn)
    id1 = request.args.get("id1", type=int)
    id2 = request.args.get("id2", type=int)
    left = _comparison_profile(conn, id1, filters) if id1 else None
    right = _comparison_profile(conn, id2, filters) if id2 else None
    metrics = []
    if left and right:
        metric_specs = (
            ("RATING 2.0", "rating", 2, ""),
            ("K/D", "kd", 2, ""),
            ("ADR", "adr", 1, ""),
            ("KAST", "kast", 1, "%"),
            ("Impact", "impact", 2, ""),
            ("爆头率", "hs", 1, "%"),
            ("每回合击杀", "kpr", 2, ""),
            ("比赛数", "matches", 0, ""),
            ("地图数", "maps", 0, ""),
        )
        for label, key, digits, suffix in metric_specs:
            left_value = left.get(key)
            right_value = right.get(key)
            if left_value is None or right_value is None:
                continue
            metrics.append(
                {
                    "label": label,
                    "left": left_value,
                    "right": right_value,
                    "left_display": f"{left_value:.{digits}f}{suffix}",
                    "right_display": f"{right_value:.{digits}f}{suffix}",
                }
            )
    return {
        "players": players,
        "left": left,
        "right": right,
        "id1": id1,
        "id2": id2,
        "metrics": metrics,
    }


@site_routes.route("/stats")
def stats_page():
    """HLTV-style statistics hub backed only by recorded site data."""
    tab = request.args.get("tab", "overview")
    if tab == "awards":
        tab = "events"
    if tab not in STATS_TABS:
        tab = "overview"
    filters = _current_filters()

    conn = get_db()
    try:
        map_options = _available_maps(conn)
        event_options = _available_events(conn)
        sidebar_feed = load_home_feed(conn)

        # Only query the active view. This keeps the six real-data pages quick.
        overview = None
        rankings = None
        matches = None
        events = None
        map_stats = None
        map_top_players = None
        comparison = None

        if tab == "overview":
            overview = _overview_context(conn, filters)
        elif tab == "players":
            rankings = _player_rankings(conn, filters, filters["ranking"], 100)
        elif tab == "matches":
            matches = _match_statistics(conn, filters, 100)
        elif tab == "events":
            events = _top_events(conn, filters, 100)
        elif tab == "maps":
            map_stats, map_top_players = _map_statistics(conn, filters)
        elif tab == "compare":
            comparison = _comparison_context(conn, filters)
    finally:
        conn.close()

    return render_template(
        "public/stats/stats.html",
        format_stat=format_stat,
        rankings=rankings,
        matches=matches,
        events=events,
        comparison=comparison,
        tab=tab,
        filters=filters,
        time_options=TIME_FILTERS,
        ranking_options=RANKING_OPTIONS,
        map_options=map_options,
        event_options=event_options,
        side_options=SIDE_OPTIONS,
        map_stats=map_stats,
        map_top_players=map_top_players,
        overview=overview,
        sidebar_feed=sidebar_feed,
    )


@site_routes.route("/stats/overview/<section>")
def stats_overview_detail(section):
    """Stats Overview 五个独立详情页。"""
    if section not in OVERVIEW_DETAIL_SECTIONS:
        abort(404)
    filters = _current_filters()
    config = OVERVIEW_DETAIL_SECTIONS[section]
    conn = get_db()
    try:
        if config["kind"] == "events":
            rows = _top_events(conn, filters, 100)
        elif config["kind"] == "flashes":
            rows = _flash_rankings(conn, filters, 100)
        elif config["kind"] == "pistol":
            rows = pistol_rankings(
                conn,
                filters,
                TIME_FILTER_MAP[filters["time"]]["months"],
                site_paths().csda_records,
                site_paths().analysis,
            )
        else:
            rows = _player_rankings(conn, filters, config["order"], 100)
        map_options = _available_maps(conn)
        event_options = _available_events(conn)
        sidebar_feed = load_home_feed(conn)
    finally:
        conn.close()
    return render_template(
        "public/stats/stats_detail.html",
        format_stat=format_stat,
        section=section,
        config=config,
        rows=rows,
        filters=filters,
        time_options=TIME_FILTERS,
        map_options=map_options,
        event_options=event_options,
        side_options=SIDE_OPTIONS,
        sidebar_feed=sidebar_feed,
    )
