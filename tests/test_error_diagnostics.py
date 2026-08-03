import os
import tempfile
import unittest
from unittest.mock import patch

from app import app
from config import Config
from models import init_tables


def _raise_diagnostic_test_error():
    raise RuntimeError("diagnostic-secret")


app.add_url_rule(
    "/__test_error_diagnostics",
    endpoint="test_error_diagnostics",
    view_func=_raise_diagnostic_test_error,
)


class ErrorDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        handle, self.database_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.original_database = Config.DATABASE
        self.original_debug = app.config.get("DEBUG")
        self.original_testing = app.config.get("TESTING")
        self.original_secure_cookie = app.config.get("SESSION_COOKIE_SECURE")
        self.original_propagate = app.config.get("PROPAGATE_EXCEPTIONS")
        Config.DATABASE = self.database_path
        app.config.update(
            DEBUG=True,
            TESTING=True,
            SESSION_COOKIE_SECURE=False,
            PROPAGATE_EXCEPTIONS=False,
        )
        init_tables()
        self.client = app.test_client()
        with self.client.session_transaction() as browser_session:
            browser_session["admin_id"] = 1
            browser_session["csrf_token"] = "diagnostic-test"

    def tearDown(self):
        Config.DATABASE = self.original_database
        app.config.update(
            DEBUG=self.original_debug,
            TESTING=self.original_testing,
            SESSION_COOKIE_SECURE=self.original_secure_cookie,
            PROPAGATE_EXCEPTIONS=self.original_propagate,
        )
        try:
            os.remove(self.database_path)
        except OSError:
            pass

    def test_500_keeps_friendly_page_and_logs_request_details(self):
        path = "/__test_error_diagnostics"
        with self.assertLogs("80gotv", level="ERROR") as captured:
            response = self.client.get(path)

        request_id = response.headers.get("X-Request-ID")
        log_text = "\n".join(captured.output)
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 500)
        self.assertRegex(request_id or "", r"^[0-9a-f]{32}$")
        self.assertIn("500", body)
        self.assertNotIn("diagnostic-secret", body)
        self.assertIn(f"request_id={request_id}", log_text)
        self.assertIn(f"path={path}", log_text)
        self.assertIn("RuntimeError: diagnostic-secret", log_text)

    def test_request_ids_are_unique(self):
        first = self.client.get("/__test_error_diagnostics")
        second = self.client.get("/__test_error_diagnostics")

        self.assertNotEqual(first.headers.get("X-Request-ID"), second.headers.get("X-Request-ID"))

    def test_admin_bracket_error_reaches_common_500_handler(self):
        with patch(
            "blueprints.admin_events.build_event_bracket",
            side_effect=RuntimeError("admin-bracket-secret"),
        ):
            with self.assertLogs("80gotv", level="ERROR") as captured:
                response = self.client.post(
                    "/admin/events/7/bracket/api/save",
                    json={"rounds": []},
                    headers={"X-CSRF-Token": "diagnostic-test"},
                )

        request_id = response.headers.get("X-Request-ID")
        log_text = "\n".join(captured.output)
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 500)
        self.assertRegex(request_id or "", r"^[0-9a-f]{32}$")
        self.assertNotIn("admin-bracket-secret", body)
        self.assertIn(f"request_id={request_id}", log_text)
        self.assertIn("path=/admin/events/7/bracket/api/save", log_text)
        self.assertIn("RuntimeError: admin-bracket-secret", log_text)
