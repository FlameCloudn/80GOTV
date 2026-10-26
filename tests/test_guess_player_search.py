import sqlite3
import unittest
from contextlib import closing

from app import app
from routes.guess_player import _resolve_player


class GuessPlayerSearchTests(unittest.TestCase):
    def resolve(self, query, pool="pro"):
        with closing(sqlite3.connect(":memory:")) as conn:
            conn.row_factory = sqlite3.Row
            conn.executescript(
                """
                CREATE TABLE guess_players (
                    id INTEGER PRIMARY KEY, nickname TEXT, full_name TEXT,
                    active INTEGER, noob_eligible INTEGER
                );
                INSERT INTO guess_players VALUES (1, 'Someone', 'Alex', 1, 1);
                INSERT INTO guess_players VALUES (2, 'Alex', 'Other Name', 1, 1);
                INSERT INTO guess_players VALUES (3, 'Duplicate A', 'Same Name', 1, 1);
                INSERT INTO guess_players VALUES (4, 'Duplicate B', 'Same Name', 1, 1);
                INSERT INTO guess_players VALUES (5, 'Inactive', 'Hidden Player', 0, 1);
                INSERT INTO guess_players VALUES (6, 'ProOnly', 'Pro Only', 1, 0);
                """
            )
            with app.test_request_context(
                "/guess-player", method="POST", data={"player_query": query}
            ):
                row = _resolve_player(conn, pool)
                return dict(row) if row else None

    def test_nickname_wins_over_another_players_real_name(self):
        self.assertEqual(self.resolve("Alex")["id"], 2)
        self.assertEqual(self.resolve("  aLeX  ")["id"], 2)

    def test_unique_real_name_remains_a_fallback(self):
        self.assertEqual(self.resolve("Other Name")["id"], 2)

    def test_ambiguous_real_name_requires_a_selected_player(self):
        self.assertIsNone(self.resolve("Same Name"))

    def test_active_and_pool_boundaries_remain_enforced(self):
        self.assertIsNone(self.resolve("Inactive"))
        self.assertIsNone(self.resolve("ProOnly", "noob"))


if __name__ == "__main__":
    unittest.main()
