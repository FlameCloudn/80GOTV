import copy
import unittest

from scripts.refresh_guess_player_metadata import POOL_REASON, refresh_snapshot


class GuessPlayerRefreshTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = {
            "generated_at": "2026-07-16",
            "latest_ranking_date": "2026-07-13",
            "players": [
                {
                    "profile_id": 1,
                    "nickname": "player",
                    "full_name": "First Last",
                    "country_code": "SE",
                    "profile_age": 22,
                    "team": "Old team",
                    "player_status": "active",
                    "role": "rifler",
                    "major_appearances": 2,
                    "source_checked_at": "2026-07-16",
                    "noob_eligible": True,
                    "eligibility": {"reasons": [POOL_REASON, "historical_top20"]},
                }
            ],
        }
        self.directory = [{"id": "blast-1"}]
        self.fetched = {
            "expected": 1,
            "failures": [],
            "records": [
                {
                    "id": "blast-1",
                    "nickname": "player",
                    "firstName": "First",
                    "lastName": "Last",
                    "nationality": {"value": "SE"},
                    "team": {"data": {"name": "New team"}},
                    "age": {"value": 23},
                    "role": {"value": "hybrid"},
                    "majorAppearances": {"value": 3},
                    "isRetired": False,
                }
            ],
        }
        self.hltv = {"checked_at": "2026-10-27", "players": []}

    def refresh(self):
        return refresh_snapshot(
            self.snapshot, self.directory, self.fetched, self.hltv, "2026-10-27"
        )

    def test_refreshes_age_team_role_without_changing_identity_or_ranking(self):
        old = copy.deepcopy(self.snapshot)
        result, report = self.refresh()
        player = result["players"][0]
        self.assertEqual(
            (player["profile_age"], player["team"], player["role"]), (23, "New team", "hybrid")
        )
        self.assertEqual(player["nickname"], "player")
        self.assertEqual(player["profile_id"], 1)
        self.assertTrue(player["noob_eligible"])
        self.assertEqual(result["latest_ranking_date"], "2026-07-13")
        self.assertFalse(report["ranking_refreshed"])
        self.assertEqual(self.snapshot, old)

    def test_preserves_and_refreshes_all_existing_aliases(self):
        alias = copy.deepcopy(self.snapshot["players"][0])
        alias["nickname"] = "old-nickname"
        alias["eligibility"]["reasons"] = ["historical_top20"]
        self.snapshot["players"].append(alias)
        result, report = self.refresh()
        self.assertEqual(len(result["players"]), 2)
        self.assertEqual([row["profile_age"] for row in result["players"]], [23, 23])
        self.assertEqual(report["existing_records_refreshed"], 2)
        self.assertNotIn(POOL_REASON, result["players"][1]["eligibility"]["reasons"])

    def test_adds_an_existing_historical_player_to_the_game_pool(self):
        self.snapshot["players"][0]["eligibility"]["reasons"] = ["historical_top20"]
        result, report = self.refresh()
        self.assertIn(POOL_REASON, result["players"][0]["eligibility"]["reasons"])
        self.assertEqual(report["added_to_game_pool"], ["player"])

    def test_blast_team_alias_uses_the_same_name_as_hltv(self):
        self.fetched["records"][0]["team"]["data"]["name"] = "Team Liquid"
        result, _ = self.refresh()
        self.assertEqual(result["players"][0]["team"], "Liquid")

    def test_same_nickname_different_person_is_not_merged(self):
        for field, value in (("country_code", "DK"), ("full_name", "Another Person")):
            with self.subTest(field=field):
                old = self.snapshot["players"][0][field]
                self.snapshot["players"][0][field] = value
                with self.assertRaises(ValueError):
                    self.refresh()
                self.snapshot["players"][0][field] = old

    def test_confirmed_name_variant_requires_matching_nickname_name_and_country(self):
        self.fetched["records"][0]["firstName"] = "First Middle"
        self.hltv["identity_matches"] = [
            {
                "nickname": "player",
                "profile_id": 1,
                "blast_full_name": "First Middle Last",
                "blast_country": "SE",
            }
        ]
        result, _ = self.refresh()
        self.assertEqual(result["players"][0]["profile_age"], 23)
        self.fetched["records"][0]["lastName"] = "Another"
        with self.assertRaises(ValueError):
            self.refresh()

    def test_incomplete_duplicate_or_wrong_id_fetch_is_rejected(self):
        for mutation in (
            lambda data: data.update(failures=["failed"]),
            lambda data: data.update(records=[]),
            lambda data: data["records"].append(data["records"][0]),
            lambda data: data["records"][0].update(id="another-id"),
        ):
            old = copy.deepcopy(self.fetched)
            mutation(self.fetched)
            with self.assertRaises(ValueError):
                self.refresh()
            self.fetched = old

    def test_no_longer_listed_player_is_retained_with_old_check_date(self):
        old = copy.deepcopy(self.snapshot["players"][0])
        old.update(nickname="retained", full_name="Different Person", profile_id=2)
        self.snapshot["players"].append(old)
        result, report = self.refresh()
        retained = result["players"][1]
        self.assertEqual(len(result["players"]), 2)
        self.assertEqual(retained["source_checked_at"], "2026-07-16")
        self.assertEqual(retained, old)
        self.assertEqual(report["retained_outside_blast_directory"], ["retained"])

    def test_verified_hltv_overrides_conflicting_blast_team_and_logs_conflict(self):
        self.hltv["players"].append(
            {
                "profile_id": 1,
                "team": "",
                "profile_age": 23,
                "player_status": "free_agent",
                "url": "https://www.hltv.org/player/1/player",
            }
        )
        result, report = self.refresh()
        self.assertEqual(result["players"][0]["team"], "")
        self.assertEqual(result["players"][0]["player_status"], "free_agent")
        self.assertEqual(report["source_conflicts"][0]["fields"]["team"]["blast"], "New team")

    def test_hltv_identity_url_and_check_date_must_match(self):
        self.hltv["players"].append(
            {
                "profile_id": 1,
                "team": "New team",
                "profile_age": 23,
                "player_status": "active",
                "url": "https://www.hltv.org/player/999/another",
            }
        )
        with self.assertRaises(ValueError):
            self.refresh()


if __name__ == "__main__":
    unittest.main()
