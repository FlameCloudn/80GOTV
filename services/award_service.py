"""Build event MVP / EVP posters from saved match statistics."""

from utils.award_poster import generate_award_poster


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

    stats = conn.execute(
        """
        SELECT COUNT(ms.id) AS maps,
               SUM(ms.kills) AS kills, SUM(ms.deaths) AS deaths,
               SUM(ms.rating * ms.stat_rounds) / NULLIF(SUM(ms.stat_rounds), 0) AS rating,
               SUM(ms.adr * ms.stat_rounds) / NULLIF(SUM(ms.stat_rounds), 0) AS adr,
               SUM(ms.kast * ms.stat_rounds) / NULLIF(SUM(ms.stat_rounds), 0) AS kast,
               SUM(ms.impact * ms.stat_rounds) / NULLIF(SUM(ms.stat_rounds), 0) AS impact,
               SUM(ms.kills) * 1.0 / NULLIF(SUM(ms.deaths), 0) AS kd,
               SUM(ms.kills) * 1.0 / NULLIF(SUM(ms.stat_rounds), 0) AS kpr,
               SUM(ms.deaths) * 1.0 / NULLIF(SUM(ms.stat_rounds), 0) AS dpr,
               SUM(ms.multi2k + ms.multi3k + ms.multi4k + ms.multi5k) * 100.0
                   / NULLIF(SUM(ms.stat_rounds), 0) AS two_k_pct,
               SUM(ms.multi1k + ms.multi2k + ms.multi3k + ms.multi4k + ms.multi5k) * 100.0
                   / NULLIF(SUM(ms.stat_rounds), 0) AS one_k_pct,
               SUM(ms.damage_delta_per_round * ms.stat_rounds)
                   / NULLIF(SUM(ms.stat_rounds), 0) AS dmg_delta,
               (SUM(ms.kills) - SUM(ms.deaths)) * 1.0
                   / NULLIF(SUM(ms.stat_rounds), 0) AS kills_delta,
               SUM(ms.rws_basic * ms.stat_rounds)
                   / NULLIF(SUM(ms.stat_rounds), 0) AS rws_basic
        FROM (
            SELECT ms.*,
                   CASE
                       WHEN COALESCE(ms.rounds_played, 0) > 0 THEN ms.rounds_played
                       WHEN COALESCE(ms.kpr, 0) > 0 THEN ROUND(ms.kills * 1.0 / ms.kpr)
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
        SELECT ms.map_name, ms.kills, ms.deaths, ms.rating,
               COALESCE(NULLIF(m.stage, ''), '-') AS stage,
               CASE WHEN ms.team_id=COALESCE(m.team1_id, -1)
                    THEN COALESCE(t2.short_name, t2.name, 'SIDE 2')
                    ELSE COALESCE(t1.short_name, t1.name, 'SIDE 1') END AS opponent,
               CASE WHEN ms.team_id=COALESCE(m.team1_id, -1)
                    THEN CASE
                        WHEN ms.map_name=m.map1 THEN m.map1_t1
                        WHEN ms.map_name=m.map2 THEN m.map2_t1
                        WHEN ms.map_name=m.map3 THEN m.map3_t1
                        WHEN ms.map_name=m.map4 THEN m.map4_t1
                        WHEN ms.map_name=m.map5 THEN m.map5_t1 ELSE 0 END
                    ELSE CASE
                        WHEN ms.map_name=m.map1 THEN m.map1_t2
                        WHEN ms.map_name=m.map2 THEN m.map2_t2
                        WHEN ms.map_name=m.map3 THEN m.map3_t2
                        WHEN ms.map_name=m.map4 THEN m.map4_t2
                        WHEN ms.map_name=m.map5 THEN m.map5_t2 ELSE 0 END END AS score_for,
               CASE WHEN ms.team_id=COALESCE(m.team1_id, -1)
                    THEN CASE
                        WHEN ms.map_name=m.map1 THEN m.map1_t2
                        WHEN ms.map_name=m.map2 THEN m.map2_t2
                        WHEN ms.map_name=m.map3 THEN m.map3_t2
                        WHEN ms.map_name=m.map4 THEN m.map4_t2
                        WHEN ms.map_name=m.map5 THEN m.map5_t2 ELSE 0 END
                    ELSE CASE
                        WHEN ms.map_name=m.map1 THEN m.map1_t1
                        WHEN ms.map_name=m.map2 THEN m.map2_t1
                        WHEN ms.map_name=m.map3 THEN m.map3_t1
                        WHEN ms.map_name=m.map4 THEN m.map4_t1
                        WHEN ms.map_name=m.map5 THEN m.map5_t1 ELSE 0 END END AS score_against
        FROM match_stats ms JOIN matches m ON m.id=ms.match_id
        LEFT JOIN teams t1 ON t1.id=m.team1_id
        LEFT JOIN teams t2 ON t2.id=m.team2_id
        WHERE ms.player_id=? AND m.event_id=?
          AND COALESCE(ms.data_status, 'final') <> 'superseded'
        ORDER BY ms.rating DESC, m.match_time DESC LIMIT 3
    """,
        (player_id, event_id),
    ).fetchall()

    stats = {key: (value or 0) for key, value in dict(stats).items()}
    return generate_award_poster(
        base_dir, dict(player), dict(event), stats, [dict(row) for row in map_rows], award_type
    )
