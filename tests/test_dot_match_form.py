import os
import tempfile
import unittest

from app import app
from config import Config
from models import get_db, init_tables


class DotMatchFormTests(unittest.TestCase):
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
        conn.execute(
            "INSERT INTO events(name,slug,status) VALUES('复现赛事','repro-cup','upcoming')"
        )
        self.event_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO events(name,slug,status) VALUES('备用赛事','backup-cup','upcoming')"
        )
        self.other_event_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO teams(name,short_name) VALUES('队伍甲','A')")
        self.team1_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO teams(name,short_name) VALUES('队伍乙','B')")
        self.team2_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO matches(
                   event_id,team1_id,team2_id,team1_score,team2_score,
                   match_time,bo_format,stage,status,stream_url
               ) VALUES(?,?,?,0,0,'2026-10-30T19:30','BO1','原阶段','upcoming',?)""",
            (self.event_id, self.team1_id, self.team2_id, "https://live.bilibili.com/100"),
        )
        self.match_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()

        self.client = app.test_client()
        with self.client.session_transaction() as browser_session:
            browser_session["admin_id"] = 1
            browser_session["admin_username"] = "admin"
            browser_session["csrf_token"] = "dot-match-form-test"

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

    def test_add_match_form_still_uses_editable_defaults(self):
        response = self.client.get("/admin/matches/add")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('name="event_id" required', html)
        self.assertIn('name="side1_type" value="team" checked', html)

    def test_rejected_completion_keeps_upcoming_setup_fields_editable(self):
        response = self.client.post(
            f"/admin/matches/edit/{self.match_id}",
            data={
                "csrf_token": "dot-match-form-test",
                "event_id": str(self.other_event_id),
                "match_time": "2026-10-31T20:00",
                "bo_format": "BO1",
                "stage": "提交的新阶段",
                "status": "completed",
                "map1": "de_nuke",
                "map1_picked_by": "t1",
                "server_address": "connect 10.0.0.1:27015",
                "stream_url": "https://live.bilibili.com/200",
                "watch_name_0": "Bilibili",
                "watch_url_0": "https://live.bilibili.com/200",
                "side1_type": "team",
                "side1_id": str(self.team1_id),
                "side2_type": "team",
                "side2_id": str(self.team2_id),
            },
        )

        self.assertEqual(response.status_code, 400)
        html = response.get_data(as_text=True)
        self.assertIn("比分尚未达到该赛制的获胜条件", html)
        self.assertIn('name="stage" value="提交的新阶段"', html)
        self.assertIn('name="stream_url" value="https://live.bilibili.com/200"', html)
        self.assertIn('name="server_address" value="10.0.0.1:27015"', html)
        self.assertIn('name="map1"', html)
        self.assertRegex(html, r'<option value="de_nuke" selected>')
        self.assertRegex(html, r'<option value="t1" selected>队伍甲 选图</option>')
        self.assertIn('value="completed" selected', html)
        self.assertIn("https://live.bilibili.com/200", html)
        self.assertIn('id="pane-roster"', html)
        self.assertIn('name="side1_type" value="team" checked', html)
        self.assertIn('name="side2_type" value="team" checked', html)
        self.assertIn('data-status="completed" onclick="setMatchStatus', html)
        self.assertIn('name="event_id" required', html)
        self.assertNotIn('name="event_id" disabled', html)
        self.assertIn('value="2026-10-31T20:00"', html)
        self.assertIn(f'value="{self.other_event_id}" data-i18n-ignore selected', html)

        retry = self.client.post(
            f"/admin/matches/edit/{self.match_id}",
            data={
                "csrf_token": "dot-match-form-test",
                "event_id": str(self.other_event_id),
                "match_time": "2026-10-31T20:00",
                "bo_format": "BO1",
                "stage": "提交的新阶段",
                "status": "upcoming",
                "map1": "de_nuke",
                "map1_picked_by": "t1",
                "server_address": "10.0.0.1:27015",
                "stream_url": "https://live.bilibili.com/200",
                "watch_name_0": "Bilibili",
                "watch_url_0": "https://live.bilibili.com/200",
                "side1_type": "team",
                "side1_id": str(self.team1_id),
                "side2_type": "team",
                "side2_id": str(self.team2_id),
            },
        )
        self.assertEqual(retry.status_code, 302)
        conn = get_db()
        saved = conn.execute("SELECT * FROM matches WHERE id=?", (self.match_id,)).fetchone()
        self.assertEqual(saved["status"], "upcoming")
        self.assertEqual(saved["event_id"], self.other_event_id)
        self.assertEqual(saved["match_time"], "2026-10-31T20:00")
        self.assertEqual(saved["stage"], "提交的新阶段")
        self.assertEqual(saved["map1"], "de_nuke")
        self.assertEqual(saved["map1_picked_by"], "t1")
        self.assertEqual(saved["server_address"], "10.0.0.1:27015")
        self.assertEqual(saved["stream_url"], "https://live.bilibili.com/200")
        self.assertEqual(
            saved["watch_urls"], '[{"name": "Bilibili", "url": "https://live.bilibili.com/200"}]'
        )
        conn.close()


if __name__ == "__main__":
    unittest.main()
