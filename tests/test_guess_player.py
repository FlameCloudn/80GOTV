import os
import tempfile
import unittest
from datetime import date

from werkzeug.security import generate_password_hash

from app import app
from config import Config
from models import get_db, init_tables
from scripts.sync_guess_player_profiles import disambiguate_duplicate_nicknames
from services.guess_player_pool import BLAST_GUESS_PLAYERS
from services.guess_player_service import MAX_GUESSES, compare_players, get_daily_answer


class GuessPlayerTests(unittest.TestCase):
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
                   username, password_hash, approval_status, group_username
               ) VALUES(?, ?, 'approved', ?)""",
            ("GuessTester", generate_password_hash("123456"), "GuessTester"),
        )
        self.user_id = cursor.lastrowid
        conn.commit()
        conn.close()

        self.client = app.test_client()
        with self.client.session_transaction() as browser_session:
            browser_session["user_id"] = self.user_id
            browser_session["user_username"] = "GuessTester"
            browser_session["csrf_token"] = "guess-player-test"

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

    def test_guest_is_sent_to_login(self):
        guest = app.test_client()
        response = guest.get("/guess-player")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login?next=/guess-player", response.headers["Location"])

    def test_page_has_full_pool_without_exposing_daily_answer(self):
        response = self.client.get("/guess-player")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertGreaterEqual(html.count("data-player-id="), 6)
        self.assertIn("advent", html)
        self.assertNotIn("answer_row", html)
        self.assertNotIn("data-answer", html)
        self.assertIn("在 8 次机会内猜出今天的职业选手", html)

    def test_pool_uses_blast_counter_strikle_public_players(self):
        self.assertGreaterEqual(len(BLAST_GUESS_PLAYERS), 300)
        self.assertTrue(
            all(
                "blast_counterstrikle_current_pool"
                in (player.get("eligibility", {}).get("reasons") or [])
                for player in BLAST_GUESS_PLAYERS
            )
        )

        conn = get_db()
        ph1nnn = conn.execute("SELECT active FROM guess_players WHERE nickname='Ph1NNN'").fetchone()
        faze_2018 = conn.execute(
            """SELECT nickname FROM guess_players
               WHERE active=1 AND nickname IN
               ('karrigan','olofmeister','GuardiaN','NiKo','rain')"""
        ).fetchall()
        conn.close()

        self.assertTrue(ph1nnn is None or ph1nnn["active"] == 0)
        self.assertEqual(
            {row["nickname"] for row in faze_2018},
            {"karrigan", "olofmeister", "GuardiaN", "NiKo", "rain"},
        )

    def test_practice_mode_can_start_a_new_round_after_finishing(self):
        first_page = self.client.get("/guess-player/practice")
        self.assertEqual(first_page.status_code, 200)
        self.assertIn("无限重玩", first_page.get_data(as_text=True))

        conn = get_db()
        game = conn.execute(
            """SELECT g.*, p.nickname FROM guess_player_practice_games g
               JOIN guess_players p ON p.id=g.player_id
               WHERE g.user_id=? ORDER BY g.id DESC LIMIT 1""",
            (self.user_id,),
        ).fetchone()
        conn.close()
        result = self.client.post(
            "/guess-player/practice",
            data={
                "csrf_token": "guess-player-test",
                "player_id": str(game["player_id"]),
                "player_query": game["nickname"],
            },
            follow_redirects=True,
        )
        self.assertIn("再来一局", result.get_data(as_text=True))

        restarted = self.client.post(
            "/guess-player/practice/new",
            data={"csrf_token": "guess-player-test"},
            follow_redirects=True,
        )
        self.assertEqual(restarted.status_code, 200)
        self.assertIn('id="guessPlayerForm"', restarted.get_data(as_text=True))

        conn = get_db()
        game_count = conn.execute(
            "SELECT COUNT(*) FROM guess_player_practice_games WHERE user_id=?",
            (self.user_id,),
        ).fetchone()[0]
        conn.close()
        self.assertEqual(game_count, 2)

    def test_practice_mode_has_noob_and_pro_pools(self):
        conn = get_db()
        pro_count = conn.execute("SELECT COUNT(*) FROM guess_players WHERE active=1").fetchone()[0]
        noob_count = conn.execute(
            "SELECT COUNT(*) FROM guess_players WHERE active=1 AND noob_eligible=1"
        ).fetchone()[0]
        conn.close()
        self.assertGreater(pro_count, noob_count)
        self.assertGreater(noob_count, 100)

        noob_page = self.client.get("/guess-player/practice?difficulty=noob")
        self.assertIn("Noob：年度 Top 20", noob_page.get_data(as_text=True))
        conn = get_db()
        noob_game = conn.execute(
            """SELECT g.pool_mode, p.noob_eligible
               FROM guess_player_practice_games g
               JOIN guess_players p ON p.id=g.player_id
               WHERE g.user_id=? ORDER BY g.id DESC LIMIT 1""",
            (self.user_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(noob_game["pool_mode"], "noob")
        self.assertEqual(noob_game["noob_eligible"], 1)

        pro_page = self.client.get("/guess-player/practice?difficulty=pro")
        self.assertIn("Pro：完整选手数据库", pro_page.get_data(as_text=True))
        conn = get_db()
        pro_game = conn.execute(
            """SELECT pool_mode FROM guess_player_practice_games
               WHERE user_id=? ORDER BY id DESC LIMIT 1""",
            (self.user_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(pro_game["pool_mode"], "pro")

    def test_multiplayer_room_syncs_answer_and_finishes_for_both_players(self):
        conn = get_db()
        second_cursor = conn.execute(
            """INSERT INTO users(
                   username, password_hash, approval_status, group_username
               ) VALUES(?, ?, 'approved', ?)""",
            ("GuessOpponent", generate_password_hash("123456"), "GuessOpponent"),
        )
        second_user_id = second_cursor.lastrowid
        conn.commit()
        conn.close()

        created = self.client.post(
            "/guess-player/multiplayer/create",
            data={"csrf_token": "guess-player-test", "pool_mode": "noob"},
        )
        self.assertEqual(created.status_code, 302)
        room_code = created.headers["Location"].rstrip("/").rsplit("/", 1)[-1]

        opponent = app.test_client()
        with opponent.session_transaction() as browser_session:
            browser_session["user_id"] = second_user_id
            browser_session["user_username"] = "GuessOpponent"
            browser_session["csrf_token"] = "guess-opponent-test"
        joined = opponent.post(
            "/guess-player/multiplayer/join",
            data={"csrf_token": "guess-opponent-test", "room_code": room_code},
        )
        self.assertEqual(joined.status_code, 302)

        conn = get_db()
        room = conn.execute(
            "SELECT * FROM guess_player_rooms WHERE room_code=?", (room_code,)
        ).fetchone()
        answer = conn.execute(
            "SELECT * FROM guess_players WHERE id=?", (room["player_id"],)
        ).fetchone()
        conn.close()
        self.assertEqual(room["status"], "active")
        self.assertEqual(room["pool_mode"], "noob")
        self.assertEqual(answer["noob_eligible"], 1)

        host_state = self.client.get(f"/api/guess-player/multiplayer/{room_code}/state").get_json()[
            "state"
        ]
        self.assertIsNone(host_state["answer"])
        self.assertEqual(host_state["opponent"]["username"], "GuessOpponent")

        solved = self.client.post(
            f"/api/guess-player/multiplayer/{room_code}/guess",
            json={"player_id": answer["id"]},
            headers={
                "X-CSRF-Token": "guess-player-test",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        self.assertEqual(solved.status_code, 200)
        self.assertEqual(solved.get_json()["state"]["outcome"], "win")
        guest_state = opponent.get(f"/api/guess-player/multiplayer/{room_code}/state").get_json()[
            "state"
        ]
        self.assertEqual(guest_state["outcome"], "loss")
        self.assertEqual(guest_state["answer"]["nickname"], answer["nickname"])

    def test_valid_guess_is_saved_and_duplicate_is_rejected(self):
        conn = get_db()
        answer = get_daily_answer(conn)
        guessed = conn.execute(
            "SELECT * FROM guess_players WHERE id<>? ORDER BY id LIMIT 1",
            (answer["id"],),
        ).fetchone()
        conn.close()

        payload = {
            "csrf_token": "guess-player-test",
            "player_id": str(guessed["id"]),
            "player_query": guessed["nickname"],
        }
        first = self.client.post("/guess-player", data=payload)
        self.assertEqual(first.status_code, 302)
        second = self.client.post("/guess-player", data=payload)
        self.assertEqual(second.status_code, 302)

        conn = get_db()
        count = conn.execute(
            "SELECT COUNT(*) FROM guess_player_attempts WHERE user_id=?",
            (self.user_id,),
        ).fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)

    def test_correct_guess_finishes_game_and_reveals_answer(self):
        conn = get_db()
        answer = get_daily_answer(conn)
        conn.close()

        response = self.client.post(
            "/guess-player",
            data={
                "csrf_token": "guess-player-test",
                "player_id": str(answer["id"]),
                "player_query": answer["nickname"],
            },
            follow_redirects=True,
        )
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("猜对了", html)
        self.assertIn(answer["full_name"], html)
        self.assertIn('id="guessCountdown"', html)
        self.assertIn('id="guessShareScore"', html)
        self.assertNotIn('id="guessPlayerForm"', html)

    def test_game_stops_after_eight_wrong_guesses(self):
        conn = get_db()
        for index in range(MAX_GUESSES + 1):
            conn.execute(
                """INSERT OR IGNORE INTO guess_players(
                       nickname, full_name, team, country_code, country_name,
                       birth_date, role, major_appearances, active
                   ) VALUES(?,?,?,?,?,?,?,?,1)""",
                (f"TestPlayer{index}", f"Test Player {index}", "Test Team", "", "", "", "", -1),
            )
        conn.commit()
        answer = get_daily_answer(conn)
        wrong_players = conn.execute(
            "SELECT * FROM guess_players WHERE id<>? ORDER BY id LIMIT ?",
            (answer["id"], MAX_GUESSES),
        ).fetchall()
        conn.close()

        for player in wrong_players:
            self.client.post(
                "/guess-player",
                data={
                    "csrf_token": "guess-player-test",
                    "player_id": str(player["id"]),
                    "player_query": player["nickname"],
                },
            )

        page = self.client.get("/guess-player").get_data(as_text=True)
        self.assertIn("今天未猜中", page)
        self.assertIn(answer["full_name"], page)
        self.assertNotIn('id="guessPlayerForm"', page)

        extra = self.client.post(
            "/guess-player",
            data={
                "csrf_token": "guess-player-test",
                "player_id": str(answer["id"]),
                "player_query": answer["nickname"],
            },
        )
        self.assertEqual(extra.status_code, 302)
        conn = get_db()
        count = conn.execute(
            "SELECT COUNT(*) FROM guess_player_attempts WHERE user_id=?",
            (self.user_id,),
        ).fetchone()[0]
        conn.close()
        self.assertEqual(count, MAX_GUESSES)

    def test_comparison_marks_close_age_and_higher_answer(self):
        conn = get_db()
        guessed = conn.execute("SELECT * FROM guess_players WHERE nickname='NiKo'").fetchone()
        answer = conn.execute("SELECT * FROM guess_players WHERE nickname='rain'").fetchone()
        conn.close()

        result = compare_players(guessed, answer, date(2026, 7, 14))
        self.assertEqual(result["age_feedback"]["state"], "close")
        self.assertEqual(result["age_feedback"]["direction"], "up")
        self.assertEqual(result["country_state"], "close")
        self.assertEqual(result["country_flag"], "🇧🇦")

    def test_duplicate_nicknames_are_disambiguated_without_dropping_players(self):
        players = [
            {"nickname": "AdreN", "country_code": "KZ", "profile_id": 334},
            {"nickname": "adreN", "country_code": "US", "profile_id": 7433},
        ]
        result = disambiguate_duplicate_nicknames(players)
        self.assertEqual(len(result), 2)
        self.assertEqual(
            {player["nickname"] for player in result},
            {"AdreN", "adreN [US]"},
        )
        self.assertEqual(len({player["nickname"].casefold() for player in result}), 2)

    def test_role_and_no_team_status_use_hltv_fields(self):
        conn = get_db()
        zywoo = conn.execute("SELECT * FROM guess_players WHERE nickname='ZywOo'").fetchone()
        niko = conn.execute("SELECT * FROM guess_players WHERE nickname='NiKo'").fetchone()
        free_agent = conn.execute(
            "SELECT * FROM guess_players WHERE active=1 AND player_status='free_agent' LIMIT 1"
        ).fetchone()
        retired = conn.execute(
            "SELECT * FROM guess_players WHERE active=1 AND player_status='retired' LIMIT 1"
        ).fetchone()
        conn.close()
        self.assertEqual(zywoo["role"], "awper")
        self.assertEqual(niko["role"], "rifler")
        result = compare_players(free_agent, retired)
        self.assertEqual(result["team_state"], "correct")
        self.assertEqual(result["affiliation"], "Free Agent")


if __name__ == "__main__":
    unittest.main()
