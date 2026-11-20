"""Read the public directory and the non-statistical parts of a player profile."""

from src.website.domains.awards.champion_service import player_championships
from src.website.domains.directory.player_directory import ACCOUNT_JOIN, IDENTITY_FIELDS
from src.website.domains.directory.player_service import player_linked_by_steam
from src.website.domains.events.arg_event_service import ordinary_event_condition
from src.website.domains.statistics.performance_service import summary_metric_sql
from src.website.domains.statistics.stats_storage import stats_relation


def with_effective_school_status(row):
    player = dict(row)
    player["is_bashizhong_student"] = player["managed_is_bashizhong_student"]
    return player


def load_player_directory(conn, *, team_filter, filter_type, initial):
    query = f"""
        SELECT p.*, t.name AS team_name, t.short_name AS team_short, t.logo AS team_logo,
               {IDENTITY_FIELDS}, COALESCE(linked.is_cheater, 0) AS is_cheater,
               {summary_metric_sql("avg_rating", "rating", stats_source=stats_relation(conn))} AS avg_rating,
               s.avg_kills, s.avg_deaths,
               COALESCE(s.maps, 0) AS match_count
        FROM players p
        {ACCOUNT_JOIN}
        LEFT JOIN teams t ON p.team_id=t.id
        LEFT JOIN player_performance_summary s ON p.id=s.player_id
    """
    clauses = []
    params = []
    if filter_type in {"mvps", "evps"}:
        clauses.append(
            "EXISTS (SELECT 1 FROM player_medals pm WHERE pm.player_id=p.id AND pm.type=?)"
        )
        params.append("MVP" if filter_type == "mvps" else "EVP")
    elif filter_type == "top10":
        clauses.append("COALESCE(s.maps, 0) > 0")
    if team_filter:
        clauses.append("p.team_id=?")
        params.append(team_filter)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY avg_rating IS NULL, avg_rating DESC, p.nickname ASC, p.id"
    if filter_type == "top10":
        query += " LIMIT 10"

    # Top 10 is chosen before the initial filter is applied.
    players = [with_effective_school_status(row) for row in conn.execute(query, params).fetchall()]
    if initial != "all":

        def matches_initial(player):
            nickname = (player["nickname"] or "").strip()
            if not nickname:
                return False
            first = nickname[0]
            if initial == "123":
                return first.isascii() and first.isdigit()
            if initial == "other":
                return not (first.isascii() and first.isalnum())
            return first.isascii() and first.lower() == initial

        players = [player for player in players if matches_initial(player)]

    if not filter_type:
        players.sort(key=lambda player: (player["nickname"] or "").casefold())

    teams = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
    return players, teams


def player_achievements(conn, player_id):
    medals = conn.execute(
        """SELECT pm.*, e.name AS event_name, e.id AS event_id,
                  e.slug AS event_slug, e.start_date AS event_date
           FROM player_medals pm LEFT JOIN events e ON pm.event_id=e.id
           WHERE pm.player_id=? ORDER BY e.start_date DESC""",
        (player_id,),
    ).fetchall()
    return medals, player_championships(conn, player_id)


def account_player_history(conn, steam_id: str | None):
    """Show the Steam-linked player, current team and events from non-superseded stats."""
    player = player_linked_by_steam(conn, steam_id)
    events = []
    if player:
        events = conn.execute(
            """SELECT e.*, COUNT(DISTINCT m.id) AS match_count,
                      SUM(CASE WHEN e.status IN ('ongoing','upcoming') THEN 1 ELSE 0 END) > 0 AS is_active
               FROM events e JOIN matches m ON m.event_id=e.id
               JOIN match_stats ms ON ms.match_id=m.id
               WHERE ms.player_id=? AND COALESCE(ms.data_status, 'final') <> 'superseded'
               GROUP BY e.id ORDER BY e.start_date DESC""",
            (player["id"],),
        ).fetchall()
    return {"player": player, "events_participated": events}


def player_profile_relations(conn, player):
    nickname_history = conn.execute(
        """SELECT nickname, source, created_at
           FROM player_nickname_history
           WHERE player_id=? AND nickname != ? COLLATE NOCASE
           ORDER BY created_at DESC, id DESC LIMIT 12""",
        (player["id"], player["nickname"]),
    ).fetchall()
    filter_events = conn.execute(
        f"SELECT id, name FROM events WHERE {ordinary_event_condition()} ORDER BY start_date DESC LIMIT 30"
    ).fetchall()
    teammates = []
    if player["team_id"]:
        teammates = conn.execute(
            """SELECT id, nickname, avatar FROM players
               WHERE team_id=? AND id!=? ORDER BY nickname LIMIT 8""",
            (player["team_id"], player["id"]),
        ).fetchall()
    return {
        "nickname_history": nickname_history,
        "filter_events": filter_events,
        "teammates": teammates,
    }
