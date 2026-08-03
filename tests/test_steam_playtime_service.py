import json
import random
import unittest
from unittest.mock import patch

from services.steam_playtime_service import (
    build_balanced_assignments,
    build_balanced_roster_plan,
    fetch_cs2_playtime_minutes,
)


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, _size):
        return json.dumps(self.payload).encode("utf-8")


class SteamPlaytimeServiceTests(unittest.TestCase):
    def test_fetches_cs2_playtime_from_public_profile(self):
        payload = {
            "response": {
                "game_count": 1,
                "games": [{"appid": 730, "playtime_forever": 12345}],
            }
        }
        with patch(
            "services.steam_playtime_service.urlopen",
            return_value=_FakeResponse(payload),
        ):
            result = fetch_cs2_playtime_minutes("76561198000000001", api_key="test-key")
        self.assertEqual(result, {"status": "public", "minutes": 12345})

    def test_private_profile_is_marked_without_becoming_zero_hours(self):
        with patch(
            "services.steam_playtime_service.urlopen",
            return_value=_FakeResponse({"response": {}}),
        ):
            result = fetch_cs2_playtime_minutes("76561198000000001", api_key="test-key")
        self.assertEqual(result, {"status": "private", "minutes": None})

    def test_balances_fixed_size_teams_by_total_playtime(self):
        playtimes = [10000, 9000, 8000, 7000, 6000, 5000, 4000, 3000, 2000, 1000]
        rows = [
            {"id": index + 1, "cs2_playtime_minutes": minutes}
            for index, minutes in enumerate(playtimes)
        ]
        draw = build_balanced_assignments(rows, rng=random.Random(7))

        team_members = {1: [], 2: []}
        for row in rows:
            team_members[draw["assignments"][row["id"]]].append(row["id"])

        self.assertEqual([len(team_members[1]), len(team_members[2])], [5, 5])
        self.assertEqual(sorted(draw["team_totals"]), [27000, 28000])
        self.assertEqual(draw["known_count"], 10)
        self.assertEqual(draw["unknown_count"], 0)

    def test_unknown_playtime_uses_known_median(self):
        rows = [
            {"id": 1, "cs2_playtime_minutes": 1000},
            {"id": 2, "cs2_playtime_minutes": 3000},
            {"id": 3, "cs2_playtime_minutes": None},
            {"id": 4, "cs2_playtime_minutes": None},
            {"id": 5, "cs2_playtime_minutes": 2000},
        ]
        draw = build_balanced_assignments(rows, rng=random.Random(3))

        self.assertEqual(draw["fallback_minutes"], 2000)
        self.assertEqual(draw["known_count"], 3)
        self.assertEqual(draw["unknown_count"], 2)
        self.assertEqual(draw["team_totals"], [10000])

    def test_roster_plan_fills_partial_team_and_creates_balanced_team(self):
        playtimes = [2100, 1400, 600, 450, 450, 450, 200, 50, 0]
        rows = [
            {"id": index + 1, "cs2_playtime_minutes": minutes}
            for index, minutes in enumerate(playtimes)
        ]
        fixed_teams = [
            {
                "registration_id": 77,
                "players": [{"cs2_playtime_minutes": 500}],
            }
        ]

        draw = build_balanced_roster_plan(
            rows,
            fixed_teams=fixed_teams,
            rng=random.Random(9),
            attempts=80,
        )

        self.assertEqual(len(draw["teams"]), 2)
        self.assertEqual(draw["teams"][0]["registration_id"], 77)
        self.assertEqual(
            [len(team["candidate_ids"]) for team in draw["teams"]],
            [4, 5],
        )
        self.assertEqual(draw["reserves"], [])
        self.assertEqual(sorted(draw["team_totals"]), [3100, 3100])
        self.assertEqual(set(draw["assignments"]), set(range(1, 10)))

    def test_roster_plan_keeps_latest_extra_registrations_as_reserves(self):
        rows = [{"id": index + 1, "cs2_playtime_minutes": 100 + index} for index in range(12)]

        draw = build_balanced_roster_plan(
            rows,
            rng=random.Random(5),
            attempts=20,
        )

        self.assertEqual(len(draw["teams"]), 2)
        self.assertEqual(draw["reserves"], [11, 12])
        self.assertEqual(len(draw["assignments"]), 10)

    def test_roster_plan_rejects_unfillable_partial_team(self):
        rows = [{"id": index + 1, "cs2_playtime_minutes": 100} for index in range(3)]
        fixed_teams = [
            {
                "registration_id": 77,
                "players": [{"cs2_playtime_minutes": 500}],
            }
        ]

        with self.assertRaises(ValueError):
            build_balanced_roster_plan(rows, fixed_teams=fixed_teams)


if __name__ == "__main__":
    unittest.main()
