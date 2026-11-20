CREATE TABLE IF NOT EXISTS managed_event_champions (
    event_id INTEGER PRIMARY KEY REFERENCES event_registration_control(event_id),
    event_entrant_id INTEGER NOT NULL,
    match_id INTEGER NOT NULL,
    match_participant_id INTEGER NOT NULL,
    settlement_id INTEGER NOT NULL REFERENCES series_settlements(settlement_id),
    official_map_result_id INTEGER NOT NULL REFERENCES official_map_results(official_map_result_id),
    club_id INTEGER REFERENCES teams(id),
    team_name TEXT NOT NULL,
    team_short_name TEXT NOT NULL,
    team_logo TEXT NOT NULL,
    awarded_by INTEGER NOT NULL REFERENCES admins(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (event_id,event_entrant_id) REFERENCES event_entrants(event_id,event_entrant_id),
    FOREIGN KEY (event_id,match_id) REFERENCES matches(event_id,id),
    FOREIGN KEY (match_id,match_participant_id) REFERENCES match_participants(match_id,match_participant_id)
);

CREATE TABLE IF NOT EXISTS managed_event_champion_players (
    event_id INTEGER NOT NULL REFERENCES managed_event_champions(event_id),
    player_id INTEGER NOT NULL REFERENCES players(id),
    roster_slot INTEGER NOT NULL CHECK (roster_slot BETWEEN 1 AND 5),
    nickname TEXT NOT NULL,
    participation_id INTEGER NOT NULL,
    participation_revision INTEGER NOT NULL,
    PRIMARY KEY (event_id,player_id),
    UNIQUE (event_id,roster_slot),
    FOREIGN KEY (participation_id,participation_revision) REFERENCES participation_decisions(participation_id,revision)
);

CREATE INDEX IF NOT EXISTS managed_championships_by_player ON managed_event_champion_players(player_id);
