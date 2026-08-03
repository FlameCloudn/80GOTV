import os
import tempfile
import unittest

from app import app
from config import Config
from models import init_tables


class HealthCheckTests(unittest.TestCase):
    def setUp(self):
        handle, self.database_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.original_database = Config.DATABASE
        self.original_testing = app.config.get("TESTING")
        Config.DATABASE = self.database_path
        app.config["TESTING"] = True
        init_tables()

    def tearDown(self):
        Config.DATABASE = self.original_database
        app.config["TESTING"] = self.original_testing
        try:
            os.remove(self.database_path)
        except OSError:
            pass

    def test_health_check_can_reach_database(self):
        response = app.test_client().get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True})


if __name__ == "__main__":
    unittest.main()
