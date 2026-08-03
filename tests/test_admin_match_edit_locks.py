import os
import tempfile
import unittest

from app import app
from config import Config
from models import get_db, init_tables


class AdminMatchEditLocksTests(unittest.TestCase):
    def setUp(self):
        handle, self.database_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.original_database = Config.DATABASE
        self.original_testing = app.config.get("TESTING")
        self.original_secure_cookie = app.config.get("SESSION_COOKIE_SECURE")
        Config.DATABASE = self.database_path
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        init_tables()

        conn = get_db()
        conn.execute("INSERT INTO events(name,slug,status) VALUES('Cup','cup','upcoming')")
        self.event_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO teams(name,short_name) VALUES('Team A','A')")
        team1_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO teams(name,short_name) VALUES('Team B','B')")
        team2_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO matches(
                   event_id,team1_id,team2_id,team1_score,team2_score,
                   match_time,bo_format,stage,status,map1,map1_t1,map1_t2,
                   bp_password,server_address,server_password
               ) VALUES(?,?,?,?,?,'2026-08-01T20:00','BO3','半决赛','upcoming',
                        'mirage',13,7,'stored-bp-hash','127.0.0.1:27015','secret')""",
            (self.event_id, team1_id, team2_id, 1, 0),
        )
        self.match_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()

        self.client = app.test_client()
        with self.client.session_transaction() as browser_session:
            browser_session["admin_id"] = 1
            browser_session["admin_username"] = "admin"
            browser_session["csrf_token"] = "match-edit-test"

    def tearDown(self):
        Config.DATABASE = self.original_database
        app.config.update(
            TESTING=self.original_testing,
            SESSION_COOKIE_SECURE=self.original_secure_cookie,
        )
        try:
            os.remove(self.database_path)
        except OSError:
            pass

    def _post(self, **overrides):
        payload = {
            "csrf_token": "match-edit-test",
            "event_id": str(self.event_id),
            "match_time": "2026-08-01T20:00",
            "bo_format": "BO3",
            "stage": "半决赛",
            "status": "upcoming",
            "bp_password": "",
            "server_address": "127.0.0.1:27015",
        }
        payload.update(overrides)
        return self.client.post(f"/admin/matches/edit/{self.match_id}", data=payload)

    def test_blank_bp_password_is_preserved_and_live_scores_ignore_form(self):
        page = self.client.get(f"/admin/matches/edit/{self.match_id}")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("当前状态：已设置", html)
        self.assertNotIn("stored-bp-hash", html)

        response = self._post(team1_score="99", team2_score="98", map1_t1="99")
        self.assertEqual(response.status_code, 302)
        conn = get_db()
        match = conn.execute("SELECT * FROM matches WHERE id=?", (self.match_id,)).fetchone()
        self.assertEqual(match["bp_password"], "stored-bp-hash")
        self.assertEqual((match["team1_score"], match["team2_score"]), (1, 0))
        self.assertEqual(match["map1_t1"], 13)
        conn.close()

    def test_clear_bp_password_is_explicit(self):
        response = self._post(clear_bp_password="1")
        self.assertEqual(response.status_code, 302)
        conn = get_db()
        value = conn.execute(
            "SELECT bp_password FROM matches WHERE id=?", (self.match_id,)
        ).fetchone()[0]
        self.assertIsNone(value)
        conn.close()

    def test_started_match_can_save_without_disabled_setup_fields(self):
        conn = get_db()
        conn.execute("UPDATE matches SET status='live' WHERE id=?", (self.match_id,))
        conn.commit()
        conn.close()

        response = self.client.post(
            f"/admin/matches/edit/{self.match_id}",
            data={
                "csrf_token": "match-edit-test",
                "status": "completed",
                "stream_url": "https://live.bilibili.com/1",
            },
        )
        self.assertEqual(response.status_code, 302)
        conn = get_db()
        match = conn.execute("SELECT * FROM matches WHERE id=?", (self.match_id,)).fetchone()
        self.assertEqual(match["event_id"], self.event_id)
        self.assertEqual(match["match_time"], "2026-08-01T20:00")
        self.assertEqual(match["map1"], "mirage")
        self.assertEqual(match["bp_password"], "stored-bp-hash")
        self.assertEqual(match["status"], "completed")
        conn.close()


if __name__ == "__main__":
    unittest.main()
