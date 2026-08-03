import os
import tempfile
import unittest

from werkzeug.security import generate_password_hash

from app import app
from config import Config
from models import get_db, init_tables


class PlayerGroupUsernameDisplayTests(unittest.TestCase):
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
                   steam_id64, is_placeholder, is_bashizhong_student
               ) VALUES(?,?,?,?,?,0,1)""",
            (
                "FlameCloud_",
                generate_password_hash("password123"),
                "approved",
                "Crinia_",
                "76561198000000001",
            ),
        )
        self.user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO players(nickname, real_name, steam_id, avatar)
               VALUES(?,?,?,?)""",
            (
                "LinkedPlayer",
                "PRIVATE_REAL_NAME",
                "76561198000000001",
                "fixture.png",
            ),
        )
        self.linked_player_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO players(nickname, real_name, steam_id, avatar)
               VALUES(?,?,?,?)""",
            (
                "UnlinkedPlayer",
                "UNLINKED_PRIVATE_NAME",
                "76561198000000002",
                None,
            ),
        )
        self.unlinked_player_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()

        self.client = app.test_client()

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

    def test_player_pages_show_group_username_without_real_name(self):
        for path in (
            f"/players/{self.linked_player_id}",
            f"/stats/players/{self.linked_player_id}",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                self.assertIn("Crinia_", html)
                self.assertIn("群内昵称", html)
                self.assertNotIn("PRIVATE_REAL_NAME", html)
                self.assertNotIn(">真名<", html)

    def test_player_directory_card_shows_nickname_before_group_username(self):
        response = self.client.get("/players")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn(
            "<strong data-i18n-ignore>LinkedPlayer"
            '<span class="player-group-username"> @Crinia_</span></strong>',
            html,
        )
        self.assertNotIn("PRIVATE_REAL_NAME", html)

    def test_search_uses_group_username_without_leaking_real_name(self):
        response = self.client.get("/search?q=Crinia_")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("LinkedPlayer", html)
        self.assertIn("Crinia_", html)
        self.assertNotIn("PRIVATE_REAL_NAME", html)

        payload = self.client.get("/api/search?q=Crinia_").get_json()
        player = next(item for item in payload["results"] if item["type"] == "player")
        self.assertEqual(player["label"], "LinkedPlayer")
        self.assertEqual(player["sub"], "Crinia_")

        private_payload = self.client.get("/api/search?q=PRIVATE_REAL_NAME").get_json()
        self.assertFalse(
            any(item.get("label") == "LinkedPlayer" for item in private_payload["results"])
        )

    def test_public_player_api_uses_group_username_field(self):
        payload = self.client.get(f"/api/front/players/{self.linked_player_id}").get_json()[
            "player"
        ]
        self.assertEqual(payload["group_username"], "Crinia_")
        self.assertNotIn("real_name", payload)

    def test_admin_player_list_and_account_use_group_username(self):
        with self.client.session_transaction() as browser_session:
            browser_session["admin_id"] = 1
            browser_session["admin_username"] = "FlameCloud_"
            browser_session["user_id"] = self.user_id
            browser_session["user_username"] = "FlameCloud_"
            browser_session["csrf_token"] = "group-name-admin-csrf"

        response = self.client.get("/admin/players")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("群内昵称", html)
        self.assertIn("Crinia_", html)
        self.assertIn("@Crinia_", html)
        self.assertLess(html.index("FlameCloud_"), html.index("@Crinia_"))
        self.assertNotIn("PRIVATE_REAL_NAME", html)
        self.assertNotIn(">真名<", html)

    def test_admin_edits_group_username_without_real_name_field(self):
        with self.client.session_transaction() as browser_session:
            browser_session["admin_id"] = 1
            browser_session["admin_username"] = "FlameCloud_"
            browser_session["csrf_token"] = "group-name-admin-csrf"

        form = self.client.get(f"/admin/players/edit/{self.linked_player_id}")
        form_html = form.get_data(as_text=True)
        self.assertEqual(form.status_code, 200)
        self.assertIn('name="group_username"', form_html)
        self.assertNotIn('name="real_name"', form_html)

        response = self.client.post(
            f"/admin/players/edit/{self.linked_player_id}",
            data={
                "csrf_token": "group-name-admin-csrf",
                "nickname": "LinkedPlayer",
                "group_username": "UpdatedGroupName",
                "is_bashizhong_student": "1",
                "team_id": "",
                "steam_id": "76561198000000001",
            },
        )
        self.assertEqual(response.status_code, 302)

        conn = get_db()
        user_group_name = conn.execute(
            "SELECT group_username FROM users WHERE id=?", (self.user_id,)
        ).fetchone()["group_username"]
        player_override = conn.execute(
            "SELECT group_username_override FROM players WHERE id=?",
            (self.linked_player_id,),
        ).fetchone()["group_username_override"]
        conn.close()
        self.assertEqual(user_group_name, "UpdatedGroupName")
        self.assertEqual(player_override, "UpdatedGroupName")
        self.assertIn(
            "UpdatedGroupName",
            self.client.get(f"/players/{self.linked_player_id}").get_data(as_text=True),
        )

    def test_unlinked_player_uses_admin_group_name_and_initial_avatar(self):
        with self.client.session_transaction() as browser_session:
            browser_session["admin_id"] = 1
            browser_session["admin_username"] = "FlameCloud_"
            browser_session["csrf_token"] = "group-name-admin-csrf"

        response = self.client.post(
            f"/admin/players/edit/{self.unlinked_player_id}",
            data={
                "csrf_token": "group-name-admin-csrf",
                "nickname": "UnlinkedPlayer",
                "group_username": "OfflineGroupName",
                "is_bashizhong_student": "1",
                "team_id": "",
                "steam_id": "76561198000000002",
            },
        )
        self.assertEqual(response.status_code, 302)
        directory_html = self.client.get("/players").get_data(as_text=True)
        self.assertIn("OfflineGroupName", directory_html)
        self.assertIn(
            '<span class="player-directory-avatar player-directory-avatar-fallback" aria-hidden="true">U</span>',
            directory_html,
        )

    def test_unlinked_player_does_not_fall_back_to_real_name(self):
        for path in (
            f"/players/{self.unlinked_player_id}",
            f"/stats/players/{self.unlinked_player_id}",
        ):
            with self.subTest(path=path):
                html = self.client.get(path).get_data(as_text=True)
                self.assertNotIn("UNLINKED_PRIVATE_NAME", html)

        payload = self.client.get("/api/search?q=UnlinkedPlayer").get_json()
        player = next(item for item in payload["results"] if item["type"] == "player")
        self.assertEqual(player["sub"], "")

    def test_external_school_player_uses_world_marker_without_group_name(self):
        conn = get_db()
        conn.execute(
            """INSERT INTO users(
                   username, password_hash, approval_status, group_username,
                   steam_id64, is_placeholder, is_bashizhong_student
               ) VALUES(?,?,?,?,?,0,0)""",
            (
                "ExternalAccount",
                generate_password_hash("password123"),
                "approved",
                "Hidden Legacy Group",
                "76561198000000003",
            ),
        )
        conn.execute(
            """INSERT INTO players(
                   nickname, group_username_override, steam_id,
                   is_bashizhong_student
               ) VALUES(?,?,?,0)""",
            (
                "ExternalPlayer",
                "Hidden Player Group",
                "76561198000000003",
            ),
        )
        external_player_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()

        directory_html = self.client.get("/players").get_data(as_text=True)
        detail_html = self.client.get(f"/players/{external_player_id}").get_data(as_text=True)
        stats_html = self.client.get(f"/stats/players/{external_player_id}").get_data(as_text=True)
        for html in (directory_html, detail_html, stats_html):
            self.assertIn("ExternalPlayer", html)
            self.assertIn("🌐", html)
            self.assertNotIn("Hidden Legacy Group", html)
            self.assertNotIn("Hidden Player Group", html)

        search_payload = self.client.get("/api/search?q=ExternalPlayer").get_json()
        search_player = next(item for item in search_payload["results"] if item["type"] == "player")
        self.assertEqual(search_player["sub"], "🌐")

        api_player = self.client.get(f"/api/front/players/{external_player_id}").get_json()[
            "player"
        ]
        self.assertEqual(api_player["group_username"], "")
        self.assertEqual(api_player["origin_symbol"], "🌐")

    def test_legacy_unconfirmed_player_keeps_existing_group_name_visible(self):
        conn = get_db()
        conn.execute(
            """INSERT INTO users(
                   username, password_hash, approval_status, group_username,
                   steam_id64, is_placeholder
               ) VALUES(?,?,?,?,?,0)""",
            (
                "LegacyAccount",
                generate_password_hash("password123"),
                "approved",
                "LegacyGroupName",
                "76561198000000004",
            ),
        )
        conn.execute(
            """INSERT INTO players(
                   nickname, group_username_override, steam_id
               ) VALUES(?,?,?)""",
            (
                "LegacyPlayer",
                "LegacyPlayerOverride",
                "76561198000000004",
            ),
        )
        legacy_player_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()

        for path in (
            "/players",
            f"/players/{legacy_player_id}",
            f"/stats/players/{legacy_player_id}",
            "/search?q=LegacyGroupName",
        ):
            with self.subTest(path=path):
                html = self.client.get(path).get_data(as_text=True)
                self.assertIn("LegacyGroupName", html)

        search_payload = self.client.get("/api/search?q=LegacyGroupName").get_json()
        search_player = next(item for item in search_payload["results"] if item["type"] == "player")
        self.assertEqual(search_player["sub"], "LegacyGroupName")

        api_player = self.client.get(f"/api/front/players/{legacy_player_id}").get_json()["player"]
        self.assertEqual(api_player["group_username"], "LegacyGroupName")
        self.assertEqual(api_player["origin_symbol"], "")


if __name__ == "__main__":
    unittest.main()
