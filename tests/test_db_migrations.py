import os
import tempfile
import unittest
from unittest.mock import patch

from config import Config
from models import CURRENT_SCHEMA_VERSION, get_db, init_tables


class DatabaseMigrationTests(unittest.TestCase):
    def setUp(self):
        handle, self.database_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.original_database = Config.DATABASE
        Config.DATABASE = self.database_path

    def tearDown(self):
        Config.DATABASE = self.original_database
        try:
            os.remove(self.database_path)
        except OSError:
            pass

    def test_schema_version_is_recorded_and_heavy_work_is_not_repeated(self):
        init_tables()
        conn = get_db()
        row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        conn.close()
        self.assertEqual(row[0], CURRENT_SCHEMA_VERSION)

        with patch("services.performance_service.refresh_player_performance") as refresh:
            init_tables()
            refresh.assert_not_called()

    def test_failed_migration_rolls_back_schema_and_version(self):
        with patch(
            "services.performance_service.refresh_player_performance",
            side_effect=RuntimeError("forced migration failure"),
        ):
            with self.assertRaises(RuntimeError):
                init_tables()

        conn = get_db()
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        conn.close()
        self.assertNotIn("schema_migrations", tables)
        self.assertNotIn("users", tables)

    def test_database_from_newer_code_is_rejected(self):
        conn = get_db()
        conn.execute(
            """CREATE TABLE schema_migrations(
                   version INTEGER PRIMARY KEY,
                   name TEXT NOT NULL,
                   applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
               )"""
        )
        conn.execute(
            "INSERT INTO schema_migrations(version, name) VALUES(?, ?)",
            (CURRENT_SCHEMA_VERSION + 1, "future"),
        )
        conn.commit()
        conn.close()

        with self.assertRaisesRegex(RuntimeError, "数据库版本高于当前代码"):
            init_tables()

        conn = get_db()
        version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        conn.close()
        self.assertEqual(version, CURRENT_SCHEMA_VERSION + 1)

    def test_version_one_database_receives_full_feature_schema(self):
        conn = get_db()
        conn.executescript(
            """
            CREATE TABLE schema_migrations(
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO schema_migrations(version, name)
            VALUES(1, 'legacy_schema_baseline');
            CREATE TABLE players(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nickname TEXT NOT NULL,
                real_name TEXT,
                team_id INTEGER,
                steam_id TEXT,
                avatar TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.commit()
        conn.close()

        init_tables()

        conn = get_db()
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        versions = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
        registration_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(event_registrations)")
        }
        player_columns = {row[1] for row in conn.execute("PRAGMA table_info(players)")}
        conn.close()

        self.assertIn(CURRENT_SCHEMA_VERSION, versions)
        self.assertTrue(
            {
                "guess_players",
                "event_individual_registrations",
                "player_performance_summary",
                "yearly_top_players",
            }.issubset(tables)
        )
        self.assertIn("team_logo", registration_columns)
        self.assertIn("group_username_override", player_columns)

    def test_explicitly_approved_placeholder_is_not_reclassified_on_startup(self):
        init_tables()
        conn = get_db()
        conn.execute(
            """INSERT INTO users(
                   username, password_hash, is_placeholder, approval_status
               ) VALUES('DemoPlaceholder', 'unused', 1, 'approved')"""
        )
        conn.commit()
        conn.close()

        init_tables()

        conn = get_db()
        status = conn.execute(
            "SELECT approval_status FROM users WHERE username='DemoPlaceholder'"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(status, "approved")

    def test_current_database_gets_playtime_cache_columns(self):
        conn = get_db()
        conn.executescript(
            """
            CREATE TABLE schema_migrations(
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE admins(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            );
            CREATE TABLE event_individual_registrations(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                player_name TEXT NOT NULL,
                steam_id TEXT NOT NULL,
                assignment_status TEXT NOT NULL DEFAULT 'pending',
                team_number INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                assigned_at TEXT
            );
            CREATE TABLE players(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nickname TEXT NOT NULL,
                steam_id TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO schema_migrations(version, name) VALUES(?, ?)",
            (CURRENT_SCHEMA_VERSION, "legacy_schema_baseline"),
        )
        conn.commit()
        conn.close()

        init_tables()

        conn = get_db()
        registration_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(event_individual_registrations)").fetchall()
        }
        player_columns = {row[1] for row in conn.execute("PRAGMA table_info(players)").fetchall()}
        conn.close()
        playtime_columns = {
            "cs2_playtime_minutes",
            "playtime_status",
            "playtime_checked_at",
        }
        self.assertTrue(
            (playtime_columns | {"preferred_registration_id"}).issubset(registration_columns)
        )
        self.assertTrue((playtime_columns | {"group_username_override"}).issubset(player_columns))

    def test_current_database_gets_match_test_mode_column(self):
        conn = get_db()
        conn.executescript(
            """
            CREATE TABLE schema_migrations(
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE admins(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            );
            CREATE TABLE matches(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER,
                match_time TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO schema_migrations(version, name) VALUES(?, ?)",
            (CURRENT_SCHEMA_VERSION, "legacy_schema_baseline"),
        )
        conn.commit()
        conn.close()

        init_tables()

        conn = get_db()
        columns = {row[1]: row for row in conn.execute("PRAGMA table_info(matches)").fetchall()}
        conn.close()
        self.assertIn("is_test_mode", columns)
        self.assertEqual(columns["is_test_mode"][4], "0")

    def test_current_database_gets_match_decider_columns(self):
        conn = get_db()
        conn.executescript(
            """
            CREATE TABLE schema_migrations(
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE admins(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            );
            CREATE TABLE matches(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER,
                match_time TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO schema_migrations(version, name) VALUES(?, ?)",
            (CURRENT_SCHEMA_VERSION, "current_without_decider_fields"),
        )
        conn.commit()
        conn.close()

        init_tables()

        conn = get_db()
        columns = {row[1] for row in conn.execute("PRAGMA table_info(matches)").fetchall()}
        conn.close()
        self.assertIn("decider_knife_winner", columns)
        self.assertIn("decider_start_side", columns)

    def test_current_database_gets_match_stats_team_side_column(self):
        conn = get_db()
        conn.executescript(
            """
            CREATE TABLE schema_migrations(
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE admins(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            );
            CREATE TABLE match_stats(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id INTEGER,
                player_id INTEGER,
                team_id INTEGER
            );
            """
        )
        conn.execute(
            "INSERT INTO schema_migrations(version, name) VALUES(?, ?)",
            (CURRENT_SCHEMA_VERSION, "current_without_match_team_side"),
        )
        conn.commit()
        conn.close()

        init_tables()

        conn = get_db()
        columns = {row[1] for row in conn.execute("PRAGMA table_info(match_stats)").fetchall()}
        conn.close()
        self.assertIn("match_team_side", columns)

    def test_current_database_gets_school_profile_columns(self):
        conn = get_db()
        conn.executescript(
            """
            CREATE TABLE schema_migrations(
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE admins(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            );
            CREATE TABLE users(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            );
            CREATE TABLE players(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nickname TEXT NOT NULL,
                steam_id TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO schema_migrations(version, name) VALUES(?, ?)",
            (CURRENT_SCHEMA_VERSION, "current_without_school_profile"),
        )
        conn.commit()
        conn.close()

        init_tables()

        conn = get_db()
        user_columns = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        player_columns = {row[1] for row in conn.execute("PRAGMA table_info(players)").fetchall()}
        conn.close()
        self.assertIn("is_bashizhong_student", user_columns)
        self.assertIn("is_bashizhong_student", player_columns)

    def test_current_database_gets_yearly_top10_table(self):
        conn = get_db()
        conn.executescript(
            """
            CREATE TABLE schema_migrations(
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE admins(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            );
            CREATE TABLE players(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nickname TEXT NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT INTO schema_migrations(version, name) VALUES(?, ?)",
            (CURRENT_SCHEMA_VERSION, "current_without_yearly_top10"),
        )
        conn.commit()
        conn.close()

        init_tables()

        conn = get_db()
        columns = {row[1] for row in conn.execute("PRAGMA table_info(yearly_top_players)")}
        conn.close()
        self.assertTrue({"year", "rank", "player_id", "decided_by"}.issubset(columns))


if __name__ == "__main__":
    unittest.main()
