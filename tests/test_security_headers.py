import unittest

from app import app


class SecurityHeaderTests(unittest.TestCase):
    def setUp(self):
        self.original_testing = app.config.get("TESTING")
        self.original_production = app.config.get("IS_PRODUCTION")
        self.original_secure_cookie = app.config.get("SESSION_COOKIE_SECURE")
        app.config.update(
            TESTING=True,
            IS_PRODUCTION=True,
            SESSION_COOKIE_SECURE=True,
        )
        self.client = app.test_client()

    def tearDown(self):
        app.config.update(
            TESTING=self.original_testing,
            IS_PRODUCTION=self.original_production,
            SESSION_COOKIE_SECURE=self.original_secure_cookie,
        )

    def test_normal_production_page_does_not_allow_local_dev_scripts(self):
        response = self.client.get("/healthz")
        policy = response.headers["Content-Security-Policy"]
        self.assertNotIn("localhost:5173", policy)
        self.assertNotIn("127.0.0.1:5173", policy)
        self.assertNotIn("'unsafe-eval'", policy)
        self.assertIn("upgrade-insecure-requests", policy)
        self.assertEqual(response.headers["X-DNS-Prefetch-Control"], "off")


if __name__ == "__main__":
    unittest.main()
