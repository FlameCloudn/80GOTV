CREATE TABLE official_map_results (
    official_map_result_id INTEGER PRIMARY KEY,
    scheduled_map_id INTEGER NOT NULL,
    map_run_id INTEGER NOT NULL,
    score1 INTEGER NOT NULL CHECK (score1 BETWEEN 0 AND 100),
    score2 INTEGER NOT NULL CHECK (score2 BETWEEN 0 AND 100 AND score1 <> score2),
    revision INTEGER NOT NULL CHECK (revision > 0),
    is_current INTEGER NOT NULL CHECK (is_current IN (0,1)),
    actor NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('admin','director')),
    terminal_receipt TEXT,
    reason TEXT NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_by INTEGER REFERENCES admins(id),
    revoke_reason TEXT,
    revoked_at TEXT,
    UNIQUE (scheduled_map_id,revision),
    CHECK (source <> 'director' OR (terminal_receipt IS NOT NULL AND length(trim(terminal_receipt)) > 0)),
    FOREIGN KEY (scheduled_map_id,map_run_id) REFERENCES map_runs(scheduled_map_id,map_run_id)
);
CREATE UNIQUE INDEX one_current_map_result ON official_map_results(scheduled_map_id) WHERE is_current=1;

-- 未决图不创建正式系列结果。主动撤结算也留一版，保留当时所依据的各图裁定。
CREATE TABLE series_settlements (
    settlement_id INTEGER PRIMARY KEY,
    match_id INTEGER NOT NULL REFERENCES matches(id),
    revision INTEGER NOT NULL,
    previous_revision INTEGER NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('settled','reopened')),
    score1 INTEGER NOT NULL,
    score2 INTEGER NOT NULL,
    home_participant_id INTEGER NOT NULL,
    away_participant_id INTEGER NOT NULL,
    map_result_ids TEXT NOT NULL,
    actor INTEGER NOT NULL REFERENCES admins(id),
    reason TEXT NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (match_id,revision),
    FOREIGN KEY (match_id,home_participant_id) REFERENCES match_participants(match_id,match_participant_id),
    FOREIGN KEY (match_id,away_participant_id) REFERENCES match_participants(match_id,match_participant_id)
);
CREATE TABLE prediction_settlement_changes (
    settlement_id INTEGER NOT NULL REFERENCES series_settlements(settlement_id),
    vote_id INTEGER NOT NULL REFERENCES match_votes(id),
    old_points INTEGER NOT NULL,
    new_points INTEGER NOT NULL,
    old_scored INTEGER NOT NULL,
    new_scored INTEGER NOT NULL,
    PRIMARY KEY (settlement_id,vote_id)
);

CREATE TABLE managed_bracket_links (
    event_id INTEGER NOT NULL,
    source_match_id INTEGER NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('winner','loser')),
    target_match_id INTEGER NOT NULL,
    target_side TEXT NOT NULL CHECK (target_side IN ('home','away')),
    configured_by INTEGER NOT NULL REFERENCES admins(id),
    PRIMARY KEY (source_match_id,outcome),
    UNIQUE (target_match_id,target_side),
    CHECK (source_match_id <> target_match_id),
    FOREIGN KEY (event_id,source_match_id) REFERENCES matches(event_id,id),
    FOREIGN KEY (event_id,target_match_id) REFERENCES matches(event_id,id)
);
CREATE TABLE bracket_settlement_changes (
    settlement_id INTEGER NOT NULL REFERENCES series_settlements(settlement_id),
    target_match_id INTEGER NOT NULL REFERENCES matches(id),
    target_side TEXT NOT NULL,
    old_entrant_id INTEGER REFERENCES event_entrants(event_entrant_id),
    new_entrant_id INTEGER REFERENCES event_entrants(event_entrant_id),
    old_participant_id INTEGER,
    new_participant_id INTEGER,
    PRIMARY KEY (settlement_id,target_match_id,target_side)
);

-- 一条例外即脱离该条自动线路的依据；签表不另存一个可能与裁定不一致的开关。
CREATE TABLE bracket_retention_decisions (
    settlement_id INTEGER NOT NULL REFERENCES series_settlements(settlement_id),
    source_match_id INTEGER NOT NULL,
    outcome TEXT NOT NULL,
    target_match_id INTEGER NOT NULL,
    target_side TEXT NOT NULL,
    retained_participant_id INTEGER NOT NULL,
    retained_entrant_id INTEGER NOT NULL REFERENCES event_entrants(event_entrant_id),
    proposed_entrant_id INTEGER REFERENCES event_entrants(event_entrant_id),
    PRIMARY KEY (source_match_id,outcome),
    CHECK (retained_entrant_id IS NOT proposed_entrant_id),
    FOREIGN KEY (source_match_id,outcome) REFERENCES managed_bracket_links(source_match_id,outcome),
    FOREIGN KEY (target_match_id,target_side) REFERENCES managed_bracket_links(target_match_id,target_side),
    FOREIGN KEY (target_match_id,retained_participant_id) REFERENCES match_participants(match_id,match_participant_id)
);
