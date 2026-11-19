import json
import os
import tempfile
import unittest
from contextlib import closing

from werkzeug.security import generate_password_hash

from app import app
from config import Config
from models import get_db, init_tables
from services import map_quiz_service as quiz
from services import player_bingo_service as bingo
from services.map_quiz_service import MAPS, SOURCE_COLLECTION, question_for_key
from services.player_bingo_service import solve_board


class GamesTests(unittest.TestCase):
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
        cursor = conn.execute(
            """INSERT INTO users(
                   username, password_hash, approval_status, group_username, is_bashizhong_student
               ) VALUES(?, ?, 'approved', ?, 1)""",
            ("GamesTester", generate_password_hash("123456"), "GamesTester"),
        )
        self.user_id = cursor.lastrowid
        conn.commit()
        conn.close()

        self.client = app.test_client()
        with self.client.session_transaction() as browser_session:
            browser_session["user_id"] = self.user_id
            browser_session["user_username"] = "GamesTester"
            browser_session["csrf_token"] = "games-test-token"

    def tearDown(self):
        Config.DATABASE = self.original_database
        app.config.update(
            TESTING=self.original_testing,
            SESSION_COOKIE_SECURE=self.original_secure_cookie,
        )
        try:
            os.remove(self.database_path)
        except OSError:
            pass

    def test_games_hub_is_public_but_gameplay_requires_login(self):
        guest = app.test_client()
        hub = guest.get("/games")
        self.assertEqual(hub.status_code, 200)
        html = hub.get_data(as_text=True)
        self.assertIn("/guess-player", html)
        self.assertIn("/map-quiz", html)
        self.assertIn("/player-bingo", html)

        protected = guest.get("/map-quiz")
        self.assertEqual(protected.status_code, 302)
        self.assertIn("/login?next=/map-quiz", protected.headers["Location"])

    def test_quiz_counts_only_daily_wins_and_keeps_yesterdays_streak(self):
        with closing(get_db()) as conn:
            for day in ("2026-05-01", "2026-05-02", "2026-05-03", "2026-05-06", "2026-05-07"):
                game = quiz.get_daily_game_row(conn, self.user_id, day)
                answer = question_for_key(game["question_key"])
                self.assertIsNone(
                    quiz.submit_guess(conn, game, answer["map_key"], answer["spot"])[1]
                )
            practice = quiz.create_practice_game(conn, self.user_id)
            answer = question_for_key(practice["question_key"])
            quiz.submit_guess(conn, practice, answer["map_key"], answer["spot"])
            quiz.get_daily_game_row(conn, self.user_id, "2026-05-08")
            for day, expected in (("2026-05-07", 2), ("2026-05-08", 2), ("2026-05-09", 0)):
                with self.subTest(day=day):
                    self.assertEqual(
                        quiz.user_statistics(conn, self.user_id, day),
                        {
                            "games": 5,
                            "win_rate": 100,
                            "current_streak": expected,
                            "longest_streak": 3,
                        },
                    )

    def test_bingo_counts_a_mistake_but_does_not_commit_the_callers_transaction(self):
        self.client.get("/player-bingo")
        with closing(get_db()) as conn:
            game = bingo.get_daily_game_row(conn, self.user_id)
            board = json.loads(game["board_json"])
            pool = conn.execute("SELECT * FROM guess_players WHERE active=1").fetchall()
            fits = [
                p["id"]
                for p in pool
                if bingo.player_matches(p, board["rows"][0], board["columns"][0])
            ]
            wrong = next(p["id"] for p in pool if p["id"] not in fits)
            state, message = bingo.submit_player(conn, game, 0, 0, wrong)
            self.assertEqual((state["mistakes"], message), (1, "这名选手不同时符合两个条件"))
            conn.execute("BEGIN")
            self.assertIsNone(bingo.submit_player(conn, game, 0, 0, fits[0])[1])
            self.assertEqual(
                bingo.submit_player(conn, game, 0, 0, fits[0])[1], "这个格子已经填过了"
            )
            self.assertTrue(conn.in_transaction)
            conn.rollback()
            fresh = bingo.get_daily_game_row(conn, self.user_id)
            self.assertEqual((fresh["mistakes"], bingo.load_game(conn, fresh)["filled"]), (1, 0))

    def test_map_quiz_hides_file_name_and_finishes_after_three_attempts(self):
        page = self.client.get("/map-quiz")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)

        conn = get_db()
        game_row = conn.execute(
            """SELECT * FROM map_quiz_games
               WHERE user_id=? AND mode='daily'""",
            (self.user_id,),
        ).fetchone()
        conn.close()
        question = question_for_key(game_row["question_key"])
        self.assertNotIn(question["image"], html)
        self.assertIn(game_row["question_key"], html)
        if question["source_url"] != SOURCE_COLLECTION:
            self.assertNotIn(question["source_url"], html)

        image = self.client.get(f"/map-quiz/image/{game_row['question_key']}")
        self.assertEqual(image.status_code, 200)
        self.assertTrue(image.mimetype.startswith("image/"))
        self.assertEqual(image.headers["Cache-Control"], "private, max-age=86400")
        self.assertEqual(self.client.get("/map-quiz/image/../../config.py").status_code, 404)

        wrong_map = next(key for key, _ in MAPS if key != question["map_key"])
        for _ in range(3):
            response = self.client.post(
                "/map-quiz",
                data={
                    "csrf_token": "games-test-token",
                    "map_name": wrong_map,
                    "spot_name": "not-a-real-place",
                },
                follow_redirects=True,
            )
            self.assertEqual(response.status_code, 200)

        conn = get_db()
        finished = conn.execute(
            "SELECT finished, won FROM map_quiz_games WHERE id=?", (game_row["id"],)
        ).fetchone()
        attempt_count = conn.execute(
            "SELECT COUNT(*) FROM map_quiz_attempts WHERE game_id=?", (game_row["id"],)
        ).fetchone()[0]
        conn.close()
        self.assertEqual((finished["finished"], finished["won"]), (1, 0))
        self.assertEqual(attempt_count, 3)
        self.assertIn(question["source_url"], response.get_data(as_text=True))

    def test_map_quiz_rejects_bad_csrf_and_cross_site_post(self):
        self.client.get("/map-quiz")
        bad_csrf = self.client.post(
            "/map-quiz",
            data={"csrf_token": "wrong", "map_name": "nuke", "spot_name": "外场"},
        )
        self.assertEqual(bad_csrf.status_code, 302)

        cross_site = self.client.post(
            "/map-quiz",
            data={"csrf_token": "games-test-token", "map_name": "nuke", "spot_name": "外场"},
            headers={"Sec-Fetch-Site": "cross-site"},
        )
        self.assertEqual(cross_site.status_code, 403)

        conn = get_db()
        count = conn.execute("SELECT COUNT(*) FROM map_quiz_attempts").fetchone()[0]
        conn.close()
        self.assertEqual(count, 0)

    def test_player_bingo_board_is_solvable_and_can_be_completed(self):
        page = self.client.get("/player-bingo")
        self.assertEqual(page.status_code, 200)

        conn = get_db()
        game_row = conn.execute(
            """SELECT * FROM player_bingo_games
               WHERE user_id=? AND mode='daily'""",
            (self.user_id,),
        ).fetchone()
        board = json.loads(game_row["board_json"])
        players = conn.execute(
            """SELECT * FROM guess_players WHERE active=1
               ORDER BY nickname COLLATE NOCASE"""
        ).fetchall()
        conn.close()
        solution = solve_board(players, board["rows"], board["columns"])
        self.assertIsNotNone(solution)
        self.assertEqual(len(solution), 9)
        self.assertEqual(len(set(solution.values())), 9)

        for (row_index, column_index), player_id in solution.items():
            response = self.client.post(
                "/player-bingo",
                data={
                    "csrf_token": "games-test-token",
                    "row_index": str(row_index),
                    "column_index": str(column_index),
                    "player_id": str(player_id),
                },
                follow_redirects=True,
            )
            self.assertEqual(response.status_code, 200)

        conn = get_db()
        result = conn.execute(
            "SELECT finished, lines, mistakes FROM player_bingo_games WHERE id=?",
            (game_row["id"],),
        ).fetchone()
        cell_count = conn.execute(
            "SELECT COUNT(*) FROM player_bingo_cells WHERE game_id=?", (game_row["id"],)
        ).fetchone()[0]
        conn.close()
        self.assertEqual(result["finished"], 1)
        self.assertEqual(result["lines"], 8)
        self.assertEqual(result["mistakes"], 0)
        self.assertEqual(cell_count, 9)

    def test_security_headers_are_present(self):
        response = self.client.get("/games")
        self.assertEqual(response.headers["Cross-Origin-Opener-Policy"], "same-origin-allow-popups")
        self.assertEqual(response.headers["Cross-Origin-Resource-Policy"], "same-site")
        self.assertEqual(response.headers["Origin-Agent-Cluster"], "?1")
        self.assertNotIn("cdn.jsdelivr.net", response.headers["Content-Security-Policy"])


if __name__ == "__main__":
    unittest.main()
