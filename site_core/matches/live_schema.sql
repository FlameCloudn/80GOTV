CREATE TABLE live_run_events (
    map_run_id INTEGER NOT NULL REFERENCES map_runs(map_run_id),
    event_type TEXT NOT NULL CHECK (event_type IN ('round', 'death', 'plant')),
    event_key TEXT NOT NULL,
    round_number INTEGER NOT NULL CHECK (round_number > 0),
    payload TEXT NOT NULL,
    PRIMARY KEY (map_run_id, event_type, event_key)
);

CREATE TABLE live_director_sessions (
    scheduled_map_id INTEGER NOT NULL,
    session_id TEXT NOT NULL,
    map_run_id INTEGER NOT NULL,
    actor INTEGER REFERENCES admins(id),
    reason TEXT NOT NULL,
    bound_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (scheduled_map_id, session_id),
    FOREIGN KEY (scheduled_map_id, map_run_id) REFERENCES map_runs(scheduled_map_id, map_run_id)
);

CREATE TABLE live_director_receipts (
    match_id INTEGER NOT NULL REFERENCES matches(id),
    result_id TEXT NOT NULL,
    scheduled_map_id INTEGER NOT NULL REFERENCES scheduled_maps(scheduled_map_id),
    map_run_id INTEGER NOT NULL,
    session_id TEXT,
    frame_seq INTEGER,
    payload_fingerprint TEXT NOT NULL,
    players_candidate TEXT,
    response TEXT NOT NULL,
    received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (match_id, result_id),
    FOREIGN KEY (scheduled_map_id, map_run_id) REFERENCES map_runs(scheduled_map_id, map_run_id)
);
