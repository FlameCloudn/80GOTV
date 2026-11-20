CREATE TABLE match_start_authorizations (
    match_id INTEGER PRIMARY KEY REFERENCES matches(id),
    admin_id INTEGER NOT NULL REFERENCES admins(id),
    authorized_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE map_runs (
    map_run_id INTEGER PRIMARY KEY,
    scheduled_map_id INTEGER NOT NULL REFERENCES scheduled_maps(scheduled_map_id),
    attempt_no INTEGER NOT NULL CHECK (attempt_no > 0),
    previous_map_run_id INTEGER,
    status TEXT NOT NULL CHECK (status IN ('active','closed','void')),
    source TEXT NOT NULL,
    start_evidence TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (scheduled_map_id, attempt_no),
    UNIQUE (scheduled_map_id, map_run_id),
    FOREIGN KEY (scheduled_map_id,previous_map_run_id) REFERENCES map_runs(scheduled_map_id,map_run_id)
);
CREATE UNIQUE INDEX single_valid_run_per_map ON map_runs(scheduled_map_id) WHERE status <> 'void';

-- 授权名单是开局时的快照，不表示名单上的人已经出场。
CREATE TABLE map_run_lineups (
    map_run_id INTEGER NOT NULL REFERENCES map_runs(map_run_id),
    player_id INTEGER NOT NULL REFERENCES players(id),
    match_participant_id INTEGER NOT NULL REFERENCES match_participants(match_participant_id),
    roster_slot INTEGER NOT NULL CHECK (roster_slot BETWEEN 1 AND 5),
    steam_id TEXT NOT NULL,
    PRIMARY KEY (map_run_id,player_id),
    UNIQUE (map_run_id,match_participant_id,roster_slot),
    UNIQUE (map_run_id,player_id,match_participant_id)
);
CREATE TABLE technical_replays (
    map_run_id INTEGER PRIMARY KEY REFERENCES map_runs(map_run_id),
    admin_id INTEGER NOT NULL REFERENCES admins(id),
    reason TEXT NOT NULL,
    approved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    match_participant_id INTEGER,
    outgoing_player_id INTEGER,
    incoming_player_id INTEGER REFERENCES players(id),
    incoming_steam_id TEXT,
    CHECK ((match_participant_id IS NULL) = (outgoing_player_id IS NULL)
       AND (outgoing_player_id IS NULL) = (incoming_player_id IS NULL)
       AND (incoming_player_id IS NULL) = (incoming_steam_id IS NULL)),
    FOREIGN KEY (map_run_id,outgoing_player_id,match_participant_id)
        REFERENCES map_run_lineups(map_run_id,player_id,match_participant_id)
);
CREATE TABLE map_run_rounds (
    map_run_id INTEGER NOT NULL REFERENCES map_runs(map_run_id),
    round_number INTEGER NOT NULL CHECK (round_number > 0),
    winner_side TEXT CHECK (winner_side IN ('home','away')),
    source TEXT NOT NULL,
    PRIMARY KEY (map_run_id,round_number)
);
CREATE TABLE run_participations (
    participation_id INTEGER PRIMARY KEY,
    map_run_id INTEGER NOT NULL,
    player_id INTEGER NOT NULL,
    match_participant_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    confirmed_by INTEGER REFERENCES admins(id),
    reason TEXT,
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0,1)),
    revision INTEGER NOT NULL DEFAULT 1,
    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (map_run_id,player_id),
    UNIQUE (map_run_id,participation_id),
    FOREIGN KEY (map_run_id,player_id,match_participant_id)
        REFERENCES map_run_lineups(map_run_id,player_id,match_participant_id)
);
CREATE TABLE participation_decisions (
    participation_id INTEGER NOT NULL REFERENCES run_participations(participation_id),
    revision INTEGER NOT NULL,
    is_current INTEGER NOT NULL CHECK (is_current IN (0,1)),
    source TEXT NOT NULL,
    admin_id INTEGER REFERENCES admins(id),
    reason TEXT,
    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (participation_id,revision)
);
CREATE TABLE run_round_participations (
    map_run_id INTEGER NOT NULL,
    round_number INTEGER NOT NULL,
    participation_id INTEGER NOT NULL,
    side TEXT CHECK (side IN ('CT','T')),
    source TEXT NOT NULL,
    PRIMARY KEY (map_run_id,round_number,participation_id),
    FOREIGN KEY (map_run_id,round_number) REFERENCES map_run_rounds(map_run_id,round_number),
    FOREIGN KEY (map_run_id,participation_id) REFERENCES run_participations(map_run_id,participation_id)
);
