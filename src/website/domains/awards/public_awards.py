"""Read published event awards and linked championship teams."""

from src.website.domains.awards.champion_service import list_championship_teams


def _award_groups(conn):
    medals = [
        dict(r)
        for r in conn.execute("""
        SELECT pm.id, pm.type, pm.evp_rank, pm.reason, pm.player_id, pm.event_id, pm.match_id,
               p.nickname, p.avatar,
               e.name AS event_name, e.slug AS event_slug, e.start_date AS event_date,
               t.short_name AS team_short, t.name AS team_name
        FROM player_medals pm
        JOIN players p ON pm.player_id = p.id
        LEFT JOIN events e ON pm.event_id = e.id
        LEFT JOIN teams t ON p.team_id = t.id
        ORDER BY e.start_date DESC, CASE pm.type WHEN 'MVP' THEN 0 ELSE 1 END, pm.evp_rank ASC
    """).fetchall()
    ]
    champions = [dict(row) for row in list_championship_teams(conn)]
    event_groups = {}
    for medal in medals:
        key = (
            medal["event_id"],
            medal["event_slug"],
            medal["event_name"],
            medal["event_date"],
        )
        event_groups.setdefault(key, {"medals": [], "champions": []})["medals"].append(medal)
    for champion in champions:
        key = (
            champion["event_id"],
            champion["event_slug"],
            champion["event_name"],
            champion["event_date"],
        )
        event_groups.setdefault(key, {"medals": [], "champions": []})["champions"].append(champion)
    return sorted(event_groups.items(), key=lambda x: x[0][3] or "", reverse=True), champions
