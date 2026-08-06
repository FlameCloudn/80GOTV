import os
import tempfile
import unittest
from io import BytesIO
from unittest.mock import patch

from app import app
from config import Config
from models import get_db, init_tables
from utils.web_helpers import check_bp_password


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

    def test_online_bp_password_is_hidden_and_live_scores_ignore_form(self):
        page = self.client.get(f"/admin/matches/edit/{self.match_id}")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("留空则保持原口令", html)
        self.assertNotIn("stored-bp-hash", html)

        response = self._post(team1_score="99", team2_score="98", map1_t1="99")
        self.assertEqual(response.status_code, 302)
        conn = get_db()
        match = conn.execute("SELECT * FROM matches WHERE id=?", (self.match_id,)).fetchone()
        self.assertEqual(match["bp_password"], "stored-bp-hash")
        self.assertEqual((match["team1_score"], match["team2_score"]), (1, 0))
        self.assertEqual(match["map1_t1"], 13)
        conn.close()

    def test_new_bp_password_is_hashed(self):
        response = self._post(bp_password="new-shared-passcode")
        self.assertEqual(response.status_code, 302)
        conn = get_db()
        value = conn.execute(
            "SELECT bp_password FROM matches WHERE id=?", (self.match_id,)
        ).fetchone()[0]
        conn.close()
        self.assertNotEqual(value, "new-shared-passcode")
        self.assertTrue(check_bp_password(value, "new-shared-passcode"))

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

    def test_match_save_validation_keeps_submitted_values_visible(self):
        response = self._post(match_time="", stage="现场改过的阶段")
        self.assertEqual(response.status_code, 400)
        html = response.get_data(as_text=True)
        self.assertIn("比赛时间不能为空", html)
        self.assertIn("现场改过的阶段", html)

    def test_admin_demo_upload_still_analyzes_and_saves_file(self):
        demo_root = tempfile.mkdtemp()
        preview = {
            "map_name": "de_mirage",
            "team_a_score": 13,
            "team_b_score": 9,
            "rounds_count": 22,
            "source": "test",
            "players": [],
            "map_slot": 0,
            "demo_data": "{}",
        }
        try:
            conn = get_db()
            conn.execute("UPDATE matches SET status='completed' WHERE id=?", (self.match_id,))
            conn.commit()
            conn.close()
            with (
                patch("blueprints.admin_matches.DEMOS_DIR", demo_root),
                patch("blueprints.admin_matches.analyze_demo", return_value=preview),
            ):
                response = self.client.post(
                    f"/admin/matches/{self.match_id}/import-demo",
                    data={
                        "csrf_token": "match-edit-test",
                        "step": "analyze",
                        "demo_file_0": (BytesIO(b"demo data"), "mirage.dem"),
                    },
                    content_type="multipart/form-data",
                )
            self.assertEqual(response.status_code, 200)
            conn = get_db()
            saved = conn.execute(
                "SELECT demo_file FROM matches WHERE id=?", (self.match_id,)
            ).fetchone()["demo_file"]
            conn.close()
            self.assertIn("mirage", saved)
            self.assertTrue(os.listdir(demo_root))
        finally:
            import shutil

            shutil.rmtree(demo_root, ignore_errors=True)

    def test_unfinished_match_rejects_demo_upload(self):
        response = self.client.get(
            f"/admin/matches/{self.match_id}/import-demo", follow_redirects=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("比赛结束后才能上传 Demo", response.get_data(as_text=True))

    def test_completed_match_keeps_demo_update_entry_point(self):
        conn = get_db()
        conn.execute("UPDATE matches SET status='completed' WHERE id=?", (self.match_id,))
        conn.commit()
        conn.close()
        page = self.client.get(f"/admin/matches/{self.match_id}/stats")
        self.assertEqual(page.status_code, 200)
        self.assertIn("从 Demo 导入/更新数据", page.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
