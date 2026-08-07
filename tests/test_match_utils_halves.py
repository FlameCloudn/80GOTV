import sqlite3
import unittest

from utils.match_utils import get_map_half_scores, parse_map_halves


class MatchHalfScoreUtilsTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            """CREATE TABLE matches(
                   id INTEGER PRIMARY KEY,
                   map1 TEXT,
                   map2 TEXT,
                   map3 TEXT,
                   map4 TEXT,
                   map5 TEXT,
                   map_halves TEXT,
                   bp_state TEXT
               )"""
        )

    def tearDown(self):
        self.conn.close()

    def _get_row(self):
        row = self.conn.execute("SELECT * FROM matches WHERE id=1").fetchone()
        if not row:
            raise AssertionError("未找到测试比赛")
        return row

    def test_half_scores_infers_opening_side_from_bp(self):
        self.conn.execute(
            """INSERT INTO matches(
                   id, map1, map_halves, bp_state
               ) VALUES(
                   1, 'de_mirage',
                   '{"0": {"h1_t1": 13, "h1_t2": 7, "h2_t1": 5, "h2_t2": 2}}',
                   '{"picks": [{"map": "Mirage", "picked_by": "t1", "side_team": "t2", "side": "CT"}]}'
               )"""
        )
        self.conn.commit()
        row = self._get_row()
        halves = get_map_half_scores(row, 0, parse_map_halves(row))

        self.assertEqual(halves["opening_ct_team"], "t2")
        self.assertEqual(halves["side_source"], "website_bp")

    def test_half_scores_uses_existing_opening_value(self):
        self.conn.execute(
            """INSERT INTO matches(
                   id, map1, map_halves, bp_state
               ) VALUES(
                   1, 'de_mirage',
                   '{"0": {"h1_t1": 13, "h1_t2": 7, "h2_t1": 5, "h2_t2": 2, "opening_ct_team": "t1"}}',
                   '{"picks": [{"map": "Mirage", "picked_by": "t1", "side_team": "t2", "side": "T"}]}'
               )"""
        )
        self.conn.commit()
        row = self._get_row()
        halves = get_map_half_scores(row, 0, parse_map_halves(row))

        self.assertEqual(halves["opening_ct_team"], "t1")
        self.assertEqual(halves["side_source"], "unknown")

    def test_half_scores_keeps_unknown_when_no_bp_info(self):
        self.conn.execute(
            """INSERT INTO matches(
                   id, map1, map_halves, bp_state
               ) VALUES(
                   1, 'de_mirage',
                   '{"0": {"h1_t1": 13, "h1_t2": 7, "h2_t1": 5, "h2_t2": 2}}',
                   NULL
               )"""
        )
        self.conn.commit()
        row = self._get_row()
        halves = get_map_half_scores(row, 0, parse_map_halves(row))

        self.assertIsNone(halves["opening_ct_team"])
        self.assertEqual(halves["side_source"], "unknown")


if __name__ == "__main__":
    unittest.main()
