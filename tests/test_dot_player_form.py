import os
import tempfile
import unittest
from html.parser import HTMLParser

from app import app
from config import Config
from models import get_db, init_tables


class _SteamInputParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.value = None

    def handle_starttag(self, tag, attrs):
        if tag != "input":
            return
        attributes = dict(attrs)
        if attributes.get("name") == "steam_id":
            self.value = attributes.get("value", "")


class DotPlayerFormTests(unittest.TestCase):
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
            "INSERT OR IGNORE INTO admins(id, username, password_hash) VALUES(1, 'dot-test-admin', 'x')"
        )
        conn.execute(
            "INSERT INTO players(nickname, is_bashizhong_student, steam_id) VALUES(?,?,NULL)",
            ("Old Player", 0),
        )
        self.player_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()
        self.client = app.test_client()
        with self.client.session_transaction() as browser_session:
            browser_session["admin_id"] = 1
            browser_session["admin_username"] = "dot-test-admin"
            browser_session["csrf_token"] = "dot-player-form-test"

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

    def _steam_value(self, response):
        parser = _SteamInputParser()
        parser.feed(response.get_data(as_text=True))
        return parser.value

    def _post_values(self, nickname, steam_id):
        return {
            "csrf_token": "dot-player-form-test",
            "nickname": nickname,
            "group_username": "",
            "team_id": "",
            "steam_id": steam_id,
            "is_bashizhong_student": "0",
        }

    def test_null_steam_id_renders_as_an_empty_input(self):
        response = self.client.get(f"/admin/players/edit/{self.player_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._steam_value(response), "")

    def test_null_steam_id_profile_can_save_nickname_without_reentering_steam(self):
        form = self.client.get(f"/admin/players/edit/{self.player_id}")
        steam_id_as_shown = self._steam_value(form)
        response = self.client.post(
            f"/admin/players/edit/{self.player_id}",
            data=self._post_values("Renamed Player", steam_id_as_shown),
        )
        self.assertEqual(response.status_code, 302)
        conn = get_db()
        player = conn.execute(
            "SELECT nickname, steam_id FROM players WHERE id=?", (self.player_id,)
        ).fetchone()
        conn.close()
        self.assertEqual(player["nickname"], "Renamed Player")
        self.assertIsNone(player["steam_id"])

    def test_valid_17_digit_steam_id_is_saved_unchanged(self):
        steam_id = "76561198000000001"
        response = self.client.post(
            f"/admin/players/edit/{self.player_id}",
            data=self._post_values("Old Player", steam_id),
        )
        self.assertEqual(response.status_code, 302)
        conn = get_db()
        player = conn.execute(
            "SELECT steam_id FROM players WHERE id=?", (self.player_id,)
        ).fetchone()
        conn.close()
        self.assertEqual(player["steam_id"], steam_id)

    def test_invalid_steam_id_is_rejected_without_changing_existing_profile(self):
        response = self.client.post(
            f"/admin/players/edit/{self.player_id}",
            data=self._post_values("Changed Name", "1234567890123456"),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Steam ID 必须为 17 位数字", response.get_data(as_text=True))
        self.assertEqual(self._steam_value(response), "1234567890123456")
        conn = get_db()
        player = conn.execute(
            "SELECT nickname, steam_id FROM players WHERE id=?", (self.player_id,)
        ).fetchone()
        conn.close()
        self.assertEqual(player["nickname"], "Old Player")
        self.assertIsNone(player["steam_id"])


if __name__ == "__main__":
    unittest.main()
