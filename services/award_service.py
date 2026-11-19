"""Build event MVP / EVP posters from saved match statistics."""

from services.performance_service import stat_average_sql
from site_core.host import is_managed_event
from utils.award_poster import generate_award_poster
from utils.demo_parser import match_map_slot
from utils.match_utils import build_raw_maps, get_bo_max_maps
from utils.stats_display import optional_number, resolve_match_team_side
from utils.stats_storage import stats_relation


def _recorded_rate_sql(numerator):
    valid = f"ms.stat_rounds > 0 AND ({numerator}) IS NOT NULL"
    return (
        f"SUM(CASE WHEN {valid} THEN ({numerator}) END) * 1.0 / "
        f"NULLIF(SUM(CASE WHEN {valid} THEN ms.stat_rounds END), 0)"
    )


def _award_map_row(row):
    row = dict(row)
    side = resolve_match_team_side(row, row)
    raw_maps = build_raw_maps(row, include_picked_by=False)[: get_bo_max_maps(row.get("bo_format"))]
    slot = match_map_slot(
        str(row.get("map_name") or "").strip(),
        [str(item[0]).strip() if item[0] else None for item in raw_maps],
    )
    result = {key: row.get(key) for key in ("map_name", "kills", "deaths", "rating", "stage")}
    result.update(opponent=None, score_for=None, score_against=None)
    if side is None:
        return result
    opponent_side = "2" if side == "t1" else "1"
    result["opponent"] = row.get(f"t{opponent_side}s") or row.get(f"team{opponent_side}_name")
    if slot >= 0 and raw_maps[slot][3]:
        _, team1_score, team2_score, _ = raw_maps[slot]
        score_for, score_against = (
            (team1_score, team2_score) if side == "t1" else (team2_score, team1_score)
        )
        result["score_for"] = optional_number(score_for)
        result["score_against"] = optional_number(score_against)
    return result


def _managed_poster_maps(conn, event_id, player_id):
    return [
        dict(row)
        for row in conn.execute(
            """SELECT ms.map_name, ms.kills, ms.deaths, ms.rating, m.stage,
                      COALESCE(NULLIF(r.short_name, ''), r.team_name) AS opponent,
                      CASE ms.match_team_side WHEN 't1' THEN official.score1 ELSE official.score2 END AS score_for,
                      CASE ms.match_team_side WHEN 't1' THEN official.score2 ELSE official.score1 END AS score_against
               FROM site_player_map_stats ms JOIN matches m ON m.id=ms.match_id
               JOIN official_stat_maps official ON official.scheduled_map_id=ms.scheduled_map_id
                                               AND official.map_run_id=ms.map_run_id
               JOIN match_participants other ON other.match_id=m.id AND other.side_key=
                   CASE ms.match_team_side WHEN 't1' THEN 'away' ELSE 'home' END
               JOIN match_rosters r USING(match_participant_id)
               WHERE ms.player_id=? AND m.event_id=?
               ORDER BY ms.rating DESC, m.match_time DESC LIMIT 3""",
            (player_id, event_id),
        )
    ]


def _poster_teams(conn, event_id, player_id, *, managed):
    if managed:
        return {
            tuple(row)
            for row in conn.execute(
                """SELECT DISTINCT r.team_name, r.short_name FROM official_stat_participants p
                   JOIN matches m ON m.id=p.match_id JOIN match_rosters r USING(match_participant_id)
                   WHERE p.player_id=? AND m.event_id=?""",
                (player_id, event_id),
            )
        }
    played_teams = conn.execute(
        """SELECT DISTINCT ms.team_id, ms.match_team_side, m.team1_id, m.team2_id,
                  t1.name AS team1_name, t1.short_name AS team1_short,
                  t2.name AS team2_name, t2.short_name AS team2_short
           FROM match_stats ms JOIN matches m ON m.id=ms.match_id
           LEFT JOIN teams t1 ON t1.id=m.team1_id
           LEFT JOIN teams t2 ON t2.id=m.team2_id
           WHERE ms.player_id=? AND m.event_id=?
             AND COALESCE(ms.data_status, 'final') <> 'superseded'""",
        (player_id, event_id),
    ).fetchall()
    historical_teams = set()
    for row in played_teams:
        side = resolve_match_team_side(row, row)
        historical_teams.add(
            (row[f"team{side[-1]}_name"], row[f"team{side[-1]}_short"]) if side else (None, None)
        )
    return historical_teams


def build_event_award_poster(conn, base_dir, event_id, player_id, award_type="MVP"):
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    player = conn.execute("SELECT * FROM players WHERE id=?", (player_id,)).fetchone()
    if not event or not player:
        return None

    source = stats_relation(conn)
    managed = source == "site_player_map_stats" and is_managed_event(conn, event_id)
    player = dict(player)
    historical_teams = _poster_teams(conn, event_id, player_id, managed=managed)
    player["team_name"], player["team_short"] = (
        next(iter(historical_teams)) if len(historical_teams) == 1 else (None, None)
    )

    stats = conn.execute(
        f"""
        SELECT COUNT(ms.id) AS maps,
               SUM(ms.kills) AS kills, SUM(ms.deaths) AS deaths,
               {stat_average_sql("rating", weight="stat_rounds")} AS rating,
               {stat_average_sql("adr", weight="stat_rounds")} AS adr,
               {stat_average_sql("kast", weight="stat_rounds")} AS kast,
               {stat_average_sql("impact", weight="stat_rounds")} AS impact,
               SUM(ms.kills) * 1.0 / NULLIF(SUM(ms.deaths), 0) AS kd,
               {_recorded_rate_sql("ms.kills")} AS kpr,
               {_recorded_rate_sql("ms.deaths")} AS dpr,
               ({_recorded_rate_sql("ms.multi2k + ms.multi3k + ms.multi4k + ms.multi5k")}) * 100 AS two_k_pct,
               ({_recorded_rate_sql("ms.multi1k + ms.multi2k + ms.multi3k + ms.multi4k + ms.multi5k")}) * 100 AS one_k_pct,
               {stat_average_sql("damage_delta_per_round", weight="stat_rounds")} AS dmg_delta,
               {_recorded_rate_sql("ms.kills - ms.deaths")} AS kills_delta,
               {stat_average_sql("rws_basic", weight="stat_rounds")} AS rws_basic
        FROM (
            SELECT ms.*,
                   CASE
                       WHEN COALESCE(ms.rounds_played, 0) > 0 THEN ms.rounds_played
                       ELSE 0
                   END AS stat_rounds
            FROM {source} ms JOIN matches m ON m.id=ms.match_id
            WHERE ms.player_id=? AND m.event_id=?
              AND COALESCE(ms.data_status, 'final') <> 'superseded'
        ) ms
    """,
        (player_id, event_id),
    ).fetchone()
    if managed:
        maps = _managed_poster_maps(conn, event_id, player_id)
    else:
        maps = [
            _award_map_row(row)
            for row in conn.execute(
                """
        SELECT ms.map_name, ms.kills, ms.deaths, ms.rating, ms.team_id, ms.match_team_side,
               m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s
        FROM match_stats ms JOIN matches m ON m.id=ms.match_id
        LEFT JOIN teams t1 ON t1.id=m.team1_id
        LEFT JOIN teams t2 ON t2.id=m.team2_id
        WHERE ms.player_id=? AND m.event_id=?
          AND COALESCE(ms.data_status, 'final') <> 'superseded'
        ORDER BY ms.rating DESC, m.match_time DESC LIMIT 3
    """,
                (player_id, event_id),
            )
        ]

    stats = dict(stats)
    return generate_award_poster(
        base_dir,
        dict(player),
        dict(event),
        stats,
        maps,
        award_type,
    )
