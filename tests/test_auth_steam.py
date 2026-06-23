import time
import unittest
import urllib.parse
from unittest.mock import patch

from werkzeug.middleware.proxy_fix import ProxyFix

from app import app
from routes import auth


class _SteamResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return b"ns:http://specs.openid.net/auth/2.0\nis_valid:true\n"


class SteamAuthTests(unittest.TestCase):
    def setUp(self):
        self.original_testing = app.config.get("TESTING")
        self.original_secret_key = app.config.get("SECRET_KEY")
        app.config.update(TESTING=True, SECRET_KEY="steam-auth-test")
        self.client = app.test_client()
        self.original_base_url = auth.Config.PUBLIC_BASE_URL

    def tearDown(self):
        auth.Config.PUBLIC_BASE_URL = self.original_base_url
        app.config.update(
            TESTING=self.original_testing,
            SECRET_KEY=self.original_secret_key,
        )

    def _start(self, base_url="http://127.0.0.1:5000", purpose="register", headers=None):
        response = self.client.get(
            f"/auth/steam/start?purpose={purpose}",
            base_url=base_url,
            headers=headers,
        )
        self.assertEqual(response.status_code, 302)
        location = response.headers["Location"]
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(location).query)
        return query

    def test_local_address_follows_current_port(self):
        auth.Config.PUBLIC_BASE_URL = "auto"
        query = self._start("http://127.0.0.1:5055")
        self.assertTrue(
            query["openid.return_to"][0].startswith("http://127.0.0.1:5055/auth/steam/callback?")
        )

    def test_lan_address_keeps_http(self):
        auth.Config.PUBLIC_BASE_URL = "auto"
        query = self._start("http://192.168.1.20:5000")
        self.assertTrue(
            query["openid.return_to"][0].startswith("http://192.168.1.20:5000/auth/steam/callback?")
        )

    def test_lan_computer_name_keeps_http(self):
        auth.Config.PUBLIC_BASE_URL = "auto"
        query = self._start("http://gaming-pc:5000")
        self.assertTrue(
            query["openid.return_to"][0].startswith("http://gaming-pc:5000/auth/steam/callback?")
        )

    def test_public_address_uses_https(self):
        auth.Config.PUBLIC_BASE_URL = "auto"
        query = self._start("http://example.trycloudflare.com")
        self.assertTrue(
            query["openid.return_to"][0].startswith(
                "https://example.trycloudflare.com/auth/steam/callback?"
            )
        )
        self.assertEqual(query["openid.realm"][0], "https://example.trycloudflare.com")

    def test_fixed_public_address_wins(self):
        auth.Config.PUBLIC_BASE_URL = "https://cs.example.com"
        query = self._start("http://127.0.0.1:5000")
        self.assertTrue(
            query["openid.return_to"][0].startswith("https://cs.example.com/auth/steam/callback?")
        )

    def test_cloudflare_proxy_headers_are_used_when_trusted(self):
        auth.Config.PUBLIC_BASE_URL = "auto"
        original_wsgi_app = app.wsgi_app
        app.wsgi_app = ProxyFix(original_wsgi_app, x_for=1, x_proto=1, x_host=1)
        try:
            query = self._start(
                "http://127.0.0.1:5000",
                headers={
                    "X-Forwarded-For": "203.0.113.10",
                    "X-Forwarded-Proto": "https",
                    "X-Forwarded-Host": "demo.trycloudflare.com",
                },
            )
        finally:
            app.wsgi_app = original_wsgi_app
        self.assertTrue(
            query["openid.return_to"][0].startswith(
                "https://demo.trycloudflare.com/auth/steam/callback?"
            )
        )

    def test_cancel_returns_to_register(self):
        auth.Config.PUBLIC_BASE_URL = "auto"
        query = self._start()
        return_to = query["openid.return_to"][0]
        response = self.client.get(f"{return_to}&openid.mode=cancel")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/register"))

    def test_expired_response_is_rejected(self):
        auth.Config.PUBLIC_BASE_URL = "auto"
        query = self._start()
        return_to = query["openid.return_to"][0]
        with self.client.session_transaction(base_url="http://127.0.0.1:5000") as session:
            session["steam_auth"]["started_at"] = time.time() - auth.STEAM_AUTH_MAX_AGE - 1
        response = self.client.get(f"{return_to}&openid.mode=cancel")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/register"))
        with self.client.session_transaction(base_url="http://127.0.0.1:5000") as session:
            self.assertNotIn("steam_auth", session)
            self.assertNotIn("steam_verified", session)

    def test_changed_return_address_is_rejected(self):
        auth.Config.PUBLIC_BASE_URL = "auto"
        query = self._start()
        return_to = query["openid.return_to"][0]
        callback = urllib.parse.urlsplit(return_to)
        response = self.client.get(
            f"{return_to}&openid.mode=id_res&openid.return_to="
            f"{urllib.parse.quote('https://attacker.example/callback', safe='')}"
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/register"))
        with self.client.session_transaction(
            base_url=f"{callback.scheme}://{callback.netloc}"
        ) as session:
            self.assertNotIn("steam_auth", session)
            self.assertNotIn("steam_verified", session)

    @patch.object(auth.urllib.request, "urlopen", return_value=_SteamResponse())
    def test_recovery_returns_to_change_password(self, _urlopen):
        auth.Config.PUBLIC_BASE_URL = "auto"
        query = self._start(purpose="recovery")
        response = self._complete_valid_response(query)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/change-password"))
        with self.client.session_transaction(base_url="http://127.0.0.1:5000") as session:
            self.assertEqual(session["steam_verified"]["purpose"], "recovery")

    def _complete_valid_response(self, query):
        """模拟 Steam 返回一份已由 Steam 服务器确认的结果。"""
        return_to = query["openid.return_to"][0]
        callback = urllib.parse.urlsplit(return_to)
        claimed_id = "https://steamcommunity.com/openid/id/76561198000000000"
        callback_values = urllib.parse.parse_qsl(callback.query)
        callback_values.extend(
            [
                ("openid.ns", auth.STEAM_OPENID_NS),
                ("openid.mode", "id_res"),
                ("openid.op_endpoint", auth.STEAM_OPENID_URL),
                ("openid.claimed_id", claimed_id),
                ("openid.identity", claimed_id),
                ("openid.return_to", return_to),
                ("openid.response_nonce", str(time.time())),
                ("openid.assoc_handle", "test"),
                ("openid.signed", "op_endpoint,claimed_id,identity,return_to,response_nonce"),
                ("openid.sig", "test"),
            ]
        )
        callback_url = urllib.parse.urlunsplit(
            (
                callback.scheme,
                callback.netloc,
                callback.path,
                urllib.parse.urlencode(callback_values),
                "",
            )
        )
        return self.client.get(callback_url)

    @patch.object(auth.urllib.request, "urlopen", return_value=_SteamResponse())
    def test_valid_response_marks_steam_as_verified(self, _urlopen):
        auth.Config.PUBLIC_BASE_URL = "auto"
        query = self._start()
        response = self._complete_valid_response(query)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/register"))
        with self.client.session_transaction(base_url="http://127.0.0.1:5000") as session:
            self.assertEqual(
                session["steam_verified"]["steam_id64"],
                "76561198000000000",
            )


if __name__ == "__main__":
    unittest.main()
