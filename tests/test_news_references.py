import os
import tempfile
import unittest
from unittest.mock import patch

from app import app
from config import Config
from models import get_db, init_tables


class NewsReferenceTests(unittest.TestCase):
    def setUp(self):
        handle, self.database_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.database_patch = patch.object(Config, "DATABASE", self.database_path)
        self.database_patch.start()
        self.original_testing = app.config.get("TESTING")
        self.original_secure_cookie = app.config.get("SESSION_COOKIE_SECURE")
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        with patch.object(Config, "DEFAULT_ADMIN_PASSWORD", ""):
            init_tables()
        conn = get_db()
        self.admin_id = conn.execute(
            "INSERT INTO admins(username, password_hash) VALUES('reference-admin', 'x')"
        ).lastrowid
        self.team1_id = conn.execute(
            "INSERT INTO teams(name) VALUES(?)", ('Alpha <One> & "Two"',)
        ).lastrowid
        self.team2_id = conn.execute("INSERT INTO teams(name) VALUES('Bravo')").lastrowid
        self.event_id = conn.execute(
            "INSERT INTO events(name, slug) VALUES('Reference Cup', 'reference-cup')"
        ).lastrowid
        self.player_id = conn.execute(
            "INSERT INTO players(nickname, real_name) VALUES('Player One', 'PRIVATE NAME')"
        ).lastrowid
        self.match_id = conn.execute(
            """INSERT INTO matches(event_id, team1_id, team2_id, slug, status)
               VALUES(?, ?, ?, 'reference-match', 'completed')""",
            (self.event_id, self.team1_id, self.team2_id),
        ).lastrowid
        conn.execute(
            "INSERT INTO match_slug_aliases(slug, match_id) VALUES('old-reference-match', ?)",
            (self.match_id,),
        )
        conn.execute(
            "INSERT INTO event_slug_aliases(slug, event_id) VALUES('old-reference-cup', ?)",
            (self.event_id,),
        )
        self.news_id = conn.execute(
            "INSERT INTO news(title, content) VALUES('Reference News', '<p>Original</p>')"
        ).lastrowid
        user_id = conn.execute(
            """INSERT INTO users(username, password_hash, approval_status, group_username)
               VALUES('reference-user', 'x', 'approved', 'Reference User')"""
        ).lastrowid
        category_id = conn.execute(
            "SELECT id FROM forum_categories ORDER BY id LIMIT 1"
        ).fetchone()[0]
        self.thread_id = conn.execute(
            """INSERT INTO forum_threads(category_id, user_id, title, content)
               VALUES(?, ?, 'Reference Thread', 'Thread body')""",
            (category_id, user_id),
        ).lastrowid
        conn.commit()
        conn.close()
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session["admin_id"] = self.admin_id
            session["admin_username"] = "reference-admin"
            session["csrf_token"] = "reference-test-token"

    def tearDown(self):
        app.config.update(
            TESTING=self.original_testing,
            SESSION_COOKIE_SECURE=self.original_secure_cookie,
        )
        self.database_patch.stop()
        try:
            os.remove(self.database_path)
        except OSError:
            pass

    def preview(self, url, client=None):
        return (client or self.client).post(
            "/admin/news/reference",
            json={"url": url},
            headers={
                "X-CSRF-Token": "reference-test-token",
                "X-Requested-With": "XMLHttpRequest",
            },
        )

    def save(self, title, content, news_id=None):
        path = f"/admin/news/edit/{news_id}" if news_id else "/admin/news/add"
        return self.client.post(
            path,
            data={
                "csrf_token": "reference-test-token",
                "title": title,
                "content": content,
                "summary": "Keep this summary",
                "author": "Reference Author",
                "publish_time": "2026-10-26T12:00",
            },
        )

    @staticmethod
    def block(url, title="Forged title", label="Forged type"):
        return (
            '<div class="news-reference"><a href="' + url + '">'
            '<span class="news-reference-type">' + label + "</span>"
            '<strong class="news-reference-title">' + title + "</strong>"
            "</a></div>"
        )

    def test_preview_reads_public_pages_without_visiting_them(self):
        cases = (
            ("/matches/reference-match", "match", "比赛", f"/matches/{self.match_id}"),
            ("/matches/old-reference-match", "match", "比赛", f"/matches/{self.match_id}"),
            (
                f"/matches/{self.match_id}/report",
                "report",
                "战报",
                f"/matches/{self.match_id}/report",
            ),
            (
                f"/matches/{self.match_id}/detailed",
                "match_stats",
                "比赛数据",
                f"/matches/{self.match_id}/detailed",
            ),
            ("/events/reference-cup", "event", "赛事", f"/events/{self.event_id}"),
            (
                "/events/old-reference-cup/stats",
                "event_stats",
                "赛事数据",
                f"/events/{self.event_id}/stats",
            ),
            (f"/players/{self.player_id}", "player", "选手", f"/players/{self.player_id}"),
            (f"/teams/{self.team1_id}", "team", "队伍", f"/teams/{self.team1_id}"),
            (f"/news/{self.news_id}", "news", "新闻", f"/news/{self.news_id}"),
            (f"/forum/t/{self.thread_id}", "forum_thread", "帖子", f"/forum/t/{self.thread_id}"),
            ("/", "page", "页面", "/"),
        )
        with patch(
            "socket.socket.connect", side_effect=AssertionError("引用识别不能发起网络请求")
        ) as network:
            for url, kind, label, canonical in cases:
                with self.subTest(url=url):
                    response = self.preview(url)
                    self.assertEqual(response.status_code, 200)
                    data = response.get_json()
                    self.assertTrue(data["ok"])
                    reference = data["reference"]
                    self.assertEqual(reference["type"], kind)
                    self.assertEqual(reference["label"], label)
                    self.assertEqual(reference["url"], canonical)
                    self.assertTrue(reference["title"])
                    self.assertNotIn("PRIVATE NAME", reference["title"])
            network.assert_not_called()
        conn = get_db()
        views = conn.execute(
            "SELECT view_count FROM forum_threads WHERE id=?", (self.thread_id,)
        ).fetchone()[0]
        conn.close()
        self.assertEqual(views or 0, 0)

    def test_full_urls_and_public_filters_become_relative_links(self):
        for host in ("https://80gotv.cn", "https://www.80gotv.cn", "http://localhost"):
            response = self.preview(host + f"/players/{self.player_id}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["reference"]["title"], "Player One")
            self.assertEqual(response.get_json()["reference"]["url"], f"/players/{self.player_id}")
        response = self.preview(
            f"/matches/{self.match_id}/detailed?map=de_nuke&tab=rounds&token=discard#map-2"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["reference"]["url"],
            f"/matches/{self.match_id}/detailed?map=de_nuke&tab=rounds#map-2",
        )

    def test_external_private_dangerous_and_missing_pages_are_rejected(self):
        urls = (
            "https://example.com/players/1",
            "https://80gotv.cn.example.com/players/1",
            "https://80gotv.cn@evil.example/players/1",
            "https://user@80gotv.cn/players/1",
            "https://80gotv.cn:8443/players/1",
            "//80gotv.cn/players/1",
            "javascript:alert(1)",
            "data:text/html,example",
            "/\\evil.example/players/1",
            "/%2f%2fevil.example/players/1",
            "/players/%252e%252e/admin",
            "/players/1\n",
            "/players/1&#10;",
            "/matches/\ud800",
            "/events/\u00b2",
            "/admin/news",
            "/api/front/news",
            "/profile",
            "/logout",
            "/forum/thread/new",
            "/static/css/app.css",
            "/players/9999999",
            "/players/99999999999999999999999999999999",
            "/events/99999999999999999999999999999999",
            "/matches/99999999999999999999999999999999",
            "/events/no-such-event",
            "/matches/no-such-match",
            "/stats/overview/no-such-section",
            "not a url",
            "",
        )
        with patch(
            "socket.socket.connect", side_effect=AssertionError("引用识别不能发起网络请求")
        ) as network:
            for url in urls:
                with self.subTest(url=url):
                    response = self.preview(url)
                    self.assertIn(response.status_code, (400, 404))
                    self.assertFalse(response.get_json()["ok"])
                    self.assertTrue(response.get_json()["msg"])
            network.assert_not_called()

    def test_preview_requires_admin_and_csrf_and_valid_json(self):
        guest = app.test_client()
        with guest.session_transaction() as session:
            session["csrf_token"] = "reference-test-token"
        self.assertEqual(self.preview("/news", guest).status_code, 401)
        response = self.client.post("/admin/news/reference", json={"url": "/news"})
        self.assertEqual(response.status_code, 403)
        for payload in ({"url": []}, {"url": None}, ["/news"], {}, {"url": "/" * 4097}):
            response = self.client.post(
                "/admin/news/reference",
                json=payload,
                headers={"X-CSRF-Token": "reference-test-token"},
            )
            self.assertEqual(response.status_code, 400)

    def test_save_rebuilds_reference_metadata_and_preserves_other_content(self):
        body = (
            '<p>Before <a href="/events">ordinary link</a></p>'
            + self.block(f"https://80gotv.cn/matches/{self.match_id}")
            + '<p>After</p><img src="/static/test-reference.png" alt="Example">'
        )
        response = self.save("Reference body", body)
        self.assertEqual(response.status_code, 302)
        conn = get_db()
        saved = conn.execute("SELECT * FROM news WHERE title='Reference body'").fetchone()
        conn.close()
        self.assertIsNotNone(saved)
        self.assertNotIn("Forged", saved["content"])
        self.assertIn('href="/matches/' + str(self.match_id) + '"', saved["content"])
        self.assertIn("Alpha &lt;One&gt; &amp; &quot;Two&quot; vs Bravo", saved["content"])
        self.assertIn('<span class="news-reference-type">比赛</span>', saved["content"])
        self.assertIn('<p>Before <a href="/events">ordinary link</a></p>', saved["content"])
        self.assertIn('<img src="/static/test-reference.png" alt="Example">', saved["content"])
        self.assertEqual(saved["summary"], "Keep this summary")
        public = self.client.get(f"/news/{saved['id']}")
        self.assertEqual(public.status_code, 200)
        self.assertIn('class="news-reference"', public.get_data(as_text=True))

    def test_edit_roundtrip_is_stable_and_follows_record_renaming(self):
        response = self.save("Roundtrip body", self.block(f"/events/{self.event_id}"))
        self.assertEqual(response.status_code, 302)
        conn = get_db()
        saved = dict(conn.execute("SELECT * FROM news WHERE title='Roundtrip body'").fetchone())
        conn.close()
        self.assertEqual(self.save(saved["title"], saved["content"], saved["id"]).status_code, 302)
        conn = get_db()
        repeated = conn.execute("SELECT content FROM news WHERE id=?", (saved["id"],)).fetchone()[0]
        self.assertEqual(repeated, saved["content"])
        conn.execute(
            "UPDATE events SET name='Renamed Cup', slug='renamed-cup' WHERE id=?", (self.event_id,)
        )
        conn.commit()
        conn.close()
        response = self.preview(f"/events/{self.event_id}")
        self.assertEqual(response.get_json()["reference"]["title"], "Renamed Cup")
        self.assertEqual(response.get_json()["reference"]["url"], f"/events/{self.event_id}")

    def test_invalid_reference_does_not_save_or_erase_form_values(self):
        response = self.save("Unsaved reference", "<p>Keep this body</p>" + self.block("/admin"))
        self.assertEqual(response.status_code, 400)
        html = response.get_data(as_text=True)
        self.assertIn("Unsaved reference", html)
        self.assertIn("Keep this body", html)
        self.assertIn("Keep this summary", html)
        conn = get_db()
        self.assertIsNone(
            conn.execute("SELECT id FROM news WHERE title='Unsaved reference'").fetchone()
        )
        conn.close()
        response = self.save(
            "Changed title", self.block("https://example.com/news/1"), self.news_id
        )
        self.assertEqual(response.status_code, 400)
        conn = get_db()
        original = conn.execute(
            "SELECT title, content FROM news WHERE id=?", (self.news_id,)
        ).fetchone()
        conn.close()
        self.assertEqual(tuple(original), ("Reference News", "<p>Original</p>"))

    def test_reference_roundtrip_preserves_filters_and_ordinary_text_exactly(self):
        ordinary = "<p>AT&T &unlistedToken text; <strong>bold</strong></p>"
        body = ordinary + self.block(
            f"/matches/{self.match_id}/detailed?map=de_nuke&amp;tab=rounds#map-2"
        )
        self.assertEqual(self.save("Exact reference body", body).status_code, 302)
        conn = get_db()
        saved = dict(
            conn.execute("SELECT * FROM news WHERE title='Exact reference body'").fetchone()
        )
        conn.close()
        self.assertTrue(saved["content"].startswith(ordinary))
        self.assertIn("?map=de_nuke&amp;tab=rounds#map-2", saved["content"])
        self.assertEqual(self.save(saved["title"], saved["content"], saved["id"]).status_code, 302)
        conn = get_db()
        repeated = conn.execute("SELECT content FROM news WHERE id=?", (saved["id"],)).fetchone()[0]
        conn.close()
        self.assertEqual(repeated, saved["content"])

    def test_malformed_blocks_are_rejected_instead_of_becoming_fake_references(self):
        cases = (
            '<div class="news-reference"><strong>No link</strong></div>',
            '<div class="news-reference"><a href="/news">One</a><a href="/events">Two</a></div>',
            '<div class="news-reference"><a href="/news">Unclosed</a>',
            '<div class="news-reference">' + self.block("/news") + "</div>",
            '<a class="news-reference" href="/news">Wrong wrapper</a>',
            '<div class="news-reference" class="ordinary"><a href="https://example.com">Hidden marker</a></div>',
            '<div class="ordinary" class="news-reference"><a href="/news">Duplicate marker</a></div>',
            '<div class="news-reference"><a href="https://example.com" href="/news">Two targets</a></div>',
        )
        for index, body in enumerate(cases):
            with self.subTest(body=body):
                self.assertEqual(self.save(f"Malformed {index}", body).status_code, 400)

    def test_news_redirects_cannot_smuggle_private_pages_or_loops(self):
        conn = get_db()
        private_id = conn.execute(
            "INSERT INTO news(title, content, redirect_url) VALUES('Private redirect', 'body', '/admin')"
        ).lastrowid
        loop_id = conn.execute(
            "INSERT INTO news(title, content) VALUES('Loop redirect', 'body')"
        ).lastrowid
        conn.execute("UPDATE news SET redirect_url=? WHERE id=?", (f"/news/{loop_id}", loop_id))
        public_id = conn.execute(
            "INSERT INTO news(title, content, redirect_url) VALUES('Public redirect', 'body', ?)",
            (f"/events/{self.event_id}",),
        ).lastrowid
        conn.commit()
        conn.close()
        for news_id in (private_id, loop_id):
            self.assertEqual(self.preview(f"/news/{news_id}").status_code, 400)
        response = self.preview(f"/news/{public_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["reference"]["url"], f"/events/{self.event_id}")

    def test_temporary_match_names_use_existing_public_rules(self):
        conn = get_db()
        temporary_id = conn.execute(
            "INSERT INTO matches(team1_players, team2_players) VALUES(?, ?)",
            (f"[{self.player_id}]", "[]"),
        ).lastrowid
        conn.commit()
        conn.close()
        response = self.preview(f"/matches/{temporary_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["reference"]["title"], "Player One vs TBD")


if __name__ == "__main__":
    unittest.main()
