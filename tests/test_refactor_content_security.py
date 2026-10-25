import os
import tempfile
import unittest
from unittest.mock import patch

from app import app
from config import Config
from models import get_db, init_tables


class RefactorContentSecurityTests(unittest.TestCase):
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
        self.user_id = conn.execute(
            """INSERT INTO users(username, password_hash, approval_status,
                                 is_bashizhong_student)
               VALUES(?, ?, 'approved', 0)""",
            ("ContentAuditUser", "unused-test-hash"),
        ).lastrowid
        category_id = conn.execute(
            "SELECT id FROM forum_categories ORDER BY id LIMIT 1"
        ).fetchone()["id"]
        self.thread_id = conn.execute(
            """INSERT INTO forum_threads(category_id, user_id, title, content)
               VALUES(?, ?, 'Pagination audit thread', 'Thread body')""",
            (category_id, self.user_id),
        ).lastrowid
        for index in range(22):
            conn.execute(
                """INSERT INTO comments(user_id, target_type, target_id, content)
                   VALUES(?, 'forum_thread', ?, ?)""",
                (self.user_id, self.thread_id, f"Reply {index + 1}"),
            )
        for index in range(21):
            conn.execute(
                "INSERT INTO news(title, content, summary, author, publish_time) VALUES(?,?,?,?,?)",
                (f"Pagination audit news {index + 1}", "Body", "Summary", "Audit", str(index)),
            )
        conn.commit()
        conn.close()
        with self.client.session_transaction() as saved:
            saved["user_id"] = self.user_id
            saved["user_username"] = "ContentAuditUser"
            saved["csrf_token"] = "content-audit-token"

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

    def test_negative_news_page_is_normalized_to_first_page(self):
        response = self.client.get("/news?page=-1")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            "第 1 / 2 页" in response.get_data(as_text=True), "新闻页码没有归一到第一页"
        )

    def test_negative_forum_reply_page_keeps_floor_numbers_valid(self):
        response = self.client.get(f"/forum/t/{self.thread_id}?page=-1")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertTrue("#2" in html, "论坛回复楼层没有从第二楼开始")
        self.assertTrue("#-19" not in html, "论坛回复出现了负数楼层")

    def test_extreme_page_numbers_are_clamped_to_existing_pages(self):
        huge_page = "999999999999999999999999999999"
        responses = (
            self.client.get(f"/news?page={huge_page}"),
            self.client.get(f"/forum?page={huge_page}"),
            self.client.get(f"/forum/t/{self.thread_id}?page={huge_page}"),
        )

        for response in responses:
            with self.subTest(status=response.status_code):
                self.assertEqual(response.status_code, 200)
        self.assertTrue("第 2 / 2 页" in responses[0].get_data(as_text=True))
        self.assertTrue("Pagination audit thread" in responses[1].get_data(as_text=True))
        self.assertTrue("#23" in responses[2].get_data(as_text=True))

    def test_feedback_stores_page_path_without_query_or_fragment(self):
        payload = {
            "type": "bug",
            "content": "页面反馈",
            "contact": "contact@example.com",
            "page_url": "https://80gotv.cn/news/1?token=temporary-secret#private-search",
        }
        with patch("routes.feedback.rate_limit", return_value=True):
            response = self.client.post(
                "/api/feedback/submit",
                json=payload,
                headers={"X-CSRF-Token": "content-audit-token"},
            )

        self.assertEqual(response.status_code, 200)
        conn = get_db()
        stored = conn.execute(
            "SELECT page_url FROM feedback WHERE user_id=?", (self.user_id,)
        ).fetchone()["page_url"]
        conn.close()
        self.assertEqual(stored, "/news/1")
        self.assertTrue("temporary-secret" not in stored and "private-search" not in stored)

    def test_feedback_rejects_oversized_contact_and_page_url(self):
        base = {"type": "bug", "content": "页面反馈", "contact": "", "page_url": ""}
        oversized = (
            {**base, "contact": "x" * 255},
            {**base, "page_url": "https://80gotv.cn/" + "x" * 2048},
        )
        with patch("routes.feedback.rate_limit", return_value=True):
            for payload in oversized:
                with self.subTest(field="contact" if payload["contact"] else "page_url"):
                    response = self.client.post(
                        "/api/feedback/submit",
                        json=payload,
                        headers={"X-CSRF-Token": "content-audit-token"},
                    )
                    self.assertEqual(response.status_code, 400)
        conn = get_db()
        count = conn.execute(
            "SELECT COUNT(*) FROM feedback WHERE user_id=?", (self.user_id,)
        ).fetchone()[0]
        conn.close()
        self.assertEqual(count, 0)

    def test_news_comment_count_recovers_from_null_cache_and_html_uses_real_count(self):
        conn = get_db()
        news_id = conn.execute(
            "SELECT id FROM news WHERE title=?", ("Pagination audit news 1",)
        ).fetchone()["id"]
        conn.execute("UPDATE news SET comment_count=NULL WHERE id=?", (news_id,))
        for index in range(2):
            conn.execute(
                """INSERT INTO comments(user_id, target_type, target_id, content)
                   VALUES(?, 'news', ?, ?)""",
                (self.user_id, news_id, f"历史评论 {index + 1}"),
            )
        conn.commit()
        conn.close()

        listing = self.client.get("/news?page=2").get_data(as_text=True)
        detail = self.client.get(f"/news/{news_id}").get_data(as_text=True)
        self.assertIn("评论 2", listing)
        self.assertIn("评论 2", detail)

        with patch("routes.comments.rate_limit", return_value=True):
            added = self.client.post(
                f"/comment/news/{news_id}",
                data={"csrf_token": "content-audit-token", "content": "新评论"},
            )
        self.assertEqual(added.status_code, 302)

        conn = get_db()
        comment_count = conn.execute(
            "SELECT comment_count FROM news WHERE id=?", (news_id,)
        ).fetchone()["comment_count"]
        added_id = conn.execute(
            "SELECT id FROM comments WHERE target_type='news' AND target_id=? AND content='新评论'",
            (news_id,),
        ).fetchone()["id"]
        conn.close()
        self.assertEqual(comment_count, 3)

        deleted = self.client.post(
            f"/comment/delete/{added_id}",
            data={"csrf_token": "content-audit-token"},
        )
        self.assertEqual(deleted.status_code, 302)
        conn = get_db()
        comment_count = conn.execute(
            "SELECT comment_count FROM news WHERE id=?", (news_id,)
        ).fetchone()["comment_count"]
        conn.close()
        self.assertEqual(comment_count, 2)


if __name__ == "__main__":
    unittest.main()
