CREATE TABLE IF NOT EXISTS formation_batch (
    event_id INTEGER PRIMARY KEY REFERENCES entrant_event(event_id),
    formed_at INTEGER NOT NULL,
    formation_revision INTEGER NOT NULL CHECK (formation_revision >= 1)
);

CREATE TABLE IF NOT EXISTS event_entrant (
    event_entrant_id INTEGER PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES formation_batch(event_id),
    registration_group_id INTEGER NOT NULL UNIQUE REFERENCES registration_group(registration_group_id),
    UNIQUE (event_id, event_entrant_id),
    FOREIGN KEY (event_id, registration_group_id) REFERENCES registration_group(event_id, registration_group_id)
);

CREATE TABLE IF NOT EXISTS entrant_member (
    event_entrant_id INTEGER NOT NULL,
    event_id INTEGER NOT NULL,
    player_id INTEGER NOT NULL REFERENCES players(id),
    roster_slot INTEGER NOT NULL CHECK (roster_slot BETWEEN 0 AND 4),
    PRIMARY KEY (event_entrant_id, roster_slot),
    UNIQUE (event_id, player_id),
    FOREIGN KEY (event_id, player_id) REFERENCES registration_entry(event_id, player_id),
    FOREIGN KEY (event_id, event_entrant_id) REFERENCES event_entrant(event_id, event_entrant_id)
);

CREATE TABLE IF NOT EXISTS initial_roster (
    event_entrant_id INTEGER PRIMARY KEY REFERENCES event_entrant(event_entrant_id),
    confirmed_by INTEGER NOT NULL REFERENCES admins(id),
    confirmed_at INTEGER NOT NULL,
    confirmed_revision INTEGER NOT NULL CHECK (confirmed_revision > 0)
);

CREATE TABLE IF NOT EXISTS initial_roster_member (
    event_entrant_id INTEGER NOT NULL REFERENCES initial_roster(event_entrant_id),
    player_id INTEGER NOT NULL REFERENCES players(id),
    roster_slot INTEGER NOT NULL CHECK (roster_slot BETWEEN 0 AND 4),
    PRIMARY KEY (event_entrant_id, roster_slot),
    UNIQUE (event_entrant_id, player_id)
);

CREATE TRIGGER IF NOT EXISTS protect_initial_roster_update BEFORE UPDATE ON initial_roster
BEGIN SELECT RAISE(ABORT, '初始名单已冻结'); END;
CREATE TRIGGER IF NOT EXISTS protect_initial_roster_delete BEFORE DELETE ON initial_roster
BEGIN SELECT RAISE(ABORT, '初始名单已冻结'); END;
CREATE TRIGGER IF NOT EXISTS protect_initial_member_update BEFORE UPDATE ON initial_roster_member
BEGIN SELECT RAISE(ABORT, '初始五人已冻结'); END;
CREATE TRIGGER IF NOT EXISTS protect_initial_member_delete BEFORE DELETE ON initial_roster_member
BEGIN SELECT RAISE(ABORT, '初始五人已冻结'); END;

CREATE TABLE IF NOT EXISTS reserve_candidate (
    event_id INTEGER NOT NULL REFERENCES formation_batch(event_id),
    player_id INTEGER NOT NULL REFERENCES players(id),
    assigned_entrant_id INTEGER,
    withdrawn_at INTEGER,
    PRIMARY KEY (event_id, player_id),
    CHECK (withdrawn_at IS NULL OR assigned_entrant_id IS NULL),
    FOREIGN KEY (event_id, player_id) REFERENCES registration_entry(event_id, player_id),
    FOREIGN KEY (event_id, assigned_entrant_id) REFERENCES event_entrant(event_id, event_entrant_id)
);

CREATE TABLE IF NOT EXISTS formation_action (
    formation_action_id INTEGER PRIMARY KEY,
    event_entrant_id INTEGER NOT NULL REFERENCES event_entrant(event_entrant_id),
    action_kind TEXT NOT NULL CHECK (action_kind IN ('adjust','assign_reserve','replace')),
    admin_id INTEGER NOT NULL REFERENCES admins(id),
    changed_at INTEGER NOT NULL,
    reason TEXT NOT NULL,
    before_json TEXT NOT NULL,
    after_json TEXT NOT NULL
);
