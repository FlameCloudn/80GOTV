import base64
import sqlite3
import string
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from app import app
from config import Config
from models import init_tables
from utils.helpers import event_path


def encoded_name(delta):
    lower = string.ascii_lowercase
    upper = string.ascii_uppercase
    table = str.maketrans(
        lower + upper, lower[delta:] + lower[:delta] + upper[delta:] + upper[:delta]
    )
    return base64.b64encode("2027Winter???".translate(table).encode("ascii")).decode("ascii")


class EventCards(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.current = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and "event-card" in attrs.get("class", "").split():
            self.current = {"href": attrs.get("href"), "classes": [], "text": ""}
            self.links.append(self.current)
        if self.current:
            self.current["classes"].extend(attrs.get("class", "").split())

    def handle_endtag(self, tag):
        if tag == "a":
            self.current = None

    def handle_data(self, data):
        if self.current:
            self.current["text"] += data


class ArgPreviewTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory(prefix="80gotv-arg-")
        self.addCleanup(self.workspace.cleanup)
        self.original_database = Config.DATABASE
        self.original_config = app.config.copy()
        self.addCleanup(setattr, Config, "DATABASE", self.original_database)
        self.addCleanup(app.config.update, self.original_config)
        Config.DATABASE = str(Path(self.workspace.name) / "test.db")
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False, TRUSTED_HOSTS=None)
        init_tables()
        self.conn = sqlite3.connect(Config.DATABASE)
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        self.event_id = self.conn.execute(
            "INSERT INTO events(name,slug,status,format) VALUES(?,?,?,?)",
            (encoded_name(1), "gte5geuvi-j", "???", "双败淘汰·?·?"),
        ).lastrowid
        self.conn.execute(
            "INSERT INTO events(name,slug,start_date,end_date,format) VALUES(?,?,?,?,?)",
            ("Existing Cup", "existing-cup", "2026-01-01", "2026-01-02", "BO3"),
        )
        self.conn.commit()
        self.client = app.test_client()

    def test_error_path_is_real_persistent_503(self):
        for path in ("/gtE5geUvi+j=", "/gtE5geUvi%2Bj=", "/gtE5geUvi+j=?preview=1"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 503)
            self.assertIn("503 Service Unavailable", response.get_data(as_text=True))
            self.assertIn("no-store", response.headers["Cache-Control"])
            self.assertNotIn("2027Winter???", response.get_data(as_text=True))

    def test_head_is_503_without_a_body(self):
        response = self.client.head("/gtE5geUvi+j=")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data, b"")

    def test_event_and_stats_addresses_lead_to_error_page(self):
        for ref in (str(self.event_id), "gte5geuvi-j"):
            for suffix in ("", "/stats"):
                response = self.client.get(f"/events/{ref}{suffix}")
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers["Location"], "/gtE5geUvi+j=")
                self.assertEqual(self.client.get(response.headers["Location"]).status_code, 503)

    def test_event_card_has_only_the_requested_details(self):
        for path in ("/events", "/events?view=list"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            cards = EventCards(html).links
            self.assertEqual(len(cards), 2)
            special = next(card for card in cards if card["href"] == "/gtE5geUvi+j=")
            self.assertIn(encoded_name(1), special["text"])
            self.assertIn("202?/0?/??", special["text"])
            self.assertIn("???", special["text"])
            self.assertIn("双败淘汰·?·?", special["text"])
            self.assertNotIn("支队伍", special["text"])
            self.assertNotIn("场比赛", special["text"])
            self.assertNotIn("event-card-date", special["classes"])
            self.assertNotIn("2027Winter???", html)
            self.assertIn("event_display.js", html)
            regular = next(card for card in cards if card["href"] == "/events/existing-cup")
            self.assertIn("BO3", regular["text"])
            self.assertIn("event-card-date", regular["classes"])

    def test_question_mark_status_does_not_become_an_ordinary_status(self):
        for status in ("ongoing", "completed", "upcoming"):
            html = self.client.get(f"/events?status={status}").get_data(as_text=True)
            self.assertFalse(
                any(card["href"] == "/gtE5geUvi+j=" for card in EventCards(html).links)
            )

    def test_front_api_does_not_list_the_special_event(self):
        data = self.client.get("/api/front/events").get_json()
        self.assertNotIn(self.event_id, [event["id"] for event in data["events"]])
        self.assertEqual(self.client.get(f"/api/front/events/{self.event_id}").status_code, 404)

    def test_home_links_and_names_do_not_reveal_plaintext(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertNotIn('href="/gtE5geUvi+j="', html)
        self.assertNotIn("2027Winter???", html)

    def test_other_public_surfaces_do_not_expose_the_event_or_animation(self):
        player_id = self.conn.execute(
            "INSERT INTO players(nickname) VALUES('Public Player')"
        ).lastrowid
        self.conn.commit()
        for path in (
            "/",
            "/matches",
            "/results",
            "/dashboard",
            "/stats",
            f"/players/{player_id}",
            "/search?q=2027",
            "/search?q=MjAy",
            "/api/search?q=2027",
            "/api/search?q=MjAy",
            "/api/front/dashboard",
            "/api/front/home",
            "/sitemap.xml",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                body = response.get_data(as_text=True)
                for value in (
                    encoded_name(1),
                    "gte5geuvi-j",
                    "/gtE5geUvi+j=",
                    "event_display.js",
                    "data-event-display",
                ):
                    self.assertNotIn(value, body)

    def test_match_sidebar_has_only_regular_events(self):
        match_id = self.conn.execute(
            "INSERT INTO matches(status,bo_format,map1) VALUES('upcoming','BO1','Dust2')"
        ).lastrowid
        self.conn.commit()
        response = self.client.get(f"/matches/{match_id}", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertNotIn(encoded_name(1), body)
        self.assertNotIn('href="/gtE5geUvi+j="', body)
        self.assertIn("Existing Cup", body)

    def test_news_article_can_link_to_the_error_page_without_redirecting(self):
        news_id = self.conn.execute(
            "INSERT INTO news(title,content,internal_link_url,internal_link_text) VALUES(?,?,?,?)",
            ("Notice", "<p>Article body</p>", "/gtE5geUvi+j=", "Continue"),
        ).lastrowid
        self.conn.commit()
        response = self.client.get(f"/news/{news_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn('href="/gtE5geUvi+j="', response.get_data(as_text=True))
        self.assertIn("news-comments", response.get_data(as_text=True))
        self.assertEqual(self.client.get("/gtE5geUvi+j=").status_code, 503)

    def test_event_path_for_database_and_partial_rows(self):
        full = self.conn.execute("SELECT * FROM events WHERE id=?", (self.event_id,)).fetchone()
        partial = self.conn.execute(
            "SELECT id,name FROM events WHERE id=?", (self.event_id,)
        ).fetchone()
        self.assertEqual(event_path(full), "/gtE5geUvi+j=")
        self.assertEqual(event_path(partial), "/gtE5geUvi+j=")

    def test_cipher_frames_include_exactly_delta_1_through_14(self):
        from services.arg_event_service import ARG_EVENT_FRAMES

        self.assertEqual(
            tuple(ARG_EVENT_FRAMES), tuple(encoded_name(delta) for delta in range(1, 15))
        )
        self.assertEqual(len(set(ARG_EVENT_FRAMES)), 14)
        for frame in ARG_EVENT_FRAMES:
            self.assertTrue(
                base64.b64decode(frame, validate=True).decode("ascii").startswith("2027")
            )

    def test_setup_is_idempotent_and_leaves_other_fields_blank(self):
        from services.arg_event_service import ensure_arg_event

        self.assertEqual(ensure_arg_event(self.conn), self.event_id)
        self.assertEqual(ensure_arg_event(self.conn), self.event_id)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0], 2)
        row = self.conn.execute("SELECT * FROM events WHERE id=?", (self.event_id,)).fetchone()
        for field in ("description", "start_date", "end_date", "stream_url", "bracket_data"):
            self.assertIsNone(row[field])
        self.assertEqual(row["status"], "???")
        self.assertEqual(row["format"], "双败淘汰·?·?")
        self.assertEqual(row["registration_open"], 0)

    def test_setup_creates_only_one_event_without_a_real_date(self):
        from services.arg_event_service import ensure_arg_event

        self.conn.execute("DELETE FROM events WHERE id=?", (self.event_id,))
        new_id = ensure_arg_event(self.conn)
        self.assertEqual(ensure_arg_event(self.conn), new_id)
        row = self.conn.execute("SELECT * FROM events WHERE id=?", (new_id,)).fetchone()
        self.assertEqual(row["status"], "???")
        self.assertEqual(row["format"], "双败淘汰·?·?")
        self.assertIsNone(row["start_date"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0], 2)

    def test_display_service_returns_only_prepared_random_names(self):
        values = self.client.get(f"/api/events/{self.event_id}/display").get_json()["values"]
        allowed = {encoded_name(delta) for delta in range(1, 15)}
        self.assertEqual(len(values), 32)
        self.assertTrue(set(values).issubset(allowed))
        self.assertTrue(all(left != right for left, right in zip(values, values[1:])))
        next_values = self.client.get(
            f"/api/events/{self.event_id}/display", query_string={"after": values[-1]}
        ).get_json()["values"]
        self.assertNotEqual(values[-1], next_values[0])
        self.assertEqual(self.client.get("/api/events/999999/display").status_code, 404)
        regular = self.conn.execute("SELECT id FROM events WHERE slug='existing-cup'").fetchone()[0]
        self.assertEqual(self.client.get(f"/api/events/{regular}/display").status_code, 404)

    def test_public_source_has_no_plaintext_or_algorithm(self):
        for path in ("/events", "/", "/gtE5geUvi+j=", "/static/js/event_display.js"):
            response = self.client.get(path)
            self.assertIn(response.status_code, (200, 503))
            body = response.get_data(as_text=True)
            for clue in (
                "2027Winter???",
                "ARG",
                "arg_event",
                "Caesar",
                "cipher",
                "delta",
                "data-frames",
            ):
                self.assertNotIn(clue, body)
        for path in (
            "/services/arg_event_service.py",
            "/templates/arg_unavailable.html",
            "/static/js/event_display.js.map",
            "/static/js/event_cipher.js",
        ):
            self.assertEqual(self.client.get(path).status_code, 404)
