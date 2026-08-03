import sqlite3
import unittest
from datetime import date

from services.player_awards_service import (
    build_award_page,
    build_top10_page,
    is_80_major_event,
)


class PlayerAwardsServiceTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE players(
                id INTEGER PRIMARY KEY,
                nickname TEXT NOT NULL,
                avatar TEXT
            );
            CREATE TABLE events(
                id INTEGER PRIMARY KEY,
                name TEXT,
                short_name TEXT,
                slug TEXT,
                start_date TEXT
            );
            CREATE TABLE player_medals(
                id INTEGER PRIMARY KEY,
                player_id INTEGER,
                type TEXT,
                event_id INTEGER,
                created_at TEXT
            );
            CREATE TABLE matches(
                id INTEGER PRIMARY KEY,
                match_time TEXT,
                is_test_mode INTEGER DEFAULT 0
            );
            CREATE TABLE match_stats(
                id INTEGER PRIMARY KEY,
                match_id INTEGER,
                player_id INTEGER,
                map_name TEXT,
                rating REAL
            );
            CREATE TABLE yearly_top_players(
                id INTEGER PRIMARY KEY,
                year INTEGER NOT NULL,
                rank INTEGER NOT NULL,
                player_id INTEGER NOT NULL
            );
            INSERT INTO players VALUES
                (1, 'Alpha', NULL),
                (2, 'Bravo', NULL),
                (3, 'Charlie', NULL);
            INSERT INTO events VALUES
                (1, '2026 Spring 80 Major', '80 Major', 'spring-80-major', '2026-02-01'),
                (2, 'Ordinary Major', 'Major', 'ordinary-major', '2026-05-01'),
                (3, '80CS Challenge', '80CS', '80cs-challenge', '2027-03-01');
            INSERT INTO player_medals VALUES
                (1, 1, 'MVP', 1, '2026-02-02'),
                (2, 1, 'MVP', 3, '2027-03-02'),
                (3, 2, 'MVP', 2, '2026-05-02'),
                (4, 2, 'EVP', 1, '2026-02-02');
            """
        )

    def tearDown(self):
        self.conn.close()

    def test_major_detection_only_accepts_explicit_80_major(self):
        self.assertTrue(is_80_major_event("2026 Spring 80 Major"))
        self.assertTrue(is_80_major_event(slug="2026-summer-80-major"))
        self.assertTrue(is_80_major_event(short_name="80major"))
        self.assertFalse(is_80_major_event("Ordinary Major"))

    def test_awards_use_real_years_and_counts(self):
        page = build_award_page(self.conn, "MVP", today=date(2026, 7, 24))
        self.assertEqual(page["years"], [2026, 2027])
        self.assertEqual(page["major_leaders"][0]["nickname"], "Alpha")
        self.assertEqual(page["major_leaders"][0]["major"], 1)
        self.assertEqual(page["ranking"][0]["year_counts"], [1, 1])
        self.assertEqual(page["ranking"][0]["total"], 2)
        self.assertEqual(page["latest"][0]["event_name"], "80CS Challenge")

    def test_top10_uses_only_manually_published_rankings(self):
        self.conn.executescript(
            """
            INSERT INTO matches VALUES
                (1, '2026-04-01', 0),
                (2, '2027-04-01', 0);
            INSERT INTO match_stats VALUES
                (1, 1, 3, 'de_mirage', 9.99),
                (2, 2, 3, 'de_nuke', 9.99);
            INSERT INTO yearly_top_players VALUES
                (1, 2026, 1, 1),
                (2, 2026, 2, 2),
                (3, 2027, 1, 1),
                (4, 2027, 2, 2);
            """
        )
        page = build_top10_page(self.conn)
        alpha = next(row for row in page["ranking"] if row["nickname"] == "Alpha")
        bravo = next(row for row in page["ranking"] if row["nickname"] == "Bravo")
        self.assertEqual(page["years"], [2026, 2027])
        self.assertEqual(alpha["first"], 2)
        self.assertEqual(bravo["second"], 2)
        self.assertNotIn("Charlie", [row["nickname"] for row in page["ranking"]])
        self.assertEqual(page["most_top1"][0]["nickname"], "Alpha")
        self.assertEqual(page["most_top5"][0]["top5"], 2)

    def test_top10_is_empty_when_only_match_stats_exist(self):
        self.conn.executescript(
            """
            INSERT INTO matches VALUES (1, '2026-04-01', 0);
            INSERT INTO match_stats VALUES
                (1, 1, 1, 'de_mirage', 1.50),
                (2, 1, 2, 'de_mirage', 1.20);
            """
        )
        page = build_top10_page(self.conn)
        self.assertEqual(page["years"], [])
        self.assertEqual(page["ranking"], [])
        self.assertEqual(page["most_top1"], [])
        self.assertEqual(page["most_top5"], [])


if __name__ == "__main__":
    unittest.main()
