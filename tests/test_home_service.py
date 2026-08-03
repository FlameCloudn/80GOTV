import os
import tempfile
import unittest
from datetime import date, timedelta

from config import Config
from models import get_db, init_tables
from services.home_service import load_home_feed


class HomeServiceTests(unittest.TestCase):
    def setUp(self):
        handle, self.database_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.original_database = Config.DATABASE
        Config.DATABASE = self.database_path
        init_tables()
        self.conn = get_db()
        self.day = date.today() + timedelta(days=1)

        self.conn.execute("INSERT INTO teams(name, short_name) VALUES('Alpha', 'ALP')")
        self.team1_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.conn.execute("INSERT INTO teams(name, short_name) VALUES('Bravo', 'BRV')")
        self.team2_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.conn.execute("INSERT INTO events(name, status) VALUES('Test Event', 'ongoing')")
        self.event_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.owner_id = self.conn.execute(
            "INSERT INTO users(username, password_hash) VALUES('forum-owner', 'unused')"
        ).lastrowid
        self.category_id = self.conn.execute(
            "SELECT id FROM forum_categories ORDER BY sort_order, id LIMIT 1"
        ).fetchone()["id"]

    def tearDown(self):
        self.conn.close()
        Config.DATABASE = self.original_database
        try:
            os.remove(self.database_path)
        except OSError:
            pass

    def _add_match(self, hour, status, day=None):
        match_day = day or self.day
        cursor = self.conn.execute(
            """INSERT INTO matches(
                   event_id, team1_id, team2_id, match_time, status, map1
               ) VALUES(?, ?, ?, ?, ?, 'de_mirage')""",
            (
                self.event_id,
                self.team1_id,
                self.team2_id,
                f"{match_day.isoformat()}T{hour:02d}:00:00",
                status,
            ),
        )
        return cursor.lastrowid

    def test_feed_keeps_home_queries_in_one_ordered_result(self):
        live_id = self._add_match(9, "live")
        early_id = self._add_match(10, "upcoming")
        late_id = self._add_match(12, "upcoming")
        self._add_match(8, "upcoming", self.day + timedelta(days=1))
        self._add_match(11, "cancelled")
        older_id = self._add_match(8, "completed", self.day - timedelta(days=2))
        newer_id = self._add_match(8, "completed", self.day - timedelta(days=1))

        for index in range(13):
            self.conn.execute(
                "INSERT INTO news(title, publish_time) VALUES(?, ?)",
                (f"News {index:02d}", f"{self.day.isoformat()}T{index:02d}:00:00"),
            )

        for index, rating in enumerate((1.01, 1.02, 1.03, 1.04, 1.05, 1.06), start=1):
            cursor = self.conn.execute(
                "INSERT INTO players(nickname, team_id) VALUES(?, ?)",
                (f"Player {index}", self.team1_id),
            )
            self.conn.execute(
                """INSERT INTO player_performance_summary(player_id, maps, avg_rating)
                   VALUES(?, 3, ?)""",
                (cursor.lastrowid, rating),
            )
        older_thread_id = self.conn.execute(
            """INSERT INTO forum_threads(
                   category_id, user_id, title, content, last_reply_at
               ) VALUES(?, ?, 'Older thread', 'Body', '2026-07-20T10:00:00')""",
            (self.category_id, self.owner_id),
        ).lastrowid
        newer_thread_id = self.conn.execute(
            """INSERT INTO forum_threads(
                   category_id, user_id, title, content, reply_count, last_reply_at
               ) VALUES(?, ?, 'Newer thread', 'Body', 3, '2026-07-21T10:00:00')""",
            (self.category_id, self.owner_id),
        ).lastrowid
        self.conn.commit()

        feed = load_home_feed(self.conn, today=self.day)

        self.assertEqual([row["id"] for row in feed["matches"]], [live_id, early_id, late_id])
        self.assertEqual([row["id"] for row in feed["recent"]], [newer_id, older_id])
        self.assertEqual(len(feed["news"]), 12)
        self.assertEqual(feed["news"][0]["title"], "News 12")
        self.assertEqual(
            [row["nickname"] for row in feed["top_players"]],
            [
                "Player 6",
                "Player 5",
                "Player 4",
                "Player 3",
                "Player 2",
            ],
        )
        self.assertTrue(all(row["team"] == "ALP" for row in feed["top_players"]))
        self.assertEqual(
            [row["id"] for row in feed["forum_activity"]],
            [newer_thread_id, older_thread_id],
        )
        self.assertEqual(
            [row["reply_count"] for row in feed["forum_activity"]],
            [3, 0],
        )


if __name__ == "__main__":
    unittest.main()
