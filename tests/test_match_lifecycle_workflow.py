import os
import tempfile
import unittest

from app import app
from config import Config
from models import get_db, init_tables
from services.match_service import supplement_temp_teams


class MatchLifecycleWorkflowTests(unittest.TestCase):
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
        self.user_id = conn.execute(
            """INSERT INTO users(username, password_hash, approval_status, is_bashizhong_student)
               VALUES('PredictionAudit', 'test-hash', 'approved', 0)"""
        ).lastrowid
        event_id = conn.execute("INSERT INTO events(name) VALUES('Prediction Cup')").lastrowid
        team1_id = conn.execute("INSERT INTO teams(name) VALUES('Alpha')").lastrowid
        team2_id = conn.execute("INSERT INTO teams(name) VALUES('Bravo')").lastrowid
        self.match_id = conn.execute(
            """INSERT INTO matches(event_id, team1_id, team2_id, status, match_time)
               VALUES(?, ?, ?, 'upcoming', datetime('now', 'localtime', '+2 hours'))""",
            (event_id, team1_id, team2_id),
        ).lastrowid
        conn.commit()
        conn.close()
        self.client = app.test_client()
        with self.client.session_transaction() as saved:
            saved["user_id"] = self.user_id
            saved["csrf_token"] = "prediction-audit"

    def tearDown(self):
        Config.DATABASE = self.original_database
        app.config.update(
            TESTING=self.original_testing, SESSION_COOKIE_SECURE=self.original_secure_cookie
        )
        os.remove(self.database_path)

    def _vote(self):
        response = self.client.post(
            f"/matches/{self.match_id}/vote",
            data={
                "csrf_token": "prediction-audit",
                "voted_for": "t1",
                "score1": "2",
                "score2": "1",
            },
        )
        self.assertTrue(response.get_json()["ok"])

    def _saved_vote(self):
        conn = get_db()
        try:
            return dict(
                conn.execute(
                    "SELECT * FROM match_votes WHERE match_id=?", (self.match_id,)
                ).fetchone()
            )
        finally:
            conn.close()

    def test_prediction_is_not_settled_during_live_match_and_completion_settles_once(self):
        self._vote()
        conn = get_db()
        conn.execute(
            "UPDATE matches SET status='live', team1_score=1, team2_score=0 WHERE id=?",
            (self.match_id,),
        )
        conn.commit()
        conn.close()
        for path in ("/predictions", "/api/front/predictions"):
            self.assertEqual(self.client.get(path).status_code, 200)
            self.assertEqual(
                (self._saved_vote()["scored"], self._saved_vote()["points_earned"]), (0, 0)
            )
        conn = get_db()
        conn.execute("UPDATE matches SET team1_score=2, team2_score=1 WHERE id=?", (self.match_id,))
        conn.commit()
        conn.close()
        with self.client.session_transaction() as saved:
            saved["admin_id"] = 1
        for _ in range(2):
            self.client.post(
                f"/admin/matches/{self.match_id}/complete", data={"csrf_token": "prediction-audit"}
            )
            self.assertEqual(
                (self._saved_vote()["scored"], self._saved_vote()["points_earned"]), (1, 8)
            )

    def test_status_fallback_honors_explicit_live_without_start_time(self):
        match = supplement_temp_teams({"status": "live", "match_time": None})
        self.assertEqual(match["effective_status"], "live")

    def test_reopen_revokes_old_prediction_points_and_new_result_is_settled(self):
        self._vote()
        conn = get_db()
        conn.execute("UPDATE matches SET team1_score=2, team2_score=1 WHERE id=?", (self.match_id,))
        conn.commit()
        conn.close()
        with self.client.session_transaction() as saved:
            saved["admin_id"] = 1
        self.client.post(
            f"/admin/matches/{self.match_id}/complete", data={"csrf_token": "prediction-audit"}
        )
        self.assertEqual(
            (self._saved_vote()["scored"], self._saved_vote()["points_earned"]), (1, 8)
        )
        self.client.post(
            f"/admin/matches/{self.match_id}/reopen", data={"csrf_token": "prediction-audit"}
        )
        self.assertEqual(
            (self._saved_vote()["scored"], self._saved_vote()["points_earned"]), (0, 0)
        )
        conn = get_db()
        conn.execute("UPDATE matches SET team1_score=1, team2_score=2 WHERE id=?", (self.match_id,))
        conn.commit()
        conn.close()
        for _ in range(2):
            self.client.post(
                f"/admin/matches/{self.match_id}/complete", data={"csrf_token": "prediction-audit"}
            )
            self.assertEqual(
                (self._saved_vote()["scored"], self._saved_vote()["points_earned"]), (1, 0)
            )

    def test_normal_account_cannot_change_admin_data(self):
        response = self.client.post(
            f"/admin/matches/{self.match_id}/complete", data={"csrf_token": "prediction-audit"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/admin/login")
        conn = get_db()
        self.assertEqual(
            conn.execute("SELECT status FROM matches WHERE id=?", (self.match_id,)).fetchone()[0],
            "upcoming",
        )
        conn.close()


if __name__ == "__main__":
    unittest.main()
