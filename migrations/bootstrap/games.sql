    CREATE TABLE IF NOT EXISTS guess_players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nickname TEXT NOT NULL UNIQUE COLLATE NOCASE,
    full_name TEXT NOT NULL,
    team TEXT NOT NULL,
    country_code TEXT NOT NULL,
    country_name TEXT NOT NULL,
    birth_date TEXT NOT NULL,
    profile_age INTEGER,
    role TEXT NOT NULL,
    sniping_score INTEGER,
    player_status TEXT NOT NULL DEFAULT 'unknown',
    noob_eligible INTEGER NOT NULL DEFAULT 0,
    major_appearances INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    source_url TEXT,
    source_checked_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

    CREATE TABLE IF NOT EXISTS guess_player_daily (
    game_date TEXT PRIMARY KEY,
    player_id INTEGER NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(player_id) REFERENCES guess_players(id)
);

    CREATE TABLE IF NOT EXISTS guess_player_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    game_date TEXT NOT NULL,
    guessed_player_id INTEGER NOT NULL,
    attempt_number INTEGER NOT NULL CHECK(attempt_number BETWEEN 1 AND 8),
    is_correct INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(guessed_player_id) REFERENCES guess_players(id),
    UNIQUE(user_id, game_date, guessed_player_id),
    UNIQUE(user_id, game_date, attempt_number)
);

    CREATE TABLE IF NOT EXISTS guess_player_practice_games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    player_id INTEGER NOT NULL,
    pool_mode TEXT NOT NULL DEFAULT 'noob',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(player_id) REFERENCES guess_players(id)
);

    CREATE TABLE IF NOT EXISTS guess_player_practice_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL,
    guessed_player_id INTEGER NOT NULL,
    attempt_number INTEGER NOT NULL CHECK(attempt_number BETWEEN 1 AND 8),
    is_correct INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(game_id) REFERENCES guess_player_practice_games(id),
    FOREIGN KEY(guessed_player_id) REFERENCES guess_players(id),
    UNIQUE(game_id, guessed_player_id),
    UNIQUE(game_id, attempt_number)
);

    CREATE TABLE IF NOT EXISTS guess_player_rooms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_code TEXT NOT NULL UNIQUE,
    host_user_id INTEGER NOT NULL,
    guest_user_id INTEGER,
    player_id INTEGER NOT NULL,
    pool_mode TEXT NOT NULL DEFAULT 'noob',
    status TEXT NOT NULL DEFAULT 'waiting',
    winner_user_id INTEGER,
    host_last_seen TEXT,
    guest_last_seen TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    finished_at TEXT,
    FOREIGN KEY(host_user_id) REFERENCES users(id),
    FOREIGN KEY(guest_user_id) REFERENCES users(id),
    FOREIGN KEY(player_id) REFERENCES guess_players(id),
    FOREIGN KEY(winner_user_id) REFERENCES users(id)
);

    CREATE TABLE IF NOT EXISTS guess_player_room_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    guessed_player_id INTEGER NOT NULL,
    attempt_number INTEGER NOT NULL CHECK(attempt_number BETWEEN 1 AND 8),
    is_correct INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(room_id) REFERENCES guess_player_rooms(id),
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(guessed_player_id) REFERENCES guess_players(id),
    UNIQUE(room_id, user_id, guessed_player_id),
    UNIQUE(room_id, user_id, attempt_number)
);

    CREATE TABLE IF NOT EXISTS map_quiz_games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('daily', 'practice')),
    game_key TEXT NOT NULL,
    question_key TEXT NOT NULL,
    finished INTEGER NOT NULL DEFAULT 0,
    won INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id),
    UNIQUE(user_id, mode, game_key)
);

    CREATE TABLE IF NOT EXISTS map_quiz_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL,
    attempt_number INTEGER NOT NULL CHECK(attempt_number BETWEEN 1 AND 3),
    guessed_map TEXT NOT NULL,
    guessed_spot TEXT NOT NULL,
    map_correct INTEGER NOT NULL DEFAULT 0,
    spot_correct INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(game_id) REFERENCES map_quiz_games(id) ON DELETE CASCADE,
    UNIQUE(game_id, attempt_number)
);

    CREATE TABLE IF NOT EXISTS player_bingo_games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('daily', 'practice')),
    game_key TEXT NOT NULL,
    board_json TEXT NOT NULL,
    mistakes INTEGER NOT NULL DEFAULT 0,
    lines INTEGER NOT NULL DEFAULT 0,
    finished INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id),
    UNIQUE(user_id, mode, game_key)
);

    CREATE TABLE IF NOT EXISTS player_bingo_cells (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL,
    row_index INTEGER NOT NULL CHECK(row_index BETWEEN 0 AND 2),
    column_index INTEGER NOT NULL CHECK(column_index BETWEEN 0 AND 2),
    player_id INTEGER NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(game_id) REFERENCES player_bingo_games(id) ON DELETE CASCADE,
    FOREIGN KEY(player_id) REFERENCES guess_players(id),
    UNIQUE(game_id, row_index, column_index),
    UNIQUE(game_id, player_id)
);
