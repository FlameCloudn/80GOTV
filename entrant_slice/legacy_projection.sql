CREATE TEMP VIEW events AS
SELECT e.id, e.name, e.short_name, e.slug, e.description, e.start_date, e.end_date,
       e.format, e.status, e.stream_url, e.bracket_data,
       CASE WHEN owned.event_id IS NULL THEN e.registration_open
            WHEN owned.archived_at IS NULL AND owned.registration_deadline > unixepoch()
            THEN e.registration_open ELSE 0 END AS registration_open,
       e.created_at
FROM main.events e
LEFT JOIN main.entrant_event owned ON owned.event_id=e.id;

CREATE TEMP VIEW event_registrations AS
SELECT r.id, r.event_id, r.team_name, r.team_logo, r.creator_user_id, r.status, r.created_at
FROM main.event_registrations r
WHERE NOT EXISTS (SELECT 1 FROM main.entrant_event owned WHERE owned.event_id=r.event_id)
UNION ALL
SELECT g.registration_group_id, g.event_id, g.display_name, g.logo, g.captain_account_id,
       'pending', datetime(g.created_at, 'unixepoch')
FROM main.registration_group g;

CREATE TEMP VIEW event_registration_slots AS
WITH slot_numbers(slot_index) AS (VALUES (0), (1), (2), (3), (4))
SELECT s.id, s.registration_id, s.slot_index, s.user_id, s.player_name, s.steam_id, s.filled_by_creator
FROM main.event_registration_slots s
JOIN main.event_registrations r ON r.id=s.registration_id
WHERE NOT EXISTS (SELECT 1 FROM main.entrant_event owned WHERE owned.event_id=r.event_id)
UNION ALL
-- The large virtual row IDs keep the old negative placeholder player IDs distinct.
-- Real players still use players.id, found by the unchanged broadcast reader.
SELECT 1099511627776 + g.registration_group_id * 5 + n.slot_index,
       g.registration_group_id, n.slot_index, COALESCE(current_entry.account_id, signup.account_id),
       COALESCE(p.nickname, held.display_label, '位置' || (n.slot_index + 1)),
       COALESCE(p.steam_id, held.steam_id),
       CASE WHEN held.roster_slot IS NOT NULL AND p.id IS NULL THEN 1 ELSE 0 END
FROM main.registration_group g CROSS JOIN slot_numbers n
LEFT JOIN main.event_entrant entrant ON entrant.registration_group_id=g.registration_group_id
LEFT JOIN main.entrant_member active
  ON entrant.event_entrant_id=active.event_entrant_id AND active.roster_slot=n.slot_index
LEFT JOIN main.registration_entry current_entry
  ON current_entry.event_id=g.event_id AND current_entry.player_id=active.player_id
LEFT JOIN main.registration_entry signup
  ON entrant.event_entrant_id IS NULL AND signup.registration_group_id=g.registration_group_id
 AND signup.roster_slot=n.slot_index
LEFT JOIN main.registration_reservation held
  ON entrant.event_entrant_id IS NULL AND held.registration_group_id=g.registration_group_id
 AND held.roster_slot=n.slot_index
LEFT JOIN main.players p ON p.id=COALESCE(active.player_id, signup.player_id);

CREATE TEMP VIEW event_individual_registrations AS
SELECT r.id, r.event_id, r.user_id, r.player_name, r.steam_id, r.assignment_status, r.team_number,
       r.created_at, r.assigned_at, r.cs2_playtime_minutes, r.playtime_status, r.playtime_checked_at,
       r.preferred_registration_id
FROM main.event_individual_registrations r
WHERE NOT EXISTS (SELECT 1 FROM main.entrant_event owned WHERE owned.event_id=r.event_id)
UNION ALL
SELECT signup.registration_entry_id, signup.event_id, signup.account_id, p.nickname, p.steam_id,
       CASE WHEN active.player_id IS NOT NULL THEN 'assigned'
            WHEN signup.registration_origin='independent_reserve' OR candidate.player_id IS NOT NULL
            THEN 'reserve' ELSE 'pending' END,
       entrant.registration_group_id, datetime(signup.created_at, 'unixepoch'),
       datetime(CASE WHEN active.player_id IS NOT NULL THEN MAX(batch.formed_at, signup.created_at)
                     WHEN signup.registration_origin='independent_reserve' THEN signup.created_at
                     WHEN candidate.player_id IS NOT NULL THEN batch.formed_at END, 'unixepoch'),
       p.cs2_playtime_minutes, p.playtime_status, p.playtime_checked_at, signup.preferred_group_id
FROM main.registration_entry signup
JOIN main.players p ON p.id=signup.player_id
LEFT JOIN main.reserve_candidate candidate
  ON candidate.event_id=signup.event_id AND candidate.player_id=signup.player_id
LEFT JOIN main.entrant_member active
  ON active.event_id=signup.event_id AND active.player_id=signup.player_id
LEFT JOIN main.event_entrant entrant ON entrant.event_entrant_id=active.event_entrant_id
LEFT JOIN main.formation_batch batch ON batch.event_id=signup.event_id
WHERE (signup.registration_origin IN ('individual', 'independent_reserve') OR candidate.player_id IS NOT NULL)
  AND (batch.event_id IS NULL OR active.player_id IS NOT NULL OR candidate.player_id IS NOT NULL)
  AND (candidate.withdrawn_at IS NULL OR active.player_id IS NOT NULL);
