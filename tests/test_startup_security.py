import unittest
from types import SimpleNamespace

from app import _local_server_options
from config import validate_production_config


class StartupSecurityTests(unittest.TestCase):
    def test_local_mode_does_not_require_production_secrets(self):
        validate_production_config(
            SimpleNamespace(IS_PRODUCTION=False), {"SECRET_KEY": "change-me"}
        )

    def test_example_production_values_are_rejected_without_echoing_secrets(self):
        secret = "change-me-this-must-not-appear"
        values = {
            "SECRET_KEY": secret,
            "PUBLIC_BASE_URL": "auto",
            "TRUSTED_HOSTS": "你的域名",
            "ADMIN_PASSWORD": "请设置管理员密码",
        }
        with self.assertRaises(RuntimeError) as raised:
            validate_production_config(SimpleNamespace(IS_PRODUCTION=True), values)
        message = str(raised.exception)
        self.assertIn("SECRET_KEY", message)
        self.assertIn("PUBLIC_BASE_URL", message)
        self.assertIn("TRUSTED_HOSTS", message)
        self.assertIn("ADMIN_PASSWORD", message)
        self.assertNotIn(secret, message)

    def test_empty_mapping_does_not_fall_back_to_process_environment(self):
        with self.assertRaises(RuntimeError) as raised:
            validate_production_config(SimpleNamespace(IS_PRODUCTION=True), {})
        self.assertIn("SECRET_KEY", str(raised.exception))

    def test_public_url_must_be_a_plain_https_origin(self):
        base = {
            "SECRET_KEY": "s" * 64,
            "TRUSTED_HOSTS": "80gotv.example.net",
        }
        for public_url in (
            "http://80gotv.example.net",
            "https://user@80gotv.example.net",
            "https://80gotv.example.net/path",
            "https://80gotv.example.net?next=1",
        ):
            with self.subTest(public_url=public_url), self.assertRaises(RuntimeError):
                validate_production_config(
                    SimpleNamespace(IS_PRODUCTION=True),
                    {**base, "PUBLIC_BASE_URL": public_url},
                )

    def test_safe_production_values_pass(self):
        values = {
            "SECRET_KEY": "s" * 64,
            "PUBLIC_BASE_URL": "https://80gotv.example.net",
            "TRUSTED_HOSTS": "80gotv.example.net",
            "ADMIN_PASSWORD": "strong-admin-password",
            "GOTV_SECRET": "g" * 32,
            "GSI_TOKEN": "t" * 32,
            "SMTP_USERNAME": "verify@example.net",
            "SMTP_PASSWORD": "mail-password",
            "STEAM_WEB_API_KEY": "k" * 32,
        }
        validate_production_config(SimpleNamespace(IS_PRODUCTION=True), values)

    def test_required_feature_credentials_cannot_be_empty(self):
        values = {
            "SECRET_KEY": "s" * 64,
            "PUBLIC_BASE_URL": "https://80gotv.example.net",
            "TRUSTED_HOSTS": "80gotv.example.net",
            "GOTV_SECRET": "",
            "GSI_TOKEN": "",
            "SMTP_USERNAME": "",
            "SMTP_PASSWORD": "",
            "STEAM_WEB_API_KEY": "",
        }
        with self.assertRaises(RuntimeError) as raised:
            validate_production_config(SimpleNamespace(IS_PRODUCTION=True), values)
        message = str(raised.exception)
        for name in (
            "GOTV_SECRET",
            "GSI_TOKEN",
            "SMTP_USERNAME",
            "SMTP_PASSWORD",
            "STEAM_WEB_API_KEY",
        ):
            self.assertIn(name, message)

    def test_local_server_is_not_debug_or_public(self):
        options = _local_server_options()
        self.assertFalse(options["debug"])
        self.assertFalse(options["use_reloader"])
        self.assertEqual(options["host"], "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
