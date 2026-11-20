-- Old signup writers and delayed repair scripts may still know the physical legacy table names.
CREATE TRIGGER host_refuse_legacy_individual_insert BEFORE INSERT ON event_individual_registrations
WHEN EXISTS (SELECT 1 FROM event_registration_control WHERE event_id=NEW.event_id)
BEGIN SELECT RAISE(ABORT,'托管赛事不写旧个人报名表'); END;
CREATE TRIGGER host_refuse_legacy_individual_update BEFORE UPDATE ON event_individual_registrations
WHEN EXISTS (SELECT 1 FROM event_registration_control WHERE event_id IN(NEW.event_id,OLD.event_id))
BEGIN SELECT RAISE(ABORT,'托管赛事不写旧个人报名表'); END;
CREATE TRIGGER host_refuse_legacy_slot_insert BEFORE INSERT ON event_registration_slots
WHEN EXISTS (SELECT 1 FROM event_registrations r JOIN event_registration_control c USING(event_id)
             WHERE r.id=NEW.registration_id)
BEGIN SELECT RAISE(ABORT,'托管赛事不写旧报名槽'); END;
CREATE TRIGGER host_refuse_legacy_slot_update BEFORE UPDATE ON event_registration_slots
WHEN EXISTS (SELECT 1 FROM event_registrations r JOIN event_registration_control c USING(event_id)
             WHERE r.id IN(NEW.registration_id,OLD.registration_id))
BEGIN SELECT RAISE(ABORT,'托管赛事不写旧报名槽'); END;

-- Historic side/impact and Demo repair tools can target match_stats by stat ID, bypassing a route.
CREATE TRIGGER host_refuse_legacy_stats_insert BEFORE INSERT ON match_stats
WHEN EXISTS (SELECT 1 FROM matches m JOIN event_registration_control c ON c.event_id=m.event_id
             WHERE m.id=NEW.match_id)
BEGIN SELECT RAISE(ABORT,'托管赛事尚未开放实战统计'); END;
CREATE TRIGGER host_refuse_legacy_stats_update BEFORE UPDATE ON match_stats
WHEN EXISTS (SELECT 1 FROM matches m JOIN event_registration_control c ON c.event_id=m.event_id
             WHERE m.id IN(OLD.match_id,NEW.match_id))
BEGIN SELECT RAISE(ABORT,'托管赛事尚未开放实战统计'); END;
