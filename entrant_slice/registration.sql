CREATE TABLE entrant_event (
    event_id INTEGER PRIMARY KEY REFERENCES events(id) ON DELETE RESTRICT,
    registration_deadline INTEGER NOT NULL,
    archived_at INTEGER
);

-- A group has a stable public registration number. Only the formation batch creates an entrant.
CREATE TABLE registration_group (
    registration_group_id INTEGER PRIMARY KEY AUTOINCREMENT CHECK (registration_group_id > 0),
    event_id INTEGER NOT NULL REFERENCES entrant_event(event_id),
    display_name TEXT NOT NULL,
    club_id INTEGER REFERENCES teams(id) ON DELETE RESTRICT,
    captain_account_id INTEGER REFERENCES users(id),
    logo TEXT,
    group_origin TEXT NOT NULL CHECK (group_origin IN ('registered','formed')),
    created_at INTEGER NOT NULL,
    UNIQUE(event_id, display_name),
    UNIQUE(event_id, registration_group_id)
);

CREATE TABLE registration_entry (
    registration_entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES entrant_event(event_id),
    account_id INTEGER NOT NULL REFERENCES users(id),
    player_id INTEGER NOT NULL REFERENCES players(id),
    registration_origin TEXT NOT NULL CHECK (registration_origin IN ('group','individual','independent_reserve')),
    registration_group_id INTEGER,
    roster_slot INTEGER CHECK (roster_slot BETWEEN 0 AND 4),
    preferred_group_id INTEGER,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (event_id,registration_group_id) REFERENCES registration_group(event_id,registration_group_id),
    FOREIGN KEY (event_id,preferred_group_id) REFERENCES registration_group(event_id,registration_group_id),
    CHECK ((registration_origin='group' AND registration_group_id IS NOT NULL AND roster_slot IS NOT NULL)
        OR (registration_origin<>'group' AND registration_group_id IS NULL AND roster_slot IS NULL)),
    UNIQUE(event_id, account_id),
    UNIQUE(event_id, player_id),
    UNIQUE(registration_group_id, roster_slot)
);

CREATE TABLE registration_reservation (
    registration_group_id INTEGER NOT NULL REFERENCES registration_group(registration_group_id) ON DELETE CASCADE,
    roster_slot INTEGER NOT NULL CHECK (roster_slot BETWEEN 0 AND 4),
    display_label TEXT NOT NULL,
    steam_id TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(registration_group_id, roster_slot)
);

-- Optional badges belong to this disposable sandbox, never to the website's static directory.
CREATE TABLE registration_logo (
    filename TEXT PRIMARY KEY,
    public_png BLOB NOT NULL,
    original_png BLOB NOT NULL
);

CREATE TABLE reservation_review (
    reservation_review_id INTEGER PRIMARY KEY,
    registration_group_id INTEGER NOT NULL REFERENCES registration_group(registration_group_id),
    roster_slot INTEGER NOT NULL,
    original_label TEXT NOT NULL,
    original_steam_id TEXT NOT NULL,
    verified_player_id INTEGER REFERENCES players(id),
    reviewed_by INTEGER NOT NULL REFERENCES admins(id),
    reviewed_at INTEGER NOT NULL,
    reason TEXT NOT NULL
);
