CREATE TABLE IF NOT EXISTS scheduled_maps (
    scheduled_map_id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    map_order INTEGER NOT NULL CHECK (map_order BETWEEN 1 AND 5),
    legacy_slot INTEGER NOT NULL CHECK (legacy_slot BETWEEN 1 AND 5),
    is_enabled INTEGER NOT NULL CHECK (is_enabled IN (0, 1)),
    map_name TEXT,
    picked_by_match_participant_id INTEGER,
    is_decider INTEGER NOT NULL CHECK (is_decider IN (0, 1)),
    side_choice_match_participant_id INTEGER,
    starting_side TEXT CHECK (starting_side IN ('CT', 'T')),
    UNIQUE (match_id, map_order),
    UNIQUE (match_id, legacy_slot),
    FOREIGN KEY (match_id, picked_by_match_participant_id)
        REFERENCES match_participants(match_id, match_participant_id),
    FOREIGN KEY (match_id, side_choice_match_participant_id)
        REFERENCES match_participants(match_id, match_participant_id),
    CHECK (is_decider = 0 OR picked_by_match_participant_id IS NULL),
    CHECK ((side_choice_match_participant_id IS NULL) = (starting_side IS NULL))
);

-- Only a reset needs a floor: the active revision itself lives in matches.bp_state.
CREATE TABLE IF NOT EXISTS match_bp_resets (
    match_id INTEGER PRIMARY KEY REFERENCES matches(id) ON DELETE CASCADE,
    minimum_revision INTEGER NOT NULL CHECK (minimum_revision > 0)
);
