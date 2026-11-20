    CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    short_name TEXT,
    slug TEXT,
    description TEXT,
    start_date TEXT,
    end_date TEXT,
    format TEXT,
    status TEXT,
    stream_url TEXT,
    bracket_data TEXT,
    registration_open INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

    CREATE TABLE IF NOT EXISTS event_slug_aliases (
    slug TEXT PRIMARY KEY,
    event_id INTEGER NOT NULL
);

    CREATE TABLE IF NOT EXISTS event_registrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    team_name TEXT NOT NULL,
    team_logo TEXT,
    creator_user_id INTEGER NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(event_id) REFERENCES events(id),
    FOREIGN KEY(creator_user_id) REFERENCES users(id)
);

    CREATE TABLE IF NOT EXISTS event_registration_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    registration_id INTEGER NOT NULL,
    slot_index INTEGER NOT NULL CHECK(slot_index BETWEEN 0 AND 4),
    user_id INTEGER,
    player_name TEXT NOT NULL,
    steam_id TEXT,
    filled_by_creator INTEGER DEFAULT 0,
    FOREIGN KEY(registration_id) REFERENCES event_registrations(id),
    FOREIGN KEY(user_id) REFERENCES users(id),
    UNIQUE(registration_id, slot_index)
);

    CREATE TABLE IF NOT EXISTS event_individual_registrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    player_name TEXT NOT NULL,
    steam_id TEXT NOT NULL,
    assignment_status TEXT NOT NULL DEFAULT 'pending'
        CHECK(assignment_status IN ('pending', 'assigned', 'reserve')),
    team_number INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    assigned_at TEXT,
    cs2_playtime_minutes INTEGER,
    playtime_status TEXT NOT NULL DEFAULT 'unknown',
    playtime_checked_at TEXT,
    preferred_registration_id INTEGER,
    FOREIGN KEY(event_id) REFERENCES events(id),
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(preferred_registration_id) REFERENCES event_registrations(id),
    UNIQUE(event_id, user_id)
);
