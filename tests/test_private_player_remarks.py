import os
import tempfile
import unittest

from app import app
from config import Config
from models import get_db, init_tables


class PrivatePlayerRemarkTests(unittest.TestCase):
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
        self.viewer_one_id = self._add_user(conn, "ViewerOne", "Viewer One", "76561198000000101")
        self.viewer_two_id = self._add_user(conn, "ViewerTwo", "Viewer Two", "76561198000000102")
        self.target_user_id = self._add_user(
            conn, "TargetAccount", "Target Group", "76561198000000103"
        )
        conn.execute(
            "INSERT INTO players(nickname, steam_id) VALUES(?, ?)",
            ("TargetOriginal", "76561198000000103"),
        )
        self.target_player_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO players(nickname, steam_id) VALUES(?, ?)",
            ("ViewerOnePlayer", "76561198000000101"),
        )
        self.viewer_one_player_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()

        self.viewer_one = app.test_client()
        self.viewer_two = app.test_client()
        self._login(self.viewer_one, self.viewer_one_id, "ViewerOne", "viewer-one-csrf")
        self._login(self.viewer_two, self.viewer_two_id, "ViewerTwo", "viewer-two-csrf")

    @staticmethod
    def _add_user(conn, username, group_username, steam_id64):
        conn.execute(
            """
            INSERT INTO users(
                username, password_hash, approval_status, group_username,
                steam_id64, is_placeholder, is_bashizhong_student
            ) VALUES(?, 'unused-in-test', 'approved', ?, ?, 0, 1)
            """,
            (username, group_username, steam_id64),
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    @staticmethod
    def _login(client, user_id, username, csrf_token):
        with client.session_transaction() as browser_session:
            browser_session["user_id"] = user_id
            browser_session["user_username"] = username
            browser_session["csrf_token"] = csrf_token

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

    def _save_remark(self, client, csrf_token, remark, action="save"):
        return client.post(
            f"/players/{self.target_player_id}/remark",
            data={
                "csrf_token": csrf_token,
                "remark": remark,
                "action": action,
            },
        )

    def test_remark_is_private_to_its_owner_across_pages_and_api(self):
        response = self._save_remark(self.viewer_one, "viewer-one-csrf", "My Ace")
        self.assertEqual(response.status_code, 302)

        conn = get_db()
        saved = conn.execute(
            """
            SELECT remark FROM player_private_remarks
            WHERE owner_user_id=? AND target_user_id=?
            """,
            (self.viewer_one_id, self.target_user_id),
        ).fetchone()
        conn.close()
        self.assertEqual(saved["remark"], "My Ace")

        detail_html = self.viewer_one.get(f"/players/{self.target_player_id}").get_data(
            as_text=True
        )
        directory_html = self.viewer_one.get("/players").get_data(as_text=True)
        search_html = self.viewer_one.get("/search?q=TargetOriginal").get_data(as_text=True)
        self.assertIn("My Ace", detail_html)
        self.assertIn("My Ace", directory_html)
        self.assertIn("My Ace", search_html)

        viewer_payload = self.viewer_one.get(
            f"/api/front/players/{self.target_player_id}"
        ).get_json()["player"]
        self.assertEqual(viewer_payload["nickname"], "My Ace")
        self.assertEqual(viewer_payload["group_username"], "")

        other_html = self.viewer_two.get(f"/players/{self.target_player_id}").get_data(as_text=True)
        other_payload = self.viewer_two.get(
            f"/api/front/players/{self.target_player_id}"
        ).get_json()["player"]
        self.assertNotIn("My Ace", other_html)
        self.assertIn("TargetOriginal", other_html)
        self.assertEqual(other_payload["nickname"], "TargetOriginal")
        self.assertEqual(other_payload["group_username"], "Target Group")

    def test_each_viewer_can_keep_a_different_remark(self):
        self.assertEqual(
            self._save_remark(self.viewer_one, "viewer-one-csrf", "Practice Friend").status_code,
            302,
        )
        self.assertEqual(
            self._save_remark(self.viewer_two, "viewer-two-csrf", "Old Teammate").status_code,
            302,
        )

        one_html = self.viewer_one.get(f"/players/{self.target_player_id}").get_data(as_text=True)
        two_html = self.viewer_two.get(f"/players/{self.target_player_id}").get_data(as_text=True)
        self.assertIn("Practice Friend", one_html)
        self.assertNotIn("Old Teammate", one_html)
        self.assertIn("Old Teammate", two_html)
        self.assertNotIn("Practice Friend", two_html)

    def test_delete_restores_the_original_name(self):
        self._save_remark(self.viewer_one, "viewer-one-csrf", "Temporary")
        response = self._save_remark(
            self.viewer_one, "viewer-one-csrf", "Temporary", action="delete"
        )
        self.assertEqual(response.status_code, 302)

        payload = self.viewer_one.get(f"/api/front/players/{self.target_player_id}").get_json()[
            "player"
        ]
        self.assertEqual(payload["nickname"], "TargetOriginal")
        conn = get_db()
        count = conn.execute("SELECT COUNT(*) AS n FROM player_private_remarks").fetchone()["n"]
        conn.close()
        self.assertEqual(count, 0)

    def test_invalid_and_self_remarks_are_rejected(self):
        response = self._save_remark(self.viewer_one, "viewer-one-csrf", "x" * 41)
        self.assertEqual(response.status_code, 302)

        response = self.viewer_one.post(
            f"/players/{self.viewer_one_player_id}/remark",
            data={
                "csrf_token": "viewer-one-csrf",
                "remark": "Me",
                "action": "save",
            },
        )
        self.assertEqual(response.status_code, 302)

        conn = get_db()
        count = conn.execute("SELECT COUNT(*) AS n FROM player_private_remarks").fetchone()["n"]
        conn.close()
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
