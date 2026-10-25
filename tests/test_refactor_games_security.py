import json
import os
import tempfile
import threading
import unittest
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from app import app
from config import Config
from models import get_db, init_tables
from services.guess_player_service import get_daily_answer
from services.map_quiz_service import MAPS, question_for_key
from services.map_quiz_service import load_game as load_map_quiz_game
from services.player_bingo_service import candidate_ids


class RefactorGamesSecurityTests(unittest.TestCase):
    def setUp(self):
        handle, self.database_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.original_database = Config.DATABASE
        self.original_testing = app.config.get("TESTING")
        self.original_propagate_exceptions = app.config.get("PROPAGATE_EXCEPTIONS")
        self.original_secure_cookie = app.config.get("SESSION_COOKIE_SECURE")
        Config.DATABASE = self.database_path
        app.config.update(
            TESTING=True,
            PROPAGATE_EXCEPTIONS=False,
            SESSION_COOKIE_SECURE=False,
        )
        init_tables()

        conn = get_db()
        self.user_id = self._insert_user(conn, "GameSecurityUser")
        self.other_user_id = self._insert_user(conn, "GameSecurityOther")
        self.third_user_id = self._insert_user(conn, "GameSecurityThird")
        conn.commit()
        conn.close()

    @staticmethod
    def _insert_user(conn, username):
        return conn.execute(
            """INSERT INTO users(username, password_hash, approval_status,
                                 group_username, is_bashizhong_student)
               VALUES(?, ?, 'approved', ?, 1)""",
            (username, generate_password_hash("123456"), username),
        ).lastrowid

    def tearDown(self):
        Config.DATABASE = self.original_database
        app.config.update(
            TESTING=self.original_testing,
            PROPAGATE_EXCEPTIONS=self.original_propagate_exceptions,
            SESSION_COOKIE_SECURE=self.original_secure_cookie,
        )
        try:
            os.remove(self.database_path)
        except OSError:
            pass

    def _client(self, user_id, username, token):
        client = app.test_client()
        with client.session_transaction() as saved:
            saved["user_id"] = user_id
            saved["user_username"] = username
            saved["csrf_token"] = token
        return client

    def _run_parallel_posts(self, path, payloads, load_patch, module_path):
        barrier = threading.Barrier(len(payloads))
        original_load = load_patch

        def pause_after_unlocked_read(conn, *args, **kwargs):
            result = original_load(conn, *args, **kwargs)
            connection_id = id(conn)
            with results_lock:
                first_read = connection_id not in seen_connections
                seen_connections.add(connection_id)
            if first_read and not conn.in_transaction:
                barrier.wait(timeout=8)
            return result

        responses = []
        worker_errors = []
        results_lock = threading.Lock()
        seen_connections = set()

        def post(payload):
            try:
                client = self._client(self.user_id, "GameSecurityUser", "games-security-token")
                response = client.post(path, data=payload)
                with results_lock:
                    responses.append(response.status_code)
            except Exception as exc:  # Keep worker failures visible to the test thread.
                with results_lock:
                    worker_errors.append(exc)

        with patch(module_path, side_effect=pause_after_unlocked_read):
            threads = [threading.Thread(target=post, args=(payload,)) for payload in payloads]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)

        self.assertFalse(any(thread.is_alive() for thread in threads), "并发测试线程未结束")
        self.assertEqual(worker_errors, [])
        return responses

    def test_daily_guess_parallel_submissions_are_serialized(self):
        conn = get_db()
        answer = get_daily_answer(conn)
        guesses = conn.execute(
            "SELECT id FROM guess_players WHERE id<>? AND active=1 ORDER BY id LIMIT 2",
            (answer["id"],),
        ).fetchall()
        conn.close()
        self.assertEqual(len(guesses), 2)

        payloads = [
            {
                "csrf_token": "games-security-token",
                "player_id": str(row["id"]),
                "player_query": "candidate",
            }
            for row in guesses
        ]
        with patch("routes.guess_player.rate_limit", return_value=True):
            statuses = self._run_parallel_posts(
                "/guess-player",
                payloads,
                __import__("routes.guess_player", fromlist=["load_game"]).load_game,
                "routes.guess_player.load_game",
            )

        self.assertEqual(statuses, [302, 302])
        conn = get_db()
        attempts = conn.execute(
            """SELECT attempt_number FROM guess_player_attempts
               WHERE user_id=? ORDER BY attempt_number""",
            (self.user_id,),
        ).fetchall()
        conn.close()
        self.assertEqual([row["attempt_number"] for row in attempts], [1, 2])

    def test_map_quiz_parallel_submissions_are_serialized(self):
        self._client(self.user_id, "GameSecurityUser", "games-security-token").get("/map-quiz")
        conn = get_db()
        game = conn.execute(
            "SELECT * FROM map_quiz_games WHERE user_id=? AND mode='daily'",
            (self.user_id,),
        ).fetchone()
        conn.close()
        question = question_for_key(game["question_key"])
        wrong_map = next(key for key, _ in MAPS if key != question["map_key"])
        payloads = [
            {
                "csrf_token": "games-security-token",
                "map_name": wrong_map,
                "spot_name": f"不存在的地点 {index}",
            }
            for index in range(2)
        ]
        with patch("routes.map_quiz.rate_limit", return_value=True):
            statuses = self._run_parallel_posts(
                "/map-quiz",
                payloads,
                load_map_quiz_game,
                "services.map_quiz_service.load_game",
            )

        self.assertEqual(statuses, [302, 302])
        conn = get_db()
        attempts = conn.execute(
            "SELECT attempt_number FROM map_quiz_attempts WHERE game_id=? ORDER BY attempt_number",
            (game["id"],),
        ).fetchall()
        conn.close()
        self.assertEqual([row["attempt_number"] for row in attempts], [1, 2])

    def test_bingo_parallel_submissions_do_not_overwrite_the_same_cell(self):
        self._client(self.user_id, "GameSecurityUser", "games-security-token").get("/player-bingo")
        conn = get_db()
        game = conn.execute(
            "SELECT * FROM player_bingo_games WHERE user_id=? AND mode='daily'",
            (self.user_id,),
        ).fetchone()
        players = conn.execute("SELECT * FROM guess_players WHERE active=1 ORDER BY id").fetchall()
        conn.close()
        board = json.loads(game["board_json"])
        candidates = candidate_ids(players, board["rows"][0], board["columns"][0])
        self.assertGreaterEqual(len(candidates), 2)
        payloads = [
            {
                "csrf_token": "games-security-token",
                "row_index": "0",
                "column_index": "0",
                "player_id": str(player_id),
            }
            for player_id in candidates[:2]
        ]
        from services.player_bingo_service import load_game

        with patch("routes.player_bingo.rate_limit", return_value=True):
            statuses = self._run_parallel_posts(
                "/player-bingo",
                payloads,
                load_game,
                "services.player_bingo_service.load_game",
            )

        self.assertEqual(statuses, [302, 302])
        conn = get_db()
        cells = conn.execute(
            "SELECT row_index, column_index FROM player_bingo_cells WHERE game_id=?",
            (game["id"],),
        ).fetchall()
        conn.close()
        self.assertEqual(len(cells), 1)
        self.assertEqual((cells[0]["row_index"], cells[0]["column_index"]), (0, 0))

    def test_individual_game_progress_is_not_shared_between_users(self):
        first = self._client(self.user_id, "GameSecurityUser", "games-first-token")
        second = self._client(self.other_user_id, "GameSecurityOther", "games-second-token")
        for client, user_id in ((first, self.user_id), (second, self.other_user_id)):
            self.assertEqual(client.get("/guess-player").status_code, 200)
            self.assertEqual(client.get("/map-quiz").status_code, 200)
            self.assertEqual(client.get("/player-bingo").status_code, 200)
            conn = get_db()
            game_ids = (
                conn.execute(
                    "SELECT id FROM map_quiz_games WHERE user_id=? AND mode='daily'",
                    (user_id,),
                ).fetchone()["id"],
                conn.execute(
                    "SELECT id FROM player_bingo_games WHERE user_id=? AND mode='daily'",
                    (user_id,),
                ).fetchone()["id"],
            )
            conn.close()
            if user_id == self.user_id:
                first_game_ids = game_ids
            else:
                second_game_ids = game_ids

        conn = get_db()
        first_map_game = conn.execute(
            "SELECT * FROM map_quiz_games WHERE id=?", (first_game_ids[0],)
        ).fetchone()
        first_bingo_game = conn.execute(
            "SELECT * FROM player_bingo_games WHERE id=?", (first_game_ids[1],)
        ).fetchone()
        bingo_players = conn.execute("SELECT * FROM guess_players WHERE active=1").fetchall()
        answer = get_daily_answer(conn)
        wrong_player = conn.execute(
            "SELECT id, nickname FROM guess_players WHERE id<>? AND active=1 ORDER BY id LIMIT 1",
            (answer["id"],),
        ).fetchone()
        conn.close()
        question = question_for_key(first_map_game["question_key"])
        wrong_map = next(key for key, _ in MAPS if key != question["map_key"])
        board = json.loads(first_bingo_game["board_json"])
        valid_bingo_player = candidate_ids(bingo_players, board["rows"][0], board["columns"][0])[0]
        first.post(
            "/guess-player",
            data={
                "csrf_token": "games-first-token",
                "player_id": str(wrong_player["id"]),
                "player_query": wrong_player["nickname"],
            },
        )
        with patch("routes.map_quiz.rate_limit", return_value=True):
            first.post(
                "/map-quiz",
                data={
                    "csrf_token": "games-first-token",
                    "map_name": wrong_map,
                    "spot_name": "不存在的点位",
                },
            )
        with patch("routes.player_bingo.rate_limit", return_value=True):
            first.post(
                "/player-bingo",
                data={
                    "csrf_token": "games-first-token",
                    "row_index": "0",
                    "column_index": "0",
                    "player_id": str(valid_bingo_player),
                },
            )
        conn = get_db()
        first_attempts = conn.execute(
            "SELECT COUNT(*) FROM guess_player_attempts WHERE user_id=?", (self.user_id,)
        ).fetchone()[0]
        other_attempts = conn.execute(
            "SELECT COUNT(*) FROM guess_player_attempts WHERE user_id=?", (self.other_user_id,)
        ).fetchone()[0]
        first_map_attempts = conn.execute(
            "SELECT COUNT(*) FROM map_quiz_attempts WHERE game_id=?", (first_game_ids[0],)
        ).fetchone()[0]
        other_map_attempts = conn.execute(
            "SELECT COUNT(*) FROM map_quiz_attempts WHERE game_id=?", (second_game_ids[0],)
        ).fetchone()[0]
        first_bingo_cells = conn.execute(
            "SELECT COUNT(*) FROM player_bingo_cells WHERE game_id=?", (first_game_ids[1],)
        ).fetchone()[0]
        other_bingo_cells = conn.execute(
            "SELECT COUNT(*) FROM player_bingo_cells WHERE game_id=?", (second_game_ids[1],)
        ).fetchone()[0]
        map_ids = {
            row["user_id"]: row["id"]
            for row in conn.execute(
                "SELECT id, user_id FROM map_quiz_games WHERE mode='daily'"
            ).fetchall()
        }
        bingo_ids = {
            row["user_id"]: row["id"]
            for row in conn.execute(
                "SELECT id, user_id FROM player_bingo_games WHERE mode='daily'"
            ).fetchall()
        }
        conn.close()
        self.assertEqual((first_attempts, other_attempts), (1, 0))
        self.assertEqual((first_map_attempts, other_map_attempts), (1, 0))
        self.assertEqual((first_bingo_cells, other_bingo_cells), (1, 0))
        self.assertNotEqual(map_ids[self.user_id], map_ids[self.other_user_id])
        self.assertNotEqual(bingo_ids[self.user_id], bingo_ids[self.other_user_id])
        self.assertNotEqual(first_game_ids[0], second_game_ids[0])
        self.assertNotEqual(first_game_ids[1], second_game_ids[1])

    def test_multiplayer_state_hides_answer_and_opponent_guess_details(self):
        host = self._client(self.user_id, "GameSecurityUser", "games-host-token")
        guest = self._client(self.other_user_id, "GameSecurityOther", "games-guest-token")
        outsider = self._client(self.third_user_id, "GameSecurityThird", "games-third-token")
        with patch("routes.guess_player.rate_limit", return_value=True):
            created = host.post(
                "/guess-player/multiplayer/create",
                data={"csrf_token": "games-host-token", "pool_mode": "noob"},
            )
        room_code = created.headers["Location"].rstrip("/").rsplit("/", 1)[-1]
        with patch("routes.guess_player.rate_limit", return_value=True):
            joined = guest.post(
                "/guess-player/multiplayer/join",
                data={"csrf_token": "games-guest-token", "room_code": room_code},
            )
        self.assertEqual(joined.status_code, 302)

        conn = get_db()
        room = conn.execute(
            "SELECT * FROM guess_player_rooms WHERE room_code=?", (room_code,)
        ).fetchone()
        wrong_player = conn.execute(
            "SELECT id FROM guess_players WHERE active=1 AND noob_eligible=1 AND id<>? LIMIT 1",
            (room["player_id"],),
        ).fetchone()
        conn.close()
        with patch("routes.guess_player.rate_limit", return_value=True):
            host.post(
                f"/api/guess-player/multiplayer/{room_code}/guess",
                json={"player_id": wrong_player["id"]},
                headers={"X-CSRF-Token": "games-host-token"},
            )

        host_state = host.get(f"/api/guess-player/multiplayer/{room_code}/state").get_json()[
            "state"
        ]
        guest_state = guest.get(f"/api/guess-player/multiplayer/{room_code}/state").get_json()[
            "state"
        ]
        outsider_state = outsider.get(f"/api/guess-player/multiplayer/{room_code}/state")
        self.assertIsNone(host_state["answer"])
        self.assertIsNone(guest_state["answer"])
        self.assertEqual(len(host_state["results"]), 1)
        self.assertEqual(guest_state["results"], [])
        self.assertEqual(guest_state["opponent"]["attempts"], 1)
        self.assertEqual(outsider_state.status_code, 404)

    def test_game_routes_reject_player_ids_outside_sqlite_integer_range(self):
        too_large_id = "9223372036854775808"
        client = self._client(self.user_id, "GameSecurityUser", "games-security-token")

        guess_response = client.post(
            "/guess-player",
            data={
                "csrf_token": "games-security-token",
                "player_id": too_large_id,
                "player_query": "",
            },
        )
        unicode_digit_response = client.post(
            "/guess-player",
            data={
                "csrf_token": "games-security-token",
                "player_id": "²",
                "player_query": "",
            },
        )
        bingo_response = client.post(
            "/player-bingo",
            data={
                "csrf_token": "games-security-token",
                "row_index": "0",
                "column_index": "0",
                "player_id": too_large_id,
            },
        )
        bingo_unicode_digit_response = client.post(
            "/player-bingo",
            data={
                "csrf_token": "games-security-token",
                "row_index": "0",
                "column_index": "0",
                "player_id": "²",
            },
        )

        with patch("routes.guess_player.rate_limit", return_value=True):
            created = client.post(
                "/guess-player/multiplayer/create",
                data={"csrf_token": "games-security-token", "pool_mode": "noob"},
            )
        room_code = created.headers["Location"].rstrip("/").rsplit("/", 1)[-1]
        with patch("routes.guess_player.rate_limit", return_value=True):
            joined = self._client(
                self.other_user_id, "GameSecurityOther", "games-other-token"
            ).post(
                "/guess-player/multiplayer/join",
                data={"csrf_token": "games-other-token", "room_code": room_code},
            )
        self.assertEqual(joined.status_code, 302)
        multiplayer_response = client.post(
            f"/api/guess-player/multiplayer/{room_code}/guess",
            json={"player_id": too_large_id},
            headers={"X-CSRF-Token": "games-security-token"},
        )
        malformed_json_response = client.post(
            f"/api/guess-player/multiplayer/{room_code}/guess",
            json=[too_large_id],
            headers={"X-CSRF-Token": "games-security-token"},
        )

        self.assertEqual(guess_response.status_code, 302)
        self.assertEqual(unicode_digit_response.status_code, 302)
        self.assertEqual(bingo_response.status_code, 302)
        self.assertEqual(bingo_unicode_digit_response.status_code, 302)
        self.assertEqual(multiplayer_response.status_code, 400)
        self.assertEqual(malformed_json_response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
