import sqlite3
import unittest

from services.match_service import supplement_temp_teams


class MatchPlaceholderTests(unittest.TestCase):
    def test_single_player_side_uses_registration_nickname_when_database_is_available(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE players(id INTEGER PRIMARY KEY, nickname TEXT)")
        conn.execute("INSERT INTO players(id,nickname) VALUES(18,'KL-2077')")
        match = supplement_temp_teams(
            {
                "team1_id": None,
                "team2_id": 2,
                "team1_players": "[18]",
                "team2_players": None,
                "team2_name": "Opponent",
                "t2s": "OPP",
            },
            conn,
        )
        conn.close()
        self.assertEqual(match["team1_name"], "KL-2077")
        self.assertEqual(match["t1s"], "KL-2077")

    def test_unassigned_bracket_match_uses_tbd_everywhere(self):
        match = supplement_temp_teams(
            {
                "team1_id": None,
                "team2_id": None,
                "team1_players": None,
                "team2_players": None,
            }
        )

        self.assertEqual(match["team1_name"], "TBD")
        self.assertEqual(match["team2_name"], "TBD")
        self.assertEqual(match["t1s"], "TBD")
        self.assertEqual(match["t2s"], "TBD")

    def test_empty_json_rosters_are_still_unassigned(self):
        match = supplement_temp_teams(
            {
                "team1_id": -1,
                "team2_id": -2,
                "team1_players": "[]",
                "team2_players": "[]",
            }
        )

        self.assertEqual(match["team1_name"], "TBD")
        self.assertEqual(match["team2_name"], "TBD")

    def test_real_temporary_rosters_keep_their_team_labels(self):
        match = supplement_temp_teams(
            {
                "team1_id": -1,
                "team2_id": -2,
                "team1_players": "[1, 2, 3, 4, 5]",
                "team2_players": "[6, 7, 8, 9, 10]",
            }
        )

        self.assertEqual(match["team1_name"], "TEAM 1")
        self.assertEqual(match["team2_name"], "TEAM 2")
        self.assertEqual(match["t1s"], "T1")
        self.assertEqual(match["t2s"], "T2")


if __name__ == "__main__":
    unittest.main()
