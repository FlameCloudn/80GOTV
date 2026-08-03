import unittest

from utils.filters import registration_team_abbr_filter


class RegistrationTeamAbbrFilterTests(unittest.TestCase):
    def test_team_prefix_uses_t_and_second_word_initial(self):
        cases = {
            "Team Falcocks": "TF",
            "team 2BMAX": "T2",
            "TEAM Spirit": "TS",
            "TeAm Spirit Academy": "TS",
            "  Team   falcons  ": "TF",
        }

        for team_name, expected in cases.items():
            with self.subTest(team_name=team_name):
                self.assertEqual(registration_team_abbr_filter(team_name), expected)

    def test_other_names_keep_two_character_fallback(self):
        cases = {
            "Natus Vincere": "NA",
            "Spirit": "SP",
            "Team": "TE",
            "T": "T",
            "": "",
        }

        for team_name, expected in cases.items():
            with self.subTest(team_name=team_name):
                self.assertEqual(registration_team_abbr_filter(team_name), expected)

    def test_none_is_empty(self):
        self.assertEqual(registration_team_abbr_filter(None), "")


if __name__ == "__main__":
    unittest.main()
