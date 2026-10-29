import unittest

from flask import template_rendered

from app import app
from services.perf_overview_service import build_perf_overview
from tests.test_refactor_stats_consistency import StatsDatabaseCase, add_stat


class MatchStatsDisplayFixTests(StatsDatabaseCase):
    def setUp(self):
        super().setUp()
        original = app.config.copy()
        self.addCleanup(app.config.update, original)
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False, TRUSTED_HOSTS=None)
        self.conn.execute(
            "UPDATE matches SET bo_format='BO1',map1='de_dust2',map1_t1=13,map1_t2=10,"
            "team1_score=1,team2_score=0 WHERE id=?",
            (self.match_id,),
        )
        self.other_player = self.conn.execute(
            "INSERT INTO players(nickname,team_id) VALUES('Other Player',?)", (self.team2,)
        ).lastrowid
        for pid, team, rating in (
            (self.player_id, self.team1, 1.96),
            (self.other_player, self.team2, 1.76),
        ):
            add_stat(
                self.conn,
                self.match_id,
                pid,
                team,
                "Dust2",
                kills=19,
                deaths=15,
                assists=6,
                adr=91.3,
                kast=87,
                rating=rating,
                rounds_played=23,
                first_kills=1,
                first_deaths=3,
                clutches_won=0,
                headshot_percentage=40,
                t_kills=7,
                t_deaths=10,
                t_adr=65,
                t_rating=0.75,
                ct_kills=12,
                ct_deaths=5,
                ct_adr=120,
                ct_rating=2.1,
            )
        self.conn.commit()

    def context(self, suffix="/detailed?map=1"):
        contexts = []

        def capture(sender, template, context, **kwargs):
            contexts.append(context)

        with template_rendered.connected_to(capture, app):
            response = app.test_client().get(
                f"/matches/{self.match_id}{suffix}", follow_redirects=True
            )
        self.assertEqual(response.status_code, 200)
        return contexts[-1], response.get_data(as_text=True)

    def test_map_alias_keeps_stats_in_both_match_pages(self):
        main, html = self.context("")
        self.assertTrue(main["map_scores"][0]["has_stats"])
        self.assertIn('class="ms-stats-btn"', html)
        detailed, _ = self.context()
        self.assertEqual(len(detailed["performance_rows"]), 2)
        self.assertEqual(detailed["summary"]["t1"]["kills"], 19)

    def test_map_name_query_and_number_query_select_the_same_data(self):
        by_name, _ = self.context("/detailed?map=de_dust2")
        by_number, _ = self.context()
        self.assertEqual(by_name["selected_map_index"], 1)
        self.assertEqual(by_name["performance_rows"], by_number["performance_rows"])

    def test_high_ratings_have_distinct_widths_and_a_matching_scale(self):
        context, html = self.context("/detailed?map=all")
        first, second = context["performance_rows"]
        self.assertGreater(first["rating_bar"], second["rating_bar"])
        self.assertLessEqual(first["rating_bar"], 100)
        self.assertGreaterEqual(context["rating_scale"]["maximum"], 1.96)
        self.assertIn("--rating-average", html)

    def test_legacy_match_chart_also_rescales_high_values(self):
        self.conn.execute("UPDATE match_stats SET rating=2.4 WHERE player_id=?", (self.player_id,))
        self.conn.execute(
            "UPDATE match_stats SET rating=2.1 WHERE player_id=?", (self.other_player,)
        )
        self.conn.commit()
        context, _ = self.context("/stats")
        first, second = context["match_performance_rows"]
        self.assertGreater(first["rating_bar"], second["rating_bar"])

    def test_side_views_do_not_repeat_overall_kills_and_unknown_metrics(self):
        context, html = self.context()
        player = context["team1_rows"][0]
        self.assertEqual(player["side_views"]["overall"]["kills"], 19)
        self.assertEqual(player["side_views"]["t"]["kills"], 7)
        self.assertEqual(player["side_views"]["ct"]["kills"], 12)
        self.assertIsNone(player["side_views"]["t"].get("assists"))
        self.assertIsNone(player["side_views"]["ct"].get("kast"))
        self.assertIn("data-side-values=", html)
        self.assertIn("match_stats_views.js", html)

    def test_unrecorded_legacy_side_zero_is_not_presented_as_a_real_half(self):
        self.conn.execute(
            "UPDATE match_stats SET t_kills=0,t_deaths=0,t_adr=0,t_rating=0,"
            "ct_kills=0,ct_deaths=0,ct_adr=0,ct_rating=0"
        )
        self.conn.commit()
        for suffix in ("/detailed?map=all", "/detailed?map=1", ""):
            context, _ = self.context(suffix)
            players = context.get("team1_rows", context.get("overall_t1"))
            self.assertIsNone(players[0]["t_rating"])
            self.assertIsNone(players[0]["ct_kills"])

    def test_actual_zero_side_rating_is_kept_when_the_half_has_recorded_data(self):
        self.conn.execute(
            "UPDATE match_stats SET t_rating=0,t_kills=0 WHERE player_id=?", (self.player_id,)
        )
        self.conn.commit()
        context, _ = self.context("/detailed?map=all")
        player = context["team1_rows"][0]
        self.assertEqual(player["t_rating"], 0)
        self.assertEqual(player["side_views"]["t"]["kills"], 0)


class PerformanceScaleFixTests(unittest.TestCase):
    def test_values_above_twice_average_do_not_all_fill_the_track(self):
        rows = [{"rating": 2.4}, {"rating": 3.0}]
        build_perf_overview(rows, {})
        bars = [next(bar for bar in row["perf_bars"] if bar["label"] == "Rating") for row in rows]
        self.assertLess(bars[0]["pct"], bars[1]["pct"])

    def test_zero_deaths_is_not_worse_than_a_small_positive_death_rate(self):
        rows = [{"dpr": 0}, {"dpr": 0.1}]
        build_perf_overview(rows, {"dpr": 0.7})
        bars = [next(bar for bar in row["perf_bars"] if bar["label"] == "DPR") for row in rows]
        self.assertGreater(bars[0]["pct"], bars[1]["pct"])
