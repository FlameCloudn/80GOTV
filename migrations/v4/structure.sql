CREATE TABLE event_registration_control (
    event_id INTEGER PRIMARY KEY REFERENCES events(id) ON DELETE RESTRICT,
    registration_deadline INTEGER NOT NULL,
    archived_at INTEGER,
    first_write_at INTEGER,
    enabled_by INTEGER NOT NULL REFERENCES admins(id),
    enabled_at INTEGER NOT NULL
);

-- Keep the actual old registration root and its global, database-assigned public number.
CREATE UNIQUE INDEX event_registration_same_event ON event_registrations(event_id,id);
CREATE TABLE event_registration_groups (
    registration_id INTEGER PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES event_registration_control(event_id),
    club_id INTEGER REFERENCES teams(id),
    group_origin TEXT NOT NULL CHECK(group_origin IN ('registered','formed')),
    archived_at INTEGER,
    archived_by INTEGER REFERENCES admins(id),
    archive_reason TEXT,
    CHECK ((archived_at IS NULL AND archived_by IS NULL AND archive_reason IS NULL)
          OR (archived_at IS NOT NULL AND archived_by IS NOT NULL AND length(trim(archive_reason))>0)),
    UNIQUE(event_id,registration_id),
    FOREIGN KEY(event_id,registration_id) REFERENCES event_registrations(event_id,id)
);
CREATE TABLE event_signup_entries (
    registration_entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES event_registration_control(event_id),
    account_id INTEGER NOT NULL REFERENCES users(id),
    player_id INTEGER NOT NULL REFERENCES players(id),
    registration_origin TEXT NOT NULL CHECK (registration_origin IN ('group','individual','independent_reserve')),
    registration_id INTEGER,
    roster_slot INTEGER CHECK (roster_slot BETWEEN 0 AND 4),
    preferred_registration_id INTEGER,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (event_id,registration_id) REFERENCES event_registration_groups(event_id,registration_id),
    FOREIGN KEY (event_id,preferred_registration_id) REFERENCES event_registration_groups(event_id,registration_id),
    CHECK ((registration_origin='group' AND registration_id IS NOT NULL AND roster_slot IS NOT NULL)
        OR (registration_origin<>'group' AND registration_id IS NULL AND roster_slot IS NULL)),
    UNIQUE(event_id, account_id),
    UNIQUE(event_id, player_id),
    UNIQUE(registration_id, roster_slot)
);

CREATE TABLE event_signup_reservations (
    registration_id INTEGER NOT NULL REFERENCES event_registration_groups(registration_id) ON DELETE CASCADE,
    roster_slot INTEGER NOT NULL CHECK (roster_slot BETWEEN 0 AND 4),
    display_label TEXT NOT NULL,
    steam_id TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(registration_id, roster_slot)
);

CREATE TABLE event_reservation_reviews (
    reservation_review_id INTEGER PRIMARY KEY,
    registration_id INTEGER NOT NULL REFERENCES event_registration_groups(registration_id),
    roster_slot INTEGER NOT NULL,
    original_label TEXT NOT NULL,
    original_steam_id TEXT NOT NULL,
    verified_player_id INTEGER REFERENCES players(id),
    reviewed_by INTEGER NOT NULL REFERENCES admins(id),
    reviewed_at INTEGER NOT NULL,
    reason TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_formation_batches (
    event_id INTEGER PRIMARY KEY REFERENCES event_registration_control(event_id),
    formed_at INTEGER NOT NULL,
    formation_revision INTEGER NOT NULL CHECK (formation_revision >= 1)
);

CREATE TABLE IF NOT EXISTS event_entrants (
    event_entrant_id INTEGER PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES event_formation_batches(event_id),
    registration_id INTEGER NOT NULL UNIQUE REFERENCES event_registration_groups(registration_id),
    UNIQUE (event_id, event_entrant_id),
    FOREIGN KEY (event_id, registration_id) REFERENCES event_registration_groups(event_id, registration_id)
);

CREATE TABLE IF NOT EXISTS event_current_members (
    event_entrant_id INTEGER NOT NULL,
    event_id INTEGER NOT NULL,
    player_id INTEGER NOT NULL REFERENCES players(id),
    roster_slot INTEGER NOT NULL CHECK (roster_slot BETWEEN 0 AND 4),
    PRIMARY KEY (event_entrant_id, roster_slot),
    UNIQUE (event_id, player_id),
    FOREIGN KEY (event_id, player_id) REFERENCES event_signup_entries(event_id, player_id),
    FOREIGN KEY (event_id, event_entrant_id) REFERENCES event_entrants(event_id, event_entrant_id)
);

CREATE TABLE IF NOT EXISTS event_initial_rosters (
    event_entrant_id INTEGER PRIMARY KEY REFERENCES event_entrants(event_entrant_id),
    confirmed_by INTEGER NOT NULL REFERENCES admins(id),
    confirmed_at INTEGER NOT NULL,
    confirmed_revision INTEGER NOT NULL CHECK (confirmed_revision > 0)
);

CREATE TABLE IF NOT EXISTS event_initial_members (
    event_entrant_id INTEGER NOT NULL REFERENCES event_initial_rosters(event_entrant_id),
    player_id INTEGER NOT NULL REFERENCES players(id),
    roster_slot INTEGER NOT NULL CHECK (roster_slot BETWEEN 0 AND 4),
    PRIMARY KEY (event_entrant_id, roster_slot),
    UNIQUE (event_entrant_id, player_id)
);

CREATE TRIGGER IF NOT EXISTS host_protect_initial_roster_update BEFORE UPDATE ON event_initial_rosters
BEGIN SELECT RAISE(ABORT, '初始名单已冻结'); END;
CREATE TRIGGER IF NOT EXISTS host_protect_initial_roster_delete BEFORE DELETE ON event_initial_rosters
BEGIN SELECT RAISE(ABORT, '初始名单已冻结'); END;
CREATE TRIGGER IF NOT EXISTS host_protect_initial_member_update BEFORE UPDATE ON event_initial_members
BEGIN SELECT RAISE(ABORT, '初始五人已冻结'); END;
CREATE TRIGGER IF NOT EXISTS host_protect_initial_member_delete BEFORE DELETE ON event_initial_members
BEGIN SELECT RAISE(ABORT, '初始五人已冻结'); END;

CREATE TABLE IF NOT EXISTS event_reserve_candidates (
    event_id INTEGER NOT NULL REFERENCES event_formation_batches(event_id),
    player_id INTEGER NOT NULL REFERENCES players(id),
    assigned_entrant_id INTEGER,
    withdrawn_at INTEGER,
    PRIMARY KEY (event_id, player_id),
    CHECK (withdrawn_at IS NULL OR assigned_entrant_id IS NULL),
    FOREIGN KEY (event_id, player_id) REFERENCES event_signup_entries(event_id, player_id),
    FOREIGN KEY (event_id, assigned_entrant_id) REFERENCES event_entrants(event_id, event_entrant_id)
);

CREATE TABLE IF NOT EXISTS event_formation_actions (
    formation_action_id INTEGER PRIMARY KEY,
    event_entrant_id INTEGER NOT NULL REFERENCES event_entrants(event_entrant_id),
    action_kind TEXT NOT NULL CHECK (action_kind IN ('adjust','assign_reserve','replace')),
    admin_id INTEGER NOT NULL REFERENCES admins(id),
    changed_at INTEGER NOT NULL,
    reason TEXT NOT NULL,
    before_json TEXT NOT NULL,
    after_json TEXT NOT NULL
);

CREATE TABLE event_formation_inputs (
    event_id INTEGER NOT NULL REFERENCES event_formation_batches(event_id),
    player_id INTEGER NOT NULL,
    minutes INTEGER,
    playtime_status TEXT NOT NULL,
    checked_at TEXT,
    PRIMARY KEY(event_id,player_id),
    FOREIGN KEY(event_id,player_id) REFERENCES event_signup_entries(event_id,player_id)
);
CREATE TRIGGER IF NOT EXISTS host_mark_first_signup AFTER INSERT ON event_signup_entries
BEGIN UPDATE event_registration_control SET first_write_at=NEW.created_at
      WHERE event_id=NEW.event_id AND first_write_at IS NULL; END;
CREATE TRIGGER IF NOT EXISTS host_mark_first_formation AFTER INSERT ON event_formation_batches
BEGIN UPDATE event_registration_control SET first_write_at=NEW.formed_at
      WHERE event_id=NEW.event_id AND first_write_at IS NULL; END;
