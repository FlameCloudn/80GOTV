CREATE UNIQUE INDEX IF NOT EXISTS idx_matches_event_match ON matches(event_id, id);

CREATE TABLE IF NOT EXISTS match_participants (
    match_participant_id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL,
    event_id INTEGER NOT NULL,
    event_entrant_id INTEGER NOT NULL,
    side_key TEXT NOT NULL CHECK (side_key IN ('home', 'away')),
    UNIQUE (match_id, side_key),
    UNIQUE (match_id, event_entrant_id),
    UNIQUE (match_id, match_participant_id),
    FOREIGN KEY (event_id, match_id) REFERENCES matches(event_id, id),
    FOREIGN KEY (event_id, event_entrant_id) REFERENCES event_entrants(event_id, event_entrant_id)
);

CREATE INDEX IF NOT EXISTS idx_match_participants_event_entrant
    ON match_participants(event_id, event_entrant_id);

CREATE TABLE IF NOT EXISTS match_rosters (
    match_participant_id INTEGER PRIMARY KEY REFERENCES match_participants(match_participant_id),
    frozen_by INTEGER NOT NULL REFERENCES admins(id),
    frozen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    team_name TEXT NOT NULL,
    short_name TEXT NOT NULL,
    team_logo TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS match_roster_members (
    match_participant_id INTEGER NOT NULL REFERENCES match_rosters(match_participant_id),
    roster_slot INTEGER NOT NULL CHECK (roster_slot BETWEEN 1 AND 5),
    player_id INTEGER NOT NULL REFERENCES players(id),
    steam_id TEXT NOT NULL CHECK (TRIM(steam_id) <> ''),
    is_substitute INTEGER NOT NULL CHECK (is_substitute IN (0, 1)),
    PRIMARY KEY (match_participant_id, roster_slot),
    UNIQUE (match_participant_id, player_id)
);
