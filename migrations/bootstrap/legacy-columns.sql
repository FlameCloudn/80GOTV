ALTER TABLE match_stats ADD COLUMN data_source TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE match_stats ADD COLUMN data_status TEXT NOT NULL DEFAULT 'final';
ALTER TABLE match_stats ADD COLUMN data_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE match_stats ADD COLUMN multi1k INTEGER DEFAULT 0;
ALTER TABLE match_stats ADD COLUMN multi2k INTEGER DEFAULT 0;
ALTER TABLE match_stats ADD COLUMN multi3k INTEGER DEFAULT 0;
ALTER TABLE match_stats ADD COLUMN multi4k INTEGER DEFAULT 0;
ALTER TABLE match_stats ADD COLUMN multi5k INTEGER DEFAULT 0;
ALTER TABLE match_stats ADD COLUMN first_kills INTEGER DEFAULT 0;
ALTER TABLE match_stats ADD COLUMN first_deaths INTEGER DEFAULT 0;
ALTER TABLE match_stats ADD COLUMN mvp_count INTEGER DEFAULT 0;
ALTER TABLE match_stats ADD COLUMN utility_damage REAL DEFAULT 0;
ALTER TABLE match_stats ADD COLUMN enemies_flashed INTEGER DEFAULT 0;
ALTER TABLE match_stats ADD COLUMN flash_count INTEGER DEFAULT 0;
ALTER TABLE match_stats ADD COLUMN flash_count_recorded INTEGER NOT NULL DEFAULT 0;
ALTER TABLE match_stats ADD COLUMN he_count INTEGER DEFAULT 0;
ALTER TABLE match_stats ADD COLUMN smoke_count INTEGER DEFAULT 0;
ALTER TABLE match_stats ADD COLUMN molotov_count INTEGER DEFAULT 0;
ALTER TABLE match_stats ADD COLUMN trade_kills INTEGER DEFAULT 0;
ALTER TABLE match_stats ADD COLUMN trade_deaths INTEGER DEFAULT 0;
ALTER TABLE match_stats ADD COLUMN bomb_plants INTEGER DEFAULT 0;
ALTER TABLE match_stats ADD COLUMN bomb_defuses INTEGER DEFAULT 0;
ALTER TABLE match_stats ADD COLUMN utility_damage_per_round REAL DEFAULT 0;
ALTER TABLE match_stats ADD COLUMN rounds_played INTEGER DEFAULT 0;
ALTER TABLE match_stats ADD COLUMN damage_delta_per_round REAL DEFAULT 0;
ALTER TABLE match_stats ADD COLUMN rws_basic REAL DEFAULT 0;
ALTER TABLE match_stats ADD COLUMN clutch_1v1 INTEGER DEFAULT 0;
ALTER TABLE match_stats ADD COLUMN clutch_1v2 INTEGER DEFAULT 0;
ALTER TABLE match_stats ADD COLUMN clutch_1v3 INTEGER DEFAULT 0;
ALTER TABLE match_stats ADD COLUMN clutch_1v4 INTEGER DEFAULT 0;
ALTER TABLE match_stats ADD COLUMN clutch_1v5 INTEGER DEFAULT 0;
ALTER TABLE match_stats ADD COLUMN flash_blinded_seconds REAL DEFAULT 0;
ALTER TABLE match_stats ADD COLUMN flash_enemy_seconds REAL DEFAULT 0;
ALTER TABLE match_stats ADD COLUMN flash_assists INTEGER DEFAULT 0;
ALTER TABLE player_performance_summary ADD COLUMN flash_maps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE player_performance_summary ADD COLUMN opponent_flash_maps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE matches ADD COLUMN stage TEXT;
ALTER TABLE matches ADD COLUMN slug TEXT;
UPDATE matches SET slug=(
    LOWER(
        REPLACE(
            COALESCE((SELECT short_name FROM teams WHERE teams.id=matches.team1_id), 't1'), ' ', '-'
        ) || '-vs-' ||
        REPLACE(
            COALESCE((SELECT short_name FROM teams WHERE teams.id=matches.team2_id), 't2'), ' ', '-'
        ) || '-' ||
        COALESCE(SUBSTR(match_time, 1, 4), '0000') || '-' ||
        REPLACE(
            COALESCE((SELECT short_name FROM events WHERE events.id=matches.event_id), 'event'), ' ', '-'
        )
    )
) WHERE slug IS NULL;
ALTER TABLE events ADD COLUMN short_name TEXT;
ALTER TABLE events ADD COLUMN slug TEXT;
ALTER TABLE events ADD COLUMN registration_open INTEGER DEFAULT 0;
ALTER TABLE news ADD COLUMN redirect_url TEXT;
ALTER TABLE news ADD COLUMN internal_link_url TEXT;
ALTER TABLE news ADD COLUMN internal_link_text TEXT;
ALTER TABLE users ADD COLUMN is_placeholder INTEGER DEFAULT 0;
ALTER TABLE users ADD COLUMN is_cheater INTEGER DEFAULT 0;
ALTER TABLE users ADD COLUMN approval_status TEXT DEFAULT 'approved';
ALTER TABLE users ADD COLUMN approval_note TEXT;
ALTER TABLE users ADD COLUMN approved_at TEXT;
ALTER TABLE users ADD COLUMN approved_by INTEGER;
ALTER TABLE users ADD COLUMN email TEXT;
ALTER TABLE users ADD COLUMN email_verified_at TEXT;
ALTER TABLE users ADD COLUMN group_username TEXT;
ALTER TABLE users ADD COLUMN is_bashizhong_student INTEGER;
ALTER TABLE players ADD COLUMN is_bashizhong_student INTEGER;
ALTER TABLE guess_players ADD COLUMN profile_age INTEGER;
ALTER TABLE guess_players ADD COLUMN sniping_score INTEGER;
ALTER TABLE guess_players ADD COLUMN player_status TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE guess_players ADD COLUMN noob_eligible INTEGER NOT NULL DEFAULT 0;
ALTER TABLE guess_player_practice_games ADD COLUMN pool_mode TEXT NOT NULL DEFAULT 'noob';
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique ON users(LOWER(email)) WHERE email IS NOT NULL AND TRIM(email)<>'';
UPDATE users SET approval_status='approved' WHERE approval_status IS NULL OR TRIM(approval_status)='';
