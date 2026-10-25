import json
import os
import tempfile
import threading
import unittest
from copy import deepcopy
from unittest.mock import patch

from app import app
from config import Config
from models import get_db, init_tables
from routes.bp import _get_player_team
from services import match_service
from services.match_service import score_predictions
from tests.test_bp_manager import complete_bp, ready_state
from utils.bp_manager import ban_map, ensure_bp_started, init_bp_state, pick_map, process_roll
from utils.match_utils import calculate_map_wins
from utils.web_helpers import hash_bp_password


class MatchIntegrityTests(unittest.TestCase):
    def setUp(self):
        handle, self.database_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.original_database = Config.DATABASE
        self.original_testing = app.config.get("TESTING")
        self.original_secure_cookie = app.config.get("SESSION_COOKIE_SECURE")
        self.test_connections = []
        Config.DATABASE = self.database_path
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        init_tables()
        conn = get_db()
        self.event_id = conn.execute("INSERT INTO events(name) VALUES('Integrity Cup')").lastrowid
        self.team1_id = conn.execute("INSERT INTO teams(name) VALUES('Alpha')").lastrowid
        self.team2_id = conn.execute("INSERT INTO teams(name) VALUES('Bravo')").lastrowid
        self.user_id = conn.execute(
            """INSERT INTO users(username,password_hash,approval_status,group_username,is_bashizhong_student)
               VALUES('Integrity Voter','test-hash','approved','Test Group',0)"""
        ).lastrowid
        self.match_id = conn.execute(
            """INSERT INTO matches(event_id,team1_id,team2_id,status,bo_format,match_time)
               VALUES(?,?,?,'live','BO3','2026-10-26T12:00')""",
            (self.event_id, self.team1_id, self.team2_id),
        ).lastrowid
        conn.commit()
        conn.close()
        self.client = app.test_client()
        with self.client.session_transaction() as saved:
            saved["admin_id"] = 1
            saved["csrf_token"] = "integrity-test"

    def tearDown(self):
        for conn in self.test_connections:
            conn.close()
        Config.DATABASE = self.original_database
        app.config.update(
            TESTING=self.original_testing, SESSION_COOKIE_SECURE=self.original_secure_cookie
        )
        os.remove(self.database_path)

    def _update(self, **values):
        conn = get_db()
        conn.execute(
            "UPDATE matches SET " + ",".join(f"{key}=?" for key in values) + " WHERE id=?",
            (*values.values(), self.match_id),
        )
        conn.commit()
        conn.close()

    def _match(self):
        conn = get_db()
        try:
            return dict(
                conn.execute("SELECT * FROM matches WHERE id=?", (self.match_id,)).fetchone()
            )
        finally:
            conn.close()

    def _post(self, suffix, payload=None):
        return self.client.post(
            f"/api/bp/{self.match_id}/{suffix}",
            json=payload if payload is not None else {},
            headers={"X-CSRF-Token": "integrity-test"},
        )

    def test_incomplete_and_impossible_series_cannot_be_completed(self):
        for score1, score2 in ((0, 0), (1, 0), (2, 2), (3, 0), (-1, 2)):
            with self.subTest(score=(score1, score2)):
                self._update(status="live", team1_score=score1, team2_score=score2)
                self.client.post(
                    f"/admin/matches/{self.match_id}/complete",
                    data={"csrf_token": "integrity-test"},
                )
                self.assertEqual(self._match()["status"], "live")

    def test_valid_manual_series_results_can_complete_without_map_details(self):
        for bo, score1, score2 in (("BO1", 1, 0), ("BO3", 2, 1), ("BO5", 1, 3)):
            with self.subTest(bo=bo):
                self._update(status="live", bo_format=bo, team1_score=score1, team2_score=score2)
                for _ in range(2):
                    response = self.client.post(
                        f"/admin/matches/{self.match_id}/complete",
                        data={"csrf_token": "integrity-test"},
                    )
                    self.assertEqual(response.status_code, 302)
                    self.assertEqual(self._match()["status"], "completed")

    def test_cancelled_match_cannot_be_completed(self):
        self._update(status="cancelled", team1_score=2, team2_score=0)
        self.client.post(
            f"/admin/matches/{self.match_id}/complete", data={"csrf_token": "integrity-test"}
        )
        self.assertEqual(self._match()["status"], "cancelled")

    def test_regular_editor_cannot_bypass_completion_validation(self):
        response = self.client.post(
            f"/admin/matches/edit/{self.match_id}",
            data={"csrf_token": "integrity-test", "status": "completed"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._match()["status"], "live")

    def test_predictions_follow_corrected_results_without_accumulating_points(self):
        conn = get_db()
        self.test_connections.append(conn)
        conn.execute(
            """INSERT INTO match_votes(match_id,user_id,voted_for,score1_guess,score2_guess)
               VALUES(?,?,'t1',2,0)""",
            (self.match_id, self.user_id),
        )
        conn.execute(
            "UPDATE matches SET status='completed',team1_score=2,team2_score=0 WHERE id=?",
            (self.match_id,),
        )
        score_predictions(conn)
        self.assertEqual(conn.execute("SELECT points_earned FROM match_votes").fetchone()[0], 8)
        conn.execute("UPDATE matches SET team1_score=0,team2_score=2 WHERE id=?", (self.match_id,))
        score_predictions(conn)
        score_predictions(conn)
        self.assertEqual(conn.execute("SELECT points_earned FROM match_votes").fetchone()[0], 0)
        conn.close()

    def test_incomplete_completed_result_does_not_award_prediction_points(self):
        conn = get_db()
        self.test_connections.append(conn)
        conn.execute(
            "INSERT INTO match_votes(match_id,user_id,voted_for) VALUES(?,?,'t1')",
            (self.match_id, self.user_id),
        )
        conn.execute(
            "UPDATE matches SET status='completed',team1_score=1,team2_score=0 WHERE id=?",
            (self.match_id,),
        )
        score_predictions(conn)
        vote = conn.execute("SELECT scored,points_earned FROM match_votes").fetchone()
        self.assertEqual(tuple(vote), (0, 0))
        conn.close()

    def test_read_only_prediction_leaderboard_uses_current_result_without_writing_points(self):
        conn = get_db()
        self.test_connections.append(conn)
        conn.execute(
            """INSERT INTO match_votes(match_id,user_id,voted_for,score1_guess,score2_guess,scored,points_earned)
               VALUES(?,?,'t1',2,0,1,8)""",
            (self.match_id, self.user_id),
        )
        conn.execute(
            "UPDATE matches SET status='completed',team1_score=0,team2_score=2 WHERE id=?",
            (self.match_id,),
        )
        conn.commit()
        before = conn.total_changes
        loader = getattr(match_service, "get_prediction_leaderboard", None)
        self.assertTrue(callable(loader))
        leaders = loader(conn)
        self.assertEqual(leaders[0]["total_points"], 0)
        self.assertEqual(leaders[0]["correct_votes"], 0)
        self.assertEqual(leaders[0]["total_votes"], 1)
        self.assertEqual(conn.total_changes, before)
        self.assertEqual(
            tuple(conn.execute("SELECT scored,points_earned FROM match_votes").fetchone()), (1, 8)
        )

    def test_cancelled_prediction_points_are_revoked_when_explicitly_reconciled(self):
        conn = get_db()
        self.test_connections.append(conn)
        conn.execute(
            "INSERT INTO match_votes(match_id,user_id,voted_for,scored,points_earned) VALUES(?,?,'t1',1,8)",
            (self.match_id, self.user_id),
        )
        conn.execute(
            "UPDATE matches SET status='cancelled',team1_score=2,team2_score=0 WHERE id=?",
            (self.match_id,),
        )
        score_predictions(conn, self.match_id)
        self.assertEqual(
            tuple(conn.execute("SELECT scored,points_earned FROM match_votes").fetchone()), (0, 0)
        )

    def test_prediction_upcoming_list_uses_the_existing_html_rules_without_writes(self):
        conn = get_db()
        self.test_connections.append(conn)
        conn.execute(
            "UPDATE matches SET status='upcoming',match_time=datetime('now','localtime','+2 hours') WHERE id=?",
            (self.match_id,),
        )
        ids = {}
        for status, offset in (
            ("upcoming", "+3 hours"),
            ("cancelled", "+3 hours"),
            ("completed", "+3 hours"),
            ("live", "+3 hours"),
            ("upcoming", "-3 hours"),
        ):
            key = (status, offset)
            ids[key] = conn.execute(
                "INSERT INTO matches(event_id,status,match_time) VALUES(?,?,datetime('now','localtime',?))",
                (self.event_id, status, offset),
            ).lastrowid
        unscheduled = conn.execute(
            "INSERT INTO matches(event_id,status,match_time) VALUES(?,'upcoming',NULL)",
            (self.event_id,),
        ).lastrowid
        for key in (("upcoming", "+3 hours"), ("cancelled", "+3 hours")):
            conn.execute(
                "INSERT INTO match_votes(match_id,user_id,voted_for) VALUES(?,?,'t1')",
                (ids[key], self.user_id),
            )
        conn.commit()
        before = conn.total_changes
        loader = getattr(match_service, "get_prediction_upcoming_matches", None)
        self.assertTrue(callable(loader))
        matches = loader(conn)
        self.assertEqual(
            {match["id"] for match in matches},
            {self.match_id, unscheduled, ids[("upcoming", "+3 hours")]},
        )
        self.assertEqual(matches[0]["id"], ids[("upcoming", "+3 hours")])
        self.assertEqual(
            next(match for match in matches if match["id"] == self.match_id)["vote_count"], 0
        )
        self.assertEqual(conn.total_changes, before)

    def test_map_wins_ignore_slots_outside_bo_limit(self):
        match = {
            "bo_format": "BO1",
            "map1": "de_nuke",
            "map1_t1": 13,
            "map1_t2": 7,
            "map2": "de_mirage",
            "map2_t1": 13,
            "map2_t2": 2,
            "map3": "de_ancient",
            "map3_t1": 2,
            "map3_t2": 13,
            "has_map3": 1,
        }
        self.assertEqual(calculate_map_wins(match), (1, 0))

    def test_bp_undo_is_locked_after_match_has_scores_or_is_closed(self):
        completed = complete_bp("BO3")
        completed["state_history"] = [ready_state("BO3")]
        for values in (
            {"status": "completed", "map1_t1": 0},
            {"status": "cancelled", "map1_t1": 0},
            {"status": "live", "map1_t1": 1},
        ):
            with self.subTest(values=values):
                self._update(bp_state=json.dumps(completed), map1="de_nuke", **values)
                before = self._match()
                response = self._post("undo")
                self.assertEqual(response.status_code, 409)
                self.assertEqual(self._match(), before)

    def test_bp_reset_is_locked_after_match_has_scores(self):
        self._update(bp_state=json.dumps(complete_bp("BO3")), map1_t1=1)
        before = self._match()
        response = self._post("reset")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self._match(), before)

    def test_reset_completed_bp_clears_only_its_generated_maps(self):
        self._update(
            bp_state=json.dumps(complete_bp("BO3")),
            map1="de_nuke",
            map1_picked_by="t1",
            bp_process="old selection",
            map_pool='["Nuke","Mirage","Ancient"]',
        )
        response = self._post("reset")
        self.assertEqual(response.status_code, 200)
        match = self._match()
        self.assertIsNone(match["bp_state"])
        self.assertIsNone(match["map1"])
        self.assertIsNone(match["map1_picked_by"])
        self.assertIsNone(match["bp_process"])
        self.assertEqual(match["map_pool"], '["Nuke","Mirage","Ancient"]')

    def test_actions_do_not_change_maps_after_scores_have_started(self):
        self._update(bp_state=json.dumps(ready_state("BO3")), map1_t1=1)
        before = self._match()["bp_state"]
        response = self._post("action", {"action": "ban", "team": "t1", "map": "Dust2"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self._match()["bp_state"], before)

    def test_closed_match_heartbeat_does_not_modify_bp(self):
        self._update(status="completed", bp_state=json.dumps(complete_bp("BO3")))
        before = self._match()["bp_state"]
        response = self._post("heartbeat")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self._match()["bp_state"], before)

    def test_password_change_invalidates_an_older_bp_verification(self):
        conn = get_db()
        conn.execute("UPDATE users SET steam_id64='76561198000000777' WHERE id=?", (self.user_id,))
        player_id = conn.execute(
            "INSERT INTO players(nickname,steam_id,team_id) VALUES('Controller','76561198000000777',?)",
            (self.team1_id,),
        ).lastrowid
        conn.commit()
        conn.close()
        self._update(
            bp_password=hash_bp_password("old-test-passphrase"),
            team1_players=json.dumps([player_id]),
            bp_state=json.dumps(ready_state("BO3")),
        )
        with self.client.session_transaction() as saved:
            saved.pop("admin_id", None)
            saved["user_id"] = self.user_id
        verified = self.client.post(
            f"/bp/{self.match_id}/verify",
            json={"password": "old-test-passphrase"},
            headers={"X-CSRF-Token": "integrity-test"},
        )
        self.assertTrue(verified.get_json()["ok"])
        self._update(bp_password=hash_bp_password("new-test-passphrase"))
        before = self._match()["bp_state"]
        response = self._post("action", {"action": "ban", "team": "t1", "map": "Dust2"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self._match()["bp_state"], before)

    def test_invalid_bp_request_does_not_commit_state_upgrade(self):
        state = ready_state("BO3")
        state["state_version"] = 5
        self._update(bp_state=json.dumps(state))
        before = self._match()["bp_state"]
        response = self._post("action", {"action": "ban", "team": "t1", "bp_revision": 99})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self._match()["bp_state"], before)

    def test_old_state_upgrade_cannot_overwrite_a_newer_committed_action(self):
        stale = ready_state("BO3")
        stale["state_version"] = 5
        self._update(bp_state=json.dumps(stale))
        old_row = self._match()
        latest = ready_state("BO3")
        ban_map(latest, "t1", "Dust2")
        latest["revision"] = 1
        self._update(bp_state=json.dumps(latest))
        conn = get_db()
        self.test_connections.append(conn)
        state, _ = ensure_bp_started(conn, old_row)
        conn.commit()
        self.assertEqual(state["revision"], 1)
        self.assertEqual(json.loads(self._match()["bp_state"])["bans"], ["Dust2"])

    def test_heartbeat_cannot_overwrite_a_concurrent_bp_action(self):
        self._update(bp_state=json.dumps(init_bp_state("BO3")))
        action_read = threading.Event()
        release_action = threading.Event()
        heartbeat_read = threading.Event()
        action_finished = threading.Event()
        responses, errors = {}, []

        def controlled_read(conn, match):
            state = ensure_bp_started(conn, match)
            if threading.current_thread().name == "bp-action-test":
                action_read.set()
                if not release_action.wait(5):
                    raise AssertionError("等待 BP 操作恢复超时")
            else:
                heartbeat_read.set()
                if not action_finished.wait(5):
                    raise AssertionError("等待 BP 操作完成超时")
            return state

        def send(name, suffix, payload):
            try:
                client = app.test_client()
                with client.session_transaction() as saved:
                    saved["admin_id"] = 1
                    saved["csrf_token"] = "integrity-test"
                responses[name] = client.post(
                    f"/api/bp/{self.match_id}/{suffix}",
                    json=payload,
                    headers={"X-CSRF-Token": "integrity-test"},
                )
            except Exception as exc:
                errors.append(exc)
            finally:
                if name == "action":
                    action_finished.set()

        action_thread = threading.Thread(
            name="bp-action-test",
            target=send,
            args=("action", "action", {"action": "roll", "team": "t1", "bp_revision": 0}),
        )
        heartbeat_thread = threading.Thread(
            name="bp-heartbeat-test",
            target=send,
            args=("heartbeat", "heartbeat", {}),
        )
        with patch("routes.bp.ensure_bp_started", side_effect=controlled_read):
            action_thread.start()
            try:
                self.assertTrue(action_read.wait(5))
                heartbeat_thread.start()
                heartbeat_read.wait(0.15)
            finally:
                release_action.set()
                action_thread.join(10)
                if heartbeat_thread.ident is not None:
                    heartbeat_thread.join(10)
        self.assertFalse(action_thread.is_alive())
        self.assertFalse(heartbeat_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(responses["action"].get_json()["ok"])
        self.assertTrue(responses["heartbeat"].get_json()["ok"])
        state = json.loads(self._match()["bp_state"])
        self.assertEqual(state["revision"], 1)
        self.assertIsNotNone(state["rolls"]["t1"])


class BPPhaseIntegrityTests(unittest.TestCase):
    def test_map_aliases_cannot_put_the_same_real_map_in_a_pool_twice(self):
        with self.assertRaisesRegex(ValueError, "重复"):
            init_bp_state("BO1", ["Dust2", "de_dust2"])

    def test_ban_requires_first_order_choice(self):
        state = init_bp_state("BO3")
        process_roll(state, "t1", 80)
        process_roll(state, "t2", 20)
        before = deepcopy(state)
        ok, _ = ban_map(state, "t2", state["pool"][0])
        self.assertFalse(ok)
        self.assertEqual(state, before)

    def test_pick_requires_first_order_choice_even_without_initial_bans(self):
        state = init_bp_state("BO3", ["Nuke", "Mirage", "Ancient"])
        process_roll(state, "t1", 80)
        process_roll(state, "t2", 20)
        before = deepcopy(state)
        ok, _ = pick_map(state, "t2", "Nuke")
        self.assertFalse(ok)
        self.assertEqual(state, before)

    def test_locked_roster_excludes_unselected_permanent_teammates(self):
        match = {
            "team1_id": 10,
            "team2_id": 20,
            "team1_players": "[101]",
            "team2_players": "[201]",
        }
        self.assertIsNone(_get_player_team({"id": 102, "team_id": 10}, match))
        self.assertEqual(_get_player_team({"id": 101, "team_id": 20}, match), "t1")

    def test_legacy_empty_roster_still_uses_permanent_membership(self):
        match = {"team1_id": 10, "team2_id": 20, "team1_players": None, "team2_players": "[]"}
        self.assertEqual(_get_player_team({"id": 102, "team_id": 10}, match), "t1")
