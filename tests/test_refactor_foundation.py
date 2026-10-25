import io
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import request

from app import app
from config import Config
from models import init_tables


class FoundationRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.old_database = Config.DATABASE
        self.addCleanup(setattr, Config, "DATABASE", self.old_database)
        Config.DATABASE = str(Path(self.temp.name) / "site.db")
        self.settings = dict(app.config)
        self.addCleanup(app.config.update, self.settings)
        app.config.update(TESTING=True, PROPAGATE_EXCEPTIONS=False, SESSION_COOKIE_SECURE=False)
        init_tables()
        self.client = app.test_client()

    def test_api_not_found_is_json_and_has_request_id(self):
        response = self.client.get("/api/front/not-a-real-route")
        self.assertEqual(response.status_code, 404)
        self.assertTrue(response.is_json)
        self.assertFalse(response.json["ok"])
        self.assertEqual(response.json["request_id"], response.headers["X-Request-ID"])

    def test_api_failure_does_not_return_html_or_internal_details(self):
        with patch("routes.front_api.load_home_feed", side_effect=RuntimeError("private-details")):
            with self.assertLogs("80gotv", level="ERROR"):
                response = self.client.get("/api/front/home")
        self.assertEqual(response.status_code, 500)
        self.assertTrue(response.is_json)
        self.assertFalse(response.json["ok"])
        self.assertNotIn("private-details", response.get_data(as_text=True))

    def test_failed_request_closes_unclosed_database_connections(self):
        connections = []

        def broken_query(conn):
            connections.append(conn)
            self.addCleanup(conn.close)
            raise sqlite3.OperationalError("forced failure")

        with patch("routes.front_api.load_home_feed", side_effect=broken_query):
            with self.assertLogs("80gotv", level="ERROR"):
                self.client.get("/api/front/dashboard")
        self.assertEqual(len(connections), 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            connections[0].execute("SELECT 1")

    def test_static_demo_aliases_do_not_bypass_protected_download(self):
        static = Path(self.temp.name) / "static"
        (static / "demos").mkdir(parents=True)
        (static / "demos" / "private.dem").write_bytes(b"private demo")
        with patch.object(app, "_static_folder", str(static)):
            for path in ("/static/demos/private.dem", "/static/other/../demos/private.dem"):
                with self.subTest(path=path):
                    with self.client.get(path) as response:
                        self.assertEqual(response.status_code, 404)
            if os.name == "nt":
                for alias in ("DEMOS", "demos.", "demos...", "demos%20"):
                    with (
                        self.subTest(alias=alias),
                        self.client.get(f"/static/{alias}/private.dem") as response,
                    ):
                        self.assertEqual(response.status_code, 404)

    def test_streamed_json_without_content_length_is_still_bounded(self):
        payload = b'{"padding":"' + b"x" * (2 * 1024 * 1024) + b'"}'
        stream = io.BytesIO(payload)
        with app.test_request_context(
            "/api/gsi/receive",
            method="POST",
            environ_overrides={
                "wsgi.input": stream,
                "wsgi.input_terminated": True,
                "CONTENT_TYPE": "application/json",
                "CONTENT_LENGTH": "",
            },
        ):
            app.preprocess_request()
            self.assertEqual(request.max_content_length, 2 * 1024 * 1024)
            self.assertLessEqual(len(request.get_data()), 2 * 1024 * 1024)
            self.assertLessEqual(stream.tell(), 2 * 1024 * 1024)

    def test_post_error_json_preserves_allow_header(self):
        response = self.client.get("/api/feedback/submit")
        self.assertEqual(response.status_code, 405)
        self.assertTrue(response.is_json)
        self.assertIn("POST", response.headers["Allow"])


if __name__ == "__main__":
    unittest.main()
