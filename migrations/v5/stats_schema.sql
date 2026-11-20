-- Install after the map-run, participation and official-result tables.
CREATE TABLE IF NOT EXISTS run_stats_revisions (
    map_run_id INTEGER NOT NULL REFERENCES map_runs(map_run_id),
    revision INTEGER NOT NULL CHECK (revision > 0),
    participation_id INTEGER NOT NULL,
    player_id INTEGER NOT NULL,
    match_participant_id INTEGER NOT NULL,
    scope TEXT NOT NULL CHECK (scope IN ('all', 'ct', 't')),
    source TEXT NOT NULL CHECK (source IN ('demo', 'director', 'admin')),
    source_ref TEXT NOT NULL,
    method TEXT NOT NULL,
    actor NOT NULL CHECK (typeof(actor) IN ('integer', 'text')),
    reason TEXT NOT NULL,
    changes_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (map_run_id, revision)
);

CREATE TABLE IF NOT EXISTS run_player_stats (
    participation_id INTEGER NOT NULL REFERENCES run_participations(participation_id)
        ON DELETE CASCADE,
    scope TEXT NOT NULL CHECK (scope IN ('all', 'ct', 't')),
    map_run_id INTEGER NOT NULL REFERENCES map_runs(map_run_id),
    player_id INTEGER NOT NULL,
    match_participant_id INTEGER NOT NULL,
    field_revisions TEXT NOT NULL,
    rounds_played INTEGER,
    kills INTEGER,
    deaths INTEGER,
    assists INTEGER,
    damage REAL,
    adr REAL,
    kast_rounds INTEGER,
    kast REAL,
    headshot_kills INTEGER,
    headshot_percentage REAL,
    impact REAL,
    rating_impact REAL,
    rating REAL,
    first_kills INTEGER,
    first_deaths INTEGER,
    multi1k INTEGER,
    multi2k INTEGER,
    multi3k INTEGER,
    multi4k INTEGER,
    multi5k INTEGER,
    mvp_count INTEGER,
    clutches_won INTEGER,
    clutch_1v1 INTEGER,
    clutch_1v2 INTEGER,
    clutch_1v3 INTEGER,
    clutch_1v4 INTEGER,
    clutch_1v5 INTEGER,
    utility_damage REAL,
    utility_damage_per_round REAL,
    enemies_flashed INTEGER,
    flash_count INTEGER,
    he_count INTEGER,
    smoke_count INTEGER,
    molotov_count INTEGER,
    trade_kills INTEGER,
    trade_deaths INTEGER,
    bomb_plants INTEGER,
    bomb_defuses INTEGER,
    flash_blinded_seconds REAL,
    flash_enemy_seconds REAL,
    flash_assists INTEGER,
    damage_delta_per_round REAL,
    rws_basic REAL,
    PRIMARY KEY (participation_id, scope)
);

-- Replaceable read index: keeps yesterday's affected players until refresh,
-- including when a participation was removed by the roster owner.
CREATE TABLE IF NOT EXISTS official_player_map_stats (
    scheduled_map_id INTEGER NOT NULL REFERENCES scheduled_maps(scheduled_map_id) ON DELETE CASCADE,
    player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    official_map_result_id INTEGER NOT NULL,
    map_run_id INTEGER NOT NULL,
    participation_id INTEGER NOT NULL,
    match_participant_id INTEGER NOT NULL,
    stats_revision INTEGER NOT NULL,
    overall_json TEXT NOT NULL,
    sides_json TEXT NOT NULL,
    PRIMARY KEY (scheduled_map_id, player_id)
);
CREATE INDEX IF NOT EXISTS official_player_map_stats_player
    ON official_player_map_stats(player_id, scheduled_map_id);

CREATE VIEW IF NOT EXISTS official_stat_maps AS
SELECT sm.scheduled_map_id, sm.match_id, sm.map_name, sm.legacy_slot,
       result.official_map_result_id, run.map_run_id, result.score1, result.score2
FROM scheduled_maps sm
JOIN matches m ON m.id=sm.match_id
JOIN event_registration_control managed ON managed.event_id=m.event_id
JOIN official_map_results result ON result.scheduled_map_id=sm.scheduled_map_id
                               AND result.is_current=1
LEFT JOIN map_runs run ON run.map_run_id=result.map_run_id
                      AND run.scheduled_map_id=sm.scheduled_map_id AND run.status='closed'
WHERE sm.is_enabled=1 AND (result.map_run_id IS NULL OR run.map_run_id IS NOT NULL);

CREATE VIEW IF NOT EXISTS official_stat_participants AS
SELECT sm.scheduled_map_id, sm.match_id, sm.map_name, sm.legacy_slot,
       sm.official_map_result_id, sm.map_run_id, rp.participation_id,
       rp.player_id, rp.match_participant_id, g.club_id AS team_id,
       CASE mp.side_key WHEN 'home' THEN 't1' WHEN 'away' THEN 't2' END AS match_team_side
FROM official_stat_maps sm
JOIN run_participations rp ON rp.map_run_id=sm.map_run_id AND rp.is_current=1
JOIN match_participants mp ON mp.match_participant_id=rp.match_participant_id
                           AND mp.match_id=sm.match_id
JOIN event_entrants entrant ON entrant.event_entrant_id=mp.event_entrant_id
JOIN event_registration_groups g ON g.registration_id=entrant.registration_id;

-- One read shape for current legacy samples and formally adopted modern samples.
-- Keep the explicit column order: upgraded and new legacy tables differ physically.
CREATE VIEW IF NOT EXISTS site_player_map_stats AS
SELECT ms.id, ms.match_id, ms.player_id, ms.team_id, ms.match_team_side,
       ms.map_name, ms.data_source, ms.data_status, ms.data_version,
       ms.kills, ms.deaths, ms.assists, ms.rounds_played, ms.adr, ms.kpr, ms.dpr,
       ms.rating, ms.impact, ms.kast, ms.headshot_percentage,
       ms.first_kills, ms.first_deaths, ms.multi1k, ms.multi2k, ms.multi3k, ms.multi4k, ms.multi5k,
       ms.mvp_count, ms.clutches_won, ms.clutch_1v1, ms.clutch_1v2, ms.clutch_1v3, ms.clutch_1v4, ms.clutch_1v5,
       ms.utility_damage, ms.utility_damage_per_round, ms.enemies_flashed,
       ms.flash_count, ms.flash_count_recorded, ms.he_count, ms.smoke_count, ms.molotov_count,
       ms.trade_kills, ms.trade_deaths, ms.bomb_plants, ms.bomb_defuses,
       ms.flash_blinded_seconds, ms.flash_enemy_seconds, ms.flash_assists,
       ms.damage_delta_per_round, ms.rws_basic,
       ms.side_stats_json, ms.t_kills, ms.ct_kills, ms.t_deaths, ms.ct_deaths,
       ms.t_rating, ms.ct_rating, ms.t_adr, ms.ct_adr,
       NULL AS scheduled_map_id, NULL AS legacy_slot, NULL AS map_run_id
FROM match_stats ms
WHERE COALESCE(ms.data_status, 'final') <> 'superseded'
  AND NOT EXISTS (
      SELECT 1 FROM matches m JOIN event_registration_control managed USING(event_id)
      WHERE m.id=ms.match_id
  )
UNION ALL
SELECT -p.participation_id, p.match_id, p.player_id, p.team_id, p.match_team_side,
       p.map_name, 'official', 'final', s.stats_revision,
       json_extract(s.overall_json, '$.kills'), json_extract(s.overall_json, '$.deaths'),
       json_extract(s.overall_json, '$.assists'), json_extract(s.overall_json, '$.rounds_played'),
       json_extract(s.overall_json, '$.adr'), json_extract(s.overall_json, '$.kpr'),
       json_extract(s.overall_json, '$.dpr'), json_extract(s.overall_json, '$.rating'),
       json_extract(s.overall_json, '$.impact'), json_extract(s.overall_json, '$.kast'),
       json_extract(s.overall_json, '$.headshot_percentage'),
       json_extract(s.overall_json, '$.first_kills'), json_extract(s.overall_json, '$.first_deaths'),
       json_extract(s.overall_json, '$.multi1k'), json_extract(s.overall_json, '$.multi2k'),
       json_extract(s.overall_json, '$.multi3k'), json_extract(s.overall_json, '$.multi4k'),
       json_extract(s.overall_json, '$.multi5k'), json_extract(s.overall_json, '$.mvp_count'),
       json_extract(s.overall_json, '$.clutches_won'), json_extract(s.overall_json, '$.clutch_1v1'),
       json_extract(s.overall_json, '$.clutch_1v2'), json_extract(s.overall_json, '$.clutch_1v3'),
       json_extract(s.overall_json, '$.clutch_1v4'), json_extract(s.overall_json, '$.clutch_1v5'),
       json_extract(s.overall_json, '$.utility_damage'), json_extract(s.overall_json, '$.utility_damage_per_round'),
       json_extract(s.overall_json, '$.enemies_flashed'), json_extract(s.overall_json, '$.flash_count'),
       json_extract(s.overall_json, '$.flash_count') IS NOT NULL,
       json_extract(s.overall_json, '$.he_count'), json_extract(s.overall_json, '$.smoke_count'),
       json_extract(s.overall_json, '$.molotov_count'), json_extract(s.overall_json, '$.trade_kills'),
       json_extract(s.overall_json, '$.trade_deaths'), json_extract(s.overall_json, '$.bomb_plants'),
       json_extract(s.overall_json, '$.bomb_defuses'), json_extract(s.overall_json, '$.flash_blinded_seconds'),
       json_extract(s.overall_json, '$.flash_enemy_seconds'), json_extract(s.overall_json, '$.flash_assists'),
       json_extract(s.overall_json, '$.damage_delta_per_round'), json_extract(s.overall_json, '$.rws_basic'),
       s.sides_json, json_extract(s.sides_json, '$.t.kills'), json_extract(s.sides_json, '$.ct.kills'),
       json_extract(s.sides_json, '$.t.deaths'), json_extract(s.sides_json, '$.ct.deaths'),
       json_extract(s.sides_json, '$.t.rating'), json_extract(s.sides_json, '$.ct.rating'),
       json_extract(s.sides_json, '$.t.adr'), json_extract(s.sides_json, '$.ct.adr'),
       p.scheduled_map_id, p.legacy_slot, p.map_run_id
FROM official_player_map_stats s
JOIN official_stat_participants p USING (
    scheduled_map_id, player_id, official_map_result_id, map_run_id,
    participation_id, match_participant_id
);
