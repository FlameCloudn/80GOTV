import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import request
from PIL import Image
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash, generate_password_hash

from app import app
from config import Config
from models import get_db, init_tables
from utils.db_helpers import validate_image_content
from web_app import _limit_request_body


class AdminSurfaceTests(unittest.TestCase):
    def setUp(self):
        handle, self.database_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.original_database = Config.DATABASE
        self.original_testing = app.config.get("TESTING")
        self.original_secure_cookie = app.config.get("SESSION_COOKIE_SECURE")
        Config.DATABASE = self.database_path
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        init_tables()
        # 自建管理员行，避免依赖 .env 种出的数据。
        # 原因：init_tables() 只在 ADMIN_PASSWORD 存在时才创建管理员，而 .env 被
        # gitignore，CI 上没有它 —— 此时 admins 表为空，而下面 session 里的
        # admin_id=1 会被写入 yearly_top_players.decided_by（外键指向 admins(id)），
        # 触发外键违约，保存被回滚却仍返回 302，测试就会以 0 != 10 失败。
        conn = get_db()
        conn.execute(
            "INSERT OR IGNORE INTO admins(id, username, password_hash) "
            "VALUES(1, 'admin-surface-test', 'x')"
        )
        conn.commit()
        conn.close()
        self.client = app.test_client()
        with self.client.session_transaction() as browser_session:
            browser_session["admin_id"] = 1
            browser_session["admin_username"] = "admin"
            browser_session["csrf_token"] = "admin-surface-test"

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

    def test_common_admin_pages_render(self):
        paths = (
            "/admin",
            "/admin/teams",
            "/admin/teams/add",
            "/admin/players",
            "/admin/players/add",
            "/admin/events",
            "/admin/events/add",
            "/admin/matches",
            "/admin/matches/add",
            "/admin/news",
            "/admin/news/add",
            "/admin/registrations",
            "/admin/feedback",
            "/admin/live",
            "/admin/nicknames",
            "/admin/awards/poster",
            "/admin/top10",
        )
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)

    def test_admin_player_and_account_lists_show_cached_cs2_playtime(self):
        conn = get_db()
        conn.execute(
            "INSERT INTO players(nickname, steam_id) VALUES(?,?)",
            ("PlaytimePlayer", "76561198000000999"),
        )
        conn.execute(
            """INSERT INTO users(
                   username, password_hash, steam_id64, approval_status,
                   group_username
               ) VALUES(?,?,?,'pending',?)""",
            (
                "PlaytimeUser",
                "test-hash",
                "76561198000000999",
                "Playtime Group",
            ),
        )
        user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO events(
                   name, slug, registration_open, status, start_date, end_date
               ) VALUES('Playtime Event','playtime-event',1,'upcoming',
                        '2026-07-20','2026-07-21')"""
        )
        event_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO event_individual_registrations(
                   event_id, user_id, player_name, steam_id,
                   cs2_playtime_minutes, playtime_status, playtime_checked_at
               ) VALUES(?,?,?,?,?,'public','2026-07-20T02:00:00+00:00')""",
            (
                event_id,
                user_id,
                "PlaytimeUser",
                "76561198000000999",
                74445,
            ),
        )
        conn.commit()
        conn.close()

        players_html = self.client.get("/admin/players").get_data(as_text=True)
        reviews_html = self.client.get("/admin/registrations").get_data(as_text=True)
        for html in (players_html, reviews_html):
            self.assertIn("1240.8 小时", html)
            self.assertIn("公开数据", html)
            self.assertIn("2026年7月20日 10:00", html)

    def test_admin_can_force_refresh_player_playtime_without_registration(self):
        conn = get_db()
        conn.execute(
            """INSERT INTO players(nickname, steam_id)
               VALUES('RefreshPlayer','76561198000000888')"""
        )
        conn.commit()
        conn.close()

        with (
            patch.object(Config, "STEAM_WEB_API_KEY", "test-key"),
            patch(
                "services.steam_playtime_service.fetch_cs2_playtime_minutes",
                return_value={"status": "public", "minutes": 54321},
            ) as fetch,
        ):
            response = self.post("/admin/players/refresh-playtime")

        self.assertEqual(response.status_code, 302)
        fetch.assert_called_once_with("76561198000000888", "test-key")
        conn = get_db()
        player = conn.execute(
            """SELECT cs2_playtime_minutes, playtime_status, playtime_checked_at
               FROM players WHERE nickname='RefreshPlayer'"""
        ).fetchone()
        conn.close()
        self.assertEqual(player["cs2_playtime_minutes"], 54321)
        self.assertEqual(player["playtime_status"], "public")
        self.assertTrue(player["playtime_checked_at"])

    def test_admin_can_create_an_approved_account(self):
        page = self.client.get("/admin/registrations")
        page_html = page.get_data(as_text=True)
        self.assertIn("/admin/players/add", page_html)
        self.assertNotIn('action="/admin/registrations/create"', page_html)

        add_page = self.client.get("/admin/players/add").get_data(as_text=True)
        self.assertIn("添加选手与账号", add_page)
        self.assertIn('name="is_bashizhong_student"', add_page)
        self.assertIn('name="create_account"', add_page)

        response = self.post(
            "/admin/players/add",
            {
                "nickname": "AdminCreated",
                "group_username": "群内昵称",
                "is_bashizhong_student": "1",
                "steam_id": "76561198000000123",
                "create_account": "1",
                "account_email": "created@example.com",
                "password": "temporary-password",
                "password2": "temporary-password",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/players", response.headers["Location"])

        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username='AdminCreated'").fetchone()
        player = conn.execute("SELECT * FROM players WHERE steam_id='76561198000000123'").fetchone()
        conn.close()
        self.assertIsNotNone(user)
        self.assertEqual(user["approval_status"], "approved")
        self.assertEqual(user["is_placeholder"], 0)
        self.assertEqual(user["group_username"], "群内昵称")
        self.assertEqual(user["is_bashizhong_student"], 1)
        self.assertTrue(check_password_hash(user["password_hash"], "temporary-password"))
        self.assertIsNotNone(player)
        self.assertEqual(player["nickname"], "AdminCreated")
        self.assertEqual(player["group_username_override"], "群内昵称")
        self.assertEqual(player["is_bashizhong_student"], 1)

    def test_admin_account_creation_rejects_duplicate_username_and_steam_id(self):
        conn = get_db()
        conn.execute(
            """INSERT INTO users(
                   username, password_hash, steam_id64, group_username,
                   approval_status
               ) VALUES(?,?,?,?, 'approved')""",
            (
                "ExistingUser",
                generate_password_hash("existing-password"),
                "76561198000000456",
                "Existing Group",
            ),
        )
        conn.commit()
        conn.close()

        duplicate_username = self.post(
            "/admin/players/add",
            {
                "nickname": "existinguser",
                "group_username": "Another Group",
                "is_bashizhong_student": "1",
                "steam_id": "76561198000000457",
                "create_account": "1",
                "password": "temporary-password",
                "password2": "temporary-password",
            },
        )
        self.assertEqual(duplicate_username.status_code, 400)

        duplicate_steam = self.post(
            "/admin/players/add",
            {
                "nickname": "NewUser",
                "group_username": "Another Group",
                "is_bashizhong_student": "1",
                "steam_id": "76561198000000456",
                "create_account": "1",
                "password": "temporary-password",
                "password2": "temporary-password",
            },
        )
        self.assertEqual(duplicate_steam.status_code, 400)

        conn = get_db()
        account_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        new_user = conn.execute("SELECT id FROM users WHERE username='NewUser'").fetchone()
        conn.close()
        self.assertEqual(account_count, 1)
        self.assertIsNone(new_user)

    def test_admin_can_change_password_for_linked_player_account(self):
        conn = get_db()
        old_hash = generate_password_hash("old-password")
        conn.execute(
            """INSERT INTO users(
                   username, password_hash, steam_id64, approval_status,
                   group_username
               ) VALUES(?,?,?,'approved',?)""",
            (
                "PasswordUser",
                old_hash,
                "76561198000000777",
                "Password Group",
            ),
        )
        user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO players(nickname, steam_id) VALUES(?,?)",
            ("PasswordPlayer", "76561198000000777"),
        )
        player_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()

        players_html = self.client.get("/admin/players").get_data(as_text=True)
        self.assertIn(f"/admin/players/password/{player_id}", players_html)
        self.assertIn("账号：PasswordUser", players_html)

        form = self.client.get(f"/admin/players/password/{player_id}")
        self.assertEqual(form.status_code, 200)
        self.assertIn("PasswordPlayer", form.get_data(as_text=True))

        mismatch = self.post(
            f"/admin/players/password/{player_id}",
            {"password": "new-password", "password2": "different-password"},
        )
        self.assertEqual(mismatch.status_code, 400)

        response = self.post(
            f"/admin/players/password/{player_id}",
            {"password": "new-password", "password2": "new-password"},
        )
        self.assertEqual(response.status_code, 302)
        conn = get_db()
        stored_hash = conn.execute(
            "SELECT password_hash FROM users WHERE id=?", (user_id,)
        ).fetchone()["password_hash"]
        conn.close()
        self.assertTrue(check_password_hash(stored_hash, "new-password"))
        self.assertFalse(check_password_hash(stored_hash, "old-password"))

    def test_password_action_marks_unlinked_player_instead_of_guessing_account(self):
        conn = get_db()
        conn.execute(
            "INSERT INTO players(nickname, steam_id) VALUES(?,?)",
            ("NoAccountPlayer", "76561198000000666"),
        )
        player_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()

        html = self.client.get("/admin/players").get_data(as_text=True)
        self.assertIn("未关联账号", html)
        response = self.client.get(f"/admin/players/password/{player_id}")
        self.assertEqual(response.status_code, 302)

    def test_common_admin_pages_use_shared_shell(self):
        paths = (
            "/admin",
            "/admin/teams",
            "/admin/players",
            "/admin/events",
            "/admin/matches",
            "/admin/news",
            "/admin/registrations",
            "/admin/feedback",
            "/admin/live",
            "/admin/nicknames",
            "/admin/awards/poster",
            "/admin/top10",
            "/admin/teams/add",
            "/admin/players/add",
            "/admin/events/add",
            "/admin/matches/add",
            "/admin/news/add",
        )
        for path in paths:
            with self.subTest(path=path):
                html = self.client.get(path).get_data(as_text=True)
                # 新版后台外壳：顶栏 + 左侧导航，和前台同一套样式；旧样式表不再加载
                self.assertIn('class="admin-topbar"', html)
                self.assertIn('aria-label="后台导航"', html)
                self.assertIn("css/app.css", html)
                self.assertIn("css/pages/admin.css", html)
                self.assertNotIn("css/style.css", html)
                self.assertNotIn("css/admin-comfort.css", html)
                self.assertIn("后台管理", html)
                self.assertIn('id="languageSelect"', html)
                self.assertNotIn('class="language-floating"', html)

    def test_every_admin_page_template_uses_the_new_shell(self):
        """后台每个页面模板都继承新版外壳（登录页单独用新版样式），不再引用旧样式和旧图标脚本。"""
        template_dir = Path(app.root_path) / "templates" / "admin"
        for template in template_dir.glob("*.html"):
            if template.name.startswith("_"):
                continue
            text = template.read_text(encoding="utf-8")
            with self.subTest(template=template.name):
                if template.name == "login.html":
                    self.assertIn("css/pages/admin.css", text)
                    self.assertIn("_standalone_head.html", text)
                else:
                    self.assertIn('{% extends "admin/_layout.html" %}', text)
                for legacy in ("css/style.css", "admin-comfort.css", "svg_icons.js", 'style="'):
                    self.assertNotIn(legacy, text)

    def test_dashboard_stat_cards_link_to_matching_management_pages(self):
        html = self.client.get("/admin").get_data(as_text=True)
        expected_links = (
            ("/admin/teams", "队伍"),
            ("/admin/players", "选手"),
            ("/admin/events", "赛事"),
            ("/admin/matches", "比赛"),
            ("/admin/news", "新闻"),
            ("/admin/registrations", "待审核账号"),
        )
        for href, label in expected_links:
            with self.subTest(label=label):
                card = re.search(
                    rf'<a[^>]+href="{re.escape(href)}"[^>]+class="admin-stat-box"[^>]*>(.*?)</a>',
                    html,
                    re.DOTALL,
                )
                self.assertIsNotNone(card)
                self.assertIn(label, card.group(1))

    def test_dashboard_live_matches_are_prioritized_before_limiting_rows(self):
        from blueprints.admin_core import _dashboard_work

        conn = get_db()
        upcoming = []
        for day in range(1, 14):
            upcoming.append(
                conn.execute(
                    "INSERT INTO matches(status,match_time) VALUES('upcoming',?)",
                    (f"2099-01-{day:02d} 12:00:00",),
                ).lastrowid
            )
        automatic_live = conn.execute(
            "INSERT INTO matches(status,match_time) VALUES('upcoming','2000-01-01 12:00:00')"
        ).lastrowid
        manual_live = conn.execute(
            "INSERT INTO matches(status,match_time) VALUES('live','2099-12-01 12:00:00')"
        ).lastrowid
        undated_live = conn.execute("INSERT INTO matches(status) VALUES('live')").lastrowid
        for status in ("completed", "cancelled"):
            conn.execute(
                "INSERT INTO matches(status,match_time) VALUES(?,'1999-01-01 12:00:00')", (status,)
            )
        conn.commit()
        try:
            matches = _dashboard_work(conn)["active_matches"]
        finally:
            conn.close()
        self.assertEqual(
            [match["id"] for match in matches],
            [automatic_live, manual_live, undated_live, *upcoming[:5]],
        )
        self.assertEqual([match["effective_status"] for match in matches[:3]], ["live"] * 3)

    def test_dashboard_pending_count_excludes_placeholder_accounts(self):
        conn = get_db()
        conn.execute(
            """INSERT INTO users(
                   username, password_hash, approval_status, is_placeholder
               ) VALUES('RealPending','hash','pending',0)"""
        )
        conn.execute(
            """INSERT INTO users(
                   username, password_hash, approval_status, is_placeholder
               ) VALUES('PlaceholderPending','hash','pending',1)"""
        )
        conn.commit()
        conn.close()

        html = self.client.get("/admin").get_data(as_text=True)
        self.assertIn("共 1 个待审核账号", html)
        self.assertIn("账号审核 (1)", html)
        self.assertNotIn("账号审核 (2)", html)

    def test_verified_placeholder_claim_is_visible_for_review(self):
        conn = get_db()
        conn.execute(
            """INSERT INTO users(
                   username, password_hash, email, email_verified_at,
                   approval_status, is_placeholder
               ) VALUES('ClaimedPending','hash','claimed@example.com',
                        CURRENT_TIMESTAMP,'pending',1)"""
        )
        conn.commit()
        conn.close()

        dashboard = self.client.get("/admin").get_data(as_text=True)
        reviews = self.client.get("/admin/registrations").get_data(as_text=True)
        self.assertIn("共 1 个待审核账号", dashboard)
        self.assertIn("ClaimedPending", reviews)

    def test_admin_can_publish_and_clear_exactly_ten_unique_top10_players(self):
        conn = get_db()
        for index in range(1, 11):
            conn.execute("INSERT INTO players(nickname) VALUES(?)", (f"Top {index}",))
        conn.commit()
        player_ids = [
            row["id"] for row in conn.execute("SELECT id FROM players ORDER BY id").fetchall()
        ]
        conn.close()

        payload = {
            "year": "2026",
            **{
                f"rank_{rank}": str(player_id) for rank, player_id in enumerate(player_ids, start=1)
            },
        }
        response = self.post("/admin/top10/save", payload)
        self.assertEqual(response.status_code, 302)
        conn = get_db()
        rows = conn.execute(
            "SELECT rank, player_id FROM yearly_top_players WHERE year=2026 ORDER BY rank"
        ).fetchall()
        conn.close()
        self.assertEqual(len(rows), 10)
        self.assertEqual([row["rank"] for row in rows], list(range(1, 11)))

        duplicate = dict(payload, rank_10=str(player_ids[0]))
        self.assertEqual(self.post("/admin/top10/save", duplicate).status_code, 302)
        conn = get_db()
        unchanged = conn.execute(
            "SELECT COUNT(*) FROM yearly_top_players WHERE year=2026"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(unchanged, 10)

        self.assertEqual(
            self.post(
                "/admin/top10/save",
                {"year": "2026", "action": "clear"},
            ).status_code,
            302,
        )
        conn = get_db()
        remaining = conn.execute(
            "SELECT COUNT(*) FROM yearly_top_players WHERE year=2026"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(remaining, 0)

    def test_news_editor_has_local_editor_and_textarea_fallback(self):
        response = self.client.get("/admin/news/add")
        html = response.get_data(as_text=True)
        self.assertIn("/static/vendor/quill/quill.min.js", html)
        self.assertIn("/static/vendor/quill/quill.snow.css", html)
        self.assertNotIn("cdn.quilljs.com", html)
        self.assertIn('id="editor" data-i18n-ignore', html)
        self.assertRegex(html, r'<textarea[^>]+id="contentTextarea"[^>]+required')
        self.assertIn("fd.append('csrf_token'", html)
        script_response = self.client.get("/static/vendor/quill/quill.min.js")
        style_response = self.client.get("/static/vendor/quill/quill.snow.css")
        self.assertEqual(script_response.status_code, 200)
        self.assertEqual(style_response.status_code, 200)
        script_response.close()
        style_response.close()

        i18n_source = (Path(app.root_path) / "static" / "js" / "i18n.js").read_text(
            encoding="utf-8"
        )
        self.assertIn('[contenteditable="true"]', i18n_source)
        # 翻译脚本改为逐条处理页面变化：编辑器里的输入必须逐条跳过，不能被翻译。
        self.assertIn("if (mutationIsInsideEditor(mutation)) continue;", i18n_source)
        self.assertIn("if (!mutationIsInsideEditor(mutation)) pendingRoots.push", i18n_source)

    def test_admin_post_forms_have_csrf_and_no_missing_helpers(self):
        template_dir = Path(app.root_path) / "templates" / "admin"
        for template in template_dir.glob("*.html"):
            text = template.read_text(encoding="utf-8")
            self.assertNotIn("window._confirmThen", text, template.name)
            self.assertNotIn("</a >", text, template.name)
            forms = re.finditer(
                r'<form\b[^>]*method=["\']post["\'][^>]*>(.*?)</form>',
                text,
                re.IGNORECASE | re.DOTALL,
            )
            for index, form in enumerate(forms, 1):
                self.assertIn("csrf_token", form.group(0), f"{template.name} form {index}")

    def post(self, path, data=None, **kwargs):
        payload = {"csrf_token": "admin-surface-test"}
        payload.update(data or {})
        return self.client.post(path, data=payload, **kwargs)

    def test_duplicate_team_and_player_values_are_rejected(self):
        first = self.post(
            "/admin/teams/add",
            {"name": "Team Alpha", "short_name": "TA", "description": ""},
        )
        self.assertEqual(first.status_code, 302)
        duplicate = self.post(
            "/admin/teams/add",
            {"name": " team alpha ", "short_name": "TB", "description": ""},
        )
        self.assertEqual(duplicate.status_code, 400)

        player = self.post(
            "/admin/players/add",
            {
                "nickname": "Player One",
                "is_bashizhong_student": "0",
                "steam_id": "76561198000000001",
            },
        )
        self.assertEqual(player.status_code, 302)
        duplicate_steam = self.post(
            "/admin/players/add",
            {
                "nickname": "Player Two",
                "is_bashizhong_student": "0",
                "steam_id": "76561198000000001",
            },
        )
        self.assertEqual(duplicate_steam.status_code, 400)
        conn = get_db()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM players").fetchone()[0], 1)
        conn.close()

    def test_event_validation_rejects_duplicate_and_reversed_dates(self):
        blank_short_name = {
            "name": "No Short Name",
            "short_name": "",
            "start_date": "2026-07-11T10:00",
            "end_date": "2026-07-12T10:00",
        }
        self.assertEqual(self.post("/admin/events/add", blank_short_name).status_code, 400)
        values = {
            "name": "Summer Cup",
            "short_name": "SUMMER",
            "start_date": "2026-07-11T10:00",
            "end_date": "2026-07-12T10:00",
        }
        self.assertEqual(self.post("/admin/events/add", values).status_code, 302)
        self.assertEqual(self.post("/admin/events/add", values).status_code, 400)
        reversed_dates = dict(values, name="Winter Cup", short_name="WINTER")
        reversed_dates.update(start_date="2026-07-13T10:00", end_date="2026-07-12T10:00")
        self.assertEqual(self.post("/admin/events/add", reversed_dates).status_code, 400)

    def test_invalid_team_logo_on_create_preserves_values_then_valid_retry_saves(self):
        values = {"name": "Logo Retry", "short_name": "LR", "description": "Keep this description"}
        with (
            tempfile.TemporaryDirectory() as upload_root,
            patch("blueprints.admin_catalog.BASE_DIR", upload_root),
        ):
            response = self.post(
                "/admin/teams/add", dict(values, logo=(io.BytesIO(b"not an image"), "broken.png"))
            )
            self.assertEqual(response.status_code, 400)
            html = response.get_data(as_text=True)
            for value in values.values():
                self.assertIn(value, html)
            self.assertIn("队标无效", html)
            conn = get_db()
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0], 0)
            conn.close()
            self.assertEqual(list(Path(upload_root).rglob("*")), [])

            picture = io.BytesIO()
            Image.new("RGB", (24, 24), "blue").save(picture, format="PNG")
            picture.seek(0)
            saved = self.post("/admin/teams/add", dict(values, logo=(picture, "valid.png")))
            self.assertEqual(saved.status_code, 302)
            conn = get_db()
            team = dict(
                conn.execute("SELECT * FROM teams WHERE name=?", (values["name"],)).fetchone()
            )
            conn.close()
            self.assertTrue(team["logo"].startswith("team_logos/"))
            self.assertTrue((Path(upload_root) / "static/uploads" / team["logo"]).is_file())
            reopened = self.client.get(f"/admin/teams/edit/{team['id']}").get_data(as_text=True)
            self.assertIn(team["logo"], reopened)
            self.assertIn(values["description"], reopened)

    def test_invalid_team_logo_edit_preserves_existing_record_and_old_file(self):
        conn = get_db()
        team_id = conn.execute(
            "INSERT INTO teams(name,short_name,description,logo) VALUES(?,?,?,?)",
            ("Old Team", "OLD", "Original description", "team_logos/old.png"),
        ).lastrowid
        conn.commit()
        conn.close()
        values = {"name": "Changed Team", "short_name": "NEW", "description": "New description"}
        with (
            tempfile.TemporaryDirectory() as upload_root,
            patch("blueprints.admin_catalog.BASE_DIR", upload_root),
        ):
            old_logo = Path(upload_root) / "static/uploads/team_logos/old.png"
            old_logo.parent.mkdir(parents=True)
            old_logo.write_bytes(b"original logo fixture")
            for filename in ("broken.png", "unsupported.txt"):
                with self.subTest(filename=filename):
                    response = self.post(
                        f"/admin/teams/edit/{team_id}",
                        dict(values, logo=(io.BytesIO(b"not an image"), filename)),
                    )
                    self.assertEqual(response.status_code, 400)
                    html = response.get_data(as_text=True)
                    for value in values.values():
                        self.assertIn(value, html)
                    self.assertIn("team_logos/old.png", html)
                    self.assertIn("队标无效", html)
                    conn = get_db()
                    record = conn.execute(
                        "SELECT name,short_name,description,logo FROM teams WHERE id=?", (team_id,)
                    ).fetchone()
                    conn.close()
                    self.assertEqual(
                        tuple(record),
                        ("Old Team", "OLD", "Original description", "team_logos/old.png"),
                    )
                    self.assertEqual(old_logo.read_bytes(), b"original logo fixture")
                    self.assertEqual(list(old_logo.parent.iterdir()), [old_logo])

            self.assertEqual(self.post(f"/admin/teams/edit/{team_id}", values).status_code, 302)
            conn = get_db()
            record = conn.execute(
                "SELECT name,short_name,description,logo FROM teams WHERE id=?", (team_id,)
            ).fetchone()
            conn.close()
            self.assertEqual(tuple(record), (*values.values(), "team_logos/old.png"))
            self.assertEqual(old_logo.read_bytes(), b"original logo fixture")

    def test_team_logo_request_allowance_does_not_raise_other_upload_limits(self):
        paths = (
            ("/admin/teams/add", 11),
            ("/admin/teams/edit/1", 11),
            ("/events/1/register", 11),
            ("/events/1/registrations/1/logo", 11),
            ("/register", 6),
            ("/profile", 6),
            ("/admin/upload/image", 6),
            ("/admin/players/add", 6),
            ("/admin/players/edit/1", 6),
        )
        for path, megabytes in paths:
            with self.subTest(path=path):
                with app.test_request_context(path, method="POST"):
                    _limit_request_body()
                    self.assertEqual(request.max_content_length, megabytes * 1024 * 1024)
        with app.test_request_context("/admin/teams/add", method="POST", json={}):
            _limit_request_body()
            self.assertEqual(request.max_content_length, 2 * 1024 * 1024)
        with app.test_request_context(
            "/admin/teams/add",
            method="POST",
            environ_overrides={"CONTENT_LENGTH": str(11 * 1024 * 1024 + 1)},
        ):
            with self.assertRaises(RequestEntityTooLarge):
                _limit_request_body()

    def test_team_logo_accepts_ten_mb_and_rejects_one_byte_over_without_changes(self):
        limit = 10 * 1024 * 1024
        picture = io.BytesIO()
        Image.new("RGB", (24, 24), "blue").save(picture, format="PNG")
        image_bytes = picture.getvalue().ljust(limit, b"\0")
        # 只放宽队标；头像和新闻图片仍使用原有的 5MB 检查。
        self.assertIsNone(validate_image_content(io.BytesIO(image_bytes)))
        values = {"name": "Ten MB Logo", "short_name": "TEN", "description": "Boundary upload"}
        with (
            tempfile.TemporaryDirectory() as upload_root,
            patch("blueprints.admin_catalog.BASE_DIR", upload_root),
        ):
            oversized = self.post(
                "/admin/teams/add",
                dict(values, logo=(io.BytesIO(image_bytes + b"\0"), "oversized.png")),
            )
            self.assertEqual(oversized.status_code, 400)
            for value in (*values.values(), "10MB"):
                self.assertIn(value, oversized.get_data(as_text=True))
            conn = get_db()
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0], 0)
            conn.close()
            self.assertEqual(list(Path(upload_root).rglob("*")), [])

            created = self.post(
                "/admin/teams/add", dict(values, logo=(io.BytesIO(image_bytes), "at-limit.png"))
            )
            self.assertEqual(created.status_code, 302)
            conn = get_db()
            team = dict(
                conn.execute("SELECT * FROM teams WHERE name=?", (values["name"],)).fetchone()
            )
            conn.close()
            old_logo = Path(upload_root) / "static/uploads" / team["logo"]
            old_bytes = old_logo.read_bytes()
            files_before = sorted(Path(upload_root).rglob("*"))
            edited_values = dict(values, description="Keep this edit after rejection")
            rejected = self.post(
                f"/admin/teams/edit/{team['id']}",
                dict(edited_values, logo=(io.BytesIO(image_bytes + b"\0"), "oversized.png")),
            )
            self.assertEqual(rejected.status_code, 400)
            for value in (*edited_values.values(), team["logo"], "10MB"):
                self.assertIn(value, rejected.get_data(as_text=True))
            conn = get_db()
            unchanged = conn.execute(
                "SELECT description,logo FROM teams WHERE id=?", (team["id"],)
            ).fetchone()
            conn.close()
            self.assertEqual(tuple(unchanged), (values["description"], team["logo"]))
            self.assertEqual(old_logo.read_bytes(), old_bytes)
            self.assertEqual(sorted(Path(upload_root).rglob("*")), files_before)

            saved = self.post(
                f"/admin/teams/edit/{team['id']}",
                dict(edited_values, logo=(io.BytesIO(image_bytes), "replacement.png")),
            )
            self.assertEqual(saved.status_code, 302)
            conn = get_db()
            updated = conn.execute(
                "SELECT description,logo FROM teams WHERE id=?", (team["id"],)
            ).fetchone()
            conn.close()
            self.assertEqual(updated["description"], edited_values["description"])
            self.assertNotEqual(updated["logo"], team["logo"])
            self.assertTrue((Path(upload_root) / "static/uploads" / updated["logo"]).is_file())

    def test_event_stream_url_is_optional_and_can_be_added_or_cleared_later(self):
        form_html = self.client.get("/admin/events/add").get_data(as_text=True)
        # 直播间地址放在可折叠的“选填”分组里（新建赛事时折叠，不打扰必填项）
        optional_group = re.search(
            r'<details class="form-group optional"\s*>(.*?)</details>', form_html, re.DOTALL
        )
        self.assertIsNotNone(optional_group)
        self.assertIn('name="stream_url"', optional_group.group(1))
        stream_input = re.search(r'<input[^>]+name="stream_url"[^>]*>', form_html)
        self.assertIsNotNone(stream_input)
        self.assertNotIn("required", stream_input.group(0))

        values = {
            "name": "Optional Stream Cup",
            "short_name": "OPTIONAL_STREAM",
            "start_date": "2026-08-01T10:00",
            "end_date": "2026-08-02T20:00",
        }
        created = self.post("/admin/events/add", values)
        self.assertEqual(created.status_code, 302)

        conn = get_db()
        event = conn.execute(
            "SELECT id, stream_url FROM events WHERE name=?",
            (values["name"],),
        ).fetchone()
        conn.close()
        self.assertIsNone(event["stream_url"])

        edited = dict(
            values,
            status="upcoming",
            stream_url="https://live.bilibili.com/123456",
        )
        self.assertEqual(
            self.post(f"/admin/events/edit/{event['id']}", edited).status_code,
            302,
        )
        conn = get_db()
        self.assertEqual(
            conn.execute("SELECT stream_url FROM events WHERE id=?", (event["id"],)).fetchone()[
                "stream_url"
            ],
            "https://live.bilibili.com/123456",
        )
        conn.close()

        edited["stream_url"] = ""
        self.assertEqual(
            self.post(f"/admin/events/edit/{event['id']}", edited).status_code,
            302,
        )
        conn = get_db()
        self.assertIsNone(
            conn.execute("SELECT stream_url FROM events WHERE id=?", (event["id"],)).fetchone()[
                "stream_url"
            ]
        )
        conn.close()

    def test_news_requires_content_rejects_duplicates_and_sets_publish_time(self):
        empty = self.post("/admin/news/add", {"title": "Empty", "content": "<p><br></p>"})
        self.assertEqual(empty.status_code, 400)
        article = {
            "title": "Site Update",
            "content": "<p>News body</p>",
            "publish_time": "",
        }
        self.assertEqual(self.post("/admin/news/add", article).status_code, 302)
        self.assertEqual(self.post("/admin/news/add", article).status_code, 400)
        conn = get_db()
        row = conn.execute("SELECT publish_time FROM news WHERE title='Site Update'").fetchone()
        self.assertTrue(row["publish_time"])
        conn.close()

    def test_event_and_match_use_readable_canonical_urls(self):
        event_values = {
            "name": "80CS Summer Major",
            "short_name": "80CS_SUMMER_MAJOR",
            "slug": "80cs-summer-major",
            "start_date": "2026-05-01T10:00",
            "end_date": "2026-05-03T22:00",
        }
        self.assertEqual(self.post("/admin/events/add", event_values).status_code, 302)
        conn = get_db()
        event = conn.execute(
            "SELECT id, slug FROM events WHERE name='80CS Summer Major'"
        ).fetchone()
        conn.execute("INSERT INTO teams(name, short_name) VALUES('Team One','TEAM1')")
        team1_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO teams(name, short_name) VALUES('Team Two','TEAM2')")
        team2_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()

        self.assertEqual(self.client.get(f"/events/{event['slug']}").status_code, 200)
        legacy = self.client.get(f"/events/{event['id']}")
        self.assertEqual(legacy.status_code, 301)
        self.assertTrue(legacy.headers["Location"].endswith("/events/80cs-summer-major"))

        match_values = {
            "event_id": str(event["id"]),
            "match_time": "2026-05-02T20:00",
            "bo_format": "BO3",
            "side1_type": "team",
            "side1_id": str(team1_id),
            "side2_type": "team",
            "side2_id": str(team2_id),
        }
        self.assertEqual(self.post("/admin/matches/add", match_values).status_code, 302)
        conn = get_db()
        match_slug = conn.execute("SELECT slug FROM matches").fetchone()["slug"]
        conn.close()
        self.assertEqual(
            match_slug,
            "80cs-summer-major-team1-vs-team2-2026-5-2",
        )
        self.assertEqual(self.client.get(f"/matches/{match_slug}").status_code, 200)

        edited_event = dict(event_values, slug="80cs-summer-major-2026", status="upcoming")
        self.assertEqual(
            self.post(f"/admin/events/edit/{event['id']}", edited_event).status_code,
            302,
        )
        conn = get_db()
        new_match_slug = conn.execute("SELECT slug FROM matches").fetchone()["slug"]
        conn.close()
        self.assertTrue(new_match_slug.startswith("80cs-summer-major-2026-team1-vs-team2"))
        old_event = self.client.get("/events/80cs-summer-major")
        self.assertEqual(old_event.status_code, 301)
        self.assertTrue(old_event.headers["Location"].endswith("/events/80cs-summer-major-2026"))
        old_match = self.client.get(f"/matches/{match_slug}")
        self.assertEqual(old_match.status_code, 301)
        self.assertTrue(old_match.headers["Location"].endswith(f"/matches/{new_match_slug}"))

    def test_news_can_redirect_to_an_internal_page(self):
        response = self.post(
            "/admin/news/add",
            {
                "title": "Event notice",
                "content": "<p>Open the event page</p>",
                "redirect_url": "https://80gotv.cn/events/80cs-summer-major",
            },
        )
        self.assertEqual(response.status_code, 302)
        conn = get_db()
        news = conn.execute(
            "SELECT id, redirect_url FROM news WHERE title='Event notice'"
        ).fetchone()
        conn.close()
        self.assertEqual(news["redirect_url"], "/events/80cs-summer-major")
        redirect_response = self.client.get(f"/news/{news['id']}")
        self.assertEqual(redirect_response.status_code, 302)
        self.assertEqual(redirect_response.headers["Location"], "/events/80cs-summer-major")
        self.assertIn(
            'href="/events/80cs-summer-major"',
            self.client.get("/news").get_data(as_text=True),
        )

    def test_missing_edit_targets_return_404(self):
        for path in (
            "/admin/teams/edit/99999",
            "/admin/players/edit/99999",
            "/admin/events/edit/99999",
            "/admin/news/edit/99999",
            "/admin/matches/edit/99999",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_match_form_rejects_missing_team_duplicate_players_and_duplicate_match(self):
        conn = get_db()
        conn.execute(
            "INSERT INTO events(name, short_name, start_date, end_date) VALUES(?,?,?,?)",
            ("League", "L", "2026-07-01", "2026-07-30"),
        )
        event_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for index in range(1, 11):
            conn.execute("INSERT INTO players(nickname) VALUES(?)", (f"P{index}",))
        conn.commit()
        conn.close()
        base = {
            "event_id": str(event_id),
            "match_time": "2026-07-20T20:00",
            "bo_format": "BO3",
            "side1_type": "team",
            "side2_type": "players",
            **{f"side2_p{i}": str(i + 6) for i in range(5)},
        }
        self.assertEqual(self.post("/admin/matches/add", base).status_code, 400)
        duplicate_players = dict(base, side1_type="players")
        duplicate_players.update({f"side1_p{i}": "1" for i in range(5)})
        self.assertEqual(self.post("/admin/matches/add", duplicate_players).status_code, 400)
        valid = dict(base, side1_type="players")
        valid.update({f"side1_p{i}": str(i + 1) for i in range(5)})
        self.assertEqual(self.post("/admin/matches/add", valid).status_code, 302)
        self.assertEqual(self.post("/admin/matches/add", valid).status_code, 400)

    def test_test_mode_match_can_be_created_without_teams_or_players(self):
        conn = get_db()
        event_id = conn.execute(
            """INSERT INTO events(name, short_name, start_date, end_date)
               VALUES('Test Event','TEST','2026-07-20','2026-07-21')"""
        ).lastrowid
        conn.commit()
        conn.close()

        form_html = self.client.get("/admin/matches/add").get_data(as_text=True)
        self.assertIn('name="is_test_mode"', form_html)
        response = self.post(
            "/admin/matches/add",
            {
                "event_id": str(event_id),
                "match_time": "2026-07-20T21:00",
                "bo_format": "BO3",
                "is_test_mode": "1",
            },
        )
        self.assertEqual(response.status_code, 302)

        conn = get_db()
        match = conn.execute(
            """SELECT id, team1_id, team2_id, team1_players, team2_players,
                      is_test_mode
               FROM matches WHERE event_id=?""",
            (event_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(match["is_test_mode"], 1)
        self.assertIsNone(match["team1_id"])
        self.assertIsNone(match["team2_id"])
        self.assertIsNone(match["team1_players"])
        self.assertIsNone(match["team2_players"])

        list_html = self.client.get("/admin/matches").get_data(as_text=True)
        edit_html = self.client.get(f"/admin/matches/edit/{match['id']}").get_data(as_text=True)
        self.assertIn('<span class="test-badge">测试</span>', list_html)
        self.assertIn("这是一场测试比赛", edit_html)

    def test_test_mode_match_can_use_single_player_sides(self):
        conn = get_db()
        event_id = conn.execute(
            """INSERT INTO events(name, short_name, start_date, end_date)
               VALUES('Director Test','DIRECTOR','2026-08-02','2026-08-03')"""
        ).lastrowid
        flamecloud_id = conn.execute("INSERT INTO players(nickname) VALUES('FlameCloud')").lastrowid
        lan1193_id = conn.execute("INSERT INTO players(nickname) VALUES('lan1193')").lastrowid
        conn.commit()
        conn.close()

        response = self.post(
            "/admin/matches/add",
            {
                "event_id": str(event_id),
                "match_time": "2026-08-02T22:43",
                "bo_format": "BO1",
                "map1": "de_mirage",
                "is_test_mode": "1",
                "side1_type": "players",
                "side1_p0": str(flamecloud_id),
                "side2_type": "players",
                "side2_p0": str(lan1193_id),
            },
        )
        self.assertEqual(response.status_code, 302)

        conn = get_db()
        match = conn.execute(
            """SELECT team1_players, team2_players, is_test_mode
               FROM matches WHERE event_id=?""",
            (event_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(match["is_test_mode"], 1)
        self.assertEqual(json.loads(match["team1_players"]), [str(flamecloud_id)])
        self.assertEqual(json.loads(match["team2_players"]), [str(lan1193_id)])

    def test_match_delete_cleans_related_rows(self):
        conn = get_db()
        conn.execute("INSERT INTO teams(name, short_name) VALUES('A','A')")
        team1_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO teams(name, short_name) VALUES('B','B')")
        team2_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO events(name, short_name) VALUES('Event','E')")
        event_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO players(nickname, team_id) VALUES('P',?)", (team1_id,))
        player_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO matches(event_id, team1_id, team2_id, match_time) VALUES(?,?,?,?)",
            (event_id, team1_id, team2_id, "2026-07-20T20:00"),
        )
        match_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO match_stats(match_id, player_id, team_id) VALUES(?,?,?)",
            (match_id, player_id, team1_id),
        )
        conn.execute(
            "INSERT INTO player_medals(player_id, type, match_id) VALUES(?,?,?)",
            (player_id, "MVP", match_id),
        )
        conn.execute(
            "INSERT INTO live_match_data(match_id, live_state) VALUES(?, '{}')", (match_id,)
        )
        conn.execute(
            "INSERT INTO live_match_events(match_id,event_key,event_type,payload) VALUES(?,?,?,?)",
            (match_id, "1", "round", "{}"),
        )
        conn.execute("INSERT INTO news(title, related_match_id) VALUES('Related',?)", (match_id,))
        conn.execute(
            "INSERT INTO live_ingest_status(source,status,match_id) VALUES('gsi','ok',?)",
            (match_id,),
        )
        conn.commit()
        conn.close()

        self.assertEqual(self.post(f"/admin/matches/delete/{match_id}").status_code, 302)
        conn = get_db()
        for table in (
            "matches",
            "match_stats",
            "player_medals",
            "live_match_data",
            "live_match_events",
        ):
            with self.subTest(table=table):
                self.assertEqual(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
        self.assertIsNone(conn.execute("SELECT related_match_id FROM news").fetchone()[0])
        self.assertIsNone(conn.execute("SELECT match_id FROM live_ingest_status").fetchone()[0])
        conn.close()


if __name__ == "__main__":
    unittest.main()
