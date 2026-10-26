import tempfile
import unittest
from contextlib import closing
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from app import app
from config import Config
from models import get_db, init_tables
from services.home_service import load_home_feed
from services.performance_service import refresh_player_performance


class StylesheetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = set()

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "link" and attributes.get("rel") == "stylesheet":
            self.paths.add(urlsplit(attributes.get("href") or "").path)


class FrontendReleaseContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(setattr, Config, "DATABASE", Config.DATABASE)
        Config.DATABASE = str(Path(self.temp.name) / "frontend.db")
        self.addCleanup(app.config.update, dict(app.config))
        app.config.update(TESTING=True, PROPAGATE_EXCEPTIONS=False, SESSION_COOKIE_SECURE=False)
        init_tables()
        self.client = app.test_client()

    def test_public_pages_load_the_new_frontend_instead_of_legacy_styles(self):
        for path, page_css in (
            ("/", "home"),
            ("/matches", "schedule"),
            ("/results", "schedule"),
            ("/events", "events"),
            ("/players", "players"),
            ("/stats", "stats"),
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                parser = StylesheetParser()
                parser.feed(response.get_data(as_text=True))
                self.assertIn("/static/css/app.css", parser.paths)
                self.assertIn(f"/static/css/pages/{page_css}.css", parser.paths)
                self.assertFalse(
                    parser.paths.intersection(
                        {
                            "/static/css/style_v2.css",
                            "/static/css/hltv_refresh.css",
                            "/static/css/mobile_hltv.css",
                        }
                    )
                )

    def test_home_keeps_avatar_and_unknown_rating_without_changing_records(self):
        with closing(get_db()) as conn:
            player_id = conn.execute(
                "INSERT INTO players(nickname,avatar) VALUES('UnknownRating','release-avatar.png')"
            ).lastrowid
            match_id = conn.execute("INSERT INTO matches(status) VALUES('completed')").lastrowid
            conn.execute(
                "INSERT INTO match_stats(match_id,player_id,map_name,rounds_played,rating) "
                "VALUES(?,?,'de_mirage',20,NULL)",
                (match_id, player_id),
            )
            refresh_player_performance(conn)
            conn.commit()
            player = load_home_feed(conn)["top_players"][0]
            self.assertEqual(player["avatar"], "release-avatar.png")
            self.assertIsNone(player["avg_rating"])

        missing = self.client.get("/")
        self.assertEqual(missing.status_code, 200)
        missing_html = missing.get_data(as_text=True)
        self.assertIn("h-player-row", missing_html)
        self.assertIn("release-avatar", missing_html)
        self.assertRegex(missing_html, r'<b class="num [^"]*">-</b>')

        with closing(get_db()) as conn:
            self.assertIsNone(conn.execute("SELECT rating FROM match_stats").fetchone()[0])
            conn.execute("UPDATE match_stats SET rating=0")
            refresh_player_performance(conn)
            conn.commit()

        zero = self.client.get("/")
        self.assertEqual(zero.status_code, 200)
        self.assertRegex(zero.get_data(as_text=True), r'<b class="num [^"]*">0\.00</b>')
        with closing(get_db()) as conn:
            self.assertEqual(conn.execute("SELECT rating FROM match_stats").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
