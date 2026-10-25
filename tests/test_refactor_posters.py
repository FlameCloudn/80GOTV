import importlib
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from services.award_service import build_event_award_poster
from tests.test_refactor_stats_consistency import StatsDatabaseCase, add_stat
from utils.award_poster import _draw_radar, generate_award_poster
from utils.poster import generate_match_poster


class PosterDisplayHelpersTests(unittest.TestCase):
    def test_optional_number_rejects_missing_and_nonfinite_but_keeps_zero(self):
        display = importlib.import_module("utils.stats_display")
        for value in (None, "", "bad", float("nan"), float("inf"), "-Infinity", True):
            with self.subTest(value=value):
                self.assertIsNone(display.optional_number(value))
        self.assertEqual(display.optional_number(0), 0)
        self.assertEqual(display.optional_number("0"), 0)
        self.assertEqual(display.optional_number(-1.5), -1.5)

    def test_format_stat_keeps_known_zero_and_marks_unknown(self):
        display = importlib.import_module("utils.stats_display")
        self.assertEqual(display.format_stat(None, 2), "-")
        self.assertEqual(display.format_stat(float("nan"), 1, suffix="%"), "-")
        self.assertEqual(display.format_stat(0, 2), "0.00")
        self.assertEqual(display.format_stat(0, 0, suffix="%"), "0%")
        self.assertEqual(display.format_stat(-1.25, 2, signed=True), "-1.25")

    def test_side_resolution_never_guesses_unknown_or_ambiguous_side(self):
        display = importlib.import_module("utils.stats_display")
        match = {"team1_id": 10, "team2_id": 20}
        self.assertIsNone(display.resolve_match_team_side({"team_id": None}, match))
        self.assertIsNone(display.resolve_match_team_side({"team_id": 99}, match))
        self.assertEqual(
            display.resolve_match_team_side({"match_team_side": " T1 ", "team_id": 20}, match), "t1"
        )
        self.assertEqual(
            display.resolve_match_team_side({"team_id": -2}, {"team1_id": None, "team2_id": None}),
            "t2",
        )
        self.assertIsNone(
            display.resolve_match_team_side({"team_id": 10}, {"team1_id": 10, "team2_id": 10})
        )


class AwardPosterDataTests(StatsDatabaseCase):
    def capture_data(self, **values):
        add_stat(
            self.conn,
            self.match_id,
            self.player_id,
            values.pop("team_id", self.team1),
            values.pop("map_name", "Mirage"),
            **values,
        )
        self.conn.execute("UPDATE matches SET map1_t1=13, map1_t2=7 WHERE id=?", (self.match_id,))
        with patch("services.award_service.generate_award_poster") as generate:
            build_event_award_poster(self.conn, ".", self.event_id, self.player_id)
        return generate.call_args.args

    def test_service_keeps_missing_metrics_instead_of_zero(self):
        args = self.capture_data(
            kills=None,
            deaths=None,
            rating=None,
            adr=None,
            kast=None,
            impact=None,
            rounds_played=20,
            rws_basic=None,
        )
        for name in (
            "kills",
            "deaths",
            "rating",
            "adr",
            "kast",
            "impact",
            "kd",
            "kpr",
            "dpr",
            "rws_basic",
        ):
            self.assertIsNone(args[3][name], name)

    def test_explicit_match_side_and_map_alias_resolve_historical_scores(self):
        args = self.capture_data(team_id=None, match_team_side="t1", map_name=" de_mirage ")
        row = args[4][0]
        self.assertEqual((row["score_for"], row["score_against"], row["opponent"]), (13, 7, "B"))
        self.assertEqual(args[1]["team_short"], "A")

    def test_unknown_side_is_not_assumed_to_be_second_team(self):
        args = self.capture_data(team_id=None)
        row = args[4][0]
        self.assertIsNone(row["score_for"])
        self.assertIsNone(row["score_against"])
        self.assertIsNone(row["opponent"])

    def test_unmatched_map_is_unknown_instead_of_zero_score(self):
        args = self.capture_data(map_name="UnknownMap")
        row = args[4][0]
        self.assertIsNone(row["score_for"])
        self.assertIsNone(row["score_against"])


class PosterRenderingTests(unittest.TestCase):
    def render_with_texts(self, callback):
        original = ImageDraw.ImageDraw.text
        texts = []

        def recording(draw, xy, value, *args, **kwargs):
            texts.append(str(value))
            return original(draw, xy, value, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "text", autospec=True, side_effect=recording):
            result = callback()
        self.assertTrue(result.getvalue().startswith(b"\x89PNG"))
        return texts

    def test_award_unknown_values_are_dashes_not_zero_or_full_dpr_radar(self):
        from utils import award_poster

        stats = {
            key: None
            for key in (
                "maps",
                "kills",
                "deaths",
                "rating",
                "adr",
                "kast",
                "impact",
                "kd",
                "kpr",
                "dpr",
                "two_k_pct",
                "one_k_pct",
                "rws_basic",
                "dmg_delta",
                "kills_delta",
            )
        }
        row = {
            "map_name": "Mirage",
            "score_for": None,
            "score_against": None,
            "kills": None,
            "deaths": None,
            "rating": None,
        }
        with patch("utils.award_poster._draw_radar", wraps=award_poster._draw_radar) as radar:
            texts = self.render_with_texts(
                lambda: generate_award_poster(
                    ".", {"nickname": "Audit"}, {"name": "Audit Cup"}, stats, [row], "MVP"
                )
            )
        self.assertNotIn("0-0", texts)
        self.assertNotIn("0.00", texts)
        self.assertIn("-", texts)
        self.assertTrue(all(dimension[2] is None for dimension in radar.call_args.args[3]))

    def test_known_zero_award_values_are_retained(self):
        stats = {
            key: 0
            for key in (
                "maps",
                "kills",
                "deaths",
                "rating",
                "adr",
                "kast",
                "impact",
                "kd",
                "kpr",
                "dpr",
                "two_k_pct",
                "one_k_pct",
                "rws_basic",
                "dmg_delta",
                "kills_delta",
            )
        }
        row = {
            "map_name": "Mirage",
            "score_for": 0,
            "score_against": 0,
            "kills": 0,
            "deaths": 0,
            "rating": 0,
        }
        texts = self.render_with_texts(
            lambda: generate_award_poster(
                ".", {"nickname": "Audit"}, {"name": "Audit Cup"}, stats, [row], "MVP"
            )
        )
        self.assertIn("0-0", texts)
        self.assertIn("0.00", texts)

    def test_missing_radar_axes_do_not_create_polygon_values(self):
        canvas = Image.new("RGB", (400, 400))
        draw = ImageDraw.Draw(canvas, "RGBA")
        dimensions = [("Known", "0.00", 0), ("Missing", "-", None), ("Invalid", "-", float("nan"))]
        with patch.object(draw, "polygon", wraps=draw.polygon) as polygon:
            _draw_radar(draw, (200, 200), 50, dimensions, (200, 160, 80))
        self.assertFalse(
            any(call.kwargs.get("fill") is not None for call in polygon.call_args_list)
        )

    def test_match_missing_scores_and_ratings_are_not_fabricated_zero(self):
        match = {"team1_id": 10, "team2_id": 20, "team1_score": None, "team2_score": None}
        texts = self.render_with_texts(
            lambda: generate_match_poster(
                match,
                [{"name": "Mirage", "played": True, "t1": None, "t2": None}],
                [{"team_id": 10, "nickname": "Audit", "rating": None}],
            )
        )
        self.assertNotIn("0 : 0", texts)
        self.assertNotIn("0.00", texts)
        self.assertIn("- : -", texts)

    def test_match_ratings_use_explicit_side_and_do_not_assign_unknown_player(self):
        match = {"team1_id": 10, "team2_id": 20, "team1_score": 0, "team2_score": 0}
        ratings = [
            {"match_team_side": "t1", "team_id": None, "nickname": "Explicit side", "rating": 0},
            {"team_id": 99, "nickname": "Unknown side", "rating": 1.0},
        ]
        texts = self.render_with_texts(lambda: generate_match_poster(match, [], ratings))
        self.assertIn("Explicit side", texts)
        self.assertNotIn("Unknown side", texts)
        self.assertIn("0 : 0", texts)
        self.assertIn("0.00", texts)
