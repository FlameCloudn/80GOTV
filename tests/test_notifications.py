import os
import tempfile
import unittest

from werkzeug.security import generate_password_hash

from app import app
from config import Config
from models import get_db, init_tables


class NotificationTests(unittest.TestCase):
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
        cursor = conn.execute(
            """INSERT INTO users(username, password_hash, group_username)
               VALUES(?, ?, ?)""",
            ("notify-user", generate_password_hash("password"), "notify-user"),
        )
        self.user_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO notifications(user_id, type, message, link) VALUES(?, ?, ?, ?)",
            (self.user_id, "system", "测试通知", "/news"),
        )
        self.notification_id = conn.execute(
            "SELECT id FROM notifications WHERE user_id=?", (self.user_id,)
        ).fetchone()[0]
        conn.commit()
        conn.close()

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

    def login_session(self):
        with self.client.session_transaction() as browser_session:
            browser_session["user_id"] = self.user_id
            browser_session["user_username"] = "notify-user"
            browser_session["csrf_token"] = "notification-test"

    def test_guest_cannot_execute_notification_writes(self):
        summary = self.client.get("/api/front/notifications").get_json()
        self.assertFalse(summary["authenticated"])

        response = self.client.post(
            f"/notifications/read/{self.notification_id}",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(response.status_code, 401)
        conn = get_db()
        is_read = conn.execute(
            "SELECT is_read FROM notifications WHERE id=?", (self.notification_id,)
        ).fetchone()[0]
        conn.close()
        self.assertEqual(is_read, 0)

    def test_popup_api_and_full_page_remain_available(self):
        self.login_session()
        summary = self.client.get("/api/front/notifications").get_json()
        self.assertTrue(summary["authenticated"])
        self.assertEqual(summary["unread"], 1)
        self.assertEqual(summary["notifications"][0]["url"], "/news")
        self.assertEqual(self.client.get("/notifications").status_code, 200)

        homepage = self.client.get("/").get_data(as_text=True)
        self.assertIn('class="notif-bell-icon"', homepage)
        self.assertNotIn("🔔", homepage)

    def test_mark_read_requires_csrf_and_updates_only_current_user(self):
        self.login_session()
        invalid = self.client.post(
            f"/notifications/read/{self.notification_id}",
            headers={"X-Requested-With": "XMLHttpRequest", "X-CSRF-Token": "wrong"},
        )
        self.assertEqual(invalid.status_code, 403)

        valid = self.client.post(
            f"/notifications/read/{self.notification_id}",
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRF-Token": "notification-test",
            },
        )
        self.assertEqual(valid.status_code, 200)
        self.assertTrue(valid.get_json()["success"])
        self.assertEqual(self.client.get("/notifications/unread-count").get_json()["count"], 0)


if __name__ == "__main__":
    unittest.main()
