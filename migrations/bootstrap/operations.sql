    CREATE TABLE IF NOT EXISTS live_match_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER UNIQUE NOT NULL,
    live_state TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(match_id) REFERENCES matches(id)
);

    CREATE TABLE IF NOT EXISTS live_match_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL,
    event_key TEXT NOT NULL,
    event_type TEXT NOT NULL,
    round_num INTEGER DEFAULT 0,
    payload TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(match_id) REFERENCES matches(id),
    UNIQUE(match_id, event_key, event_type)
);

    CREATE TABLE IF NOT EXISTS live_ingest_status (
    source TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    message TEXT,
    match_id INTEGER,
    map_name TEXT,
    received_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(match_id) REFERENCES matches(id)
);
