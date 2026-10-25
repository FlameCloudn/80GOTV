"""Build event MVP / EVP posters from saved match statistics."""

from services.performance_service import weighted_average_sql
from utils.award_poster import generate_award_poster
from utils.demo_parser import match_map_slot
from utils.match_utils import build_raw_maps, get_bo_max_maps
from utils.stats_display import optional_number, resolve_match_team_side


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


def find_event_award_player(conn, event_id, award_type="MVP"):
    return conn.execute(
        """
        SELECT p.id, p.nickname
        FROM player_medals pm
        JOIN players p ON p.id=pm.player_id
        WHERE pm.event_id=? AND pm.type=?
        ORDER BY pm.id LIMIT 1
    """,
        (event_id, award_type),
    ).fetchone()


def list_event_award_players(conn, event_id):
    return conn.execute(
        """
        SELECT p.id, p.nickname, pm.type, pm.evp_rank
        FROM player_medals pm
        JOIN players p ON p.id=pm.player_id
        WHERE pm.event_id=? AND pm.type IN ('MVP', 'EVP')
        ORDER BY CASE pm.type WHEN 'MVP' THEN 0 ELSE 1 END,
                 COALESCE(NULLIF(pm.evp_rank, 0), 999), pm.id
    """,
        (event_id,),
    ).fetchall()


def build_event_award_poster(conn, base_dir, event_id, player_id, award_type="MVP"):
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    player = conn.execute(
        """
        SELECT p.*, t.name AS team_name, t.short_name AS team_short
        FROM players p LEFT JOIN teams t ON p.team_id=t.id WHERE p.id=?
    """,
        (player_id,),
    ).fetchone()
    if not event or not player:
        return None

    player = dict(player)
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
    player["team_name"], player["team_short"] = (
        next(iter(historical_teams)) if len(historical_teams) == 1 else (None, None)
    )

    stats = conn.execute(
        f"""
        SELECT COUNT(ms.id) AS maps,
               SUM(ms.kills) AS kills, SUM(ms.deaths) AS deaths,
               {weighted_average_sql("ms.rating", "ms.stat_rounds")} AS rating,
               {weighted_average_sql("ms.adr", "ms.stat_rounds")} AS adr,
               {weighted_average_sql("ms.kast", "ms.stat_rounds")} AS kast,
               {weighted_average_sql("ms.impact", "ms.stat_rounds")} AS impact,
               SUM(ms.kills) * 1.0 / NULLIF(SUM(ms.deaths), 0) AS kd,
               {_recorded_rate_sql("ms.kills")} AS kpr,
               {_recorded_rate_sql("ms.deaths")} AS dpr,
               ({_recorded_rate_sql("ms.multi2k + ms.multi3k + ms.multi4k + ms.multi5k")}) * 100 AS two_k_pct,
               ({_recorded_rate_sql("ms.multi1k + ms.multi2k + ms.multi3k + ms.multi4k + ms.multi5k")}) * 100 AS one_k_pct,
               {weighted_average_sql("ms.damage_delta_per_round", "ms.stat_rounds")} AS dmg_delta,
               {_recorded_rate_sql("ms.kills - ms.deaths")} AS kills_delta,
               {weighted_average_sql("ms.rws_basic", "ms.stat_rounds")} AS rws_basic
        FROM (
            SELECT ms.*,
                   CASE
                       WHEN COALESCE(ms.rounds_played, 0) > 0 THEN ms.rounds_played
                       ELSE 0
                   END AS stat_rounds
            FROM match_stats ms JOIN matches m ON m.id=ms.match_id
            WHERE ms.player_id=? AND m.event_id=?
              AND COALESCE(ms.data_status, 'final') <> 'superseded'
        ) ms
    """,
        (player_id, event_id),
    ).fetchone()
    map_rows = conn.execute(
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
    ).fetchall()

    stats = dict(stats)
    return generate_award_poster(
        base_dir,
        dict(player),
        dict(event),
        stats,
        [_award_map_row(row) for row in map_rows],
        award_type,
    )
