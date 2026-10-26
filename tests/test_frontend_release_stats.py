import unittest
from unittest.mock import patch

from services.performance_service import refresh_player_performance
from tests.test_refactor_stats_consistency import StatsDatabaseCase, add_stat


class FrontendReleasePlayerBlocksTests(unittest.TestCase):
    def overall(self, value):
        fields = (
            "rounds_played maps matches total_kills total_deaths total_assists "
            "first_kills first_deaths trade_kills trade_deaths utility_damage "
            "multi2k multi3k multi4k multi5k avg_rating avg_kpr avg_adr avg_impact "
            "avg_t_rating avg_ct_rating avg_dpr avg_kast avg_hs clutches_won "
            "bomb_plants bomb_defuses utility_damage_per_round enemies_flashed flash_count"
        ).split()
        overall = dict.fromkeys(fields, value)
        overall.update(matches=1, maps=1)
        return overall

    def test_new_category_labels_keep_missing_input_guards(self):
        from routes.players import _build_player_blocks

        summary, cards, statistics = _build_player_blocks(self.overall(None))
        self.assertEqual(
            [card["title"] for card in cards], ["火力", "补枪", "突破", "开局", "残局", "道具"]
        )
        self.assertIsNone(summary["rating"])
        self.assertTrue(all(card["score"] is None for card in cards))
        self.assertTrue(all(item["value"] == "-" for card in cards for item in card["items"]))
        self.assertEqual(
            next(item for item in statistics if item["label"] == "Impact")["value"], "-"
        )

    def test_new_category_labels_keep_recorded_zero(self):
        from routes.players import _build_player_blocks

        summary, cards, _ = _build_player_blocks(self.overall(0))
        self.assertEqual(summary["rating"], 0)
        self.assertTrue(all(card["score"] == 0 for card in cards))
        self.assertTrue(all(item["value"] != "-" for card in cards for item in card["items"]))

    def test_compare_missing_values_do_not_become_zero_or_win(self):
        from routes.players import _compare_rows, _compare_values

        summary = dict.fromkeys(
            "rounds_played total_kills total_deaths avg_rating avg_kpr avg_dpr avg_kast "
            "avg_impact avg_adr avg_hs total_assists first_kills flash_assists".split()
        )
        summary["maps"] = 1
        values = _compare_values(summary)
        rows = _compare_rows(values, {"rating": -0.25, "dpr": 0.7})
        self.assertTrue(all(row["value"] == "-" and not row["state"] for row in rows))

    def test_compare_null_and_zero_are_distinct(self):
        from routes.players import _compare_rows

        rows = {
            row["label"]: row
            for row in _compare_rows({"rating": 0, "dpr": None}, {"rating": None, "dpr": 0.7})
        }
        self.assertEqual(rows["Rating"]["value"], "0.00")
        self.assertEqual(rows["Rating"]["state"], "")
        self.assertEqual(rows["DPR"]["value"], "-")
        self.assertEqual(rows["DPR"]["state"], "")

    def test_compare_does_not_claim_a_lead_without_comparable_data(self):
        from routes.players import _compare_card

        mine = {"player": {"id": 1}, "maps": 1, "values": {"rating": None}}
        theirs = {"player": {"id": 2}, "maps": 1, "values": {"rating": 0}}
        self.assertIsNone(_compare_card("a", "id1", mine, theirs)["lead"])

    def test_missing_rating_has_no_low_rating_colour(self):
        from utils.filters import rating_class_filter

        for value in (None, "", float("nan"), float("inf")):
            with self.subTest(value=value):
                self.assertEqual(rating_class_filter(value), "")
        self.assertEqual(rating_class_filter(0), "rt-1")


class FrontendReleasePerformanceTests(StatsDatabaseCase):
    def test_compare_summary_ignores_superseded_availability(self):
        from routes.players import _compare_player

        missing = dict.fromkeys(
            (
                "rating",
                "kills",
                "deaths",
                "rounds_played",
                "assists",
                "kast",
                "impact",
                "adr",
                "headshot_percentage",
                "first_kills",
                "flash_assists",
            )
        )
        add_stat(self.conn, self.match_id, self.player_id, self.team1, "Mirage", **missing)
        add_stat(
            self.conn,
            self.match_id,
            self.player_id,
            self.team1,
            "Mirage",
            rating=2,
            kills=30,
            deaths=5,
            rounds_played=20,
            data_status="superseded",
        )
        refresh_player_performance(self.conn, [self.player_id])
        result = _compare_player(self.conn, self.player_id)
        self.assertIsNotNone(result)
        self.assertTrue(all(value is None for value in result["values"].values()))

    def test_perf_average_uses_recorded_rounds_and_keeps_zero(self):
        from services.perf_overview_service import load_metric_averages

        add_stat(
            self.conn,
            self.match_id,
            self.player_id,
            self.team1,
            "Mirage",
            kills=10,
            deaths=0,
            rounds_played=10,
            kast=0,
            impact=0,
            rws_basic=0,
            adr=50,
        )
        add_stat(
            self.conn,
            self.match_id,
            self.player_id,
            self.team1,
            "Nuke",
            kills=None,
            deaths=0,
            rounds_played=30,
            kast=0,
            impact=0,
            rws_basic=0,
            adr=100,
        )
        averages = load_metric_averages(self.conn)
        self.assertEqual(averages["kpr"], 1)
        self.assertEqual(averages["dpr"], 0)
        self.assertEqual(averages["impact"], 0)
        self.assertEqual(averages["kast"], 0)
        self.assertEqual(averages["rws"], 0)
        self.assertEqual(averages["adr"], 87.5)

    def test_perf_average_without_recorded_inputs_stays_unknown(self):
        from services.perf_overview_service import load_metric_averages

        add_stat(
            self.conn,
            self.match_id,
            self.player_id,
            self.team1,
            "Mirage",
            kills=None,
            deaths=None,
            rounds_played=20,
            kast=None,
            impact=None,
            rws_basic=None,
            adr=None,
        )
        self.assertTrue(all(value is None for value in load_metric_averages(self.conn).values()))

    def test_new_team_roster_does_not_expose_unknown_cached_zero_rating(self):
        from routes.stats import team_detail
        from web_app import app

        add_stat(self.conn, self.match_id, self.player_id, self.team1, "Mirage", rating=None)
        refresh_player_performance(self.conn, [self.player_id])
        self.conn.commit()
        with app.test_request_context(f"/teams/{self.team2}"):
            with patch("routes.stats.render_template") as render:
                team_detail(self.team2)
        self.assertIsNone(render.call_args.kwargs["players"][0]["avg_rating"])

    def test_new_profile_unknown_data_has_no_fake_radar_points(self):
        from app import app

        missing = dict.fromkeys(
            (
                "rating",
                "kills",
                "deaths",
                "assists",
                "rounds_played",
                "kast",
                "impact",
                "adr",
                "headshot_percentage",
                "first_kills",
                "first_deaths",
                "trade_kills",
                "trade_deaths",
                "utility_damage",
                "multi2k",
                "multi3k",
                "multi4k",
                "multi5k",
                "clutches_won",
                "bomb_plants",
                "bomb_defuses",
                "enemies_flashed",
                "flash_count",
            )
        )
        add_stat(self.conn, self.match_id, self.player_id, self.team1, "Mirage", **missing)
        self.conn.commit()
        with patch("routes.players.enrich_player_from_steam", return_value=False):
            response = app.test_client().get(f"/players/{self.player_id}")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("pp-skill-body", html)
        self.assertFalse('class="pp-radar-shape"' in html)
        self.assertFalse('class="pp-radar-dot"' in html)
        self.assertNotIn("--pct:None", html)

    def test_recent_match_uses_recorded_side_not_current_team(self):
        from routes.players import player_detail
        from web_app import app

        add_stat(
            self.conn, self.match_id, self.player_id, self.team2, "Mirage", match_team_side="t1"
        )
        self.conn.commit()
        with app.test_request_context(f"/players/{self.player_id}"):
            with (
                patch("routes.players.enrich_player_from_steam", return_value=False),
                patch("routes.players.render_template") as render,
            ):
                player_detail(self.player_id)
        self.assertEqual(render.call_args.kwargs["recent_matches"][0].get("stat_team_side"), "t1")

    def test_recent_zero_zero_match_is_not_a_loss(self):
        from app import app

        add_stat(self.conn, self.match_id, self.player_id, self.team1, "Mirage")
        self.conn.commit()
        with patch("routes.players.enrich_player_from_steam", return_value=False):
            response = app.test_client().get(f"/players/{self.player_id}")
        self.assertEqual(response.status_code, 200)
        self.assertFalse('class="pp-match-row loss"' in response.get_data(as_text=True))

    def test_new_map_stats_page_accepts_an_unknown_top_rating(self):
        from app import app

        add_stat(
            self.conn,
            self.match_id,
            self.player_id,
            self.team1,
            "Mirage",
            rating=None,
            kills=None,
            deaths=None,
        )
        self.conn.commit()
        response = app.test_client().get("/stats?tab=maps")
        self.assertEqual(response.status_code, 200)
        self.assertFalse("None</b>" in response.get_data(as_text=True))


class FrontendReleasePerfBarsTests(unittest.TestCase):
    averages = {"kpr": 0.7, "dpr": 0.7, "kast": 70, "impact": 1, "rws": 10, "adr": 75}

    def test_unknown_perf_values_have_no_numeric_bar_or_advantage(self):
        from services.perf_overview_service import build_perf_overview

        row = dict.fromkeys(("kpr", "dpr", "kast", "mk_rating", "rws", "adr", "rating"))
        build_perf_overview([row], self.averages)
        self.assertTrue(all(bar["text"] == "-" and bar["pct"] == 0 for bar in row["perf_bars"]))
        self.assertTrue(all(bar["tier"] != "perf-top" for bar in row["perf_bars"]))

    def test_zero_reference_is_not_substituted_by_a_default(self):
        from services.perf_overview_service import build_perf_overview

        row = {"kpr": 0, "dpr": 0, "kast": 0, "mk_rating": 0, "rws": 0, "adr": 0, "rating": 0}
        build_perf_overview([row], dict.fromkeys(self.averages, 0))
        self.assertTrue(all(bar["text"] != "-" for bar in row["perf_bars"]))
        self.assertEqual(next(bar for bar in row["perf_bars"] if bar["label"] == "DPR")["pct"], 0)

    def test_nonfinite_values_are_not_rendered_as_numbers(self):
        from services.perf_overview_service import build_perf_overview

        row = {
            "kpr": float("nan"),
            "dpr": float("inf"),
            "kast": None,
            "mk_rating": None,
            "rws": None,
            "adr": None,
            "rating": None,
        }
        build_perf_overview([row], self.averages)
        self.assertTrue(all(bar["text"] == "-" and bar["pct"] == 0 for bar in row["perf_bars"]))


if __name__ == "__main__":
    unittest.main()
