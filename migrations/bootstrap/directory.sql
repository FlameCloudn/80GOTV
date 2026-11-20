    CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    short_name TEXT,
    logo TEXT,
    description TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

    CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nickname TEXT NOT NULL,
    real_name TEXT,
    group_username_override TEXT,
    is_bashizhong_student INTEGER,
    team_id INTEGER,
    steam_id TEXT,
    avatar TEXT,
    cs2_playtime_minutes INTEGER,
    playtime_status TEXT NOT NULL DEFAULT 'unknown',
    playtime_checked_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(team_id) REFERENCES teams(id)
);

    CREATE TABLE IF NOT EXISTS player_nickname_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    nickname TEXT NOT NULL COLLATE NOCASE,
    source TEXT DEFAULT 'website',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(player_id) REFERENCES players(id),
    UNIQUE(player_id, nickname)
);

    CREATE TABLE IF NOT EXISTS player_private_remarks (
    owner_user_id INTEGER NOT NULL,
    target_user_id INTEGER NOT NULL,
    remark TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(owner_user_id, target_user_id),
    CHECK(owner_user_id <> target_user_id),
    FOREIGN KEY(owner_user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(target_user_id) REFERENCES users(id) ON DELETE CASCADE
);

    CREATE INDEX IF NOT EXISTS idx_player_private_remarks_target
    ON player_private_remarks(target_user_id);
