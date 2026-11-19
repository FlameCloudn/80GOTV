"""Schema upgrades use only synthetic pre-upgrade website data."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import models
from config import Config


class HostPrematchMigrationTests(unittest.TestCase):
    def setUp(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory(prefix="host-migrate-"))
        self.enterContext(patch.object(Config, "DATABASE", str(Path(tmp) / "old.db")))
        # Generate the old website schema without the new extension. Do not open an actual old file.
        with patch("models._add_prematch_schema"), patch("models.CURRENT_SCHEMA_VERSION", 3):
            models.init_tables()
        with closing(models.get_db()) as db:
            db.execute("UPDATE schema_migrations SET name='admin_yearly_top10_v3' WHERE version=3")
            db.execute(
                "INSERT INTO users(id,username,password_hash) VALUES(70,'旧报名人','disabled')"
            )
            db.execute("INSERT INTO events(id,name,slug) VALUES(40,'往届测试','old-fixture-event')")
            db.execute(
                "INSERT INTO event_registrations(id,event_id,team_name,creator_user_id) VALUES(80,40,'往届队',70)"
            )
            db.execute(
                "INSERT INTO matches(id,event_id,slug,team1_registration_id) VALUES(60,40,'old-fixture-match',80)"
            )
            db.commit()

    def test_narrow_upgrade_keeps_ids_links_and_unknown_history(self):
        with (
            patch("services.performance_service.refresh_player_performance") as performance,
            patch("services.champion_service.backfill_champion_members") as champions,
        ):
            models.init_tables()
            performance.assert_not_called()
            champions.assert_not_called()
        models.init_tables()
        with closing(models.get_db()) as db:
            self.assertEqual(
                list(map(tuple, db.execute("SELECT id,slug,team1_registration_id FROM matches"))),
                [(60, "old-fixture-match", 80)],
            )
            self.assertEqual(
                list(map(tuple, db.execute("SELECT id,slug FROM events"))),
                [(40, "old-fixture-event")],
            )
            self.assertEqual(
                list(
                    map(tuple, db.execute("SELECT version FROM schema_migrations ORDER BY version"))
                ),
                [(3,), (4,), (5,), (6,)],
            )
            for table in (
                "event_registration_control",
                "event_initial_members",
                "match_participants",
                "scheduled_maps",
            ):
                self.assertEqual(db.execute(f"SELECT count(*) FROM {table}").fetchone()[0], 0)
            self.assertFalse(db.execute("PRAGMA foreign_key_check").fetchall())

    def test_last_statement_failure_removes_all_new_objects_then_retry_succeeds(self):
        original = models._execute_sql_script
        with closing(models.get_db()) as db:
            old_objects = set(map(tuple, db.execute("SELECT type,name FROM sqlite_master")))

        def fail_late(conn, script):
            original(conn, script)
            if "CREATE TRIGGER host_refuse_legacy_stats_update" in script:
                conn.execute("INSERT INTO intentionally_absent_fixture_table VALUES (1)")

        with (
            patch("models._execute_sql_script", side_effect=fail_late),
            self.assertRaises(sqlite3.OperationalError),
        ):
            models.init_tables()
        with closing(models.get_db()) as db:
            self.assertEqual(
                db.execute("SELECT max(version) FROM schema_migrations").fetchone()[0], 3
            )
            self.assertEqual(
                set(map(tuple, db.execute("SELECT type,name FROM sqlite_master"))), old_objects
            )
            self.assertEqual(
                db.execute("SELECT team1_registration_id FROM matches").fetchone()[0], 80
            )
        models.init_tables()
        with closing(models.get_db()) as db:
            self.assertEqual(
                db.execute("SELECT max(version) FROM schema_migrations").fetchone()[0], 6
            )

    def test_older_v3_has_login_and_news_storage_after_one_upgrade(self):
        # Older installations were already labelled v3 before these website fields existed.
        with closing(models.get_db()) as db:
            db.execute("DROP TABLE request_rate_limits")
            db.execute("ALTER TABLE news DROP COLUMN internal_link_text")
            db.commit()
        models.init_tables()
        with closing(models.get_db()) as db:
            db.execute("INSERT INTO request_rate_limits(bucket, attempted_at, expires_at) VALUES('fixture', 0, 1)")
            self.assertEqual(db.execute("SELECT internal_link_text FROM news").fetchall(), [])
            self.assertEqual(db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 6)
