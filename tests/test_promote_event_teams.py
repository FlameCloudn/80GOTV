import sqlite3
import tempfile
import unittest
from pathlib import Path

from werkzeug.security import check_password_hash

from scripts.promote_event_teams import promote_event_teams

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE teams(id INTEGER PRIMARY KEY, name TEXT, short_name TEXT, logo TEXT, description TEXT, created_at TEXT);
CREATE TABLE players(id INTEGER PRIMARY KEY, nickname TEXT, team_id INTEGER REFERENCES teams(id), steam_id TEXT);
ALTER TABLE players ADD COLUMN real_name TEXT;
ALTER TABLE players ADD COLUMN group_username_override TEXT;
ALTER TABLE players ADD COLUMN is_bashizhong_student INTEGER;
ALTER TABLE players ADD COLUMN avatar TEXT;
CREATE TABLE users(
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE,
    password_hash TEXT,
    group_username TEXT,
    avatar TEXT,
    is_bashizhong_student INTEGER,
    steam_id64 TEXT,
    is_placeholder INTEGER DEFAULT 0,
    approval_status TEXT,
    approved_at TEXT
);
CREATE TABLE events(id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE event_registrations(id INTEGER PRIMARY KEY, event_id INTEGER, team_name TEXT, team_logo TEXT, creator_user_id INTEGER, status TEXT, created_at TEXT);
CREATE TABLE event_registration_slots(id INTEGER PRIMARY KEY, registration_id INTEGER, slot_index INTEGER, player_name TEXT, steam_id TEXT);
"""


class PromoteEventTeamsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "site.db"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.executescript(SCHEMA)
        self.conn.execute("INSERT INTO teams VALUES(1, '星辰电竞社', 'STAR', NULL, '', '')")
        self.conn.execute("INSERT INTO events VALUES(5, '2026 Summer 80 Major')")
        self.conn.execute(
            "INSERT INTO event_registrations VALUES(3, 5, 'Team 2BMAX', 'badge.png', 1, 'pending', '')"
        )
        self.conn.execute(
            """
            INSERT INTO players(id, nickname, team_id, steam_id)
            VALUES(20, 'Evang3l', NULL, 'steam-20')
            """
        )
        self.conn.execute(
            "INSERT INTO event_registration_slots VALUES(1, 3, 0, 'Evang3l', 'steam-20')"
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def test_apply_promotes_team_assigns_player_and_removes_unused_seed(self):
        result = promote_event_teams(self.conn, 5, remove_test_teams=True, apply=True)
        team = self.conn.execute(
            "SELECT id, short_name, logo FROM teams WHERE name='Team 2BMAX'"
        ).fetchone()
        self.assertEqual(team[1], "T2")
        self.assertEqual(team[2], "team_logos/badge.png")
        self.assertEqual(
            self.conn.execute("SELECT team_id FROM players WHERE id=20").fetchone()[0],
            team[0],
        )
        self.assertEqual(result["deleted_test_teams"], ["星辰电竞社"])

    def test_dry_run_leaves_database_unchanged(self):
        promote_event_teams(self.conn, 5, remove_test_teams=True, apply=False)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0], 1)
        self.assertIsNone(
            self.conn.execute("SELECT team_id FROM players WHERE id=20").fetchone()[0]
        )

    def test_missing_player_is_created_from_reserved_slot_steam_id(self):
        self.conn.execute(
            "INSERT INTO event_registration_slots VALUES(2, 3, 1, 'Nightmire@Nightmire', 'steam-nightmire')"
        )
        self.conn.commit()
        result = promote_event_teams(
            self.conn,
            5,
            apply=True,
            create_missing_accounts=True,
            initial_password="123456",
        )
        player = self.conn.execute(
            """
            SELECT nickname, group_username_override, team_id
            FROM players WHERE steam_id='steam-nightmire'
            """
        ).fetchone()
        self.assertEqual(player[0], "Nightmire")
        self.assertEqual(player[1], "")
        self.assertIsNotNone(player[2])
        self.assertEqual(len(result["created_players"]), 1)
        account = self.conn.execute(
            """
            SELECT username, password_hash, group_username, approval_status
            FROM users WHERE steam_id64='steam-nightmire'
            """
        ).fetchone()
        self.assertEqual(account[0], "Nightmire")
        self.assertTrue(check_password_hash(account[1], "123456"))
        self.assertIsNone(account[2])
        self.assertEqual(account[3], "approved")
        self.assertEqual(len(result["created_accounts"]), 1)

    def test_referenced_seed_team_aborts_without_partial_changes(self):
        self.conn.execute("UPDATE players SET team_id=1 WHERE id=20")
        self.conn.commit()
        with self.assertRaises(RuntimeError):
            promote_event_teams(self.conn, 5, remove_test_teams=True, apply=True)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
