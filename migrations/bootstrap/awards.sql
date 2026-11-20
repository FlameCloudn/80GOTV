    CREATE TABLE IF NOT EXISTS player_medals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    event_id INTEGER,
    match_id INTEGER,
    reason TEXT,
    evp_rank INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(player_id) REFERENCES players(id),
    FOREIGN KEY(event_id) REFERENCES events(id),
    FOREIGN KEY(match_id) REFERENCES matches(id)
);

    CREATE TABLE IF NOT EXISTS yearly_top_players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year INTEGER NOT NULL,
    rank INTEGER NOT NULL CHECK(rank BETWEEN 1 AND 10),
    player_id INTEGER NOT NULL,
    decided_by INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(year, rank),
    UNIQUE(year, player_id),
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE,
    FOREIGN KEY(decided_by) REFERENCES admins(id) ON DELETE SET NULL
);

    CREATE TABLE IF NOT EXISTS event_champions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    team_id INTEGER NOT NULL,
    players_snapshot_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(event_id) REFERENCES events(id),
    FOREIGN KEY(team_id) REFERENCES teams(id)
);

    CREATE TABLE IF NOT EXISTS event_champion_players (
    champion_id INTEGER NOT NULL,
    player_id INTEGER NOT NULL,
    PRIMARY KEY(champion_id, player_id),
    FOREIGN KEY(champion_id) REFERENCES event_champions(id) ON DELETE CASCADE,
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
);
