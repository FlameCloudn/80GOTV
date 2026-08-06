import unittest

from services.demo_service import _infer_demo_team_order


class DemoTeamMappingTests(unittest.TestCase):
    def test_demo_team_names_override_demo_a_b_order(self):
        players = [
            {"id": 1, "team_id": 11},
            {"id": 2, "team_id": 11},
            {"id": 3, "team_id": 9},
            {"id": 4, "team_id": 9},
        ]
        self.assertFalse(
            _infer_demo_team_order(
                {"team_a_name": "2BMAX", "team_b_name": "G8"},
                {"team1_name": "G8 Esports", "team2_name": "Team 2BMAX"},
                {1, 2},
                {3, 4},
                players,
                set(),
                set(),
                11,
                9,
            )
        )

    def test_player_team_is_fallback_when_demo_names_are_missing(self):
        players = [{"id": 1, "team_id": 11}, {"id": 2, "team_id": 9}]
        self.assertTrue(
            _infer_demo_team_order(
                {"team_a_name": "", "team_b_name": ""},
                {"team1_name": "G8", "team2_name": "2BMAX"},
                {1},
                {2},
                players,
                set(),
                set(),
                11,
                9,
            )
        )


if __name__ == "__main__":
    unittest.main()
