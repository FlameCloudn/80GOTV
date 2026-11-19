import os
import tempfile
import unittest
from unittest.mock import patch

from app import app
from config import Config
from models import get_db, init_tables
from utils.helpers import normalize_internal_path


class NewsArticleLinksTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory(prefix="news-article-link-")
        self.addCleanup(self.workspace.cleanup)
        self.database_patch = patch.object(
            Config, "DATABASE", os.path.join(self.workspace.name, "test.db")
        )
        self.database_patch.start()
        self.addCleanup(self.database_patch.stop)
        original = app.config.copy()
        self.addCleanup(app.config.update, original)
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False, TRUSTED_HOSTS=None)
        init_tables()
        self.conn = get_db()
        self.addCleanup(self.conn.close)
        self.admin_id = self.conn.execute(
            "INSERT INTO admins(username,password_hash) VALUES('article-admin','x')"
        ).lastrowid
        self.user_id = self.conn.execute(
            "INSERT INTO users(username,password_hash,group_username,approval_status,steam_id64,is_bashizhong_student) VALUES('article-user','x','Article User','approved','76561198000000331',1)"
        ).lastrowid
        self.conn.commit()
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session.update(
                admin_id=self.admin_id,
                admin_username="article-admin",
                csrf_token="article-test-token",
                user_id=self.user_id,
            )

    def save(self, **values):
        news_id = values.pop("news_id", None)
        data = {
            "csrf_token": "article-test-token",
            "title": "Article Notice",
            "content": "<p>Keep article body</p>",
            "internal_link_url": "/events?view=list#archive",
            "internal_link_text": "Open schedule",
            **values,
        }
        return self.client.post(
            f"/admin/news/edit/{news_id}" if news_id else "/admin/news/add", data=data
        )

    def test_create_retains_article_comments_and_clickable_link(self):
        self.assertEqual(
            self.save(internal_link_url="https://80gotv.cn/events?view=list#archive").status_code,
            302,
        )
        news = self.conn.execute("SELECT * FROM news").fetchone()
        self.assertEqual(news["internal_link_url"], "/events?view=list#archive")
        self.assertIsNone(news["redirect_url"])
        response = self.client.get(f"/news/{news['id']}")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Keep article body", html)
        self.assertIn('href="/events?view=list#archive"', html)
        self.assertIn("Open schedule", html)
        comment = self.client.post(
            f"/comment/news/{news['id']}",
            data={"csrf_token": "article-test-token", "content": "Article comment stays here"},
        )
        self.assertEqual(comment.status_code, 302)
        self.assertIn(
            "Article comment stays here",
            self.client.get(f"/news/{news['id']}").get_data(as_text=True),
        )
        self.assertIn(f'href="/news/{news["id"]}"', self.client.get("/news").get_data(as_text=True))

    def test_edit_clears_automatic_redirect_when_article_link_is_set(self):
        news_id = self.conn.execute(
            "INSERT INTO news(title,content,redirect_url) VALUES('Old','<p>Old body</p>','/events')"
        ).lastrowid
        self.conn.commit()
        self.assertEqual(self.save(news_id=news_id, redirect_url="/events").status_code, 302)
        news = self.conn.execute("SELECT * FROM news WHERE id=?", (news_id,)).fetchone()
        self.assertIsNone(news["redirect_url"])
        self.assertEqual(self.client.get(f"/news/{news_id}").status_code, 200)

    def test_link_can_be_cleared_and_no_empty_button_remains(self):
        self.save()
        news_id = self.conn.execute("SELECT id FROM news").fetchone()[0]
        self.assertEqual(
            self.save(news_id=news_id, internal_link_url="", internal_link_text="").status_code, 302
        )
        self.assertIsNone(self.conn.execute("SELECT internal_link_url FROM news").fetchone()[0])
        self.assertNotIn(
            "news-article-actions", self.client.get(f"/news/{news_id}").get_data(as_text=True)
        )

    def test_invalid_external_and_script_links_are_rejected(self):
        for url in (
            "https://other.example/path",
            "//other.example",
            "/\\other.example",
            "javascript:alert(1)",
            "https://80gotv.cn@other.example/path",
            "https://other.example@80gotv.cn/",
            "/%2fother.example",
            "/events\nX-Test:yes",
            "http://[broken",
        ):
            with self.subTest(url=url):
                response = self.save(internal_link_url=url)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM news").fetchone()[0], 0)

    def test_valid_nonstandard_path_and_query_are_preserved(self):
        self.assertEqual(
            normalize_internal_path("https://80gotv.cn/path+with=value?one=a%2Bb#section"),
            "/path+with=value?one=a%2Bb#section",
        )

    def test_missing_csrf_or_administrator_does_not_save(self):
        guest = app.test_client()
        self.assertIn(
            guest.post("/admin/news/add", data={"title": "No permission"}).status_code,
            (302, 400, 403),
        )
        self.assertIn(
            self.client.post("/admin/news/add", data={"title": "No token"}).status_code,
            (302, 400, 403),
        )
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM news").fetchone()[0], 0)

    def test_current_schema_upgrade_adds_optional_link_columns(self):
        self.conn.execute("ALTER TABLE news DROP COLUMN internal_link_url")
        self.conn.execute("ALTER TABLE news DROP COLUMN internal_link_text")
        self.conn.commit()
        init_tables()
        cols = {row[1] for row in self.conn.execute("PRAGMA table_info(news)")}
        self.assertTrue({"internal_link_url", "internal_link_text"}.issubset(cols))
