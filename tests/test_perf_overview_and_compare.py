import unittest

from routes.players import _compare_card, _compare_rows
from services.perf_overview_service import _tier, build_perf_overview

AVERAGES = {"kpr": 0.7, "dpr": 0.7, "kast": 70.0, "impact": 0.2, "rws": 10.0, "adr": 75.0}


def _player_row(**overrides):
    row = {
        "kpr": 0.7,
        "dpr": 0.7,
        "kast": 70.0,
        "mk_rating": 0.2,
        "rws": 10.0,
        "adr": 75.0,
        "rating": 1.0,
    }
    row.update(overrides)
    return row


def _compare_values(**overrides):
    values = {
        "rating": 1.0,
        "kpr": 0.7,
        "dpr": 0.7,
        "kast": 70.0,
        "impact": 0.2,
        "adr": 75.0,
        "kd": 1.0,
        "hs": 40.0,
        "apr": 0.1,
        "opk": 0.1,
        "fapr": 0.01,
    }
    values.update(overrides)
    return values


class PerfOverviewTests(unittest.TestCase):
    def test_bars_compare_with_average_and_rating_average_is_one(self):
        row = _player_row(dpr=0.35, rating=1.2)
        avg = build_perf_overview([row], AVERAGES)
        bars = {bar["label"]: bar for bar in row["perf_bars"]}

        # DPR 只有平均的一半 → 比值 2.0，正好是尺子的上限，所以平均线在一半的位置
        self.assertAlmostEqual(avg, 0.5)
        self.assertEqual(bars["DPR"]["pct"], 100.0)
        self.assertEqual(bars["KPR"]["pct"], 50.0)
        self.assertEqual(bars["Rating"]["pct"], 60.0)
        self.assertEqual(bars["Rating"]["tier"], "perf-rating")
        self.assertEqual(bars["KPR"]["tier"], "perf-avg")
        self.assertEqual(bars["KAST"]["text"], "70.0%")
        self.assertTrue(bars["Rating"]["fixed"])
        self.assertFalse(bars["影响力"]["fixed"])

    def test_scale_keeps_room_on_the_right_of_the_average_line(self):
        rows = [_player_row(), _player_row(kpr=0.35)]
        avg = build_perf_overview(rows, AVERAGES)

        self.assertAlmostEqual(avg, round(1 / 1.4, 4))
        self.assertEqual(rows[1]["perf_bars"][0]["tier"], "perf-low")

    def test_tiers_follow_hltv_steps(self):
        self.assertEqual(_tier(0.99), "perf-low")
        self.assertEqual(_tier(1.0), "perf-avg")
        self.assertEqual(_tier(1.15), "perf-good")
        self.assertEqual(_tier(1.25), "perf-great")
        self.assertEqual(_tier(1.6), "perf-top")


class PlayerCompareTests(unittest.TestCase):
    def test_lower_dpr_wins_and_equal_values_stay_neutral(self):
        mine = _compare_values(rating=1.51, dpr=0.64)
        theirs = _compare_values(rating=1.53, dpr=0.72)
        rows = {row["label"]: row for row in _compare_rows(mine, theirs)}

        self.assertEqual(rows["Rating"]["state"], "worse")
        self.assertEqual(rows["DPR"]["state"], "better")
        self.assertEqual(rows["KPR"]["state"], "")
        self.assertEqual(rows["KAST"]["value"], "70.0%")

    def test_card_counts_leads_only_when_both_sides_have_data(self):
        side_a = {"player": {"id": 1}, "maps": 4, "values": _compare_values(rating=1.2, adr=90.0)}
        side_b = {"player": {"id": 2}, "maps": 5, "values": _compare_values()}

        self.assertEqual(_compare_card("a", "id1", side_a, side_b)["lead"], 2)
        self.assertEqual(_compare_card("b", "id2", side_b, side_a)["lead"], 0)
        self.assertIsNone(_compare_card("a", "id1", side_a, None)["lead"])
        self.assertEqual(_compare_card("b", "id2", None, side_a)["rows"], [])

    def test_player_without_stats_shows_dashes(self):
        rows = _compare_rows({}, _compare_values())

        self.assertTrue(all(row["value"] == "-" and row["state"] == "" for row in rows))


if __name__ == "__main__":
    unittest.main()
