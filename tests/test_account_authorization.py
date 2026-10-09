import os
import tempfile
import unittest
from unittest.mock import patch

from app import app
from config import Config
from models import get_db, init_tables


class AccountAuthorizationTests(unittest.TestCase):
    def setUp(self):
        handle, self.database_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.original_database = Config.DATABASE
        self.original_testing = app.config.get("TESTING")
        self.original_secure_cookie = app.config.get("SESSION_COOKIE_SECURE")
        Config.DATABASE = self.database_path
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        init_tables()
        self.client = app.test_client()
        conn = get_db()
        self.user_id = conn.execute(
            """INSERT INTO users(username, password_hash, approval_status,
                                 group_username, is_bashizhong_student)
               VALUES('AuditUser', 'unused-test-hash', 'approved', 'Audit Group', 1)"""
        ).lastrowid
        conn.commit()
        conn.close()
        with self.client.session_transaction() as saved:
            saved["user_id"] = self.user_id
            saved["user_username"] = "AuditUser"
            saved["csrf_token"] = "audit-token"

    def tearDown(self):
        Config.DATABASE = self.original_database
        app.config.update(
            TESTING=self.original_testing, SESSION_COOKIE_SECURE=self.original_secure_cookie
        )
        os.remove(self.database_path)

    def _feedback(self, content="Audit feedback"):
        return self.client.post(
            "/api/feedback/submit",
            json={"type": "bug", "content": content},
            headers={"X-CSRF-Token": "audit-token", "X-Requested-With": "XMLHttpRequest"},
        )

    def _count(self, table):
        conn = get_db()
        try:
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        finally:
            conn.close()

    def test_account_check_failure_blocks_feedback_without_logout_and_retry_saves_once(self):
        with patch("web_app.get_db", side_effect=RuntimeError("test database unavailable")):
            response = self._feedback()
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.get_json().get("ok"))
        self.assertFalse(response.get_json().get("success"))
        self.assertIn("重试", response.get_json()["error"])
        self.assertEqual(self._count("feedback"), 0)
        with self.client.session_transaction() as saved:
            self.assertEqual(saved["user_id"], self.user_id)
        retry = self._feedback()
        self.assertEqual(retry.status_code, 200)
        self.assertTrue(retry.get_json()["ok"])
        self.assertEqual(self._count("feedback"), 1)

    def test_account_check_failure_blocks_private_reads_and_forum_creation(self):
        for path in ("/notifications", "/api/front/notifications", "/profile", "/bp/1"):
            with (
                self.subTest(path=path),
                patch("web_app.get_db", side_effect=RuntimeError("test database unavailable")),
            ):
                self.assertEqual(self.client.get(path).status_code, 503)
        conn = get_db()
        category = conn.execute("SELECT id FROM forum_categories LIMIT 1").fetchone()[0]
        conn.close()
        with patch("web_app.get_db", side_effect=RuntimeError("test database unavailable")):
            response = self.client.post(
                "/forum/thread/new",
                data={
                    "csrf_token": "audit-token",
                    "category_id": category,
                    "title": "Audit title",
                    "content": "Audit content",
                },
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self._count("forum_threads"), 0)

    def test_account_check_failure_does_not_block_public_read_apis(self):
        for path in ("/", "/matches", "/forum", "/api/front/home", "/api/live/999", "/healthz"):
            with (
                self.subTest(path=path),
                patch("web_app.get_db", side_effect=RuntimeError("test database unavailable")),
            ):
                # healthz independently checks storage and must report its real failure.
                self.assertEqual(
                    self.client.get(path).status_code, 503 if path == "/healthz" else 200
                )
        with self.client.session_transaction() as saved:
            self.assertEqual(saved["user_id"], self.user_id)

    def test_revoked_approval_cannot_submit_and_does_not_write(self):
        conn = get_db()
        conn.execute("UPDATE users SET approval_status='rejected' WHERE id=?", (self.user_id,))
        conn.commit()
        conn.close()
        self.assertEqual(self._feedback().status_code, 401)
        self.assertEqual(self._count("feedback"), 0)

    def test_account_check_failure_does_not_block_public_detailed_match(self):
        conn = get_db()
        event_id = conn.execute("INSERT INTO events(name) VALUES('Public Read Audit')").lastrowid
        team1_id = conn.execute("INSERT INTO teams(name) VALUES('Public Alpha')").lastrowid
        team2_id = conn.execute("INSERT INTO teams(name) VALUES('Public Bravo')").lastrowid
        match_id = conn.execute(
            """INSERT INTO matches(event_id, team1_id, team2_id, status, bo_format, map1)
               VALUES(?, ?, ?, 'live', 'BO1', 'Mirage')""",
            (event_id, team1_id, team2_id),
        ).lastrowid
        player_id = conn.execute(
            "INSERT INTO players(nickname, team_id) VALUES('PublicAuditPlayer', ?)",
            (team1_id,),
        ).lastrowid
        conn.execute(
            """INSERT INTO match_stats(match_id, player_id, team_id, match_team_side,
                                       map_name, kills, deaths, rounds_played)
               VALUES(?, ?, ?, 't1', 'Mirage', 19, 9, 20)""",
            (match_id, player_id, team1_id),
        )
        conn.commit()
        conn.close()
        path = f"/matches/{match_id}/detailed"
        self.assertEqual(app.test_client().get(path).status_code, 200)
        with patch("web_app.get_db", side_effect=RuntimeError("test database unavailable")):
            response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        self.assertIn("PublicAuditPlayer", response.get_data(as_text=True))

    def test_profile_missing_in_storage_is_blocked_even_with_old_complete_session(self):
        conn = get_db()
        conn.execute("UPDATE users SET group_username=NULL WHERE id=?", (self.user_id,))
        conn.commit()
        conn.close()
        response = self._feedback()
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.get_json()["requires_profile_completion"])
        self.assertEqual(self._count("feedback"), 0)

    def test_invalid_feedback_shape_is_rejected_without_writing(self):
        for payload in (
            ["not an object"],
            {"content": 123},
            {"content": "Valid content", "contact": []},
        ):
            with self.subTest(payload=payload):
                response = self.client.post(
                    "/api/feedback/submit",
                    json=payload,
                    headers={"X-CSRF-Token": "audit-token", "X-Requested-With": "XMLHttpRequest"},
                )
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.get_json()["ok"])
                self.assertEqual(self._count("feedback"), 0)

    def test_failed_feedback_commit_does_not_leave_a_record_and_retry_saves_once(self):
        real_connection = get_db()

        class FailedCommit:
            def execute(self, *args):
                return real_connection.execute(*args)

            def commit(self):
                raise OSError("test commit failure")

            def close(self):
                real_connection.close()

        with patch("routes.feedback.get_db", return_value=FailedCommit()):
            response = self._feedback("Commit failure audit")
        self.assertEqual(response.status_code, 500)
        self.assertFalse(response.get_json()["ok"])
        self.assertEqual(self._count("feedback"), 0)
        self.assertTrue(self._feedback("Commit failure audit").get_json()["ok"])
        self.assertEqual(self._count("feedback"), 1)


if __name__ == "__main__":
    unittest.main()
