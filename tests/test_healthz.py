import unittest

from app import app


class HealthCheckTests(unittest.TestCase):
    def test_health_check_can_reach_database(self):
        original_testing = app.config.get("TESTING")
        app.config["TESTING"] = True
        try:
            response = app.test_client().get("/healthz")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json(), {"ok": True})
        finally:
            app.config["TESTING"] = original_testing


if __name__ == "__main__":
    unittest.main()
