import unittest

from utils.demo_parser import calculate_event_player_stats, parse_player_stats


def _player(name, letter, **stats):
    data = {
        "name": name,
        "team": {"letter": letter},
        "killCount": 0,
        "deathCount": 0,
        "assistCount": 0,
        "oneVsOneWonCount": 9,
        "oneVsTwoWonCount": 9,
        "oneKillCount": 9,
        "twoKillCount": 9,
    }
    data.update(stats)
    return data


class DemoEventStatsTests(unittest.TestCase):
    def test_counts_enemy_kills_but_never_trusts_raw_clutch_summary(self):
        data = {
            "players": {
                "1": _player("A1", "A"),
                "2": _player("A2", "A"),
                "3": _player("B1", "B"),
                "4": _player("B2", "B"),
            },
            "kills": [
                {
                    "roundNumber": 1,
                    "killerSteamId": 1,
                    "victimSteamId": 3,
                    "killerSide": 3,
                    "victimSide": 2,
                },
                {
                    "roundNumber": 1,
                    "killerSteamId": 1,
                    "victimSteamId": 4,
                    "killerSide": 3,
                    "victimSide": 2,
                },
                {
                    "roundNumber": 2,
                    "killerSteamId": 1,
                    "victimSteamId": 3,
                    "killerSide": 2,
                    "victimSide": 3,
                },
                {
                    "roundNumber": 2,
                    "killerSteamId": 1,
                    "victimSteamId": 2,
                    "killerSide": 2,
                    "victimSide": 2,
                },
            ],
            "clutches": [
                {"clutcherSteamId": 1, "opponentCount": 2, "hasWon": True},
                {"clutcherSteamId": 1, "opponentCount": 3, "hasWon": False},
            ],
        }

        stats = calculate_event_player_stats(data)["1"]

        self.assertEqual(stats["multi1k"], 1)
        self.assertEqual(stats["multi2k"], 1)
        self.assertEqual(stats["multi3k"], 0)
        self.assertEqual(stats["clutches_won"], 0)
        self.assertEqual(stats["clutch_1v2"], 0)
        self.assertEqual(stats["clutch_1v3"], 0)

    def test_reconstructs_won_clutch_when_clutch_events_are_absent(self):
        data = {
            "players": {
                "1": _player("A1", "A"),
                "2": _player("A2", "A"),
                "3": _player("B1", "B"),
                "4": _player("B2", "B"),
                "5": _player("B3", "B"),
            },
            "rounds": [
                {
                    "number": 1,
                    "teamAName": "A",
                    "teamBName": "B",
                    "winnerName": "A",
                    "winnerSide": 3,
                    "teamASide": 3,
                    "teamBSide": 2,
                }
            ],
            "playerEconomies": [
                {"roundNumber": 1, "steamId": 1, "playerSide": 3},
                {"roundNumber": 1, "steamId": 2, "playerSide": 3},
                {"roundNumber": 1, "steamId": 3, "playerSide": 2},
                {"roundNumber": 1, "steamId": 4, "playerSide": 2},
                {"roundNumber": 1, "steamId": 5, "playerSide": 2},
            ],
            "kills": [
                {"roundNumber": 1, "tick": 1, "killerSteamId": 3, "victimSteamId": 2},
                {"roundNumber": 1, "tick": 2, "killerSteamId": 1, "victimSteamId": 3},
                {"roundNumber": 1, "tick": 3, "killerSteamId": 1, "victimSteamId": 4},
                {"roundNumber": 1, "tick": 4, "killerSteamId": 1, "victimSteamId": 5},
            ],
        }

        stats = calculate_event_player_stats(data)["1"]

        self.assertEqual(stats["clutches_won"], 1)
        self.assertEqual(stats["clutch_1v3"], 1)
        self.assertEqual(stats["multi3k"], 1)

    def test_timeline_overrides_incorrect_clutch_events_and_string_false(self):
        data = {
            "players": {
                "1": _player("A1", "A"),
                "2": _player("A2", "A"),
                "3": _player("B1", "B"),
                "4": _player("B2", "B"),
                "5": _player("B3", "B"),
            },
            "rounds": [
                {
                    "number": 1,
                    "teamAName": "A",
                    "teamBName": "B",
                    "winnerName": "A",
                }
            ],
            "playerEconomies": [
                {"roundNumber": 1, "steamId": 1, "playerSide": 3},
                {"roundNumber": 1, "steamId": 2, "playerSide": 3},
                {"roundNumber": 1, "steamId": 3, "playerSide": 2},
                {"roundNumber": 1, "steamId": 4, "playerSide": 2},
                {"roundNumber": 1, "steamId": 5, "playerSide": 2},
            ],
            "kills": [
                {"roundNumber": 1, "tick": 1, "killerSteamId": 3, "victimSteamId": 2},
                {"roundNumber": 1, "tick": 2, "killerSteamId": 1, "victimSteamId": 3},
                {"roundNumber": 1, "tick": 3, "killerSteamId": 1, "victimSteamId": 4},
                {"roundNumber": 1, "tick": 4, "killerSteamId": 1, "victimSteamId": 5},
            ],
            # The analyzer payload is deliberately wrong.  It must not replace
            # the real 1v3 reconstructed from the round timeline.
            "clutches": [
                {"clutcherSteamId": 1, "opponentCount": 1, "hasWon": "true"},
                {"clutcherSteamId": 1, "opponentCount": 5, "hasWon": "false"},
            ],
        }

        stats = calculate_event_player_stats(data)["1"]

        self.assertEqual(stats["clutches_won"], 1)
        self.assertEqual(stats["clutch_1v3"], 1)
        self.assertEqual(stats["clutch_1v1"], 0)
        self.assertEqual(stats["clutch_1v5"], 0)

    def test_player_stats_ignore_misleading_summary_counters(self):
        data = {
            "players": {
                "1": _player("A1", "A"),
                "2": _player("B1", "B"),
            },
            "teamA": {"name": "A"},
            "teamB": {"name": "B"},
            "rounds": [{"number": 1, "teamASide": 3, "teamBSide": 2}],
            "kills": [],
            "damages": [],
            "clutches": [],
        }

        player = next(item for item in parse_player_stats(data) if item["steam_id"] == 1)

        self.assertEqual(player["clutches_won"], 0)
        self.assertEqual(player["clutch_1v1"], 0)
        self.assertEqual(player["multi1k"], 0)
        self.assertEqual(player["multi2k"], 0)

    def test_uses_actual_round_roster_for_side_swap_and_substitute(self):
        data = {
            "players": {
                "1": _player("A1", "A"),
                "2": _player("A-left", "A"),
                "6": _player("A-substitute", "A"),
                "3": _player("B1", "B"),
                "4": _player("B2", "B"),
            },
            "rounds": [
                {
                    "number": 1,
                    "teamAName": "A",
                    "teamBName": "B",
                    "teamASide": 2,
                    "teamBSide": 3,
                    "winnerName": "A",
                    "winnerSide": 2,
                    "startTick": 10,
                    "endTick": 40,
                }
            ],
            # The complete economy list is the real roster for this round:
            # A-left has gone and A-substitute is playing after the side swap.
            "playerEconomies": [
                {"roundNumber": 1, "steamId": 1, "playerSide": 2},
                {"roundNumber": 1, "steamId": 6, "playerSide": 2},
                {"roundNumber": 1, "steamId": 3, "playerSide": 3},
                {"roundNumber": 1, "steamId": 4, "playerSide": 3},
            ],
            "kills": [
                {
                    "roundNumber": 1,
                    "tick": 20,
                    "killerSteamId": 3,
                    "victimSteamId": 6,
                    "killerSide": 3,
                    "victimSide": 2,
                },
                {
                    "roundNumber": 1,
                    "tick": 25,
                    "killerSteamId": 1,
                    "victimSteamId": 3,
                    "killerSide": 2,
                    "victimSide": 3,
                },
                {
                    "roundNumber": 1,
                    "tick": 30,
                    "killerSteamId": 1,
                    "victimSteamId": 4,
                    "killerSide": 2,
                    "victimSide": 3,
                },
            ],
            "clutches": [{"clutcherSteamId": 1, "opponentCount": 5, "hasWon": True}],
        }

        stats = calculate_event_player_stats(data)["1"]

        self.assertEqual(stats["clutches_won"], 1)
        self.assertEqual(stats["clutch_1v2"], 1)
        self.assertEqual(stats["clutch_1v5"], 0)

    def test_counts_objective_and_time_clutches_but_ignores_post_round_kills(self):
        data = {
            "players": {
                "1": _player("A1", "A"),
                "2": _player("A2", "A"),
                "3": _player("B1", "B"),
                "4": _player("B2", "B"),
            },
            "rounds": [
                {
                    "number": 1,
                    "teamAName": "A",
                    "teamBName": "B",
                    "winnerName": "A",
                    "startTick": 10,
                    "endTick": 30,
                    "endReason": 7,
                },
                {
                    "number": 2,
                    "teamAName": "A",
                    "teamBName": "B",
                    "winnerName": "A",
                    "startTick": 40,
                    "endTick": 60,
                    "endReason": 12,
                },
                {
                    "number": 3,
                    "teamAName": "A",
                    "teamBName": "B",
                    "winnerName": "A",
                    "startTick": 70,
                    "endTick": 90,
                    "endReason": 1,
                },
            ],
            "playerEconomies": [
                {"roundNumber": round_number, "steamId": steam_id, "playerSide": side}
                for round_number in (1, 2, 3)
                for steam_id, side in ((1, 3), (2, 3), (3, 2), (4, 2))
            ],
            "kills": [
                {"roundNumber": 1, "tick": 20, "killerSteamId": 3, "victimSteamId": 2},
                {"roundNumber": 1, "tick": 35, "killerSteamId": 4, "victimSteamId": 1},
                {"roundNumber": 2, "tick": 50, "killerSteamId": 3, "victimSteamId": 2},
                {"roundNumber": 3, "tick": 80, "killerSteamId": 4, "victimSteamId": 2},
            ],
            "bombsDefused": [{"roundNumber": 1, "tick": 30, "defuserSteamId": 1}],
            "bombsExploded": [{"roundNumber": 3, "tick": 90}],
        }

        stats = calculate_event_player_stats(data)

        self.assertEqual(stats["1"]["clutches_won"], 3)
        self.assertEqual(stats["1"]["clutch_1v2"], 3)
        self.assertEqual(stats["4"]["multi1k"], 1)

    def test_teamkill_self_kill_and_world_kill_remove_the_victim(self):
        data = {
            "players": {
                "1": _player("A1", "A"),
                "2": _player("A2", "A"),
                "5": _player("A3", "A"),
                "3": _player("B1", "B"),
                "4": _player("B2", "B"),
            },
            "rounds": [
                {"number": 1, "teamAName": "A", "teamBName": "B", "winnerName": "A"},
                {"number": 2, "teamAName": "A", "teamBName": "B", "winnerName": "A"},
                {"number": 3, "teamAName": "A", "teamBName": "B", "winnerName": "A"},
            ],
            "playerEconomies": [
                {"roundNumber": 1, "steamId": 1, "playerSide": 3},
                {"roundNumber": 1, "steamId": 2, "playerSide": 3},
                {"roundNumber": 1, "steamId": 5, "playerSide": 3},
                {"roundNumber": 1, "steamId": 3, "playerSide": 2},
                {"roundNumber": 1, "steamId": 4, "playerSide": 2},
                {"roundNumber": 2, "steamId": 1, "playerSide": 3},
                {"roundNumber": 2, "steamId": 2, "playerSide": 3},
                {"roundNumber": 2, "steamId": 3, "playerSide": 2},
                {"roundNumber": 2, "steamId": 4, "playerSide": 2},
                {"roundNumber": 3, "steamId": 1, "playerSide": 3},
                {"roundNumber": 3, "steamId": 2, "playerSide": 3},
                {"roundNumber": 3, "steamId": 3, "playerSide": 2},
                {"roundNumber": 3, "steamId": 4, "playerSide": 2},
            ],
            "kills": [
                {
                    "roundNumber": 1,
                    "tick": 1,
                    "killerSteamId": 2,
                    "victimSteamId": 5,
                    "killerSide": 3,
                    "victimSide": 3,
                },
                {"roundNumber": 1, "tick": 2, "killerSteamId": 3, "victimSteamId": 2},
                {"roundNumber": 1, "tick": 3, "killerSteamId": 1, "victimSteamId": 3},
                {"roundNumber": 1, "tick": 4, "killerSteamId": 1, "victimSteamId": 4},
                {"roundNumber": 2, "tick": 1, "killerSteamId": 2, "victimSteamId": 2},
                {"roundNumber": 2, "tick": 2, "killerSteamId": 1, "victimSteamId": 3},
                {"roundNumber": 2, "tick": 3, "killerSteamId": 1, "victimSteamId": 4},
                {"roundNumber": 3, "tick": 1, "killerSteamId": 0, "victimSteamId": 2},
                {"roundNumber": 3, "tick": 2, "killerSteamId": 1, "victimSteamId": 3},
                {"roundNumber": 3, "tick": 3, "killerSteamId": 1, "victimSteamId": 4},
            ],
        }

        stats = calculate_event_player_stats(data)["1"]

        self.assertEqual(stats["clutches_won"], 3)
        self.assertEqual(stats["clutch_1v2"], 3)
        self.assertEqual(stats["multi2k"], 3)

    def test_invalidates_clutch_when_a_dead_teammate_returns_in_the_timeline(self):
        data = {
            "players": {
                "1": _player("A1", "A"),
                "2": _player("A2", "A"),
                "3": _player("B1", "B"),
                "4": _player("B2", "B"),
            },
            "rounds": [
                {
                    "number": 1,
                    "teamAName": "A",
                    "teamBName": "B",
                    "winnerName": "A",
                    "startTick": 10,
                    "endTick": 50,
                }
            ],
            "playerEconomies": [
                {"roundNumber": 1, "steamId": 1, "playerSide": 3},
                {"roundNumber": 1, "steamId": 2, "playerSide": 3},
                {"roundNumber": 1, "steamId": 3, "playerSide": 2},
                {"roundNumber": 1, "steamId": 4, "playerSide": 2},
            ],
            "kills": [
                {"roundNumber": 1, "tick": 20, "killerSteamId": 3, "victimSteamId": 2},
                # A2 was already dead. This is a broken timeline, not a revive
                # signal we can safely turn into a clutch.
                {"roundNumber": 1, "tick": 25, "killerSteamId": 2, "victimSteamId": 3},
                {"roundNumber": 1, "tick": 30, "killerSteamId": 1, "victimSteamId": 4},
            ],
        }

        stats = calculate_event_player_stats(data)["1"]

        self.assertEqual(stats["clutches_won"], 0)
        self.assertEqual(stats["clutch_1v2"], 0)

    def test_groups_same_tick_events_and_ignores_duplicate_deaths(self):
        data = {
            "players": {
                "1": _player("A1", "A"),
                "2": _player("A2", "A"),
                "3": _player("B1", "B"),
                "4": _player("B2", "B"),
                "5": _player("B3", "B"),
            },
            "rounds": [{"number": 1, "teamAName": "A", "teamBName": "B", "winnerName": "A"}],
            "playerEconomies": [
                {"roundNumber": 1, "steamId": steam_id, "playerSide": side}
                for steam_id, side in ((1, 3), (2, 3), (3, 2), (4, 2), (5, 2))
            ],
            "kills": [
                # These two deaths share a tick, so the resulting state is
                # A1 versus B2/B3: a 1v2, not a transient 1v3.
                {"roundNumber": 1, "tick": 10, "killerSteamId": 3, "victimSteamId": 2},
                {"roundNumber": 1, "tick": 10, "killerSteamId": 1, "victimSteamId": 3},
                # CSDA can repeat the same death event. It must not corrupt
                # the timeline or create a second kill.
                {"roundNumber": 1, "tick": 10, "killerSteamId": 1, "victimSteamId": 3},
                {"roundNumber": 1, "tick": 20, "killerSteamId": 1, "victimSteamId": 4},
                {"roundNumber": 1, "tick": 30, "killerSteamId": 1, "victimSteamId": 5},
            ],
        }

        stats = calculate_event_player_stats(data)["1"]

        self.assertEqual(stats["clutches_won"], 1)
        self.assertEqual(stats["clutch_1v2"], 1)
        self.assertEqual(stats["clutch_1v3"], 0)

    def test_skips_conflicting_winner_identity(self):
        data = {
            "players": {
                "1": _player("A1", "A"),
                "2": _player("A2", "A"),
                "3": _player("B1", "B"),
                "4": _player("B2", "B"),
            },
            "rounds": [
                {
                    "number": 1,
                    "teamAName": "A",
                    "teamBName": "B",
                    "teamASide": 3,
                    "teamBSide": 2,
                    "winnerName": "A",
                    "winnerSide": 2,
                }
            ],
            "playerEconomies": [
                {"roundNumber": 1, "steamId": steam_id, "playerSide": side}
                for steam_id, side in ((1, 3), (2, 3), (3, 2), (4, 2))
            ],
            "kills": [
                {"roundNumber": 1, "tick": 1, "killerSteamId": 3, "victimSteamId": 2},
                {"roundNumber": 1, "tick": 2, "killerSteamId": 1, "victimSteamId": 3},
                {"roundNumber": 1, "tick": 3, "killerSteamId": 1, "victimSteamId": 4},
            ],
        }

        self.assertEqual(calculate_event_player_stats(data)["1"]["clutches_won"], 0)


if __name__ == "__main__":
    unittest.main()
