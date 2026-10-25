import os
import tempfile
import unittest
from unittest.mock import patch

from flask import session

from app import app
from config import Config
from models import get_db, init_tables
from utils.web_helpers import csrf_required, safe_redirect_target, validate_admin_session


class RefactorAccountSecurityTests(unittest.TestCase):
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
        self.client = app.test_client()

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

    def test_deleted_admin_session_is_rejected_by_admin_routes(self):
        conn = get_db()
        admin_id = conn.execute(
            "INSERT INTO admins(username, password_hash) VALUES(?, ?)",
            ("RevokedAdmin", "unused-test-hash"),
        ).lastrowid
        conn.commit()
        conn.close()
        with self.client.session_transaction() as saved:
            saved["admin_id"] = admin_id
            saved["admin_username"] = "RevokedAdmin"
            saved["csrf_token"] = "revoked-admin-token"

        conn = get_db()
        conn.execute("DELETE FROM admins WHERE id=?", (admin_id,))
        conn.commit()
        conn.close()

        response = self.client.get("/admin/")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/admin/login"))
        with self.client.session_transaction() as saved:
            self.assertNotIn("admin_id", saved)
            self.assertNotIn("admin_username", saved)

    def test_admin_route_fails_closed_when_permissions_cannot_be_checked(self):
        with self.client.session_transaction() as saved:
            saved["admin_id"] = 1
            saved["admin_username"] = "UnverifiedAdmin"

        with (
            patch("utils.web_helpers.get_db", side_effect=OSError("test database unavailable")),
            patch("utils.web_helpers.logger.exception"),
        ):
            response = self.client.get("/admin/")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers.get("Retry-After"), "5")
        with self.client.session_transaction() as saved:
            self.assertEqual(saved["admin_id"], 1)

    def test_admin_api_permission_failure_returns_json(self):
        response = self.client.get("/admin/events/1/bracket/api/teams")

        self.assertEqual(response.status_code, 401)
        self.assertTrue(response.is_json)

    def test_admin_session_check_is_cached_for_one_request(self):
        conn = get_db()
        admin_id = conn.execute(
            "INSERT INTO admins(username, password_hash) VALUES(?, ?)",
            ("CachedAdmin", "unused-test-hash"),
        ).lastrowid
        conn.commit()
        conn.close()

        with app.test_request_context("/admin/"):
            session["admin_id"] = admin_id
            with patch("utils.web_helpers.get_db", wraps=get_db) as database_factory:
                self.assertTrue(validate_admin_session())
                self.assertTrue(validate_admin_session())
            database_factory.assert_called_once()

    def test_admin_api_permission_database_failure_returns_json(self):
        with self.client.session_transaction() as saved:
            saved["admin_id"] = 1
            saved["admin_username"] = "UnverifiedAdmin"

        with (
            patch("utils.web_helpers.get_db", side_effect=OSError("test database unavailable")),
            patch("utils.web_helpers.logger.exception"),
        ):
            response = self.client.get("/admin/events/1/bracket/api/teams")

        self.assertEqual(response.status_code, 503)
        self.assertTrue(response.is_json)

    def test_csrf_protection_includes_patch(self):
        @csrf_required
        def protected_change():
            return "the change ran"

        with app.test_request_context(
            "/example/change", method="PATCH", headers={"X-Requested-With": "XMLHttpRequest"}
        ):
            session["csrf_token"] = "expected-token"
            response = protected_change()

        self.assertEqual(response[1], 403)
        self.assertFalse(response[0].json["success"])

    def test_api_path_returns_json_without_xhr_header_on_csrf_failure(self):
        @csrf_required
        def protected_change():
            return "the change ran"

        with app.test_request_context("/admin/example/api/save", method="POST"):
            session["csrf_token"] = "expected-token"
            response = protected_change()

        self.assertEqual(response[1], 403)
        self.assertFalse(response[0].json["success"])

    def test_csrf_failure_log_does_not_include_referrer_query_values(self):
        @csrf_required
        def protected_change():
            return "the change ran"

        with app.test_request_context(
            "/api/example/change",
            method="POST",
            headers={"Referer": "https://80gotv.cn/profile?token=temporary-secret"},
        ):
            session["csrf_token"] = "expected-token"
            with patch("utils.web_helpers.logger.debug") as debug_log:
                response = protected_change()

        self.assertEqual(response[1], 403)
        self.assertNotIn("temporary-secret", repr(debug_log.call_args))

    def test_referrer_with_special_path_cannot_turn_into_external_redirect(self):
        for referrer in (
            "https://80gotv.cn/\\\\evil.example",
            "https://80gotv.cn///evil.example",
        ):
            with self.subTest(referrer=referrer):
                with app.test_request_context(
                    "/comment/delete/1",
                    base_url="https://80gotv.cn",
                    headers={"Referer": referrer},
                ):
                    self.assertEqual(safe_redirect_target("/"), "/")

    def test_malformed_referrer_falls_back_without_server_error(self):
        with app.test_request_context(
            "/comment/delete/1",
            base_url="https://80gotv.cn",
            headers={"Referer": "https://[invalid"},
        ):
            self.assertEqual(safe_redirect_target("/"), "/")

    def test_group_username_and_linked_player_update_roll_back_together(self):
        conn = get_db()
        user_id = conn.execute(
            """INSERT INTO users(username, password_hash, steam_id64, approval_status,
                                 group_username, is_bashizhong_student)
               VALUES(?, ?, ?, 'approved', ?, 1)""",
            ("ProfileOwner", "unused-test-hash", "76561198000000001", "Old Group"),
        ).lastrowid
        conn.execute(
            "INSERT INTO players(nickname, steam_id, group_username_override) VALUES(?,?,?)",
            ("ProfileOwner", "76561198000000001", "Old Group"),
        )
        conn.execute(
            """CREATE TRIGGER reject_group_name_update
               BEFORE UPDATE OF group_username_override ON players
               BEGIN SELECT RAISE(ABORT, 'test database failure'); END"""
        )
        conn.commit()
        conn.close()

        with self.client.session_transaction() as saved:
            saved["user_id"] = user_id
            saved["user_username"] = "ProfileOwner"
            saved["csrf_token"] = "profile-atomic-token"

        with patch("routes.auth.logger.exception"):
            response = self.client.post(
                "/profile",
                data={
                    "csrf_token": "profile-atomic-token",
                    "action": "group_username",
                    "group_username": "New Group",
                },
                follow_redirects=True,
            )

        conn = get_db()
        saved_user = conn.execute(
            "SELECT group_username FROM users WHERE id=?", (user_id,)
        ).fetchone()["group_username"]
        saved_player = conn.execute(
            "SELECT group_username_override FROM players WHERE steam_id=?",
            ("76561198000000001",),
        ).fetchone()["group_username_override"]
        conn.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(saved_user, "Old Group")
        self.assertEqual(saved_player, "Old Group")
        self.assertIn("保存失败", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
