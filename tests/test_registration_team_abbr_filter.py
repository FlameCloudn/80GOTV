import unittest

from utils.filters import registration_team_abbr_filter
from utils.helpers import event_abbr, team_abbr


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


class PlaceholderAbbrTests(unittest.TestCase):
    """没有队标 / 赛事图标时圆圈里写的字：有现成简称用简称，临时队伍 TEAM X 写成 TX，赛事要能区分。"""

    def test_team_uses_existing_short_name_and_temp_team_rule(self):
        cases = [
            (("TEAM1", "T1"), "T1"),
            (("TEAM 2", ""), "T2"),
            (("队伍 3", ""), "T3"),
            (("G8 Esports", "G8"), "G8"),
            (("Team Falcocks", "flks"), "flks"),
            (("Team Alpha", ""), "TA"),
            (("TBD", "TBD"), "?"),
        ]
        for (name, short_name), expected in cases:
            with self.subTest(name=name):
                self.assertEqual(team_abbr(name, short_name), expected)

    def test_event_abbr_tells_seasons_and_editions_apart(self):
        self.assertEqual(event_abbr("2026 Summer 80 Major", "80MAJOR_SUMMER26"), "SU26")
        self.assertEqual(event_abbr("2026 Spring 80 Major ", "80MAJOR_SPRING26"), "SP26")
        self.assertEqual(event_abbr("80CS Challenge S1", "80CS_S1"), "CH1")
        self.assertEqual(event_abbr("Anything", "S26M"), "S26M")


if __name__ == "__main__":
    unittest.main()
