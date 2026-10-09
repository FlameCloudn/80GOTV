import sqlite3
import unittest

from utils.match_utils import (
    get_sql_effective_status,
    get_sql_match_completed,
    get_sql_match_live,
    get_sql_match_upcoming,
)


class MatchStatusTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            """CREATE TABLE matches(
                   id INTEGER PRIMARY KEY,
                   status TEXT,
                   match_time TEXT,
                   map1 TEXT,
                   map2 TEXT,
                   map3 TEXT,
                   map4 TEXT,
                   map5 TEXT
               )"""
        )

    def tearDown(self):
        self.conn.close()

    def _insert(self, match_id, status, time_expression, map1="mirage"):
        self.conn.execute(
            """INSERT INTO matches(id, status, match_time, map1)
               VALUES(?, ?, datetime('now', 'localtime', ?), ?)""",
            (match_id, status, time_expression, map1),
        )

    def _ids(self, fragment):
        return {
            row["id"]
            for row in self.conn.execute(f"SELECT m.id FROM matches m WHERE {fragment}").fetchall()
        }

    def test_upcoming_match_moves_through_time_based_statuses(self):
        self._insert(1, "upcoming", "+2 hours")
        self._insert(2, "upcoming", "-10 minutes")
        self._insert(3, "upcoming", "-2 days")
        self._insert(4, "cancelled", "-10 minutes")

        self.assertEqual(self._ids(get_sql_match_upcoming()), {1})
        self.assertEqual(self._ids(get_sql_match_live()), {2, 3})
        self.assertEqual(self._ids(get_sql_match_completed()), set())

        statuses = {
            row["id"]: row["effective_status"]
            for row in self.conn.execute(
                f"SELECT m.id, {get_sql_effective_status()} FROM matches m"
            ).fetchall()
        }
        self.assertEqual(
            statuses,
            {1: "upcoming", 2: "live", 3: "live", 4: "cancelled"},
        )

    def test_recent_past_upcoming_match_can_receive_gsi_data(self):
        self._insert(8, "upcoming", "-5 minutes", "ancient")
        rows = self.conn.execute(
            f"""SELECT m.id FROM matches m
                WHERE ({get_sql_match_live()})
                  AND (m.map1=? OR m.map2=? OR m.map3=? OR m.map4=? OR m.map5=?)""",
            ("ancient",) * 5,
        ).fetchall()
        self.assertEqual([row["id"] for row in rows], [8])

    def test_overdue_match_is_not_completed_without_an_explicit_result(self):
        self._insert(9, "upcoming", "-2 days", "nuke")
        self.assertEqual(self._ids(get_sql_match_completed()), set())
        self.assertEqual(self._ids(get_sql_match_live()), {9})
        self.conn.execute("UPDATE matches SET status='completed' WHERE id=9")
        self.assertEqual(self._ids(get_sql_match_completed()), {9})
        self.assertEqual(self._ids(get_sql_match_live()), set())


if __name__ == "__main__":
    unittest.main()
