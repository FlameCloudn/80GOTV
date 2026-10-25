import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from app import app
from config import Config
from models import get_db, init_tables
from utils import poster
from utils.stats_display import resolve_match_team_side


class MatchPosterRouteTests(unittest.TestCase):
    def setUp(self):
        handle, self.database_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.original_database = Config.DATABASE
        self.original_testing = app.config.get("TESTING")
        self.original_secure_cookie = app.config.get("SESSION_COOKIE_SECURE")
        Config.DATABASE = self.database_path
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        init_tables()
        conn = get_db()
        event_id = conn.execute("INSERT INTO events(name) VALUES('Poster Route Cup')").lastrowid
        self.player_ids = {
            name: conn.execute("INSERT INTO players(nickname) VALUES(?)", (name,)).lastrowid
            for name in ("LeftOne", "LeftTwo", "RightOne", "RightTwo", "Unknown", "Conflict")
        }
        self.match_id = conn.execute(
            """INSERT INTO matches(event_id,status,bo_format,team1_players,team2_players,
                       team1_score,team2_score,map1,map2,map3,map1_t1,map1_t2)
               VALUES(?,'completed','BO3',?,?,2,0,'de_nuke','de_mirage','de_ancient',13,7)""",
            (
                event_id,
                json.dumps([self.player_ids["LeftOne"], self.player_ids["LeftTwo"]]),
                json.dumps([self.player_ids["RightOne"], self.player_ids["RightTwo"]]),
            ),
        ).lastrowid
        conn.commit()
        conn.close()
        self.client = app.test_client()

    def tearDown(self):
        Config.DATABASE = self.original_database
        app.config.update(
            TESTING=self.original_testing, SESSION_COOKIE_SECURE=self.original_secure_cookie
        )
        os.remove(self.database_path)

    def _stat(self, name, map_name, side, rating, rounds, *, team_id=None, status="final"):
        conn = get_db()
        try:
            conn.execute(
                """INSERT INTO match_stats(match_id,player_id,team_id,match_team_side,
                           map_name,rating,rounds_played,data_status)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (
                    self.match_id,
                    self.player_ids[name],
                    team_id,
                    side,
                    map_name,
                    rating,
                    rounds,
                    status,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _update(self, **values):
        conn = get_db()
        try:
            conn.execute(
                "UPDATE matches SET " + ",".join(f"{key}=?" for key in values) + " WHERE id=?",
                (*values.values(), self.match_id),
            )
            conn.commit()
        finally:
            conn.close()

    def _render(self):
        texts = []
        original_text = ImageDraw.ImageDraw.text

        def record_text(draw, xy, value, *args, **kwargs):
            texts.append(str(value))
            return original_text(draw, xy, value, *args, **kwargs)

        with (
            patch(
                "utils.poster.generate_match_poster", wraps=poster.generate_match_poster
            ) as generate,
            patch.object(ImageDraw.ImageDraw, "text", autospec=True, side_effect=record_text),
        ):
            response = self.client.get(f"/matches/{self.match_id}/poster")
            data = response.get_data()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/png")
        self.assertTrue(data.startswith(b"\x89PNG"))
        with Image.open(io.BytesIO(data)) as image:
            self.assertEqual(image.size, (750, 1050))
            self.assertTrue(any(low != high for low, high in image.getextrema()))
        return generate.call_args.args, texts

    def test_real_route_keeps_temporary_players_on_their_explicit_sides(self):
        self._stat("LeftOne", "de_nuke", "t1", 1.0, 20)
        self._stat("RightOne", "de_nuke", "t2", 0.8, 20)
        args, texts = self._render()
        by_name = {row["nickname"]: row for row in args[2]}
        self.assertEqual(by_name["LeftOne"].get("match_team_side"), "t1")
        self.assertEqual(by_name["RightOne"].get("match_team_side"), "t2")
        self.assertIn("LeftOne", texts)
        self.assertIn("RightOne", texts)

    def test_real_route_uses_recorded_round_weights_and_excludes_superseded_rows(self):
        self._stat("LeftOne", "de_nuke", "t1", 1.0, 10)
        self._stat("LeftOne", "de_mirage", "t1", 2.0, 30)
        self._stat("LeftOne", "de_mirage", "t1", 99.0, 100, status="superseded")
        args, texts = self._render()
        row = next(row for row in args[2] if row["nickname"] == "LeftOne")
        self.assertAlmostEqual(row["rating"], 1.75)
        self.assertIn("1.75", texts)

    def test_unknown_side_is_not_silently_drawn_on_team_two(self):
        self._stat("Unknown", "de_nuke", None, 9.0, 20)
        args, texts = self._render()
        row = next(row for row in args[2] if row["nickname"] == "Unknown")
        self.assertIsNone(resolve_match_team_side(row, args[0]))
        self.assertNotIn("Unknown", texts)
        self.assertNotIn("9.00", texts)

    def test_conflicting_explicit_sides_are_unknown_instead_of_picking_one(self):
        self._stat("Conflict", "de_nuke", "t1", 1.0, 10)
        self._stat("Conflict", "de_mirage", "t2", 2.0, 30)
        args, texts = self._render()
        rows = [row for row in args[2] if row["nickname"] == "Conflict"]
        self.assertEqual(len(rows), 1)
        self.assertIn("match_team_side", rows[0])
        self.assertIsNone(rows[0]["match_team_side"])
        self.assertNotIn("Conflict", texts)

    def test_unknown_rating_stays_none_while_real_zero_is_rendered(self):
        self._stat("LeftTwo", "de_nuke", "t1", None, 20)
        self._stat("RightTwo", "de_nuke", "t2", 0, 20)
        args, texts = self._render()
        rows = {row["nickname"]: row for row in args[2]}
        self.assertIsNone(rows["LeftTwo"]["rating"])
        self.assertEqual(rows["RightTwo"]["rating"], 0)
        self.assertIn("0.00", texts)

    def test_map_scores_preserve_unknowns_and_known_zero_without_inventing_results(self):
        for score1, score2, played in (
            (None, None, False),
            (None, 13, False),
            (0, 13, True),
            (0, 0, True),
        ):
            with self.subTest(scores=(score1, score2)):
                self._update(map1_t1=score1, map1_t2=score2)
                args, _ = self._render()
                score = next(score for score in args[1] if score["name"] == "de_nuke")
                self.assertEqual((score["t1"], score["t2"]), (score1, score2))
                self.assertEqual(score["played"], played)

    def test_inactive_map_cannot_be_marked_played_even_if_old_scores_remain(self):
        self._update(has_map3=0, map3_t1=13, map3_t2=7)
        args, _ = self._render()
        score = next(score for score in args[1] if score["name"] == "de_ancient")
        self.assertEqual((score["t1"], score["t2"]), (13, 7))
        self.assertFalse(score["played"])
