    CREATE TABLE IF NOT EXISTS match_votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    voted_for TEXT NOT NULL,
    score1_guess INTEGER,
    score2_guess INTEGER,
    points_earned INTEGER DEFAULT 0,
    scored INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(match_id, user_id),
    FOREIGN KEY(match_id) REFERENCES matches(id),
    FOREIGN KEY(user_id) REFERENCES users(id)
);
