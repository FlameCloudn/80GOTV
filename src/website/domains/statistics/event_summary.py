"""Read the participants, team history and standings used by event statistics."""

from src.website.domains.directory.team_names import team_abbr
from src.website.domains.matches.match_roster_service import match_player_slots, match_side_identity
from src.website.domains.matches.match_utils import get_sql_effective_status
from src.website.domains.matches.opponents import supplement_temp_teams
from src.website.domains.statistics.stats_display import resolve_match_team_side
from src.website.domains.statistics.stats_storage import stats_relation

_SQL_EFFECTIVE_STATUS = get_sql_effective_status()


def _event_matches_with_teams(conn, event_id):
    """本赛事的比赛（补齐临时队伍、报名队伍的名称）：比赛编号 → 比赛。"""
    rows = conn.execute(
        f"""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s,
               {_SQL_EFFECTIVE_STATUS}
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        WHERE m.event_id=?
        """,
        (event_id,),
    ).fetchall()
    matches = {}
    for row in rows:
        match = supplement_temp_teams(row, conn)
        for side in (1, 2):
            identity = match_side_identity(match, side)
            if identity is None:
                identity = match_side_identity(match, side, match_player_slots(conn, match, side))
            match[f"_team{side}_identity"] = identity
        matches[row["id"]] = match
    return matches


def _side_team_label(match, side):
    """这一方在本场的队伍叫法：正式队伍用简称；临时 / 报名队伍没有简称时用队名（比自动缩写 T3 好认）。"""
    number = side[1]
    name = str(match.get(f"team{number}_name") or "").strip()
    short = str(match.get(f"t{number}s") or "").strip()
    team_id = match.get(f"team{number}_id")
    if (not team_id or team_id < 0) and short == team_abbr(name):
        return name or None
    return short or name or None


def _event_player_teams(conn, event_id, matches):
    """每名选手在本赛事代表的队伍（按每场数据记的是哪一方）：换过队的记 None（页面写“-”），认不出哪一方的记录不算。"""
    found = {}
    records = conn.execute(
        f"""
        SELECT ms.player_id, ms.match_id, ms.team_id, ms.match_team_side
        FROM {stats_relation(conn)} ms
        JOIN matches m ON ms.match_id=m.id
        WHERE m.event_id=? AND ms.player_id IS NOT NULL
          AND COALESCE(ms.data_status, 'final') <> 'superseded'
        """,
        (event_id,),
    ).fetchall()
    for record in records:
        match = matches.get(record["match_id"])
        side = resolve_match_team_side(dict(record), match) if match else None
        label = _side_team_label(match, side) if side else None
        identity = (
            (match.get(f"_team{side[1]}_identity") or match_side_identity(match, int(side[1])))
            if side
            else None
        )
        if label and identity is not None:
            found.setdefault(record["player_id"], {})[identity] = label
    return {
        player_id: next(iter(teams.values())) if len(teams) == 1 else None
        for player_id, teams in found.items()
    }


def _event_team_rankings(matches):
    """队伍排名：已结束比赛的双方（临时队伍也算）各打了几场、赢了几场、场均赢下几张图。"""
    table = {}
    for match in matches.values():
        if match.get("effective_status") != "completed":
            continue
        scores = (match.get("team1_score") or 0, match.get("team2_score") or 0)
        for index, side in enumerate(("t1", "t2")):
            label = _side_team_label(match, side)
            if not label or label == "TBD":
                continue
            key = match.get(f"_team{side[1]}_identity") or match_side_identity(match, int(side[1]))
            if key is None:
                continue
            entry = table.setdefault(
                key,
                {
                    "team_name": match.get(f"team{side[1]}_name") or label,
                    "team_short": label,
                    "match_count": 0,
                    "wins": 0,
                    "score_total": 0,
                },
            )
            own, other = scores[index], scores[1 - index]
            entry["match_count"] += 1
            entry["wins"] += 1 if own > other else 0
            entry["score_total"] += own
    rankings = []
    for entry in table.values():
        entry["avg_score"] = entry.pop("score_total") / entry["match_count"]
        rankings.append(entry)
    return sorted(
        rankings,
        key=lambda t: (-t["wins"], -t["wins"] / t["match_count"], t["team_short"].casefold()),
    )


def _event_team_count(conn, event_id):
    """Count the same participant identities used by event cards and rankings."""
    sides = set()
    for match in _event_matches_with_teams(conn, event_id).values():
        if match.get("status") == "cancelled":
            continue
        for side in (1, 2):
            identity = match.get(f"_team{side}_identity")
            if identity is not None:
                sides.add(identity)
    return len(sides)
