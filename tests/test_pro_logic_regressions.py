import json
import os
import secrets
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from flask import session

from app import app
from blueprints import admin_matches
from config import Config
from models import get_db, init_tables
from routes.stats import _current_filters, _map_statistics
from services.bracket_service import build_event_bracket
from services.guess_player_service import create_practice_game, get_daily_answer, load_practice_game
from services.live_log_service import load_match_timeline, persist_live_match_events


class ProDatabaseCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="80gotv-pro-logic-")
        cls.baseline = str(Path(cls.temp.name) / "baseline.db")
        original = Config.DATABASE
        try:
            Config.DATABASE = cls.baseline
            init_tables()
        finally:
            Config.DATABASE = original

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.database_path = str(Path(self.temp.name) / f"{self._testMethodName}.db")
        with (
            closing(sqlite3.connect(self.baseline)) as source,
            closing(sqlite3.connect(self.database_path)) as target,
        ):
            source.backup(target)
        self.original_database = Config.DATABASE
        self.original_config = {
            name: app.config.get(name)
            for name in ("TESTING", "PROPAGATE_EXCEPTIONS", "SESSION_COOKIE_SECURE", "SECRET_KEY")
        }
        Config.DATABASE = self.database_path
        app.config.update(
            TESTING=True,
            PROPAGATE_EXCEPTIONS=False,
            SESSION_COOKIE_SECURE=False,
            SECRET_KEY=secrets.token_urlsafe(48),
        )
        self.conn = get_db()
        self.event_id = self.conn.execute("INSERT INTO events(name) VALUES('Pro Cup')").lastrowid
        self.other_event_id = self.conn.execute(
            "INSERT INTO events(name) VALUES('Other Cup')"
        ).lastrowid
        self.team_ids = [
            self.conn.execute(
                "INSERT INTO teams(name,short_name) VALUES(?,?)", (f"Pro Team {i}", f"P{i}")
            ).lastrowid
            for i in range(4)
        ]
        self.player_id = self.conn.execute(
            "INSERT INTO players(nickname,steam_id,team_id) VALUES('Pro Player','111',?)",
            (self.team_ids[0],),
        ).lastrowid
        self.user_id = self.conn.execute(
            """INSERT INTO users(username,password_hash,group_username,approval_status,
                                 is_bashizhong_student)
               VALUES('Pro User','not-a-login-hash','Pro Group','approved',0)"""
        ).lastrowid
        self.match_id = self.conn.execute(
            """INSERT INTO matches(event_id,team1_id,team2_id,match_time,status,bo_format,
                                   map1,map1_t1,map1_t2)
               VALUES(?,?,?,'2030-01-01T18:00','live','BO3','de_nuke',5,4)""",
            (self.event_id, self.team_ids[0], self.team_ids[1]),
        ).lastrowid
        self.conn.commit()
        self.client = app.test_client()
        with self.client.session_transaction() as saved:
            saved["admin_id"] = 1
            saved["csrf_token"] = "pro-logic-csrf"

    def tearDown(self):
        self.conn.close()
        Config.DATABASE = self.original_database
        app.config.update(self.original_config)
        os.remove(self.database_path)

    def _user_client(self):
        client = app.test_client()
        with client.session_transaction() as saved:
            saved["user_id"] = self.user_id
            saved["user_username"] = "Pro User"
            saved["csrf_token"] = "pro-logic-csrf"
        return client

    def _edit(self, **values):
        payload = {
            "csrf_token": "pro-logic-csrf",
            "event_id": str(self.event_id),
            "match_time": "2030-01-01T18:00",
            "bo_format": "BO3",
            "status": "live",
            **values,
        }
        return self.client.post(f"/admin/matches/edit/{self.match_id}", data=payload)

    def _map_stats(self):
        with app.test_request_context("/stats?tab=maps"):
            return _map_statistics(self.conn, _current_filters())

    def _add_map_stat(self, *, kills=20, deaths=9):
        self.conn.execute(
            """INSERT INTO match_stats(match_id,player_id,team_id,map_name,kills,deaths,rating)
               VALUES(?,?,?,'de_nuke',?,?,1.5)""",
            (self.match_id, self.player_id, self.team_ids[0], kills, deaths),
        )
        self.conn.commit()


class ProLogicRegressionTests(ProDatabaseCase):
    def test_regular_edit_does_not_overwrite_scores_written_after_its_read(self):
        original = admin_matches._preserve_managed_match_fields
        halves = json.dumps({"0": {"h1_t1": 6, "h1_t2": 4}})
        changed_before_lock = False

        def after_read(values, existing):
            nonlocal changed_before_lock
            result = original(values, existing)
            if changed_before_lock:
                return result
            changed_before_lock = True
            with closing(sqlite3.connect(self.database_path)) as live:
                live.execute(
                    """UPDATE matches SET map1_t1=6,map1_t2=4,team1_score=1,
                           has_map3=0,map_halves=? WHERE id=?""",
                    (halves, self.match_id),
                )
                live.commit()
            return result

        with patch.object(admin_matches, "_preserve_managed_match_fields", side_effect=after_read):
            response = self._edit(stream_url="https://live.bilibili.com/123")
        self.assertTrue(changed_before_lock)
        self.assertEqual(response.status_code, 302)
        match = self.conn.execute("SELECT * FROM matches WHERE id=?", (self.match_id,)).fetchone()
        self.assertEqual((match["map1_t1"], match["map1_t2"]), (6, 4))
        self.assertEqual(match["team1_score"], 1)
        self.assertEqual(match["has_map3"], 0)
        self.assertEqual(json.loads(match["map_halves"]), json.loads(halves))
        self.assertEqual(match["stream_url"], "https://live.bilibili.com/123")

    def test_edit_detects_a_match_that_started_while_the_form_was_being_saved(self):
        self.conn.execute("UPDATE matches SET status='upcoming' WHERE id=?", (self.match_id,))
        self.conn.commit()
        original = admin_matches._preserve_managed_match_fields
        changed_before_lock = False

        def after_read(values, existing):
            nonlocal changed_before_lock
            result = original(values, existing)
            if changed_before_lock:
                return result
            changed_before_lock = True
            with closing(sqlite3.connect(self.database_path)) as live:
                live.execute("UPDATE matches SET status='live' WHERE id=?", (self.match_id,))
                live.commit()
            return result

        with patch.object(admin_matches, "_preserve_managed_match_fields", side_effect=after_read):
            response = self._edit(status="upcoming", map1="de_mirage")
        self.assertTrue(changed_before_lock)
        self.assertEqual(response.status_code, 400)
        match = self.conn.execute(
            "SELECT status,map1 FROM matches WHERE id=?", (self.match_id,)
        ).fetchone()
        self.assertEqual(tuple(match), ("live", "de_nuke"))

    def test_bound_match_cannot_move_and_block_its_old_bracket(self):
        data = build_event_bracket(
            self.conn,
            self.event_id,
            {
                "tournament": {
                    "format_key": "4se",
                    "bo_format": "BO3",
                    "teams": [
                        {"id": f"t{i + 1}", "db_id": team_id, "name": f"Pro Team {i}"}
                        for i, team_id in enumerate(self.team_ids)
                    ],
                    "sections": [
                        {
                            "rounds": [
                                {
                                    "matches": [
                                        {"id": "SF_M1", "team1": "t1", "team2": "t4"},
                                        {"id": "SF_M2", "team1": "t2", "team2": "t3"},
                                    ]
                                }
                            ]
                        }
                    ],
                }
            },
        )
        self.conn.commit()
        nodes = {
            match["id"]: match
            for section in data["tournament"]["sections"]
            for round_data in section["rounds"]
            for match in round_data["matches"]
        }
        self.match_id = nodes["SF_M1"]["match_id"]
        response = self._edit(event_id=str(self.other_event_id), status="upcoming")
        self.assertEqual(response.status_code, 400)
        owner = self.conn.execute(
            "SELECT event_id FROM matches WHERE id=?", (self.match_id,)
        ).fetchone()[0]
        self.assertEqual(owner, self.event_id)
        other_match = nodes["SF_M2"]["match_id"]
        self.conn.execute(
            "UPDATE matches SET status='live',team1_score=2,team2_score=0 WHERE id=?",
            (other_match,),
        )
        self.conn.commit()
        response = self.client.post(
            f"/admin/matches/{other_match}/complete", data={"csrf_token": "pro-logic-csrf"}
        )
        self.assertEqual(response.status_code, 302)
        state = self.conn.execute(
            "SELECT status FROM matches WHERE id=?", (other_match,)
        ).fetchone()[0]
        self.assertEqual(state, "completed")

    def test_unbound_upcoming_match_can_still_move_to_another_event(self):
        self.conn.execute("UPDATE matches SET status='upcoming' WHERE id=?", (self.match_id,))
        self.conn.commit()
        response = self._edit(event_id=str(self.other_event_id), status="upcoming")
        self.assertEqual(response.status_code, 302)
        owner = self.conn.execute(
            "SELECT event_id FROM matches WHERE id=?", (self.match_id,)
        ).fetchone()[0]
        self.assertEqual(owner, self.other_event_id)

    def test_overtime_rounds_are_durable_and_deduplicated_with_regulation(self):
        state = {
            "gsi": {"map": {"name": "de_nuke"}},
            "round_history": [{"round": 24, "winner": "team2"}],
            "overtime_history": [{"round": 25, "winner": "team1"}],
        }
        self.assertEqual(persist_live_match_events(self.conn, self.match_id, state), 2)
        self.assertEqual(persist_live_match_events(self.conn, self.match_id, state), 0)
        state["gsi"]["map"]["name"] = "de_mirage"
        state["round_history"] = [{"round": 1, "winner": "team2"}]
        state["overtime_history"] = []
        persist_live_match_events(self.conn, self.match_id, state)
        events = load_match_timeline(self.conn, self.match_id)
        self.assertEqual(
            [(event["map_name"], event["round"]) for event in events],
            [
                ("de_nuke", 24),
                ("de_nuke", 25),
                ("de_mirage", 1),
            ],
        )

    def test_unknown_kills_do_not_crash_the_map_page_or_become_zero_kd(self):
        self._add_map_stat(kills=None, deaths=9)
        rows, leaders = self._map_stats()
        self.assertEqual(len(rows), 1)
        self.assertIsNone(leaders["de_nuke"]["kd"])
        self.assertEqual(self.client.get("/stats?tab=maps").status_code, 200)

    def test_map_win_rates_follow_bp_when_the_first_team_starts_ct(self):
        self._add_map_stat()
        self.conn.execute(
            "UPDATE matches SET map_halves=?,bp_state=? WHERE id=?",
            (
                json.dumps(
                    {
                        "0": {
                            "h1_t1": 10,
                            "h1_t2": 2,
                            "h2_t1": 3,
                            "h2_t2": 7,
                            "opening_ct_team": "t1",
                            "side_source": "website_bp",
                        }
                    }
                ),
                json.dumps({"picks": [{"map": "de_nuke", "side": "CT", "side_team": "t1"}]}),
                self.match_id,
            ),
        )
        self.conn.commit()
        rows, _ = self._map_stats()
        self.assertEqual((rows[0]["t_win_pct"], rows[0]["ct_win_pct"]), (22.7, 77.3))

    def test_unknown_opening_side_does_not_produce_t_or_ct_win_rates(self):
        self._add_map_stat()
        self.conn.execute(
            "UPDATE matches SET map_halves=? WHERE id=?",
            (json.dumps({"0": {"h1_t1": 10, "h1_t2": 2, "h2_t1": 3, "h2_t2": 7}}), self.match_id),
        )
        self.conn.commit()
        rows, _ = self._map_stats()
        self.assertIsNone(rows[0]["t_win_pct"])
        self.assertIsNone(rows[0]["ct_win_pct"])

    def test_dissolving_a_team_keeps_its_preferred_substitutes_as_public_reserves(self):
        registration_id = self.conn.execute(
            "INSERT INTO event_registrations(event_id,team_name,creator_user_id) VALUES(?,?,?)",
            (self.event_id, "Pro Registered", self.user_id),
        ).lastrowid
        for slot in range(5):
            self.conn.execute(
                "INSERT INTO event_registration_slots(registration_id,slot_index,player_name) VALUES(?,?,?)",
                (registration_id, slot, f"Reserved {slot}"),
            )
        self.conn.execute(
            """INSERT INTO event_individual_registrations(event_id,user_id,player_name,
                       steam_id,assignment_status,preferred_registration_id)
               VALUES(?,?,?,'111','reserve',?)""",
            (self.event_id, self.user_id, "Pro Substitute", registration_id),
        )
        self.conn.commit()
        response = self.client.post(
            f"/events/{self.event_id}/registrations/{registration_id}/dissolve",
            data={"csrf_token": "pro-logic-csrf"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(response.status_code, 200)
        reserve = self.conn.execute(
            "SELECT assignment_status,preferred_registration_id FROM event_individual_registrations WHERE user_id=?",
            (self.user_id,),
        ).fetchone()
        self.assertEqual(tuple(reserve), ("reserve", None))
        self.assertIsNone(
            self.conn.execute(
                "SELECT id FROM event_registrations WHERE id=?", (registration_id,)
            ).fetchone()
        )

    def test_comment_limits_cannot_be_reset_by_replaying_a_login_cookie(self):
        client = self._user_client()
        cookie_name = app.config["SESSION_COOKIE_NAME"]
        original_cookie = client.get_cookie(cookie_name)
        self.assertIsNotNone(original_cookie)
        statuses = []
        for index in range(12):
            client.set_cookie(cookie_name, original_cookie.value)
            response = client.post(
                f"/comment/match/{self.match_id}",
                data={"csrf_token": "pro-logic-csrf", "content": f"Replay {index}"},
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
            statuses.append(response.status_code)
        self.assertEqual(statuses[-2:], [429, 429])
        count = self.conn.execute(
            "SELECT COUNT(*) FROM comments WHERE user_id=?", (self.user_id,)
        ).fetchone()[0]
        self.assertEqual(count, 10)

    def _email_challenge(self):
        client = app.test_client()
        with client.session_transaction() as saved:
            saved["csrf_token"] = "pro-logic-csrf"
        with (
            patch("routes.auth._send_registration_email"),
            patch("routes.auth.secrets.randbelow", return_value=23456),
        ):
            response = client.post(
                "/auth/email/send-code",
                data={"csrf_token": "pro-logic-csrf", "email": "pro-logic@example.com"},
            )
        self.assertEqual(response.status_code, 200)
        return client, client.get_cookie(app.config["SESSION_COOKIE_NAME"])

    @staticmethod
    def _verify(client, code):
        return client.post(
            "/auth/email/verify-code",
            data={"csrf_token": "pro-logic-csrf", "email": "pro-logic@example.com", "code": code},
        )

    def test_email_attempts_stay_exhausted_after_replaying_the_original_cookie(self):
        client, original_cookie = self._email_challenge()
        for _ in range(5):
            self.assertEqual(self._verify(client, "000000").status_code, 400)
        client.set_cookie(app.config["SESSION_COOKIE_NAME"], original_cookie.value)
        self.assertEqual(self._verify(client, "123456").status_code, 400)

    def test_email_verification_cannot_consume_the_same_challenge_twice(self):
        client, original_cookie = self._email_challenge()
        self.assertEqual(self._verify(client, "123456").status_code, 200)
        client.set_cookie(app.config["SESSION_COOKIE_NAME"], original_cookie.value)
        self.assertEqual(self._verify(client, "123456").status_code, 400)

    def test_daily_answer_creation_does_not_commit_the_callers_transaction(self):
        self.conn.execute("BEGIN IMMEDIATE")
        get_daily_answer(self.conn)
        self.assertTrue(self.conn.in_transaction)
        self.conn.rollback()
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM guess_player_daily").fetchone()[0], 0
        )

    def test_first_daily_submissions_are_serialized_without_precreating_the_answer(self):
        import routes.guess_player as route

        self.conn.execute("BEGIN IMMEDIATE")
        answer_id = get_daily_answer(self.conn)["id"]
        self.conn.rollback()
        guesses = [
            row[0]
            for row in self.conn.execute(
                "SELECT id FROM guess_players WHERE active=1 AND id<>? LIMIT 2", (answer_id,)
            )
        ]
        clients = [self._user_client(), self._user_client()]
        entered = threading.Event()
        second_loaded = threading.Event()
        counts = []
        count_lock = threading.Lock()
        original = route.load_game

        def controlled_load(conn, user_id):
            game = original(conn, user_id)
            with count_lock:
                first = not counts
                counts.append(len(game["results"]))
            if first:
                entered.set()
                second_loaded.wait(0.5)
            else:
                second_loaded.set()
            return game

        def submit(index):
            return (
                clients[index]
                .post(
                    "/guess-player",
                    data={"csrf_token": "pro-logic-csrf", "player_id": guesses[index]},
                )
                .status_code
            )

        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM guess_player_daily").fetchone()[0], 0
        )
        with (
            patch.object(route, "load_game", side_effect=controlled_load),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            first = executor.submit(submit, 0)
            self.assertTrue(entered.wait(3))
            second = executor.submit(submit, 1)
            statuses = [first.result(timeout=5), second.result(timeout=5)]
        self.assertEqual(statuses, [302, 302])
        self.assertEqual(counts, [0, 1])
        self.assertEqual(
            [
                row[0]
                for row in self.conn.execute(
                    "SELECT attempt_number FROM guess_player_attempts ORDER BY attempt_number"
                )
            ],
            [1, 2],
        )

    def test_practice_initialization_also_keeps_the_callers_transaction(self):
        for initialize in (
            lambda: create_practice_game(self.conn, self.user_id),
            lambda: load_practice_game(self.conn, self.user_id),
        ):
            self.conn.execute("BEGIN IMMEDIATE")
            initialize()
            self.assertTrue(self.conn.in_transaction)
            self.conn.rollback()
            self.assertEqual(
                self.conn.execute("SELECT COUNT(*) FROM guess_player_practice_games").fetchone()[0],
                0,
            )

    def test_rate_limits_survive_new_requests_and_keep_users_actions_and_windows_separate(self):
        from utils.rate_limiter import rate_limit

        def attempt(user_id, action, now):
            with (
                app.test_request_context(),
                patch("utils.rate_limiter.time.time", return_value=now),
            ):
                session["user_id"] = user_id
                return rate_limit(action, 2, 60)

        self.assertTrue(attempt(self.user_id, "persistent-test", 1000))
        self.assertTrue(attempt(self.user_id, "persistent-test", 1001))
        self.assertFalse(attempt(self.user_id, "persistent-test", 1002))
        self.assertTrue(attempt(self.user_id + 1, "persistent-test", 1002))
        self.assertTrue(attempt(self.user_id, "another-action", 1002))
        self.assertTrue(attempt(self.user_id, "persistent-test", 1062))

    def test_concurrent_rate_checks_cannot_exceed_the_server_limit(self):
        from utils.rate_limiter import rate_limit

        def attempt(_):
            with app.test_request_context():
                session["user_id"] = self.user_id
                return rate_limit("parallel-test", 5, 60)

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(attempt, range(12)))
        self.assertEqual(sum(results), 5)

    def test_email_expiry_and_wrong_email_are_checked_on_the_server(self):
        client, _ = self._email_challenge()
        wrong = client.post(
            "/auth/email/verify-code",
            data={"csrf_token": "pro-logic-csrf", "email": "another@example.com", "code": "123456"},
        )
        self.assertEqual(wrong.status_code, 400)
        self.conn.execute("UPDATE email_verification_challenges SET expires_at=0")
        self.conn.commit()
        self.assertEqual(self._verify(client, "123456").status_code, 400)

    def test_verified_email_consumption_rolls_back_with_registration_and_cannot_be_reused_after_commit(
        self,
    ):
        from routes.auth import (
            _consume_verified_registration_email,
            _get_verified_registration_email,
        )

        client, _ = self._email_challenge()
        for _ in range(4):
            self.assertEqual(self._verify(client, "000000").status_code, 400)
        self.assertEqual(self._verify(client, "123456").status_code, 200)
        with client.session_transaction() as saved:
            verified = dict(saved["registration_email_verified"])
        with app.test_request_context():
            session["registration_email_verified"] = verified
            self.conn.execute("BEGIN IMMEDIATE")
            self.assertTrue(
                _consume_verified_registration_email(self.conn, "pro-logic@example.com")
            )
            self.conn.rollback()
            self.assertEqual(_get_verified_registration_email(), "pro-logic@example.com")
            self.conn.execute("BEGIN IMMEDIATE")
            self.assertTrue(
                _consume_verified_registration_email(self.conn, "pro-logic@example.com")
            )
            self.conn.commit()
            self.assertFalse(
                _consume_verified_registration_email(self.conn, "pro-logic@example.com")
            )
            self.conn.rollback()
            self.assertEqual(_get_verified_registration_email(), "")

    def test_failed_dissolve_rolls_back_preferences_roster_and_logo_together(self):
        registration_id = self.conn.execute(
            "INSERT INTO event_registrations(event_id,team_name,creator_user_id,team_logo) VALUES(?,?,?,'team_logos/test-logo.png')",
            (self.event_id, "Rollback Team", self.user_id),
        ).lastrowid
        for slot in range(5):
            self.conn.execute(
                "INSERT INTO event_registration_slots(registration_id,slot_index,player_name) VALUES(?,?,?)",
                (registration_id, slot, f"Player {slot}"),
            )
        self.conn.execute(
            "INSERT INTO event_individual_registrations(event_id,user_id,player_name,steam_id,assignment_status,preferred_registration_id) VALUES(?,?,?,'111','reserve',?)",
            (self.event_id, self.user_id, "Preferred Reserve", registration_id),
        )
        self.conn.execute(
            "CREATE TRIGGER reject_test_dissolve BEFORE DELETE ON event_registration_slots BEGIN SELECT RAISE(ABORT, 'forced-test-failure'); END"
        )
        self.conn.commit()
        with (
            patch("routes.events.remove_uploaded_team_logo") as remove_logo,
            patch.object(app.logger, "exception"),
        ):
            response = self.client.post(
                f"/events/{self.event_id}/registrations/{registration_id}/dissolve",
                data={"csrf_token": "pro-logic-csrf"},
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
        self.assertEqual(response.status_code, 500)
        remove_logo.assert_not_called()
        self.assertEqual(
            self.conn.execute(
                "SELECT preferred_registration_id FROM event_individual_registrations WHERE user_id=?",
                (self.user_id,),
            ).fetchone()[0],
            registration_id,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM event_registration_slots WHERE registration_id=?",
                (registration_id,),
            ).fetchone()[0],
            5,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT team_logo FROM event_registrations WHERE id=?", (registration_id,)
            ).fetchone()[0],
            "team_logos/test-logo.png",
        )

    def test_live_endpoint_keeps_overtime_in_the_report_after_switching_maps(self):
        self.conn.execute("UPDATE matches SET map2='de_mirage' WHERE id=?", (self.match_id,))
        self.conn.commit()

        def payload(map_name, number):
            return {
                "map": {
                    "name": map_name,
                    "mode": "competitive",
                    "phase": "live",
                    "round": number,
                    "team_ct": {"name": "Pro Team 1", "score": number // 2},
                    "team_t": {"name": "Pro Team 0", "score": number - number // 2},
                },
                "allplayers": {},
                "round": {"phase": "live"},
                "_80gotv": {
                    "team_ct": "team2",
                    "team_t": "team1",
                    "round_events": [{"round": number, "winner": "t1", "side": "t"}],
                },
            }

        token = secrets.token_urlsafe(24)
        with (
            patch.object(Config, "GSI_TOKEN", token),
            patch("routes.live_ingest.rate_limit", return_value=True),
        ):
            for number in (24, 25, 25):
                response = self.client.post(
                    f"/api/broadcast/matches/{self.match_id}/live",
                    json=payload("de_nuke", number),
                    headers={"X-80GOTV-Token": token},
                )
                self.assertEqual(response.status_code, 200)
            finished = payload("de_nuke", 25)
            finished["map"]["phase"] = "gameover"
            finished["round"]["phase"] = "over"
            self.assertEqual(
                self.client.post(
                    f"/api/broadcast/matches/{self.match_id}/live",
                    json=finished,
                    headers={"X-80GOTV-Token": token},
                ).status_code,
                200,
            )
            self.assertEqual(self.client.get(f"/api/live/{self.match_id}").get_json()["round"], 25)
            response = self.client.post(
                f"/api/broadcast/matches/{self.match_id}/live",
                json=payload("de_mirage", 1),
                headers={"X-80GOTV-Token": token},
            )
            self.assertEqual(response.status_code, 200)
        timeline = load_match_timeline(self.conn, self.match_id)
        self.assertEqual(
            [(item["map_name"], item["round"]) for item in timeline],
            [("de_nuke", 24), ("de_nuke", 25), ("de_mirage", 1)],
        )
        report = self.client.get(f"/matches/{self.match_id}/report")
        self.assertEqual(report.status_code, 200)
        self.assertIn("R25</span>", report.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
