import os
import tempfile
import unittest
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from app import app
from config import Config
from models import get_db, init_tables


class UserProfileGroupUsernameTests(unittest.TestCase):
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
        conn.execute(
            """INSERT INTO users(
                   username, password_hash, approval_status, group_username,
                   is_bashizhong_student
               ) VALUES(?,?,?,?,1)""",
            ("FlameCloud_", generate_password_hash("password123"), "approved", "Crinia_"),
        )
        self.user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()

        self.client = app.test_client()
        with self.client.session_transaction() as browser_session:
            browser_session["user_id"] = self.user_id
            browser_session["user_username"] = "FlameCloud_"
            browser_session["csrf_token"] = "profile-group-username-test"

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

    def _post(self, value):
        return self.client.post(
            "/profile",
            data={
                "csrf_token": "profile-group-username-test",
                "action": "group_username",
                "group_username": value,
            },
            follow_redirects=True,
        )

    def _stored_value(self):
        conn = get_db()
        value = conn.execute(
            "SELECT group_username FROM users WHERE id=?", (self.user_id,)
        ).fetchone()["group_username"]
        conn.close()
        return value

    def test_profile_displays_site_username_before_group_username(self):
        response = self.client.get("/profile")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertLess(html.index("FlameCloud_"), html.index("@Crinia_"))

    def test_profile_exposes_group_username_edit_controls(self):
        response = self.client.get("/profile")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('href="#group-username-settings"', html)
        self.assertIn('id="group-username-settings"', html)
        self.assertIn('name="action" value="group_username"', html)
        self.assertIn("保存群昵称", html)
        self.assertIn("选手昵称 @群昵称", html)

    def test_profile_error_is_rendered_once_as_a_global_toast(self):
        response = self.client.post(
            "/profile",
            data={
                "csrf_token": "profile-group-username-test",
                "action": "avatar",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertEqual(html.count("请选择图片"), 1)
        self.assertIn("server-toast", html)

    def test_user_can_set_trim_but_cannot_clear_group_username(self):
        response = self._post("  NAVI Pe0ple  ")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._stored_value(), "NAVI Pe0ple")
        self.assertIn("NAVI Pe0ple", response.get_data(as_text=True))

        response = self._post("   ")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._stored_value(), "NAVI Pe0ple")
        self.assertIn("请填写群内用户名", response.get_data(as_text=True))

    def test_group_username_rejects_newlines_and_values_over_40_characters(self):
        response = self._post("line one\nline two")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._stored_value(), "Crinia_")
        self.assertIn("群内用户名不能包含换行或制表符", response.get_data(as_text=True))

        response = self._post("x" * 41)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._stored_value(), "Crinia_")
        self.assertIn("群内用户名最多 40 个字符", response.get_data(as_text=True))

    def test_login_requires_existing_user_to_complete_group_username(self):
        conn = get_db()
        conn.execute("UPDATE users SET group_username=NULL WHERE id=?", (self.user_id,))
        conn.commit()
        conn.close()

        self.client = app.test_client()
        with self.client.session_transaction() as browser_session:
            browser_session["csrf_token"] = "login-group-username-test"

        with patch("routes.auth._check_captcha", return_value=True):
            response = self.client.post(
                "/login",
                data={
                    "csrf_token": "login-group-username-test",
                    "username": "FlameCloud_",
                    "password": "password123",
                    "captcha": "ABCDE",
                },
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/"))

        page = self.client.get("/", follow_redirects=False)
        self.assertEqual(page.status_code, 200)
        self.assertIn("profile-completion-backdrop", page.get_data(as_text=True))

        with self.client.session_transaction() as browser_session:
            csrf_token = browser_session["csrf_token"]
            self.assertTrue(browser_session["profile_completion_required"])
        saved = self.client.post(
            "/account/complete-profile",
            data={
                "csrf_token": csrf_token,
                "is_bashizhong_student": "1",
                "group_username": "Crinia_",
            },
            follow_redirects=False,
        )
        self.assertEqual(saved.status_code, 302)
        with self.client.session_transaction() as browser_session:
            self.assertNotIn("profile_completion_required", browser_session)

    def test_existing_session_shows_modal_when_login_marked_profile_incomplete(self):
        conn = get_db()
        conn.execute("UPDATE users SET group_username=NULL WHERE id=?", (self.user_id,))
        conn.commit()
        conn.close()

        with self.client.session_transaction() as browser_session:
            browser_session["profile_completion_required"] = True
        response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 200)
        self.assertIn("profile-completion-backdrop", response.get_data(as_text=True))

    def test_profile_completion_gate_returns_json_for_frontend_requests(self):
        conn = get_db()
        conn.execute("UPDATE users SET group_username='' WHERE id=?", (self.user_id,))
        conn.commit()
        conn.close()

        with self.client.session_transaction() as browser_session:
            browser_session["profile_completion_required"] = True
        response = self.client.get(
            "/api/front/home", headers={"X-Requested-With": "XMLHttpRequest"}
        )
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.get_json()["requires_profile_completion"])

    def test_other_profile_changes_wait_until_group_username_is_filled(self):
        conn = get_db()
        conn.execute("UPDATE users SET group_username=NULL WHERE id=?", (self.user_id,))
        conn.commit()
        conn.close()

        response = self.client.post(
            "/profile",
            data={
                "csrf_token": "profile-group-username-test",
                "action": "nickname",
                "nickname": "ChangedBeforeGroupName",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("请先完成账号资料设置", response.get_data(as_text=True))
        conn = get_db()
        username = conn.execute(
            "SELECT username FROM users WHERE id=?", (self.user_id,)
        ).fetchone()["username"]
        conn.close()
        self.assertEqual(username, "FlameCloud_")


if __name__ == "__main__":
    unittest.main()
