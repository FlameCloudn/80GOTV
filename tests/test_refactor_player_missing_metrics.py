import re
from unittest.mock import patch

from flask import template_rendered

from app import app
from tests import test_refactor_stats_consistency as stats_tests


class PlayerMissingMetricRouteTests(stats_tests.StatsDatabaseCase):
    metric_fields = (
        "kills",
        "deaths",
        "assists",
        "rating",
        "adr",
        "kast",
        "headshot_percentage",
        "kpr",
        "dpr",
        "impact",
        "t_rating",
        "ct_rating",
        "rounds_played",
        "first_kills",
        "first_deaths",
        "multi1k",
        "multi2k",
        "multi3k",
        "multi4k",
        "multi5k",
        "trade_kills",
        "trade_deaths",
        "clutches_won",
        "utility_damage",
        "utility_damage_per_round",
        "enemies_flashed",
        "flash_count",
        "bomb_plants",
        "bomb_defuses",
        "damage_delta_per_round",
        "rws_basic",
    )

    def setUp(self):
        super().setUp()
        self.old_testing = app.config.get("TESTING")
        app.config.update(TESTING=True)
        self.client = app.test_client()
        self.stat_id = None

    def tearDown(self):
        app.config.update(TESTING=self.old_testing)
        super().tearDown()

    def _set_metrics(self, default, **overrides):
        values = {field: default for field in self.metric_fields}
        values.update(overrides)
        if self.stat_id is None:
            data = {
                "match_id": self.match_id,
                "player_id": self.player_id,
                "team_id": self.team2,
                "match_team_side": "t2",
                "map_name": "Mirage",
                **values,
            }
            self.stat_id = self.conn.execute(
                f"INSERT INTO match_stats({','.join(data)}) VALUES({','.join('?' for _ in data)})",
                tuple(data.values()),
            ).lastrowid
        else:
            self.conn.execute(
                "UPDATE match_stats SET "
                + ",".join(f"{field}=?" for field in values)
                + " WHERE id=?",
                (*values.values(), self.stat_id),
            )
        self.conn.commit()

    def _page(self, detail):
        captured = []

        def capture(_sender, template, context, **_extra):
            if template.name in ("player_detail.html", "player_stats.html"):
                captured.append(context)

        before = tuple(
            self.conn.execute("SELECT * FROM match_stats WHERE id=?", (self.stat_id,)).fetchone()
        )
        template_rendered.connect(capture, app)
        try:
            with patch("routes.players.enrich_player_from_steam", return_value=False):
                prefix = "/stats/players" if detail else "/players"
                response = self.client.get(f"{prefix}/{self.player_id}")
        finally:
            template_rendered.disconnect(capture, app)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(captured), 1)
        after = tuple(
            self.conn.execute("SELECT * FROM match_stats WHERE id=?", (self.stat_id,)).fetchone()
        )
        self.assertEqual(before, after)
        return captured[0], response.get_data(as_text=True)

    def test_all_null_raw_metrics_remain_unknown_on_both_real_pages(self):
        self._set_metrics(None)
        for detail in (False, True):
            with self.subTest(detail=detail):
                context, _ = self._page(detail)
                summary = context["player_summary"]
                for field in ("rating", "rounds", "kpr", "dpr", "multi_kill"):
                    self.assertIsNone(summary[field], field)
                for card in context["player_category_cards"]:
                    self.assertIsNone(card["score"], card["title"])
                    self.assertTrue(
                        all(item["value"] == "-" for item in card["items"]), card["title"]
                    )
                    self.assertTrue(all(item["pct"] == 0 for item in card["items"]))
                statistics = {item["label"]: item["value"] for item in context["player_statistics"]}
                for label in (
                    "总击杀",
                    "总死亡",
                    "总回合",
                    "每回合助攻",
                    "每回合击杀",
                    "每回合死亡",
                ):
                    self.assertEqual(statistics[label], "-", label)

    def test_known_counter_zero_and_overall_rating_zero_are_not_hidden(self):
        self._set_metrics(0, rounds_played=20)
        for detail in (False, True):
            with self.subTest(detail=detail):
                context, html = self._page(detail)
                self.assertEqual(context["player_summary"]["rating"], 0)
                self.assertEqual(context["player_summary"]["multi_kill"], 0)
                self.assertTrue(
                    all(card["score"] == 0 for card in context["player_category_cards"])
                )
                statistics = {item["label"]: item["value"] for item in context["player_statistics"]}
                self.assertEqual(statistics["总击杀"], "0")
                self.assertEqual(statistics["总死亡"], "0")
                self.assertEqual(statistics["每回合助攻"], "0.00")
                self.assertTrue("0.00" in html)

    def test_known_inputs_keep_the_existing_category_formulas(self):
        self._set_metrics(
            0,
            rounds_played=20,
            kills=20,
            deaths=10,
            assists=4,
            rating=1.2,
            adr=90,
            first_kills=5,
            first_deaths=3,
            trade_kills=5,
            trade_deaths=4,
            clutches_won=2,
            utility_damage=100,
            enemies_flashed=8,
            flash_count=10,
            multi2k=2,
            multi3k=1,
        )
        profile, _ = self._page(False)
        detail, _ = self._page(True)
        self.assertEqual(
            [card["score"] for card in profile["player_category_cards"]], [67, 93, 94, 83, 100, 100]
        )
        self.assertEqual(profile["player_category_cards"], detail["player_category_cards"])
        self.assertEqual(profile["player_summary"]["multi_kill"], 15)

    def test_one_unknown_required_input_only_removes_affected_derived_values(self):
        self._set_metrics(
            0,
            rounds_played=20,
            kills=20,
            deaths=10,
            rating=1.2,
            adr=90,
            first_kills=4,
            first_deaths=None,
        )
        for detail in (False, True):
            with self.subTest(detail=detail):
                context, _ = self._page(detail)
                cards = {card["title"]: card for card in context["player_category_cards"]}
                self.assertIsNone(cards["突破"]["score"])
                self.assertIsNone(cards["开局"]["score"])
                self.assertIsNotNone(cards["火力"]["score"])
                opening = {item["label"]: item["value"] for item in cards["开局"]["items"]}
                self.assertEqual(opening["每回合首杀"], "0.20")
                self.assertEqual(opening["首杀对枪胜率"], "-")
                self.assertEqual(opening["每回合首死"], "-")

    def test_unknown_scores_render_as_dash_while_bar_geometry_remains_numeric(self):
        self._set_metrics(None)
        _, profile_html = self._page(False)
        _, detail_html = self._page(True)
        profile_scores = re.findall(r"<b>([^<]+)<small>/100</small>", profile_html)
        detail_scores = re.findall(
            r'class="pd-category-score">([^<]+)<small>/100</small>', detail_html
        )
        self.assertEqual(profile_scores, ["-"] * 6)
        self.assertTrue(detail_scores and all(score == "-" for score in detail_scores))
        self.assertFalse("--pct:None" in profile_html + detail_html)
        self.assertTrue("<dt>MULTI-KILL</dt><dd>-</dd>" in detail_html)

    def test_recent_match_kda_text_distinguishes_unknown_from_real_zero(self):
        self._set_metrics(None)
        for detail in (False, True):
            with self.subTest(detail=detail, value="unknown"):
                _, html = self._page(detail)
                values = re.findall(r"<td(?:\s[^>]*)?>([\w-]+)</td>", html)
                self.assertNotIn("None-None-None", values)
                self.assertIn("-----", values)
        self._set_metrics(0, rounds_played=20)
        for detail in (False, True):
            with self.subTest(detail=detail, value="zero"):
                _, html = self._page(detail)
                values = re.findall(r"<td(?:\s[^>]*)?>([\w-]+)</td>", html)
                self.assertIn("0-0-0", values)
