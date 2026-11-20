"""Public JSON contracts for match listings, scores, and details."""

from contextlib import closing

from flask import jsonify, request

from src.website.domains.community import interactions as community
from src.website.domains.matches.opponents import supplement_temp_teams
from src.website.domains.statistics.stats_storage import stats_relation
from src.website.runtime.database import get_db
from src.website.web.read_models.front_payloads import (
    _SQL_EFFECTIVE_STATUS,
    _SQL_MATCH_COMPLETED,
    _avatar_url,
    _comment_payload,
    _get,
    _match_payload,
    _page_params,
    _player_display_name,
    _text,
)
from src.website.web.read_models.public_data_service import load_match_page
from src.website.web.routing import site_routes


@site_routes.route("/api/front/matches")
def api_front_matches():
    """Match list data for frontend clients."""
    date_filter = request.args.get("date", "").strip()
    event_filter = request.args.get("event", "").strip()
    status = request.args.get("status", "active").strip()
    if status not in ("active", "completed"):
        status = "active"

    page, per_page, offset = _page_params(default=50)
    with closing(get_db()) as conn:
        rows, total = load_match_page(
            conn,
            status=status,
            event=event_filter,
            date=date_filter,
            month=request.args.get("month", "").strip(),
            limit=per_page,
            offset=offset,
        )
    return jsonify(
        {
            "ok": True,
            "page": page,
            "per_page": per_page,
            "total": total,
            "matches": [_match_payload(row) for row in rows],
        }
    )


@site_routes.route("/api/front/results")
def api_front_results():
    """Completed match results."""
    event_filter = request.args.get("event", "").strip()
    page, per_page, offset = _page_params(default=20, maximum=80)
    conn = get_db()
    query = f"""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s, e.name AS event_name,
               {_SQL_EFFECTIVE_STATUS}
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id
        WHERE {_SQL_MATCH_COMPLETED}
    """
    params = []
    if event_filter:
        query += " AND m.event_id=?"
        params.append(event_filter)
    count_query = "SELECT COUNT(*) AS cnt FROM matches m WHERE " + _SQL_MATCH_COMPLETED
    count_params = []
    if event_filter:
        count_query += " AND m.event_id=?"
        count_params.append(event_filter)
    query += " ORDER BY m.match_time DESC, m.id DESC LIMIT ? OFFSET ?"
    rows = [
        supplement_temp_teams(row, conn)
        for row in conn.execute(query, (*params, per_page, offset)).fetchall()
    ]
    total = conn.execute(count_query, tuple(count_params)).fetchone()["cnt"]
    conn.close()
    return jsonify(
        {
            "ok": True,
            "page": page,
            "per_page": per_page,
            "total": total,
            "results": [_match_payload(row) for row in rows],
        }
    )


@site_routes.route("/api/front/matches/<int:match_id>")
def api_front_match_detail(match_id):
    """Single match detail."""
    conn = get_db()
    match = conn.execute(
        f"""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s, e.name AS event_name,
               {_SQL_EFFECTIVE_STATUS}
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id
        WHERE m.id=?
    """,
        (match_id,),
    ).fetchone()
    if not match:
        conn.close()
        return jsonify({"ok": False, "error": "比赛不存在"}), 404
    match = supplement_temp_teams(match, conn)
    stats_rows = conn.execute(
        f"""
        SELECT ms.*, p.nickname, p.avatar, t.short_name AS team_short, t.name AS team_name
        FROM {stats_relation(conn)} ms
        JOIN players p ON ms.player_id=p.id
        LEFT JOIN teams t ON ms.team_id=t.id
        WHERE ms.match_id=?
          AND COALESCE(ms.data_status, 'final') <> 'superseded'
        ORDER BY ms.legacy_slot, ms.team_id, ms.rating DESC
    """,
        (match_id,),
    ).fetchall()
    comments = community.list_comments(conn, "match", match_id)
    conn.close()
    return jsonify(
        {
            "ok": True,
            "match": _match_payload(match),
            "stats": [
                {
                    "player_id": row["player_id"],
                    "nickname": _player_display_name(row["player_id"], row["nickname"]),
                    "avatar": _avatar_url(_get(row, "avatar", "")),
                    "team_id": row["team_id"],
                    "team": _text(_get(row, "team_short", _get(row, "team_name", ""))),
                    "map": _text(row["map_name"]),
                    "kills": row["kills"],
                    "deaths": row["deaths"],
                    "assists": row["assists"],
                    "adr": row["adr"],
                    "rating": row["rating"],
                    "hs": row["headshot_percentage"],
                    **(
                        {
                            "scheduled_map_id": row["scheduled_map_id"],
                            "map_slot": row["legacy_slot"],
                            "team_side": row["match_team_side"],
                        }
                        if row["scheduled_map_id"] is not None
                        else {}
                    ),
                }
                for row in stats_rows
            ],
            "comments": [_comment_payload(row) for row in comments],
        }
    )
