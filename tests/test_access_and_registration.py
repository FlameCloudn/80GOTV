import os
import tempfile
import time
import unittest
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from app import app
from config import Config
from models import get_db, init_tables


class AccessAndRegistrationTests(unittest.TestCase):
    def setUp(self):
        handle, self.database_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.original_database = Config.DATABASE
        self.original_testing = app.config.get("TESTING")
        self.original_secure_cookie = app.config.get("SESSION_COOKIE_SECURE")
        self.original_cookie_domain = app.config.get("SESSION_COOKIE_DOMAIN")
        self.original_cookie_name = app.config.get("SESSION_COOKIE_NAME")
        Config.DATABASE = self.database_path
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        init_tables()
        self.client = app.test_client()

    def tearDown(self):
        Config.DATABASE = self.original_database
        app.config.update(
            TESTING=self.original_testing,
            SESSION_COOKIE_SECURE=self.original_secure_cookie,
            SESSION_COOKIE_DOMAIN=self.original_cookie_domain,
            SESSION_COOKIE_NAME=self.original_cookie_name,
        )
        try:
            os.remove(self.database_path)
        except OSError:
            pass

    def test_anonymous_visitors_can_browse_read_only_pages(self):
        for path in (
            "/",
            "/news",
            "/matches",
            "/results",
            "/events",
            "/players",
            "/stats",
            "/predictions",
            "/dashboard",
            "/forum",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        api = self.client.get("/api/front/home")
        self.assertEqual(api.status_code, 200)

        self.assertEqual(self.client.get("/login").status_code, 200)
        self.assertEqual(self.client.get("/register").status_code, 200)
        self.assertEqual(self.client.get("/healthz").status_code, 200)
        self.assertEqual(self.client.get("/admin/").headers["Location"], "/admin/login")

    def test_anonymous_visitors_cannot_use_write_features(self):
        feedback = self.client.post(
            "/api/feedback/submit",
            json={"type": "suggestion", "content": "guest write attempt"},
        )
        self.assertEqual(feedback.status_code, 401)
        self.assertEqual(feedback.get_json()["error"], "请先登录")

        comment = self.client.post("/comment/news/1", data={"content": "guest"})
        self.assertEqual(comment.status_code, 302)
        self.assertTrue(comment.headers["Location"].startswith("/login?next="))

        vote = self.client.post(
            "/matches/1/vote",
            data={"voted_for": "t1"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(vote.status_code, 401)
        self.assertEqual(vote.get_json()["error"], "请先登录")

        conn = get_db()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM match_votes").fetchone()[0], 0)
        conn.close()

    def test_approved_login_survives_normal_page_navigation(self):
        conn = get_db()
        conn.execute(
            """INSERT INTO users(
                   username, password_hash, approval_status, group_username
               ) VALUES('PersistentUser', ?, 'approved', 'Persistent Group')""",
            (generate_password_hash("password123"),),
        )
        conn.commit()
        conn.close()

        self.client.get("/login")
        with self.client.session_transaction() as browser_session:
            csrf_token = browser_session["csrf_token"]
        with patch("routes.auth._check_captcha", return_value=True):
            response = self.client.post(
                "/login",
                data={
                    "csrf_token": csrf_token,
                    "username": "PersistentUser",
                    "password": "password123",
                    "captcha": "ABCDE",
                },
            )
        self.assertEqual(response.status_code, 302)

        for path in ("/", "/events", "/forum"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
                with self.client.session_transaction() as browser_session:
                    self.assertIn("user_id", browser_session)
                    self.assertTrue(browser_session.permanent)

    def test_transient_account_check_failure_does_not_log_user_out(self):
        conn = get_db()
        conn.execute(
            """INSERT INTO users(
                   username, password_hash, approval_status, group_username
               ) VALUES('TransientUser', ?, 'approved', 'Transient Group')""",
            (generate_password_hash("password123"),),
        )
        user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()
        with self.client.session_transaction() as browser_session:
            browser_session["user_id"] = user_id
            browser_session["user_username"] = "TransientUser"
            browser_session["csrf_token"] = "transient-test"

        with patch("web_app.get_db", side_effect=RuntimeError("temporary database error")):
            self.assertEqual(self.client.get("/").status_code, 200)

        with self.client.session_transaction() as browser_session:
            self.assertEqual(browser_session.get("user_id"), user_id)

    def test_session_cookie_can_be_shared_between_apex_and_www(self):
        app.config.update(
            SESSION_COOKIE_DOMAIN=".80gotv.cn",
            SESSION_COOKIE_NAME="80gotv_session",
        )
        conn = get_db()
        conn.execute(
            """INSERT INTO users(
                   username, password_hash, approval_status, group_username
               ) VALUES('SharedDomainUser', ?, 'approved', 'Shared Domain Group')""",
            (generate_password_hash("password123"),),
        )
        conn.commit()
        conn.close()

        # 模拟浏览器里还留着改版前的同名登录记录；新会话必须完全避开它。
        self.client.set_cookie("session", "stale-host-cookie", domain="80gotv.cn")
        login_page = self.client.get("/login", base_url="https://www.80gotv.cn")
        self.assertIn("80gotv_session=", login_page.headers.get("Set-Cookie", ""))
        with self.client.session_transaction(base_url="https://www.80gotv.cn") as browser_session:
            csrf_token = browser_session["csrf_token"]
        with patch("routes.auth._check_captcha", return_value=True):
            response = self.client.post(
                "/login",
                base_url="https://www.80gotv.cn",
                data={
                    "csrf_token": csrf_token,
                    "username": "SharedDomainUser",
                    "password": "password123",
                    "captcha": "ABCDE",
                },
            )
        self.assertEqual(response.status_code, 302)
        apex = self.client.get("/", base_url="https://80gotv.cn")
        self.assertEqual(apex.status_code, 200)
        self.assertIn("SharedDomainUser", apex.get_data(as_text=True))
        protected = self.client.get("/guess-player", base_url="https://80gotv.cn")
        self.assertEqual(protected.status_code, 200)

    def test_admin_login_uses_the_new_cookie_name(self):
        app.config.update(
            SESSION_COOKIE_DOMAIN=".80gotv.cn",
            SESSION_COOKIE_NAME="80gotv_session",
        )
        conn = get_db()
        conn.execute(
            "INSERT INTO admins(username, password_hash) VALUES(?, ?)",
            ("CookieAdmin", generate_password_hash("adminpass123")),
        )
        conn.commit()
        conn.close()

        self.client.set_cookie("session", "stale-admin-cookie", domain="80gotv.cn")
        login_page = self.client.get("/admin/login", base_url="https://www.80gotv.cn")
        with self.client.session_transaction(base_url="https://www.80gotv.cn") as browser_session:
            csrf_token = browser_session["csrf_token"]
        response = self.client.post(
            "/admin/login",
            base_url="https://www.80gotv.cn",
            data={
                "csrf_token": csrf_token,
                "username": "CookieAdmin",
                "password": "adminpass123",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("80gotv_session=", response.headers.get("Set-Cookie", ""))
        dashboard = self.client.get("/admin/", base_url="https://80gotv.cn")
        self.assertEqual(dashboard.status_code, 200)

    def test_feedback_requires_csrf_for_logged_in_users(self):
        conn = get_db()
        conn.execute(
            """INSERT INTO users(
                   username, password_hash, approval_status, group_username
               ) VALUES('FeedbackUser', ?, 'approved', 'Feedback Group')""",
            (generate_password_hash("password123"),),
        )
        user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()
        with self.client.session_transaction() as browser_session:
            browser_session["user_id"] = user_id
            browser_session["user_username"] = "FeedbackUser"
            browser_session["csrf_token"] = "feedback-test"

        rejected = self.client.post(
            "/api/feedback/submit",
            json={"type": "suggestion", "content": "missing token"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(rejected.status_code, 403)

        accepted = self.client.post(
            "/api/feedback/submit",
            json={"type": "suggestion", "content": "valid feedback"},
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRF-Token": "feedback-test",
            },
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertTrue(accepted.get_json()["ok"])

    def test_claimed_placeholder_account_still_requires_admin_approval(self):
        steam_id = "76561198000000077"
        conn = get_db()
        conn.execute(
            """INSERT INTO users(
                   username, password_hash, steam_id64,
                   is_placeholder, approval_status
               ) VALUES('ClaimMe', ?, ?, 1, 'approved')""",
            (generate_password_hash("temporary-password"), steam_id),
        )
        conn.commit()
        conn.close()
        with self.client.session_transaction() as browser_session:
            browser_session["csrf_token"] = "claim-test"
            browser_session["steam_verified"] = {
                "purpose": "recovery",
                "steam_id64": steam_id,
                "verified_at": time.time(),
            }

        response = self.client.post(
            "/change-password",
            data={
                "csrf_token": "claim-test",
                "password": "new-password-123",
                "password2": "new-password-123",
            },
        )
        self.assertEqual(response.status_code, 302)
        conn = get_db()
        user = conn.execute(
            """SELECT is_placeholder, approval_status
               FROM users WHERE username='ClaimMe'"""
        ).fetchone()
        conn.close()
        self.assertEqual(user["is_placeholder"], 0)
        self.assertEqual(user["approval_status"], "pending")

    def test_captcha_is_an_image_and_answer_is_not_stored(self):
        response = self.client.get("/captcha/image")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content_type, "image/png")
        with self.client.session_transaction() as browser_session:
            challenge = browser_session["captcha_challenge"]
            self.assertIn("digest", challenge)
            self.assertNotIn("answer", challenge)

    def test_register_page_can_refresh_a_stale_csrf_token(self):
        self.client.get("/register")
        with self.client.session_transaction() as browser_session:
            stale_token = browser_session["csrf_token"]
            browser_session["csrf_token"] = "current-registration-token"

        stale = self.client.post(
            "/auth/email/send-code",
            data={"csrf_token": stale_token, "email": "new@example.com"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(stale.status_code, 403)

        refreshed = self.client.get("/auth/csrf-token")
        self.assertEqual(refreshed.status_code, 200)
        self.assertEqual(refreshed.get_json()["csrf_token"], "current-registration-token")
        self.assertIn("no-store", refreshed.headers["Cache-Control"])

    def test_public_http_registration_redirects_to_https(self):
        app.config["SESSION_COOKIE_SECURE"] = True
        response = self.client.get(
            "/register?source=mobile",
            base_url="http://80gotv.cn",
            headers={
                "X-Forwarded-Proto": "http",
                "X-Forwarded-Host": "80gotv.cn",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 308)
        self.assertEqual(response.headers["Location"], "https://80gotv.cn/register?source=mobile")

        tunnel_response = self.client.get(
            "/register",
            base_url="http://80gotv.cn",
            headers={"CF-Visitor": '{"scheme":"http"}'},
            follow_redirects=False,
        )
        self.assertEqual(tunnel_response.status_code, 308)
        self.assertEqual(tunnel_response.headers["Location"], "https://80gotv.cn/register")

    def test_new_registration_waits_for_admin_approval(self):
        with self.client.session_transaction() as browser_session:
            browser_session["csrf_token"] = "registration-test"
            browser_session["register_form_started_at"] = time.time() - 3
            browser_session["steam_verified"] = {
                "purpose": "register",
                "steam_id64": "76561198000000001",
                "verified_at": time.time(),
            }
            browser_session["registration_email_verified"] = {
                "email": "pending@example.com",
                "verified_at": time.time(),
            }

        with patch("routes.auth._check_captcha", return_value=True):
            response = self.client.post(
                "/register",
                data={
                    "csrf_token": "registration-test",
                    "username": "PendingPlayer",
                    "group_username": "Pending In Group",
                    "is_bashizhong_student": "1",
                    "email": "pending@example.com",
                    "password": "strongpass123",
                    "password2": "strongpass123",
                    "captcha": "ABCDE",
                    "website": "",
                },
            )
        self.assertEqual(response.status_code, 302)
        conn = get_db()
        user = conn.execute(
            """SELECT approval_status, email, email_verified_at, group_username
               FROM users WHERE username='PendingPlayer'"""
        ).fetchone()
        player = conn.execute(
            "SELECT id FROM players WHERE steam_id='76561198000000001'"
        ).fetchone()
        conn.close()
        self.assertEqual(user["approval_status"], "pending")
        self.assertEqual(user["email"], "pending@example.com")
        self.assertEqual(user["group_username"], "Pending In Group")
        self.assertIsNotNone(user["email_verified_at"])
        self.assertIsNone(player)

    def test_new_registration_requires_group_username(self):
        with self.client.session_transaction() as browser_session:
            browser_session["csrf_token"] = "registration-group-test"
            browser_session["register_form_started_at"] = time.time() - 3
            browser_session["steam_verified"] = {
                "purpose": "register",
                "steam_id64": "76561198000000011",
                "verified_at": time.time(),
            }
            browser_session["registration_email_verified"] = {
                "email": "missing-group@example.com",
                "verified_at": time.time(),
            }

        with patch("routes.auth._check_captcha", return_value=True):
            response = self.client.post(
                "/register",
                data={
                    "csrf_token": "registration-group-test",
                    "username": "MissingGroup",
                    "group_username": "   ",
                    "is_bashizhong_student": "1",
                    "email": "missing-group@example.com",
                    "password": "strongpass123",
                    "password2": "strongpass123",
                    "captcha": "ABCDE",
                    "website": "",
                },
                follow_redirects=True,
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("请填写群内用户名", response.get_data(as_text=True))
        conn = get_db()
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM users WHERE username='MissingGroup'").fetchone()[0],
            0,
        )
        conn.close()

    def test_external_school_registration_does_not_require_group_username(self):
        with self.client.session_transaction() as browser_session:
            browser_session["csrf_token"] = "external-registration-test"
            browser_session["register_form_started_at"] = time.time() - 3
            browser_session["steam_verified"] = {
                "purpose": "register",
                "steam_id64": "76561198000000012",
                "verified_at": time.time(),
            }
            browser_session["registration_email_verified"] = {
                "email": "external@example.com",
                "verified_at": time.time(),
            }

        with patch("routes.auth._check_captcha", return_value=True):
            response = self.client.post(
                "/register",
                data={
                    "csrf_token": "external-registration-test",
                    "username": "ExternalPlayer",
                    "group_username": "",
                    "is_bashizhong_student": "0",
                    "email": "external@example.com",
                    "password": "strongpass123",
                    "password2": "strongpass123",
                    "captcha": "ABCDE",
                    "website": "",
                },
            )
        self.assertEqual(response.status_code, 302)
        conn = get_db()
        user = conn.execute(
            """SELECT group_username, is_bashizhong_student, approval_status
               FROM users WHERE username='ExternalPlayer'"""
        ).fetchone()
        conn.close()
        self.assertIsNotNone(user)
        self.assertEqual(user["is_bashizhong_student"], 0)
        self.assertIsNone(user["group_username"])
        self.assertEqual(user["approval_status"], "pending")

    def test_existing_account_gets_uncloseable_profile_modal_after_login(self):
        steam_id = "76561198000000013"
        conn = get_db()
        conn.execute(
            """INSERT INTO users(
                   username, password_hash, approval_status, group_username,
                   steam_id64
               ) VALUES('LegacyPlayer', ?, 'approved', 'Legacy Group', ?)""",
            (generate_password_hash("password123"), steam_id),
        )
        conn.execute(
            "INSERT INTO players(nickname, steam_id) VALUES('LegacyPlayer', ?)",
            (steam_id,),
        )
        conn.commit()
        conn.close()

        self.client.get("/login")
        with self.client.session_transaction() as browser_session:
            login_csrf = browser_session["csrf_token"]
        with patch("routes.auth._check_captcha", return_value=True):
            login = self.client.post(
                "/login",
                data={
                    "csrf_token": login_csrf,
                    "username": "LegacyPlayer",
                    "password": "password123",
                    "captcha": "ABCDE",
                },
            )
        self.assertEqual(login.status_code, 302)

        page = self.client.get("/")
        html = page.get_data(as_text=True)
        self.assertIn('id="profileCompletionForm"', html)
        self.assertIn("登录前请补充一项资料", html)
        self.assertNotIn('class="profile-completion-close"', html)

        with self.client.session_transaction() as browser_session:
            profile_csrf = browser_session["csrf_token"]
            self.assertTrue(browser_session["profile_completion_required"])
        blocked = self.client.post(
            "/api/feedback/submit",
            json={"type": "suggestion", "content": "blocked before completion"},
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRF-Token": profile_csrf,
            },
        )
        self.assertEqual(blocked.status_code, 409)
        self.assertTrue(blocked.get_json()["requires_profile_completion"])

        completed = self.client.post(
            "/account/complete-profile",
            data={
                "csrf_token": profile_csrf,
                "is_bashizhong_student": "0",
                "group_username": "",
                "next": "/",
            },
        )
        self.assertEqual(completed.status_code, 302)
        self.assertEqual(completed.headers["Location"], "/")

        conn = get_db()
        user = conn.execute(
            """SELECT is_bashizhong_student
               FROM users WHERE username='LegacyPlayer'"""
        ).fetchone()
        player = conn.execute(
            """SELECT is_bashizhong_student
               FROM players WHERE steam_id=?""",
            (steam_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(user["is_bashizhong_student"], 0)
        self.assertEqual(player["is_bashizhong_student"], 0)
        self.assertNotIn(
            'id="profileCompletionForm"',
            self.client.get("/").get_data(as_text=True),
        )

    def test_student_profile_completion_requires_group_username(self):
        conn = get_db()
        conn.execute(
            """INSERT INTO users(
                   username, password_hash, approval_status,
                   is_bashizhong_student
               ) VALUES('StudentWithoutGroup', ?, 'approved', 1)""",
            (generate_password_hash("password123"),),
        )
        user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()

        with self.client.session_transaction() as browser_session:
            browser_session["user_id"] = user_id
            browser_session["user_username"] = "StudentWithoutGroup"
            browser_session["csrf_token"] = "student-completion-test"
            browser_session["profile_completion_required"] = True

        response = self.client.post(
            "/account/complete-profile",
            data={
                "csrf_token": "student-completion-test",
                "is_bashizhong_student": "1",
                "group_username": " ",
                "next": "/",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("请填写群内用户名", html)
        self.assertIn('id="profileCompletionForm"', html)

    def test_email_code_can_be_sent_and_verified(self):
        with self.client.session_transaction() as browser_session:
            browser_session["csrf_token"] = "email-test"
        with (
            patch("routes.auth._send_registration_email") as send_email,
            patch("routes.auth.secrets.randbelow", return_value=0),
        ):
            response = self.client.post(
                "/auth/email/send-code",
                data={"csrf_token": "email-test", "email": "new@example.com"},
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
        self.assertEqual(response.status_code, 200)
        send_email.assert_called_once_with("new@example.com", "100000")
        with self.client.session_transaction() as browser_session:
            challenge = browser_session["register_email_challenge"]
            self.assertNotIn("code", challenge)

        response = self.client.post(
            "/auth/email/verify-code",
            data={
                "csrf_token": "email-test",
                "email": "new@example.com",
                "code": "100000",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as browser_session:
            self.assertEqual(
                browser_session["registration_email_verified"]["email"], "new@example.com"
            )

    def test_admin_can_approve_registration(self):
        conn = get_db()
        conn.execute(
            "INSERT INTO admins(username, password_hash) VALUES(?,?)",
            ("reviewer", generate_password_hash("adminpass123")),
        )
        admin_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO users(username, password_hash, steam_id64, approval_status)
               VALUES(?,?,?,'pending')""",
            ("ApprovalPlayer", generate_password_hash("strongpass123"), "76561198000000002"),
        )
        user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()

        with self.client.session_transaction() as browser_session:
            browser_session["admin_id"] = admin_id
            browser_session["admin_username"] = "reviewer"
            browser_session["csrf_token"] = "approval-test"
        response = self.client.post(
            f"/admin/registrations/{user_id}/approve",
            data={"csrf_token": "approval-test"},
        )
        self.assertEqual(response.status_code, 302)

        conn = get_db()
        user = conn.execute("SELECT approval_status FROM users WHERE id=?", (user_id,)).fetchone()
        player = conn.execute(
            "SELECT nickname FROM players WHERE steam_id='76561198000000002'"
        ).fetchone()
        conn.close()
        self.assertEqual(user["approval_status"], "approved")
        self.assertEqual(player["nickname"], "ApprovalPlayer")


if __name__ == "__main__":
    unittest.main()
