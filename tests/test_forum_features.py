import os
import tempfile
import unittest

from app import app
from config import Config
from models import get_db, init_tables


class ForumFeatureTests(unittest.TestCase):
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
                   username, password_hash, group_username, is_bashizhong_student
               ) VALUES(?,?,?,1)""",
            ("owner", "unused", "Owner In Group"),
        )
        self.owner_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO users(
                   username, password_hash, group_username, is_bashizhong_student
               ) VALUES(?,?,?,1)""",
            ("replier", "unused", "Reply In Group"),
        )
        self.replier_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.general_id = conn.execute(
            "SELECT id FROM forum_categories WHERE slug='cs2-general'"
        ).fetchone()["id"]
        self.tournament_id = conn.execute(
            "SELECT id FROM forum_categories WHERE slug='tournaments'"
        ).fetchone()["id"]

        conn.execute(
            """INSERT INTO forum_threads(
                   category_id, user_id, title, content, view_count, reply_count, last_reply_at
               ) VALUES(?,?,?,?,?,?,?)""",
            (
                self.general_id,
                self.owner_id,
                "General thread",
                "General body",
                5,
                0,
                "2026-07-18T09:00:00",
            ),
        )
        self.general_thread_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO forum_threads(
                   category_id, user_id, title, content, view_count, reply_count,
                   last_reply_at, last_reply_user_id
               ) VALUES(?,?,?,?,?,?,?,?)""",
            (
                self.tournament_id,
                self.owner_id,
                "Tournament thread",
                "Tournament body",
                100,
                2,
                "2026-07-18T10:00:00",
                self.replier_id,
            ),
        )
        self.tournament_thread_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO comments(user_id, target_type, target_id, content, created_at)
               VALUES(?, 'forum_thread', ?, ?, ?)""",
            (self.owner_id, self.tournament_thread_id, "First reply", "2026-07-18T09:30:00"),
        )
        self.first_reply_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO comments(user_id, target_type, target_id, content, created_at)
               VALUES(?, 'forum_thread', ?, ?, ?)""",
            (self.replier_id, self.tournament_thread_id, "Second reply", "2026-07-18T10:00:00"),
        )
        self.second_reply_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
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

    def login_user(self, user_id=None, username="owner"):
        with self.client.session_transaction() as browser_session:
            browser_session.clear()
            browser_session["user_id"] = user_id or self.owner_id
            browser_session["user_username"] = username
            browser_session["csrf_token"] = "forum-feature-test"

    def login_admin(self):
        with self.client.session_transaction() as browser_session:
            browser_session.clear()
            browser_session["admin_id"] = 1
            browser_session["admin_username"] = "admin"
            browser_session["csrf_token"] = "forum-feature-test"

    def post(self, path, data=None, **kwargs):
        payload = {"csrf_token": "forum-feature-test"}
        payload.update(data or {})
        return self.client.post(path, data=payload, **kwargs)

    def test_categories_sorting_and_my_threads_are_available(self):
        page = self.client.get("/forum").get_data(as_text=True)
        self.assertIn("全部版块", page)
        self.assertIn("赛事讨论", page)
        self.assertIn("最新回复", page)
        self.assertIn("热门讨论", page)
        self.assertIn("owner", page)
        self.assertIn("@Owner In Group", page)

        category_page = self.client.get("/forum?category=tournaments").get_data(as_text=True)
        self.assertIn("Tournament thread", category_page)
        self.assertNotIn("General thread", category_page)

        popular_page = self.client.get("/forum?sort=popular").get_data(as_text=True)
        self.assertLess(
            popular_page.index("Tournament thread"), popular_page.index("General thread")
        )

        self.login_user(self.replier_id, "replier")
        mine_page = self.client.get("/forum?mine=1").get_data(as_text=True)
        self.assertIn("你还没有发表帖子", mine_page)

    def test_new_thread_uses_selected_category(self):
        self.login_user()
        form = self.client.get("/forum/thread/new").get_data(as_text=True)
        self.assertIn('name="category_id"', form)
        self.assertIn("游戏更新", form)

        response = self.post(
            "/forum/thread/new",
            {
                "category_id": str(self.tournament_id),
                "title": "Selected category thread",
                "content": "Body",
            },
        )
        self.assertEqual(response.status_code, 302)
        conn = get_db()
        category_id = conn.execute(
            "SELECT category_id FROM forum_threads WHERE title='Selected category thread'"
        ).fetchone()["category_id"]
        conn.close()
        self.assertEqual(category_id, self.tournament_id)

    def test_owner_can_edit_and_delete_only_an_empty_thread(self):
        self.login_user()
        response = self.post(
            f"/forum/t/{self.general_thread_id}/edit",
            {
                "category_id": str(self.tournament_id),
                "title": "Edited thread",
                "content": "Edited body",
            },
        )
        self.assertEqual(response.status_code, 302)
        conn = get_db()
        edited = conn.execute(
            "SELECT title, content, category_id FROM forum_threads WHERE id=?",
            (self.general_thread_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(edited["title"], "Edited thread")
        self.assertEqual(edited["content"], "Edited body")
        self.assertEqual(edited["category_id"], self.tournament_id)

        blocked = self.post(f"/forum/t/{self.tournament_thread_id}/manage", {"action": "delete"})
        self.assertEqual(blocked.status_code, 403)
        deleted = self.post(f"/forum/t/{self.general_thread_id}/manage", {"action": "delete"})
        self.assertEqual(deleted.status_code, 302)
        conn = get_db()
        self.assertIsNone(
            conn.execute(
                "SELECT id FROM forum_threads WHERE id=?", (self.general_thread_id,)
            ).fetchone()
        )
        conn.close()

    def test_admin_can_pin_lock_unlock_and_delete(self):
        self.login_admin()
        for action, column, expected in (
            ("pin", "is_pinned", 1),
            ("lock", "is_locked", 1),
            ("unlock", "is_locked", 0),
        ):
            with self.subTest(action=action):
                response = self.post(
                    f"/forum/t/{self.tournament_thread_id}/manage", {"action": action}
                )
                self.assertEqual(response.status_code, 302)
                conn = get_db()
                value = conn.execute(
                    f"SELECT {column} FROM forum_threads WHERE id=?",
                    (self.tournament_thread_id,),
                ).fetchone()[column]
                conn.close()
                self.assertEqual(value, expected)

        deleted = self.post(f"/forum/t/{self.tournament_thread_id}/manage", {"action": "delete"})
        self.assertEqual(deleted.status_code, 302)
        conn = get_db()
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM comments WHERE target_type='forum_thread' AND target_id=?",
                (self.tournament_thread_id,),
            ).fetchone()[0],
            0,
        )
        conn.close()

    def test_quote_controls_and_reply_count_repair(self):
        self.login_user()
        page = self.client.get(f"/forum/t/{self.tournament_thread_id}").get_data(as_text=True)
        self.assertIn("forum-quote-btn", page)
        self.assertIn('id="forumReplyContent"', page)
        self.assertIn("Reply In Group", page)
        self.assertNotIn("登录</a> 后即可回复", page)

        response = self.post(
            f"/comment/delete/{self.second_reply_id}",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(response.status_code, 403)

        self.login_user(self.replier_id, "replier")
        response = self.post(
            f"/comment/delete/{self.second_reply_id}",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(response.status_code, 200)
        conn = get_db()
        thread = conn.execute(
            "SELECT reply_count, last_reply_user_id FROM forum_threads WHERE id=?",
            (self.tournament_thread_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(thread["reply_count"], 1)
        self.assertEqual(thread["last_reply_user_id"], self.owner_id)


if __name__ == "__main__":
    unittest.main()
