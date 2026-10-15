import os
import sqlite3
import tempfile
import unittest
import uuid
from contextlib import closing
from unittest.mock import patch

from flask import template_rendered
from werkzeug.security import generate_password_hash

from app import app
from config import Config
from models import get_db, init_tables


class PublicBackendWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = os.path.join(self.temp.name, "site.db")
        self.original_database = Config.DATABASE
        self.original_config = {
            key: app.config.get(key)
            for key in ("TESTING", "SESSION_COOKIE_SECURE", "PROPAGATE_EXCEPTIONS", "TRUSTED_HOSTS")
        }
        Config.DATABASE = self.database
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False, PROPAGATE_EXCEPTIONS=False)
        init_tables()
        self.client = app.test_client()
        suffix = uuid.uuid4().hex
        self.admin_name = "dot-admin-" + suffix
        self.user_name = "dot-user-" + suffix
        with closing(get_db()) as conn:
            self.admin_id = conn.execute(
                "INSERT INTO admins(username,password_hash) VALUES(?,?)",
                (self.admin_name, generate_password_hash("test-admin-password")),
            ).lastrowid
            self.user_id = conn.execute(
                "INSERT INTO users(username,password_hash,approval_status,is_bashizhong_student) VALUES(?,?,'approved',0)",
                (self.user_name, generate_password_hash("test-user-password")),
            ).lastrowid
            self.team_id = conn.execute(
                "INSERT INTO teams(name,short_name,description) VALUES('Dot Alpha','DAL','Alpha description')"
            ).lastrowid
            self.other_id = conn.execute(
                "INSERT INTO teams(name,short_name) VALUES('Dot Beta','DBE')"
            ).lastrowid
            self.player_id = conn.execute(
                "INSERT INTO players(nickname,team_id) VALUES('Dot Player',?)", (self.team_id,)
            ).lastrowid
            self.other_player = conn.execute(
                "INSERT INTO players(nickname,team_id) VALUES('Other Player',?)", (self.other_id,)
            ).lastrowid
            self.event_id = conn.execute(
                "INSERT INTO events(name,slug,start_date) VALUES('Dot Cup','dot-cup','2026-10-01')"
            ).lastrowid
            self.match_ids = []
            for index in range(3):
                match_id = conn.execute(
                    "INSERT INTO matches(event_id,team1_id,team2_id,status,team1_score,team2_score,match_time,slug) VALUES(?,?,?,'completed',2,0,?,?)",
                    (
                        self.event_id,
                        self.team_id,
                        self.other_id,
                        f"2026-10-0{index + 1} 12:00:00",
                        f"dot-match-{index}",
                    ),
                ).lastrowid
                self.match_ids.append(match_id)
                self.add_stat(conn, match_id, "de_mirage")
            self.add_stat(conn, self.match_ids[0], "de_nuke")
            conn.commit()

    def tearDown(self):
        Config.DATABASE = self.original_database
        app.config.update(self.original_config)
        self.temp.cleanup()

    def add_stat(self, conn, match_id, map_name, team_id=None):
        conn.execute(
            "INSERT INTO match_stats(match_id,player_id,team_id,map_name,rating,rounds_played,kills,deaths) VALUES(?,?,?,?,1.2,20,18,12)",
            (match_id, self.player_id, self.team_id if team_id is None else team_id, map_name),
        )

    def rendered(self, path):
        contexts = []

        def record(sender, template, context, **extra):
            contexts.append(context)

        with template_rendered.connected_to(record, app):
            response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        return contexts[-1], response.get_data(as_text=True)

    def login(self, name, password, captcha=""):
        self.client.get("/login")
        with self.client.session_transaction() as browser:
            csrf = browser["csrf_token"]
        return self.client.post(
            "/login",
            data={"csrf_token": csrf, "username": name, "password": password, "captcha": captcha},
        )

    def test_real_admin_password_can_login_without_captcha(self):
        response = self.login(self.admin_name, "test-admin-password")
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as browser:
            self.assertEqual(browser.get("admin_id"), self.admin_id)
            self.assertNotIn("user_id", browser)
        self.assertEqual(self.client.get("/admin/").status_code, 200)

    def test_admin_name_with_wrong_password_cannot_skip_captcha_or_gain_a_session(self):
        response = self.login(self.admin_name, "wrong-password")
        self.assertNotEqual(response.status_code, 302)
        with self.client.session_transaction() as browser:
            self.assertNotIn("admin_id", browser)
            self.assertNotIn("user_id", browser)
        self.assertEqual(self.client.get("/admin/").status_code, 302)

    def test_frequent_wrong_admin_passwords_block_the_next_attempt(self):
        for _ in range(5):
            self.assertNotEqual(self.login(self.admin_name, "wrong-password").status_code, 302)
        response = self.login(self.admin_name, "test-admin-password")
        self.assertNotEqual(response.status_code, 302)
        self.assertTrue("登录尝试次数过多" in response.get_data(as_text=True))
        with self.client.session_transaction() as browser:
            self.assertNotIn("admin_id", browser)

    def test_shared_username_with_only_regular_password_does_not_gain_admin(self):
        with closing(get_db()) as conn:
            ordinary = conn.execute(
                "INSERT INTO users(username,password_hash,approval_status,is_bashizhong_student) VALUES(?,?,'approved',0)",
                (self.admin_name, generate_password_hash("ordinary-test-password")),
            ).lastrowid
            conn.commit()
        self.client.get("/login")
        with self.client.session_transaction() as browser:
            csrf = browser["csrf_token"]
        with patch("routes.auth.CAPTCHA_CHARS", "A"):
            self.client.get("/captcha/image")
        response = self.client.post(
            "/login",
            data={
                "csrf_token": csrf,
                "username": self.admin_name,
                "password": "ordinary-test-password",
                "captcha": "AAAAA",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as browser:
            self.assertEqual(browser.get("user_id"), ordinary)
            self.assertNotIn("admin_id", browser)

    def test_regular_user_still_needs_a_real_captcha_and_cannot_reuse_it(self):
        self.assertNotEqual(self.login(self.user_name, "test-user-password").status_code, 302)
        with self.client.session_transaction() as browser:
            csrf = browser["csrf_token"]
            self.assertNotIn("user_id", browser)
        with patch("routes.auth.CAPTCHA_CHARS", "A"):
            image = self.client.get("/captcha/image")
        self.assertEqual(image.mimetype, "image/png")
        form = {
            "csrf_token": csrf,
            "username": self.user_name,
            "password": "test-user-password",
            "captcha": "AAAAA",
        }
        response = self.client.post("/login", data=form)
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as browser:
            self.assertEqual(browser.get("user_id"), self.user_id)
            self.assertNotIn("admin_id", browser)
            self.assertNotIn("captcha_challenge", browser)
            form["csrf_token"] = browser["csrf_token"]
        replay = self.client.post("/login", data=form)
        self.assertEqual(replay.status_code, 200)
        self.assertIn("验证码错误", replay.get_data(as_text=True))

    def test_admin_shortcut_does_not_attach_a_rejected_same_name_user(self):
        with closing(get_db()) as conn:
            conn.execute(
                "INSERT INTO users(username,password_hash,approval_status) VALUES(?,'unused','rejected')",
                (self.admin_name,),
            )
            conn.commit()
        self.assertEqual(self.login(self.admin_name, "test-admin-password").status_code, 302)
        with self.client.session_transaction() as browser:
            self.assertEqual(browser.get("admin_id"), self.admin_id)
            self.assertNotIn("user_id", browser)

    def test_profile_and_data_page_distinguish_three_matches_from_four_maps(self):
        for path in (f"/players/{self.player_id}", f"/stats/players/{self.player_id}"):
            with self.subTest(path=path):
                context, html = self.rendered(path)
                self.assertEqual(context["overall"]["matches"], 3)
                self.assertEqual(context["overall"]["maps"], 4)
                self.assertEqual(context["player_summary"].get("matches"), 3)
                self.assertEqual(context["player_summary"]["maps"], 4)
                self.assertEqual(len(context["recent_matches"]), 3)
                if path.startswith("/players/"):
                    self.assertRegex(html, r"<dt>比赛数</dt>\s*<dd>3</dd>")
                    self.assertRegex(html, r"<dt>地图数</dt>\s*<dd>4</dd>")

    def test_live_and_cancelled_scores_do_not_become_finished_player_wins(self):
        with closing(get_db()) as conn:
            for status in ("live", "cancelled"):
                match = conn.execute(
                    "INSERT INTO matches(team1_id,team2_id,status,team1_score,team2_score) VALUES(?,?,?,13,0)",
                    (self.team_id, self.other_id, status),
                ).lastrowid
                self.add_stat(conn, match, "de_nuke")
            conn.commit()
        context, _ = self.rendered(f"/players/{self.player_id}")
        self.assertEqual(context["match_record"], {"wins": 3, "losses": 0, "finished": 3})

    def test_temporary_team_result_uses_the_explicit_side_saved_by_demo_import(self):
        for side, expected in (
            ("t1", {"wins": 3, "losses": 0, "finished": 3}),
            ("t2", {"wins": 2, "losses": 1, "finished": 3}),
        ):
            with self.subTest(side=side):
                with closing(get_db()) as conn:
                    conn.execute(
                        "UPDATE matches SET team1_id=NULL, team2_id=NULL, team1_players=?, team2_players=? WHERE id=?",
                        (
                            f"[{self.player_id}]" if side == "t1" else "[]",
                            f"[{self.player_id}]" if side == "t2" else "[]",
                            self.match_ids[0],
                        ),
                    )
                    conn.execute(
                        "UPDATE match_stats SET team_id=NULL, match_team_side=? WHERE match_id=?",
                        (side, self.match_ids[0]),
                    )
                    conn.commit()
                context, _ = self.rendered(f"/players/{self.player_id}")
                self.assertEqual(context["match_record"], expected)

    def test_explicit_historical_side_has_precedence_over_a_stale_team_id(self):
        with closing(get_db()) as conn:
            conn.execute(
                "UPDATE match_stats SET match_team_side='t2' WHERE match_id=?", (self.match_ids[0],)
            )
            conn.commit()
        context, _ = self.rendered(f"/players/{self.player_id}")
        self.assertEqual(context["match_record"], {"wins": 2, "losses": 1, "finished": 3})

    def test_legacy_temporary_team_result_uses_the_recorded_side(self):
        with closing(get_db()) as conn:
            conn.execute("INSERT INTO teams(id,name) VALUES(-1,'Temporary Side One')")
            conn.execute(
                "UPDATE matches SET team1_id=NULL, team1_players=? WHERE id=?",
                (f"[{self.player_id}]", self.match_ids[0]),
            )
            conn.execute("UPDATE match_stats SET team_id=-1 WHERE match_id=?", (self.match_ids[0],))
            conn.commit()
        context, _ = self.rendered(f"/players/{self.player_id}")
        self.assertEqual(context["match_record"]["wins"], 3)

    def test_unknown_historical_side_does_not_guess_from_current_roster(self):
        with closing(get_db()) as conn:
            conn.execute(
                "UPDATE match_stats SET team_id=NULL WHERE match_id=?", (self.match_ids[0],)
            )
            conn.commit()
        context, _ = self.rendered(f"/players/{self.player_id}")
        self.assertEqual(context["match_record"], {"wins": 2, "losses": 0, "finished": 2})

    def test_team_navigation_and_search_open_the_corresponding_real_detail(self):
        for path in ("/", "/teams", "/search?q=Dot"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(
                    f'href="/teams/{self.team_id}"' in response.get_data(as_text=True),
                    f"{path} 缺少对应队伍入口",
                )
        result = self.client.get("/api/search?q=Dot%20Alpha").get_json()
        team_result = next(item for item in result["results"] if item["type"] == "team")
        context, _ = self.rendered(team_result["url"])
        self.assertEqual(context["team"]["id"], self.team_id)
        self.assertEqual([row["id"] for row in context["players"]], [self.player_id])
        self.assertEqual({row["id"] for row in context["matches"]}, set(self.match_ids))
        self.assertEqual(context["record"], {"wins": 3, "losses": 0, "draws": 0, "finished": 3})

    def test_public_team_detail_remains_readable_when_account_check_is_unavailable(self):
        with self.client.session_transaction() as browser:
            browser["user_id"] = self.user_id
            browser["user_username"] = self.user_name
        with patch("web_app.get_db", side_effect=RuntimeError("test account lookup unavailable")):
            response = self.client.get(f"/teams/{self.team_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Dot Alpha", response.get_data(as_text=True))
        with self.client.session_transaction() as browser:
            self.assertEqual(browser["user_id"], self.user_id)

    def test_missing_team_is_404_and_empty_team_is_not_a_redirect(self):
        self.assertEqual(self.client.get("/teams/99999999").status_code, 404)
        with closing(get_db()) as conn:
            empty_id = conn.execute("INSERT INTO teams(name) VALUES('Empty Dot Team')").lastrowid
            conn.commit()
        context, _ = self.rendered(f"/teams/{empty_id}")
        self.assertEqual(context["players"], [])
        self.assertEqual(context["matches"], [])
        self.assertEqual(context["record"]["finished"], 0)
        with closing(get_db()) as conn:
            for status, first, second in (
                ("completed", 0, 0),
                ("completed", None, None),
                ("live", 13, 0),
                ("cancelled", 7, 0),
            ):
                conn.execute(
                    "INSERT INTO matches(team1_id,team2_id,status,team1_score,team2_score) VALUES(?,?,?,?,?)",
                    (empty_id, self.other_id, status, first, second),
                )
            conn.commit()
        context, _ = self.rendered(f"/teams/{empty_id}")
        self.assertEqual(len(context["matches"]), 4)
        self.assertEqual(context["record"], {"wins": 0, "losses": 0, "draws": 0, "finished": 0})

    def test_dashboard_counts_database_matches_without_slug_specific_inflation(self):
        with closing(get_db()) as conn:
            conn.execute(
                "UPDATE events SET slug='2026-spring-80-major' WHERE id=?", (self.event_id,)
            )
            conn.execute(
                "DELETE FROM match_stats WHERE match_id IN (?,?)", tuple(self.match_ids[1:])
            )
            conn.execute("DELETE FROM matches WHERE id IN (?,?)", tuple(self.match_ids[1:]))
            conn.commit()
        context, _ = self.rendered("/dashboard")
        event = next(
            row for row in context["event_matches"] if row["slug"] == "2026-spring-80-major"
        )
        self.assertEqual(event["cnt"], 1)

    def test_untrusted_host_is_rejected_without_error_template_recursion(self):
        app.config["TRUSTED_HOSTS"] = ["80gotv.cn"]
        response = self.client.get("/search?q=test", base_url="https://invalid.example")
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("Traceback", response.get_data(as_text=True))
        self.assertEqual(self.client.get("/healthz", base_url="https://80gotv.cn").status_code, 200)

    def test_search_database_failure_closes_connection_and_is_not_an_empty_success(self):
        class TrackedConnection(sqlite3.Connection):
            closed = False

            def close(self):
                self.closed = True
                super().close()

        with closing(get_db()) as conn:
            conn.execute("DROP TABLE news")
            conn.commit()
        for path in ("/search?q=Dot", "/api/search?q=Dot"):
            with self.subTest(path=path):
                connection = sqlite3.connect(self.database, factory=TrackedConnection)
                connection.row_factory = sqlite3.Row
                try:
                    with patch("routes.search.get_db", return_value=connection):
                        with self.assertLogs("80gotv", level="ERROR"):
                            response = self.client.get(path)
                    self.assertEqual(response.status_code, 500)
                    self.assertTrue(connection.closed)
                    self.assertNotIn("没有找到与", response.get_data(as_text=True))
                finally:
                    connection.close()

    def test_notification_commit_failure_is_not_success_and_retry_really_saves(self):
        with closing(get_db()) as conn:
            notice = conn.execute(
                "INSERT INTO notifications(user_id,type,message) VALUES(?,'system','Dot notice')",
                (self.user_id,),
            ).lastrowid
            conn.execute(
                "CREATE TABLE commit_guard(notification_id INTEGER REFERENCES notifications(id) DEFERRABLE INITIALLY DEFERRED)"
            )
            conn.commit()
        with self.client.session_transaction() as browser:
            browser["user_id"] = self.user_id
            browser["user_username"] = self.user_name
            browser["csrf_token"] = "dot-notification-check"
        for path in (f"/notifications/read/{notice}", "/notifications/read-all"):
            with self.subTest(path=path):
                with closing(get_db()) as conn:
                    conn.execute("DROP TRIGGER IF EXISTS fail_notification_commit")
                    conn.execute(
                        "CREATE TRIGGER fail_notification_commit AFTER UPDATE ON notifications BEGIN INSERT INTO commit_guard(notification_id) VALUES(-999); END"
                    )
                    conn.commit()
                response = self.client.post(
                    path, headers={"X-CSRF-Token": "dot-notification-check"}
                )
                self.assertEqual(response.status_code, 500)
                with closing(get_db()) as conn:
                    self.assertEqual(
                        conn.execute(
                            "SELECT is_read FROM notifications WHERE id=?", (notice,)
                        ).fetchone()[0],
                        0,
                    )
                    self.assertEqual(
                        conn.execute("SELECT COUNT(*) FROM commit_guard").fetchone()[0], 0
                    )
                    conn.execute("DROP TRIGGER fail_notification_commit")
                    conn.commit()
                retried = self.client.post(path, headers={"X-CSRF-Token": "dot-notification-check"})
                self.assertEqual(retried.status_code, 200)
                self.assertTrue(retried.get_json()["success"])
                with closing(get_db()) as conn:
                    self.assertEqual(
                        conn.execute(
                            "SELECT is_read FROM notifications WHERE id=?", (notice,)
                        ).fetchone()[0],
                        1,
                    )
                    conn.execute("UPDATE notifications SET is_read=0 WHERE id=?", (notice,))
                    conn.commit()


if __name__ == "__main__":
    unittest.main()
