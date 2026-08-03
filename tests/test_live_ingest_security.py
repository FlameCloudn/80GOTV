import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from app import app
from config import Config
from models import get_db, init_tables
from routes.live_ingest import _run_with_database, _sanitize_live_state


class LiveIngestSecurityTests(unittest.TestCase):
    def setUp(self):
        handle, self.database_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.original_database = Config.DATABASE
        self.original_gsi_token = Config.GSI_TOKEN
        self.original_gotv_secret = Config.GOTV_SECRET
        self.original_testing = app.config.get("TESTING")
        self.original_secure_cookie = app.config.get("SESSION_COOKIE_SECURE")
        Config.DATABASE = self.database_path
        Config.GSI_TOKEN = "gsi-test-secret"
        Config.GOTV_SECRET = "gotv-test-secret"
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        init_tables()
        self.client = app.test_client()

    def tearDown(self):
        Config.DATABASE = self.original_database
        Config.GSI_TOKEN = self.original_gsi_token
        Config.GOTV_SECRET = self.original_gotv_secret
        app.config.update(
            TESTING=self.original_testing,
            SESSION_COOKIE_SECURE=self.original_secure_cookie,
        )
        try:
            os.remove(self.database_path)
        except OSError:
            pass

    @staticmethod
    def _gsi_payload(token):
        return {
            "auth": {"token": token},
            "map": {
                "name": "de_mirage",
                "round": 0,
                "team_ct": {"score": 0},
                "team_t": {"score": 0},
            },
            "allplayers": {},
            "bomb": {},
            "round": {},
            "previously": {},
            "phase_countdowns": {},
        }

    def test_bad_credentials_do_not_open_database(self):
        with patch("routes.live_ingest.get_db") as get_db_mock:
            response = self.client.post("/api/gsi/receive", json=self._gsi_payload("wrong"))
            self.assertEqual(response.status_code, 403)
            get_db_mock.assert_not_called()

    def test_bad_credentials_do_not_consume_authenticated_quota(self):
        with patch("routes.live_ingest.rate_limit", return_value=True) as limiter:
            response = self.client.post("/api/gsi/receive", json=self._gsi_payload("wrong"))
        self.assertEqual(response.status_code, 403)
        keys = [call.args[0] for call in limiter.call_args_list]
        self.assertIn("gsi_public", keys)
        self.assertIn("gsi_bad_auth", keys)
        self.assertNotIn("gsi_ingest", keys)

        with patch("routes.live_ingest.rate_limit", return_value=True) as limiter:
            response = self.client.post(
                "/api/gotv/stats",
                json={"match_id": 1},
                headers={"X-GOTV-Secret": "wrong"},
            )
        self.assertEqual(response.status_code, 403)
        keys = [call.args[0] for call in limiter.call_args_list]
        self.assertIn("gotv_public", keys)
        self.assertIn("gotv_bad_auth", keys)
        self.assertNotIn("gotv_ingest", keys)

    def test_non_ascii_or_non_text_gsi_token_is_rejected(self):
        for token in ("错误密钥", ["not", "text"]):
            with self.subTest(token=token), patch("routes.live_ingest.get_db") as get_db_mock:
                response = self.client.post("/api/gsi/receive", json=self._gsi_payload(token))
                self.assertEqual(response.status_code, 403)
                get_db_mock.assert_not_called()

    def test_public_limit_rejects_before_database_work(self):
        with (
            patch("routes.live_ingest.rate_limit", return_value=False),
            patch("routes.live_ingest.get_db") as get_db_mock,
        ):
            response = self.client.post(
                "/api/gsi/receive",
                json=self._gsi_payload(Config.GSI_TOKEN),
            )
        self.assertEqual(response.status_code, 429)
        get_db_mock.assert_not_called()

    def test_database_wrapper_rolls_back_and_closes_after_error(self):
        conn = MagicMock()

        def fail(active_conn):
            self.assertIs(active_conn, conn)
            raise RuntimeError("write failed")

        with patch("routes.live_ingest.get_db", return_value=conn):
            with self.assertRaisesRegex(RuntimeError, "write failed"):
                _run_with_database(fail)
        conn.rollback.assert_called_once_with()
        conn.close.assert_called_once_with()

        with patch("routes.live_ingest.get_db") as get_db_mock:
            response = self.client.post(
                "/api/gotv/stats",
                json={"match_id": 1},
                headers={"X-GOTV-Secret": "wrong"},
            )
            self.assertEqual(response.status_code, 403)
            get_db_mock.assert_not_called()

    def test_valid_gsi_is_saved_without_auth_token(self):
        conn = get_db()
        conn.execute("INSERT INTO teams(name, short_name) VALUES('Team 1', 'T1')")
        team1_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO teams(name, short_name) VALUES('Team 2', 'T2')")
        team2_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO events(name, status) VALUES('Test Event', 'ongoing')")
        event_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO matches(event_id, team1_id, team2_id, match_time, status, map1)
               VALUES(?, ?, ?, ?, 'live', 'de_mirage')""",
            (event_id, team1_id, team2_id, datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
        conn.close()

        response = self.client.post(
            "/api/gsi/receive",
            json=self._gsi_payload(Config.GSI_TOKEN),
        )
        self.assertEqual(response.status_code, 200)

        conn = get_db()
        row = conn.execute("SELECT live_state FROM live_match_data").fetchone()
        conn.close()
        state = json.loads(row["live_state"])
        self.assertNotIn("auth", state["gsi"])
        self.assertNotIn(Config.GSI_TOKEN, row["live_state"])

    def test_desktop_manager_can_push_to_selected_match(self):
        conn = get_db()
        team1_id = conn.execute(
            "INSERT INTO teams(name, short_name) VALUES('Team 1', 'T1')"
        ).lastrowid
        team2_id = conn.execute(
            "INSERT INTO teams(name, short_name) VALUES('Team 2', 'T2')"
        ).lastrowid
        event_id = conn.execute(
            "INSERT INTO events(name, status) VALUES('Test Event', 'ongoing')"
        ).lastrowid
        match_id = conn.execute(
            """INSERT INTO matches(event_id, team1_id, team2_id, match_time, status, map1)
               VALUES(?, ?, ?, ?, 'upcoming', 'de_mirage')""",
            (event_id, team1_id, team2_id, datetime.now().isoformat(timespec="seconds")),
        ).lastrowid
        conn.commit()
        conn.close()

        with patch("routes.live_ingest.rate_limit", return_value=True):
            response = self.client.post(
                f"/api/broadcast/matches/{match_id}/live",
                json=self._gsi_payload("ignored"),
                headers={"X-80GOTV-Token": Config.GSI_TOKEN},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["match_id"], match_id)

        conn = get_db()
        row = conn.execute(
            "SELECT live_state FROM live_match_data WHERE match_id=?", (match_id,)
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertNotIn("ignored", row["live_state"])

    def test_desktop_manager_rejects_bad_token(self):
        with patch("routes.live_ingest.get_db") as get_db_mock:
            response = self.client.post(
                "/api/broadcast/matches/1/live",
                json=self._gsi_payload("ignored"),
                headers={"X-80GOTV-Token": "wrong"},
            )
        self.assertEqual(response.status_code, 403)
        get_db_mock.assert_not_called()

    def test_desktop_manager_connection_test_verifies_match_without_writing_live_data(self):
        conn = get_db()
        team1_id = conn.execute(
            "INSERT INTO teams(name, short_name) VALUES('Golden Eight', 'G8')"
        ).lastrowid
        team2_id = conn.execute(
            "INSERT INTO teams(name, short_name) VALUES('Ultimate Eight', 'U8')"
        ).lastrowid
        event_id = conn.execute(
            "INSERT INTO events(name, status) VALUES('Test Event', 'ongoing')"
        ).lastrowid
        match_id = conn.execute(
            """INSERT INTO matches(event_id, team1_id, team2_id, match_time, status, map1)
               VALUES(?, ?, ?, ?, 'upcoming', 'de_mirage')""",
            (event_id, team1_id, team2_id, datetime.now().isoformat(timespec="seconds")),
        ).lastrowid
        conn.commit()
        conn.close()

        with patch("routes.live_ingest.rate_limit", return_value=True):
            response = self.client.get(
                f"/api/broadcast/matches/{match_id}/connection-test",
                headers={"X-80GOTV-Token": Config.GSI_TOKEN},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["match_id"], match_id)
        self.assertEqual(payload["team1_name"], "Golden Eight")
        self.assertEqual(payload["team2_name"], "Ultimate Eight")
        self.assertTrue(payload["server_time"])

        conn = get_db()
        live = conn.execute(
            "SELECT * FROM live_match_data WHERE match_id=?", (match_id,)
        ).fetchone()
        conn.close()
        self.assertIsNone(live)

    def test_connection_test_rejects_bad_token_before_database_work(self):
        with patch("routes.live_ingest.get_db") as get_db_mock:
            response = self.client.get(
                "/api/broadcast/matches/1/connection-test",
                headers={"X-80GOTV-Token": "wrong"},
            )
        self.assertEqual(response.status_code, 403)
        get_db_mock.assert_not_called()

    def test_connection_test_names_single_player_test_sides(self):
        conn = get_db()
        player1_id = conn.execute("INSERT INTO players(nickname) VALUES('KL-2077')").lastrowid
        player2_id = conn.execute("INSERT INTO players(nickname) VALUES('myh666')").lastrowid
        event_id = conn.execute(
            "INSERT INTO events(name, status) VALUES('Test Event', 'ongoing')"
        ).lastrowid
        match_id = conn.execute(
            """INSERT INTO matches(
                   event_id, team1_players, team2_players, match_time, status, map1, is_test_mode
               ) VALUES(?, ?, ?, ?, 'live', 'de_mirage', 1)""",
            (
                event_id,
                f"[{player1_id}]",
                f"[{player2_id}]",
                datetime.now().isoformat(timespec="seconds"),
            ),
        ).lastrowid
        conn.commit()
        conn.close()

        with patch("routes.live_ingest.rate_limit", return_value=True):
            response = self.client.get(
                f"/api/broadcast/matches/{match_id}/connection-test",
                headers={"X-80GOTV-Token": Config.GSI_TOKEN},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["team1_name"], "KL-2077")
        self.assertEqual(payload["team2_name"], "myh666")

    def test_old_saved_token_is_removed_without_changing_other_data(self):
        state = {"gsi": {"auth": {"token": "old"}, "map": {"name": "de_nuke"}}, "x": 1}
        clean = _sanitize_live_state(state)
        self.assertNotIn("auth", clean["gsi"])
        self.assertEqual(clean["gsi"]["map"]["name"], "de_nuke")
        self.assertEqual(clean["x"], 1)


if __name__ == "__main__":
    unittest.main()
