"""Public JSON contracts for events, players, teams, and aggregate statistics."""

from contextlib import closing
from functools import partial

from flask import jsonify, request

from src.website.domains.awards.champion_service import list_championship_teams
from src.website.domains.awards.player_awards_service import list_event_medals
from src.website.domains.directory.player_directory import (
    ACCOUNT_JOIN,
    IDENTITY_FIELDS,
    player_profile,
)
from src.website.domains.events.arg_event_service import is_arg_event, ordinary_event_condition
from src.website.domains.events.event_references import event_path
from src.website.domains.events.status import add_effective_event_status
from src.website.domains.matches.opponents import supplement_temp_teams
from src.website.domains.statistics.performance_service import summary_metric_sql
from src.website.domains.statistics.stats_storage import stats_relation
from src.website.runtime.database import get_db
from src.website.web.read_models.front_payloads import (
    _SQL_EFFECTIVE_STATUS,
    _avatar_url,
    _event_payload,
    _get,
    _match_payload,
    _page_params,
    _player_display_name,
    _player_payload,
    _rounded,
    _team_payload,
    _text,
)
from src.website.web.read_models.public_data_service import (
    load_map_statistics,
    load_player_page,
    load_player_summary,
    load_statistics_totals,
    load_team_statistics,
)
from src.website.web.routing import site_routes


@site_routes.route("/api/front/events")
def api_front_events():
    """Event list data."""
    status_filter = request.args.get("status", "").strip()
    conn = get_db()
    rows = conn.execute(f"""
        SELECT e.*,
               COUNT(DISTINCT CASE
                   WHEN COALESCE(m.status, '') != 'cancelled' THEN m.id
               END) AS match_count,
               (SELECT COUNT(DISTINCT team_id) FROM (
                   SELECT team1_id AS team_id FROM matches
                   WHERE event_id = e.id AND COALESCE(status, '') != 'cancelled'
                   UNION
                   SELECT team2_id FROM matches
                   WHERE event_id = e.id AND COALESCE(status, '') != 'cancelled'
               )) AS team_count
        FROM events e
        LEFT JOIN matches m ON e.id=m.event_id
        WHERE {ordinary_event_condition("e")}
        GROUP BY e.id
        ORDER BY e.start_date DESC
    """).fetchall()
    from src.website.domains.events.reads import public_event

    events = [add_effective_event_status(public_event(conn, row)) for row in rows]
    conn.close()
    if status_filter in ("ongoing", "completed", "upcoming"):
        events = [event for event in events if event.get("effective_event_status") == status_filter]
    return jsonify({"ok": True, "events": [_event_payload(row) for row in events]})


@site_routes.route("/api/front/events/<int:event_id>")
def api_front_event_detail(event_id):
    """Event detail data with teams, matches and awards."""
    conn = get_db()
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not event or is_arg_event(event):
        conn.close()
        return jsonify({"ok": False, "error": "赛事不存在"}), 404
    from src.website.domains.events.reads import event_team_cards, public_event, registration_groups
    from src.website.runtime.host import is_managed_event

    event = add_effective_event_status(public_event(conn, event))
    matches = conn.execute(
        f"""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s, e.name AS event_name,
               {_SQL_EFFECTIVE_STATUS}
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id
        WHERE m.event_id=?
        ORDER BY m.match_time
    """,
        (event_id,),
    ).fetchall()
    matches = [supplement_temp_teams(row, conn) for row in matches]
    teams = conn.execute(
        """
        SELECT DISTINCT t.*, COUNT(p.id) AS players
        FROM teams t
        LEFT JOIN players p ON p.team_id=t.id
        WHERE t.id IN (
            SELECT team1_id FROM matches WHERE event_id=? AND team1_id>0
            UNION
            SELECT team2_id FROM matches WHERE event_id=? AND team2_id>0
        )
        GROUP BY t.id
        ORDER BY t.name
    """,
        (event_id, event_id),
    ).fetchall()
    if is_managed_event(conn, event_id):
        teams = [
            {**team, "players": len(team["players"]), "event_url": event_path(event)}
            for team in event_team_cards(registration_groups(conn, event_id))
        ]
        event["match_count"] = len(matches)
    awards = list_event_medals(conn, event_id)
    champions = list_championship_teams(conn, event_id)
    conn.close()
    return jsonify(
        {
            "ok": True,
            "event": _event_payload(event),
            "matches": [_match_payload(row) for row in matches],
            "teams": [_team_payload(row) for row in teams],
            "awards": [
                {
                    "type": row["type"],
                    "player_id": row["player_id"],
                    "nickname": _player_display_name(row["player_id"], row["nickname"]),
                    "avatar": _avatar_url(_get(row, "avatar", "")),
                    "rank": _get(row, "evp_rank"),
                    "reason": _text(_get(row, "reason", "")),
                }
                for row in awards
            ],
            "champions": [
                _team_payload(
                    {
                        **dict(row),
                        "id": row["team_id"],
                        "name": row["team_name"],
                        "short_name": row["team_short"],
                        "event_url": event_path(event),
                    }
                )
                for row in champions
            ],
        }
    )


@site_routes.route("/api/front/players")
def api_front_players():
    """Player list and top player data."""
    page, per_page, offset = _page_params(default=50, maximum=120)
    filter_key = request.args.get("filter", "").strip().lower()
    team_filter = request.args.get("team", "").strip()
    # This older API uses Rating, not the published yearly awards shown by /players.
    if filter_key == "top20":
        filter_key = "top10"
    initial = request.args.get("initial", "all").strip().lower()
    if filter_key == "top10":
        per_page = min(10, per_page)
        offset = (page - 1) * per_page
    with closing(get_db()) as conn:
        rows, total = load_player_page(
            conn,
            team=team_filter,
            filter_key=filter_key,
            initial=initial,
            limit=per_page,
            offset=offset,
        )
    return jsonify(
        {
            "ok": True,
            "page": page,
            "per_page": per_page,
            "total": total,
            "players": [_player_payload(row) for row in rows],
        }
    )


@site_routes.route("/api/front/players/<int:player_id>")
def api_front_player_detail(player_id):
    """Player profile and statistics data."""
    conn = get_db()
    player = player_profile(conn, player_id)
    if not player:
        conn.close()
        return jsonify({"ok": False, "error": "选手不存在"}), 404
    summary = load_player_summary(conn, player_id)
    recent = conn.execute(
        f"""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s, e.name AS event_name,
               {_SQL_EFFECTIVE_STATUS}
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id
        WHERE EXISTS (
            SELECT 1 FROM {stats_relation(conn)} ms WHERE ms.match_id=m.id AND ms.player_id=?
              AND COALESCE(ms.data_status, 'final') <> 'superseded'
        )
        ORDER BY m.match_time DESC, m.id DESC
        LIMIT 10
    """,
        (player_id,),
    ).fetchall()
    recent = [supplement_temp_teams(row, conn) for row in recent]
    medals = conn.execute(
        """
        SELECT pm.*, e.name AS event_name
        FROM player_medals pm
        LEFT JOIN events e ON pm.event_id=e.id
        WHERE pm.player_id=?
        ORDER BY pm.created_at DESC
    """,
        (player_id,),
    ).fetchall()
    conn.close()
    return jsonify(
        {
            "ok": True,
            "player": _player_payload(player),
            "summary": {
                "maps": summary["maps"] or 0,
                "rounds": summary["rounds"],
                "kills": summary["kills"],
                "deaths": summary["deaths"],
                "assists": summary["assists"],
                "rating": _rounded(summary["rating"], 2),
                "adr": _rounded(summary["adr"], 1),
                "kast": _rounded(summary["kast"], 1),
                "hs": _rounded(summary["hs"], 1),
                "kpr": _rounded(summary["kpr"], 2),
                "dpr": _rounded(summary["dpr"], 2),
                "impact": _rounded(summary["impact"], 2),
                "coverage": summary["coverage"],
            },
            "recent_matches": [_match_payload(row) for row in recent],
            "awards": [
                {
                    "type": row["type"],
                    "event_id": row["event_id"],
                    "event": _text(_get(row, "event_name", "")),
                    "rank": _get(row, "evp_rank"),
                    "reason": _text(_get(row, "reason", "")),
                }
                for row in medals
            ],
        }
    )


@site_routes.route("/api/front/teams")
def api_front_teams():
    """Team list data."""
    conn = get_db()
    rows = load_team_statistics(conn)
    conn.close()
    return jsonify({"ok": True, "teams": [_team_payload(row) for row in rows]})


@site_routes.route("/api/front/stats/overview")
def api_front_stats_overview():
    """Stats overview data for frontend pages."""
    conn = get_db()
    metric = partial(summary_metric_sql, stats_source=stats_relation(conn))
    top_players = conn.execute(f"""
        SELECT p.id, p.nickname, p.avatar, t.short_name AS team,
               {IDENTITY_FIELDS},
               s.maps, {metric("avg_rating", "rating")} AS rating,
               {metric("total_kills", "kills")} AS kills,
               {metric("total_deaths", "deaths")} AS deaths,
               {metric("total_assists", "assists")} AS assists,
               {metric("avg_adr", "adr")} AS adr,
               {metric("avg_hs", "headshot_percentage")} AS hs
        FROM player_performance_summary s
        JOIN players p ON s.player_id=p.id {ACCOUNT_JOIN}
        LEFT JOIN teams t ON p.team_id=t.id
        WHERE s.maps > 0
        ORDER BY rating DESC, s.maps DESC, p.id
        LIMIT 10
    """).fetchall()
    top_teams = load_team_statistics(conn, ranked=True)
    top_maps = load_map_statistics(conn)
    overview = load_statistics_totals(conn)
    conn.close()
    return jsonify(
        {
            "ok": True,
            "summary": {
                "matches": overview["matches"] or 0,
                "players": overview["players"] or 0,
                "player_maps": overview["player_maps"] or 0,
                "avg_rating": _rounded(overview["rating"], 2),
                "kills": overview["kills"] if overview["player_maps"] else 0,
            },
            "top_players": [_player_payload(row) for row in top_players],
            "top_teams": [_team_payload(row) for row in top_teams],
            "top_maps": [
                {
                    "map": _text(row["map_name"]),
                    "maps": row["maps"],
                    "rating": _rounded(row["rating"], 2),
                    "adr": _rounded(row["adr"], 1),
                    "hs": _rounded(row["hs"], 1),
                }
                for row in top_maps
            ],
        }
    )
