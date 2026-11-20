"""Read event matches, entrants, starting rosters and published ratings."""

import json
from typing import Any

from src.website.domains.awards.player_awards_service import list_event_award_players
from src.website.domains.events import reads as event_reads
from src.website.domains.events.registration_reads import _load_event_registrations
from src.website.domains.events.status import add_effective_event_status
from src.website.domains.matches.bracket_display import public_bracket_data
from src.website.domains.matches.match_roster_service import (
    match_side_identity,
    resolve_match_roster,
)
from src.website.domains.matches.match_utils import get_sql_effective_status
from src.website.domains.matches.opponents import supplement_temp_teams
from src.website.domains.statistics.performance_service import stat_average_sql
from src.website.domains.statistics.stats_storage import stats_relation
from src.website.runtime.host import is_managed_event

_SQL_EFFECTIVE_STATUS = get_sql_effective_status()


def _bp_window_is_open(match):
    """BP is manually started and remains available until the match is closed."""
    return bool(match and match.get("effective_status") not in {"completed", "cancelled"})


def build_event_page_context(conn, event) -> dict[str, Any]:
    event_id = event["id"]

    event = add_effective_event_status(event_reads.public_event(conn, event))

    matches = conn.execute(
        f"""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s,
               t1.logo AS t1_logo, t2.logo AS t2_logo,
               {_SQL_EFFECTIVE_STATUS}
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        WHERE m.event_id=? AND COALESCE(m.status, '') != 'cancelled'
        ORDER BY m.match_time
    """,
        (event_id,),
    ).fetchall()
    matches = [supplement_temp_teams(m, conn) for m in matches]
    for match in matches:
        match["bp_window_open"] = _bp_window_is_open(match)

    # 参赛者可能每场重新组队，只使用本场名单或本赛事报名，不读取长期队籍。
    registrations = _load_event_registrations(conn, event_id)
    team_map = {}
    match_players_map = {}
    for m in matches:
        match_players_map[m["id"]] = resolve_match_roster(conn, m)["players"]
        for side in (1, 2):
            tid = m.get(f"team{side}_id")
            slots = match_players_map[m["id"]][side]
            players = [p for p in slots if p.get("id") or p.get("steam_id") or p.get("nickname")]
            key = match_side_identity(m, side, players)
            if key is None:
                continue
            if key not in team_map:
                team_map[key] = {
                    "id": tid if tid and tid > 0 else None,
                    "name": m.get(f"team{side}_name", ""),
                    "short_name": m.get(f"t{side}s", ""),
                    "logo": m.get(f"t{side}_logo", ""),
                    "is_temp": not (tid and tid > 0),
                    "players": players,
                }

    # 已结束的场次只展示该场表现；未开赛的场次使用本赛事已有的数据。
    stats_source = stats_relation(conn)
    event_ratings = conn.execute(
        f"""
        SELECT ms.player_id, {stat_average_sql("rating")} AS rating
        FROM {stats_source} ms
        JOIN matches m ON m.id=ms.match_id
        WHERE m.event_id=? AND ms.player_id IS NOT NULL
          AND COALESCE(ms.data_status, 'final') <> 'superseded'
        GROUP BY ms.player_id
        """,
        (event_id,),
    ).fetchall()
    rating_by_player = {
        int(row["player_id"]): round(float(row["rating"]), 2)
        for row in event_ratings
        if row["player_id"] and row["rating"] is not None
    }
    match_ratings = {
        (row["match_id"], row["player_id"]): round(float(row["rating"]), 2)
        for row in conn.execute(
            f"""SELECT ms.match_id,ms.player_id,
                       {stat_average_sql("rating")} AS rating
                FROM {stats_source} ms JOIN matches m ON m.id=ms.match_id
                WHERE m.event_id=? AND COALESCE(ms.data_status,'final')<>'superseded'
                GROUP BY ms.match_id,ms.player_id""",
            (event_id,),
        )
        if row["rating"] is not None
    }
    for match in matches:
        for slots in match_players_map[match["id"]].values():
            for player in slots:
                player["rating"] = (
                    match_ratings.get((match["id"], player.get("id")))
                    if match["effective_status"] == "completed"
                    else rating_by_player.get(player.get("id"))
                )
    if is_managed_event(conn, event_id):
        event["bracket_data"] = public_bracket_data(conn, event, matches)
        teams = event_reads.event_team_cards(registrations)
    else:
        teams = list(team_map.values())
    teams.sort(key=lambda t: (t["is_temp"], t["name"]))

    # 构建 team_id → players 映射（供对阵图卡片悬停用）
    team_players_map = {}
    for t in teams:
        players = t["players"][:5]
        if t["id"] is not None:
            team_players_map[str(t["id"])] = players
        if t["is_temp"]:
            team_players_map[t["name"]] = players
            team_players_map[t["name"].lower()] = players

    # 赛事图池从比赛配置汇总；不再让详情页写死一套地图。
    event_map_pool = []
    seen_map_names = set()
    for match in matches:
        try:
            configured_pool = json.loads(match["map_pool"] or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            configured_pool = []
        if not isinstance(configured_pool, list):
            continue
        for map_name in configured_pool:
            display_name = str(map_name or "").strip()
            key = display_name.casefold()
            if display_name and key not in seen_map_names:
                seen_map_names.add(key)
                event_map_pool.append(display_name)
    if not event_map_pool:
        from src.website.domains.matches.bp_manager import ALL_MAPS

        event_map_pool = list(ALL_MAPS)

    # 报名关闭后也保留名单和分队结果，方便参赛者查看。
    award_players = list_event_award_players(conn, event_id)

    return dict(
        event=event,
        matches=matches,
        teams=teams,
        team_players_map=team_players_map,
        match_players_map=match_players_map,
        event_map_pool=event_map_pool,
        registrations=registrations,
        award_players=award_players,
    )
