import os
import tempfile
import unittest

from app import app
from config import Config
from models import get_db, init_tables


class RemovedTagFeatureTests(unittest.TestCase):
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
            """INSERT INTO news(title, content, summary, author, publish_time, tags)
               VALUES(?,?,?,?,?,?)""",
            ("Tagged news", "Body", "Summary", "admin", "2026-07-18T10:00", "legacy-tag"),
        )
        conn.execute(
            """INSERT INTO news(title, content, summary, author, publish_time, tags)
               VALUES(?,?,?,?,?,?)""",
            ("Plain news", "Body", "Summary", "admin", "2026-07-18T11:00", ""),
        )
        conn.execute(
            "INSERT OR IGNORE INTO forum_categories(name, slug, sort_order) VALUES(?,?,?)",
            ("General", "general", 0),
        )
        conn.execute(
            "INSERT INTO users(username, password_hash, group_username) VALUES(?,?,?)",
            ("tag-test-user", "unused", "Tag Test User"),
        )
        self.user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        category_id = conn.execute(
            "SELECT id FROM forum_categories ORDER BY sort_order, id LIMIT 1"
        ).fetchone()["id"]
        conn.execute(
            """INSERT INTO forum_threads(category_id, user_id, title, content, tags, last_reply_at)
               VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)""",
            (category_id, self.user_id, "Tagged thread", "Thread body", "legacy-tag"),
        )
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

    def test_legacy_tags_are_not_shown_or_used_as_filters(self):
        news_html = self.client.get("/news?tag=does-not-match").get_data(as_text=True)
        self.assertIn("Tagged news", news_html)
        self.assertIn("Plain news", news_html)
        self.assertNotIn("legacy-tag", news_html)
        self.assertNotIn("热门标签", news_html)

        forum_html = self.client.get("/forum?tag=does-not-match").get_data(as_text=True)
        self.assertIn("Tagged thread", forum_html)
        self.assertNotIn("legacy-tag", forum_html)
        self.assertNotIn("多标签模式", forum_html)

    def test_front_apis_do_not_expose_or_filter_tags(self):
        news = self.client.get("/api/front/news?tag=does-not-match").get_json()
        self.assertEqual(news["total"], 2)
        self.assertNotIn("tags", news)
        self.assertTrue(all("tags" not in item for item in news["news"]))

        forum = self.client.get("/api/front/forum?tag=does-not-match").get_json()
        self.assertEqual(forum["total"], 1)
        self.assertTrue(all("tags" not in item for item in forum["threads"]))
        self.assertEqual(self.client.get("/api/forum/tags").status_code, 404)

    def test_editors_do_not_accept_or_store_tags(self):
        with self.client.session_transaction() as browser_session:
            browser_session["admin_id"] = 1
            browser_session["admin_username"] = "admin"
            browser_session["csrf_token"] = "removed-tag-test"

        form_html = self.client.get("/admin/news/add").get_data(as_text=True)
        self.assertNotIn('name="tags"', form_html)
        response = self.client.post(
            "/admin/news/add",
            data={
                "csrf_token": "removed-tag-test",
                "title": "New no-tag news",
                "content": "<p>Body</p>",
                "tags": "ignored-tag",
            },
        )
        self.assertEqual(response.status_code, 302)

        with self.client.session_transaction() as browser_session:
            browser_session.pop("admin_id", None)
            browser_session.pop("admin_username", None)
            browser_session["user_id"] = self.user_id
            browser_session["user_username"] = "tag-test-user"
            browser_session["csrf_token"] = "removed-tag-test"

        forum_form = self.client.get("/forum/thread/new").get_data(as_text=True)
        self.assertNotIn('name="tags"', forum_form)
        response = self.client.post(
            "/forum/thread/new",
            data={
                "csrf_token": "removed-tag-test",
                "title": "New no-tag thread",
                "content": "Body",
                "tags": "ignored-tag",
            },
        )
        self.assertEqual(response.status_code, 302)

        conn = get_db()
        news_tags = conn.execute("SELECT tags FROM news WHERE title='New no-tag news'").fetchone()[
            "tags"
        ]
        thread_tags = conn.execute(
            "SELECT tags FROM forum_threads WHERE title='New no-tag thread'"
        ).fetchone()["tags"]
        conn.close()
        self.assertEqual(news_tags, "")
        self.assertEqual(thread_tags, "")


if __name__ == "__main__":
    unittest.main()
