import io
import sqlite3
import struct
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import closing
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app import app
from config import Config
from models import init_tables
from utils.db_helpers import validate_image_content


class PageInfo(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.meta = {}
        self.canonical = []
        self.headings = 0
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            name = attrs.get("name") or attrs.get("property")
            if name:
                self.meta.setdefault(name, []).append(attrs.get("content", ""))
        if tag == "link" and attrs.get("rel") == "canonical":
            self.canonical.append(attrs.get("href"))
        if tag == "h1":
            self.headings += 1


def png_bytes(corrupt=False):
    output = io.BytesIO()
    Image.new("RGB", (5, 5), (30, 80, 140)).save(output, format="PNG")
    data = bytearray(output.getvalue())
    if corrupt:
        position = 8
        while position < len(data):
            size = struct.unpack_from(">I", data, position)[0]
            if data[position + 4 : position + 8] == b"IDAT":
                data[position + 8 + size // 2] ^= 1
                break
            position += size + 12
    return bytes(data)


class ConfirmedReportFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory(prefix="80gotv-confirmed-report-")
        cls.addClassCleanup(cls.workspace.cleanup)
        cls.original_database = Config.DATABASE
        cls.original_config = app.config.copy()
        cls.addClassCleanup(setattr, Config, "DATABASE", cls.original_database)
        cls.addClassCleanup(app.config.update, cls.original_config)
        cls.baseline = Path(cls.workspace.name) / "baseline.db"
        Config.DATABASE = str(cls.baseline)
        app.config.update(
            TESTING=True,
            SESSION_COOKIE_SECURE=False,
            TRUSTED_HOSTS=None,
            PUBLIC_BASE_URL="auto",
            PROPAGATE_EXCEPTIONS=False,
        )
        init_tables()
        with closing(sqlite3.connect(cls.baseline)) as conn, conn:
            conn.execute(
                "INSERT OR IGNORE INTO admins(id,username,password_hash) VALUES(1,'report-admin','test-only')"
            )
            for name in ("report-user", "report-other"):
                conn.execute(
                    "INSERT INTO users(username,password_hash,group_username,is_bashizhong_student,approval_status) VALUES(?,'test-only',?,1,'approved')",
                    (name, name),
                )
            cls.user_id = conn.execute(
                "SELECT id FROM users WHERE username='report-user'"
            ).fetchone()[0]
            cls.other_id = conn.execute(
                "SELECT id FROM users WHERE username='report-other'"
            ).fetchone()[0]
            for name, short in (("Report Alpha", "RA"), ("Report Beta", "RB")):
                conn.execute(
                    "INSERT INTO teams(name,short_name,created_at) VALUES(?,?,'2026-05-01 10:00:00')",
                    (name, short),
                )
            cls.team_id = conn.execute("SELECT id FROM teams WHERE name='Report Alpha'").fetchone()[
                0
            ]
            team2 = conn.execute("SELECT id FROM teams WHERE name='Report Beta'").fetchone()[0]
            cls.event_id = conn.execute(
                "INSERT INTO events(name,short_name,slug,status,start_date,end_date,description,created_at) VALUES('Report Cup','RC','report-cup','completed','2026-05-01','2026-05-02','Report event information','2026-05-01 10:00:00')"
            ).lastrowid
            cls.match_id = conn.execute(
                "INSERT INTO matches(event_id,team1_id,team2_id,team1_score,team2_score,match_time,bo_format,status,map1,map1_t1,map1_t2,slug,created_at) VALUES(?,?,?,1,0,'2026-05-02T20:00','BO1','completed','de_dust2',13,10,'report-alpha-beta','2026-05-01 11:00:00')",
                (cls.event_id, cls.team_id, team2),
            ).lastrowid
            cls.player_id = conn.execute(
                "INSERT INTO players(nickname,real_name,team_id,created_at) VALUES('Report Player','Private real name',?,'2026-05-01 10:00:00')",
                (cls.team_id,),
            ).lastrowid
            cls.news_id = conn.execute(
                "INSERT INTO news(title,content,summary,publish_time,created_at) VALUES(?,?,?,?,?)",
                (
                    "Report Article & review",
                    '<p>A "quoted" match report &amp; follow-up</p>',
                    'Report summary & "details"',
                    "2026-05-04T10:30",
                    "2026-05-03 10:00:00",
                ),
            ).lastrowid
            cls.own_notice = conn.execute(
                "INSERT INTO notifications(user_id,type,message,link) VALUES(?,'system','Own notice','/news')",
                (cls.user_id,),
            ).lastrowid
            cls.other_notice = conn.execute(
                "INSERT INTO notifications(user_id,type,message,link) VALUES(?,'system','Other notice','/news')",
                (cls.other_id,),
            ).lastrowid

    def setUp(self):
        self.database = Path(self.workspace.name) / (self._testMethodName + ".db")
        with (
            closing(sqlite3.connect(self.baseline)) as source,
            closing(sqlite3.connect(self.database)) as target,
        ):
            source.backup(target)
        Config.DATABASE = str(self.database)
        app.config["PUBLIC_BASE_URL"] = "auto"
        self.client = app.test_client()

    def login(self, *, admin=False):
        with self.client.session_transaction() as session:
            session.clear()
            session["csrf_token"] = "report-test"
            if admin:
                session["admin_id"] = 1
                session["admin_username"] = "report-admin"
            else:
                session["user_id"] = self.user_id
                session["user_username"] = "report-user"

    def row(self, sql, values=()):
        with closing(sqlite3.connect(self.database)) as conn:
            return conn.execute(sql, values).fetchone()

    def test_corrupt_png_is_rejected_and_stream_is_rewound(self):
        data = png_bytes(corrupt=True)
        with Image.open(io.BytesIO(data)) as image, self.assertRaises(SyntaxError):
            image.verify()
        stream = io.BytesIO(data)
        self.assertIsNone(validate_image_content(stream))
        self.assertEqual(stream.tell(), 0)
        self.assertEqual(validate_image_content(io.BytesIO(png_bytes())), "png")

    def test_corrupt_png_upload_returns_400_without_saving_a_file(self):
        self.login(admin=True)
        uploads = Path(self.workspace.name) / "image-root"
        with (
            patch("blueprints.admin_core.BASE_DIR", str(uploads)),
            patch("web_app.logger.exception") as logged,
        ):
            response = self.client.post(
                "/admin/upload/image",
                data={
                    "csrf_token": "report-test",
                    "image": (io.BytesIO(png_bytes(corrupt=True)), "damaged.png"),
                },
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("文件内容无效", response.get_json()["error"])
        self.assertFalse(uploads.exists())
        logged.assert_not_called()

    def test_foreign_and_missing_notifications_return_404_without_changes(self):
        self.login()
        for notice in (self.other_notice, 999999):
            with self.subTest(notice=notice):
                response = self.client.post(
                    f"/notifications/read/{notice}",
                    json={},
                    headers={"X-CSRF-Token": "report-test"},
                )
                self.assertEqual(response.status_code, 404)
                self.assertIs(response.get_json()["success"], False)
        self.assertEqual(
            self.row("SELECT is_read FROM notifications WHERE id=?", (self.other_notice,))[0], 0
        )

    def test_owned_notification_can_be_marked_read_repeatedly(self):
        self.login()
        for _ in range(2):
            response = self.client.post(
                f"/notifications/read/{self.own_notice}",
                json={},
                headers={"X-CSRF-Token": "report-test"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertIs(response.get_json()["success"], True)
        self.assertEqual(
            self.row("SELECT is_read FROM notifications WHERE id=?", (self.own_notice,))[0], 1
        )

    def sitemap_urls(self):
        response = self.client.get("/sitemap.xml", base_url="https://untrusted.example")
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/xml", response.content_type)
        root = ET.fromstring(response.data)
        namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        return {
            item.findtext("s:loc", namespaces=namespace): item.findtext(
                "s:lastmod", namespaces=namespace
            )
            for item in root.findall("s:url", namespace)
        }

    def test_sitemap_defaults_to_real_domain_and_contains_entity_urls(self):
        urls = self.sitemap_urls()
        for path in (
            "/news",
            f"/news/{self.news_id}",
            "/matches/report-alpha-beta",
            "/events/report-cup",
            f"/players/{self.player_id}",
            f"/teams/{self.team_id}",
        ):
            with self.subTest(path=path):
                self.assertIn("https://80gotv.cn" + path, urls)
        for url in urls:
            self.assertTrue(url.startswith("https://80gotv.cn/"))
        for path in (
            f"/news/{self.news_id}",
            "/matches/report-alpha-beta",
            "/events/report-cup",
            f"/players/{self.player_id}",
        ):
            self.assertIsNotNone(urls["https://80gotv.cn" + path])
            date.fromisoformat(urls["https://80gotv.cn" + path])

    def test_sitemap_uses_configured_site_and_excludes_redirected_articles(self):
        app.config["PUBLIC_BASE_URL"] = "https://scores.example.org"
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute(
                "UPDATE news SET redirect_url='/matches/report-alpha-beta' WHERE id=?",
                (self.news_id,),
            )
        urls = self.sitemap_urls()
        self.assertTrue(all(url.startswith("https://scores.example.org/") for url in urls))
        self.assertNotIn(f"https://scores.example.org/news/{self.news_id}", urls)

    def test_sitemap_omits_invalid_dates_instead_of_emitting_invalid_xml_values(self):
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute("UPDATE events SET created_at='unknown' WHERE id=?", (self.event_id,))
        self.assertIsNone(self.sitemap_urls()["https://80gotv.cn/events/report-cup"])

    def test_public_pages_have_one_description_canonical_and_open_graph_set(self):
        for path in (
            "/",
            "/news",
            f"/news/{self.news_id}",
            "/matches/report-alpha-beta",
            "/events/report-cup",
            f"/players/{self.player_id}",
            f"/teams/{self.team_id}",
            "/stats",
        ):
            with self.subTest(path=path):
                response = self.client.get(
                    path + "?utm_source=report", base_url="https://untrusted.example"
                )
                self.assertEqual(response.status_code, 200)
                info = PageInfo(response.get_data(as_text=True))
                self.assertEqual(info.canonical, ["https://80gotv.cn" + path])
                for name in (
                    "description",
                    "og:title",
                    "og:description",
                    "og:url",
                    "og:type",
                    "og:image",
                ):
                    self.assertEqual(len(info.meta.get(name, [])), 1, name)
                    self.assertTrue(info.meta[name][0].strip(), name)
                self.assertEqual(info.meta["description"], info.meta["og:description"])
                self.assertEqual(info.meta["og:url"], info.canonical)
                self.assertNotIn("Private real name", info.meta["description"][0])

    def test_article_metadata_is_plain_text_and_escaped(self):
        response = self.client.get(f"/news/{self.news_id}")
        info = PageInfo(response.get_data(as_text=True))
        self.assertEqual(info.meta.get("description"), ['Report summary & "details"'])
        self.assertEqual(info.meta.get("og:type"), ["article"])
        self.assertEqual(info.meta.get("og:title"), ["Report Article & review - 80GOTV"])

    def test_player_metadata_never_uses_the_viewers_private_remark(self):
        with patch.dict(
            app.jinja_env.globals,
            {"private_remark_for_player": lambda _player_id: "Private viewer note"},
        ):
            for path in (f"/players/{self.player_id}", f"/stats/players/{self.player_id}"):
                with self.subTest(path=path):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200)
                    html = response.get_data(as_text=True)
                    self.assertIn("Private viewer note", html)
                    info = PageInfo(html)
                    self.assertIn("Report Player", info.meta["og:title"][0])
                    self.assertNotIn("Private viewer note", info.meta["og:title"][0])
                    self.assertNotIn("Private viewer note", info.meta["description"][0])

    def test_metadata_uses_configured_origin_and_preserves_normalized_page_number(self):
        app.config["PUBLIC_BASE_URL"] = "https://scores.example.org"
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.executemany(
                "INSERT INTO news(title,content,publish_time) VALUES(?,'<p>Page content</p>','2026-05-04')",
                [(f"Article {index}",) for index in range(20)],
            )
        info = PageInfo(self.client.get("/news?page=2&utm_source=report").get_data(as_text=True))
        self.assertEqual(info.canonical, ["https://scores.example.org/news?page=2"])
        self.assertTrue(info.meta["og:image"][0].startswith("https://scores.example.org/"))
        clamped = PageInfo(self.client.get("/news?page=9999").get_data(as_text=True))
        self.assertEqual(clamped.canonical, ["https://scores.example.org/news?page=2"])

    def test_invalid_site_configuration_does_not_leak_into_page_urls(self):
        for configured in (
            "auto",
            "//untrusted.example",
            "https://user:password@example.org",
            "javascript:alert(1)",
        ):
            with self.subTest(configured=configured):
                app.config["PUBLIC_BASE_URL"] = configured
                info = PageInfo(
                    self.client.get("/news", base_url="https://untrusted.example").get_data(
                        as_text=True
                    )
                )
                self.assertEqual(info.canonical, ["https://80gotv.cn/news"])

    def test_match_and_match_stats_have_exactly_one_page_heading(self):
        for path in ("/matches/report-alpha-beta", "/matches/report-alpha-beta/stats"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(PageInfo(response.get_data(as_text=True)).headings, 1)

    def test_team_create_rejects_excessive_lengths_and_keeps_inputs(self):
        self.login(admin=True)
        before = self.row("SELECT COUNT(*) FROM teams")[0]
        for name, short in (("n" * 41, "OK"), ("Valid name", "s" * 17), ("n" * 300, "s" * 60)):
            with self.subTest(name_length=len(name), short_length=len(short)):
                response = self.client.post(
                    "/admin/teams/add",
                    data={
                        "csrf_token": "report-test",
                        "name": name,
                        "short_name": short,
                        "description": "Keep this input",
                    },
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("Keep this input", response.get_data(as_text=True))
                self.assertEqual(self.row("SELECT COUNT(*) FROM teams")[0], before)

    def test_team_edit_rejects_excessive_lengths_without_partial_updates(self):
        self.login(admin=True)
        before = self.row(
            "SELECT name,short_name,description FROM teams WHERE id=?", (self.team_id,)
        )
        for name, short in (("n" * 41, "OK"), ("Valid name", "s" * 17)):
            with self.subTest(name_length=len(name), short_length=len(short)):
                response = self.client.post(
                    f"/admin/teams/edit/{self.team_id}",
                    data={
                        "csrf_token": "report-test",
                        "name": name,
                        "short_name": short,
                        "description": "Do not save",
                    },
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    self.row(
                        "SELECT name,short_name,description FROM teams WHERE id=?", (self.team_id,)
                    ),
                    before,
                )

    def test_team_length_boundaries_save_in_create_and_edit(self):
        self.login(admin=True)
        for index, path in enumerate(("/admin/teams/add", f"/admin/teams/edit/{self.team_id}")):
            data = {
                "csrf_token": "report-test",
                "name": str(index) + "n" * 39,
                "short_name": str(index) + "s" * 15,
            }
            self.assertEqual(self.client.post(path, data=data).status_code, 302)
            self.assertIsNotNone(
                self.row(
                    "SELECT id FROM teams WHERE name=? AND short_name=?",
                    (data["name"], data["short_name"]),
                )
            )

    def test_oversized_news_is_rejected_for_create_and_edit_and_preserved_in_form(self):
        self.login(admin=True)
        before = self.row("SELECT title,content,summary FROM news WHERE id=?", (self.news_id,))
        for path in ("/admin/news/add", f"/admin/news/edit/{self.news_id}"):
            for content in ("x" * (200 * 1024), "中" * 35000):
                with self.subTest(path=path, characters=len(content)):
                    response = self.client.post(
                        path,
                        data={
                            "csrf_token": "report-test",
                            "title": "Oversized article",
                            "content": content,
                            "summary": "Keep this summary",
                        },
                    )
                    self.assertEqual(response.status_code, 400)
                    self.assertIn("Keep this summary", response.get_data(as_text=True))
                    self.assertIn(content[:500], response.get_data(as_text=True))
                    self.assertEqual(
                        self.row(
                            "SELECT title,content,summary FROM news WHERE id=?", (self.news_id,)
                        ),
                        before,
                    )
                    self.assertEqual(self.row("SELECT COUNT(*) FROM news")[0], 1)

    def test_news_content_at_byte_limit_is_accepted(self):
        self.login(admin=True)
        content = "<p>" + "x" * (100 * 1024 - 7) + "</p>"
        for index, path in enumerate(("/admin/news/add", f"/admin/news/edit/{self.news_id}")):
            response = self.client.post(
                path,
                data={
                    "csrf_token": "report-test",
                    "title": f"Boundary article {index}",
                    "content": content,
                },
            )
            self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.row("SELECT content FROM news WHERE id=?", (self.news_id,))[0], content
        )

    def test_admin_forms_expose_the_matching_input_limits(self):
        self.login(admin=True)
        teams = self.client.get("/admin/teams/add").get_data(as_text=True)
        self.assertRegex(teams, r'<input\b[^>]*name="name"[^>]*maxlength="40"')
        self.assertRegex(teams, r'<input\b[^>]*name="short_name"[^>]*maxlength="16"')
        news = self.client.get("/admin/news/add").get_data(as_text=True)
        self.assertRegex(news, r'<textarea\b[^>]*name="content"[^>]*data-max-utf8-bytes="102400"')


if __name__ == "__main__":
    unittest.main()
