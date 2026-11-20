-- Named, read-only projections. They never shadow the legacy tables or store their rows.
CREATE VIEW host_registration_slots_read AS
WITH positions(roster_slot) AS (VALUES(0),(1),(2),(3),(4))
SELECT g.event_id,g.registration_id,n.roster_slot AS slot_index,
       COALESCE(active.player_id,signup.player_id) AS player_id,
       COALESCE(current_entry.account_id,signup.account_id) AS user_id,
       COALESCE(p.nickname,held.display_label,'位置'||(n.roster_slot+1)) AS player_name,
       COALESCE(p.steam_id,held.steam_id,'') AS steam_id,
       held.roster_slot IS NOT NULL AS filled_by_creator,
       u.username AS user_username,
       CASE WHEN COALESCE(p.is_bashizhong_student,u.is_bashizhong_student,1)<>0
            THEN COALESCE(NULLIF(p.group_username_override,''),u.group_username,'') ELSE '' END AS group_username,
       COALESCE(NULLIF(p.avatar,''),u.avatar,'') AS avatar,
       COALESCE(p.is_bashizhong_student,u.is_bashizhong_student) AS is_bashizhong_student
FROM event_registration_groups g CROSS JOIN positions n
LEFT JOIN event_entrants e ON e.registration_id=g.registration_id
LEFT JOIN event_current_members active ON active.event_entrant_id=e.event_entrant_id AND active.roster_slot=n.roster_slot
LEFT JOIN event_signup_entries current_entry ON current_entry.event_id=g.event_id AND current_entry.player_id=active.player_id
LEFT JOIN event_signup_entries signup ON e.event_entrant_id IS NULL AND signup.registration_id=g.registration_id AND signup.roster_slot=n.roster_slot
LEFT JOIN event_signup_reservations held ON e.event_entrant_id IS NULL AND held.registration_id=g.registration_id AND held.roster_slot=n.roster_slot
LEFT JOIN players p ON p.id=COALESCE(active.player_id,signup.player_id)
LEFT JOIN users u ON u.id=COALESCE(current_entry.account_id,signup.account_id);

CREATE VIEW host_individual_entries_read AS
SELECT s.registration_entry_id AS id,s.event_id,s.account_id AS user_id,s.player_id,
       p.nickname AS player_name,p.steam_id,u.username AS website_name,
       CASE WHEN COALESCE(p.is_bashizhong_student,u.is_bashizhong_student,1)<>0
            THEN COALESCE(NULLIF(p.group_username_override,''),u.group_username,'') ELSE '' END AS group_username,
       COALESCE(NULLIF(p.avatar,''),u.avatar,'') AS avatar,
       COALESCE(p.is_bashizhong_student,u.is_bashizhong_student) AS is_bashizhong_student,
       CASE WHEN active.player_id IS NOT NULL THEN 'assigned'
            WHEN s.registration_origin='independent_reserve' OR candidate.player_id IS NOT NULL THEN 'reserve'
            ELSE 'pending' END AS assignment_status,
       e.registration_id AS team_number,active.player_id IS NOT NULL AS is_formal_member,
       datetime(s.created_at,'unixepoch') AS created_at,
       datetime(CASE WHEN active.player_id IS NOT NULL THEN max(b.formed_at,s.created_at)
                     WHEN s.registration_origin='independent_reserve' THEN s.created_at
                     WHEN candidate.player_id IS NOT NULL THEN b.formed_at END,'unixepoch') AS assigned_at,
       p.cs2_playtime_minutes,p.playtime_status,p.playtime_checked_at,s.preferred_registration_id,
       pref.team_name AS preferred_team_name
FROM event_signup_entries s
JOIN players p ON p.id=s.player_id JOIN users u ON u.id=s.account_id
LEFT JOIN event_reserve_candidates candidate ON candidate.event_id=s.event_id AND candidate.player_id=s.player_id
LEFT JOIN event_current_members active ON active.event_id=s.event_id AND active.player_id=s.player_id
LEFT JOIN event_entrants e ON e.event_entrant_id=active.event_entrant_id
LEFT JOIN event_formation_batches b ON b.event_id=s.event_id
LEFT JOIN event_registrations pref ON pref.event_id=s.event_id AND pref.id=s.preferred_registration_id
WHERE (s.registration_origin<>'group' OR candidate.player_id IS NOT NULL)
  AND (b.event_id IS NULL OR active.player_id IS NOT NULL OR candidate.player_id IS NOT NULL)
  AND (candidate.withdrawn_at IS NULL OR active.player_id IS NOT NULL);
