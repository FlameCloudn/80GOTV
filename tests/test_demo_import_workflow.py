import json
import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from app import app
from config import Config
from models import get_db, init_tables
from services.demo_service import insert_match_stat
from utils.demo_naming import build_demo_filename
from utils.demo_parser import match_map_slot


class DemoImportWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="audit-demo-")
        self.original_database = Config.DATABASE
        self.original_testing = app.config.get("TESTING")
        self.original_secure_cookie = app.config.get("SESSION_COOKIE_SECURE")
        Config.DATABASE = os.path.join(self.temp_dir.name, "audit.db")
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        init_tables()
        conn = get_db()
        event_id = conn.execute("INSERT INTO events(name) VALUES('Audit Cup')").lastrowid
        self.team1_id = conn.execute("INSERT INTO teams(name) VALUES('Alpha')").lastrowid
        team2_id = conn.execute("INSERT INTO teams(name) VALUES('Bravo')").lastrowid
        self.player1_id = conn.execute(
            "INSERT INTO players(nickname, steam_id, team_id) VALUES('Alpha Player', '111', ?)",
            (self.team1_id,),
        ).lastrowid
        conn.execute(
            "INSERT INTO players(nickname, steam_id, team_id) VALUES('Bravo Player', '222', ?)",
            (team2_id,),
        )
        self.match_id = conn.execute(
            """INSERT INTO matches(event_id, team1_id, team2_id, status, bo_format, map1, map2)
               VALUES(?, ?, ?, 'live', 'BO3', 'Mirage', 'Nuke')""",
            (event_id, self.team1_id, team2_id),
        ).lastrowid
        insert_match_stat(
            conn,
            self.match_id,
            self.player1_id,
            self.team1_id,
            "t1",
            {"kills": 4, "rounds_played": 20},
            "Mirage",
        )
        conn.commit()
        conn.close()
        self.client = app.test_client()
        with self.client.session_transaction() as saved:
            saved["admin_id"] = 1
            saved["csrf_token"] = "audit-demo-token"

    def tearDown(self):
        Config.DATABASE = self.original_database
        app.config.update(
            TESTING=self.original_testing, SESSION_COOKIE_SECURE=self.original_secure_cookie
        )
        self.temp_dir.cleanup()

    def _payload(self, map_name="de_mirage"):
        return json.dumps(
            {
                "info": {
                    "map_name": map_name,
                    "team_a_name": "Alpha",
                    "team_b_name": "Bravo",
                    "team_a_score": 13,
                    "team_b_score": 7,
                    "rounds_count": 20,
                },
                "players": [
                    {
                        "name": "Alpha Player",
                        "steam_id": "111",
                        "team_letter": "A",
                        "kills": 19,
                        "deaths": 9,
                        "rating": 1.23,
                        "rounds_played": 20,
                    },
                    {
                        "name": "Bravo Player",
                        "steam_id": "222",
                        "team_letter": "B",
                        "kills": 9,
                        "deaths": 19,
                        "rating": 0.7,
                        "rounds_played": 20,
                    },
                ],
            }
        )

    def _post(self, **data):
        return self.client.post(
            f"/admin/matches/{self.match_id}/import-demo",
            data={"csrf_token": "audit-demo-token", **data},
        )

    def _snapshot(self):
        conn = get_db()
        try:
            return (
                [dict(row) for row in conn.execute("SELECT * FROM match_stats ORDER BY id")],
                dict(conn.execute("SELECT * FROM matches WHERE id=?", (self.match_id,)).fetchone()),
            )
        finally:
            conn.close()

    def _messages(self):
        with self.client.session_transaction() as saved:
            return list(saved.get("_flashes", []))

    def test_unknown_map_never_falls_back_to_first_or_empty_slot(self):
        self.assertEqual(match_map_slot("de_inferno", ["Mirage", "Nuke"]), -1)
        self.assertEqual(match_map_slot("de_inferno", ["Mirage", None]), -1)
        self.assertEqual(match_map_slot("de_nuke", ["Mirage", "Nuke"]), 1)

    def test_mismatched_map_cannot_overwrite_existing_stats_or_scores(self):
        before = self._snapshot()
        response = self._post(
            step="import_single", map_slot=0, demo_data=self._payload("de_inferno")
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._snapshot(), before)
        self.assertTrue(
            any(category == "error" and "地图" in message for category, message in self._messages())
        )

    def test_batch_validation_failure_rolls_back_all_maps_and_reports_failure(self):
        before = self._snapshot()
        previews = [
            {"map_slot": 0, "demo_data": self._payload()},
            {
                "map_slot": 1,
                "demo_data": json.dumps({"info": {"map_name": "de_nuke"}, "players": []}),
            },
        ]
        self._post(step="import_all", all_demo_data=json.dumps(previews))
        self.assertEqual(self._snapshot(), before)
        self.assertTrue(any(category == "error" for category, _ in self._messages()))
        self.assertFalse(any(category == "success" for category, _ in self._messages()))

    def test_empty_batch_is_not_reported_as_success(self):
        before = self._snapshot()
        self._post(step="import_all", all_demo_data="[]")
        self.assertEqual(self._snapshot(), before)
        self.assertFalse(any(category == "success" for category, _ in self._messages()))
        self.assertTrue(any(category == "error" for category, _ in self._messages()))

    def test_player_creation_failure_cannot_silently_skip_a_player_and_commit_partial_stats(self):
        conn = get_db()
        conn.execute("""CREATE TRIGGER audit_refuse_new_user BEFORE INSERT ON users
                        BEGIN SELECT RAISE(ABORT, 'test write refused'); END""")
        conn.commit()
        conn.close()
        before = self._snapshot()
        payload = json.loads(self._payload())
        payload["players"][0].update(name="UnseenAuditPlayer", steam_id="333")
        self._post(step="import_single", map_slot=0, demo_data=json.dumps(payload))
        self.assertEqual(self._snapshot(), before)
        self.assertTrue(any(category == "error" for category, _ in self._messages()))
        self.assertFalse(any(category == "success" for category, _ in self._messages()))

    def test_more_than_five_players_per_team_is_not_silently_truncated(self):
        payload = json.loads(self._payload())
        conn = get_db()
        for index in range(5):
            name, steam_id = f"Extra Alpha {index}", str(400 + index)
            conn.execute(
                "INSERT INTO players(nickname, steam_id, team_id) VALUES(?, ?, ?)",
                (name, steam_id, self.team1_id),
            )
            payload["players"].append({**payload["players"][0], "name": name, "steam_id": steam_id})
        conn.commit()
        conn.close()
        before = self._snapshot()
        self._post(step="import_single", map_slot=0, demo_data=json.dumps(payload))
        self.assertEqual(self._snapshot(), before)
        self.assertTrue(any(category == "error" for category, _ in self._messages()))
        self.assertFalse(any(category == "success" for category, _ in self._messages()))

    def test_username_collision_retries_without_hiding_other_write_failures(self):
        conn = get_db()
        conn.execute(
            "INSERT INTO users(username, password_hash, steam_id64) VALUES(?, ?, ?)",
            ("NewAuditPlayer", "not-a-login-password", "444"),
        )
        conn.commit()
        conn.close()
        payload = json.loads(self._payload())
        payload["players"][0].update(name="NewAuditPlayer", steam_id="333")
        with patch("services.demo_service.enrich_player_from_steam", return_value=False):
            self._post(step="import_single", map_slot=0, demo_data=json.dumps(payload))
        stats, match = self._snapshot()
        self.assertEqual(len([row for row in stats if row["data_status"] != "superseded"]), 2)
        self.assertEqual((match["map1_t1"], match["map1_t2"]), (13, 7))
        conn = get_db()
        try:
            created = conn.execute("SELECT username FROM users WHERE steam_id64='333'").fetchone()
            self.assertIsNotNone(created)
            self.assertNotEqual(created["username"], "NewAuditPlayer")
        finally:
            conn.close()
        self.assertTrue(any(category == "success" for category, _ in self._messages()))

    def test_valid_import_and_repeat_keep_correct_team_scores_and_one_final_row_per_player(self):
        for expected_version in (1, 2):
            self.assertEqual(
                self._post(step="import_single", map_slot=0, demo_data=self._payload()).status_code,
                302,
            )
            stats, match = self._snapshot()
            final = [row for row in stats if row["data_status"] != "superseded"]
            self.assertEqual(len(final), 2)
            alpha = next(row for row in final if row["player_id"] == self.player1_id)
            self.assertEqual(alpha["kills"], 19)
            self.assertEqual(alpha["match_team_side"], "t1")
            self.assertEqual(alpha["team_id"], self.team1_id)
            self.assertEqual(alpha["map_name"], "Mirage")
            self.assertGreaterEqual(alpha["data_version"], expected_version)
            self.assertEqual((match["map1_t1"], match["map1_t2"]), (13, 7))
            self.assertEqual((match["team1_score"], match["team2_score"]), (1, 0))

    def test_file_save_failure_does_not_offer_a_successful_import_preview(self):
        payload = json.loads(self._payload())
        info = {**payload["info"], "source": "test-analyzer", "rounds_count": 20}
        # Only the external Demo analyzer is simulated; preview validation and file saving are real.
        with (
            patch("services.demo_service.run_analysis", return_value={}),
            patch("services.demo_service.parse_player_stats", return_value=payload["players"]),
            patch("services.demo_service.get_match_info", return_value=info),
            patch("services.demo_service.build_demo_performance_payload", return_value={}),
            patch("blueprints.admin_matches.DEMOS_DIR", self.temp_dir.name),
            patch(
                "blueprints.admin_matches.shutil.copy2",
                side_effect=OSError("test disk unavailable"),
            ),
        ):
            response = self._post(step="analyze", demo_file_0=(BytesIO(b"test demo"), "test.dem"))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('name="step" value="import_all"', response.get_data(as_text=True))
        self.assertIsNone(self._snapshot()[1]["demo_file"])

    def test_demo_download_requires_an_approved_account(self):
        filename = "audit.dem"
        Path(self.temp_dir.name, filename).write_bytes(b"local test demo")
        conn = get_db()
        conn.execute(
            "UPDATE matches SET demo_file=? WHERE id=?", (json.dumps([filename]), self.match_id)
        )
        conn.commit()
        conn.close()
        anonymous = app.test_client()
        with patch("routes.match_assets.DEMOS_DIR", self.temp_dir.name):
            response = anonymous.get(f"/matches/{self.match_id}/download-demo")
        try:
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.headers["Location"].startswith("/login"))
        finally:
            response.close()

    def test_failed_upload_commit_preserves_existing_demo_bytes_and_reference(self):
        filename = build_demo_filename(self.match_id, 0, None, "Mirage")
        original_file = Path(self.temp_dir.name, filename)
        original_file.write_bytes(b"previous saved demo")
        conn = get_db()
        conn.execute(
            "UPDATE matches SET demo_file=? WHERE id=?", (json.dumps([filename]), self.match_id)
        )
        conn.commit()
        conn.close()

        class FailedCommit:
            def __init__(self):
                self.connection = get_db()

            def __getattr__(self, name):
                return getattr(self.connection, name)

            def commit(self):
                raise OSError("test commit unavailable")

        payload = json.loads(self._payload())
        info = {**payload["info"], "source": "test-analyzer", "rounds_count": 20}
        with (
            patch("services.demo_service.run_analysis", return_value={}),
            patch("services.demo_service.parse_player_stats", return_value=payload["players"]),
            patch("services.demo_service.get_match_info", return_value=info),
            patch("services.demo_service.build_demo_performance_payload", return_value={}),
            patch("blueprints.admin_matches.DEMOS_DIR", self.temp_dir.name),
            patch("blueprints.admin_matches.get_db", side_effect=FailedCommit),
        ):
            response = self._post(
                step="analyze", demo_file_0=(BytesIO(b"replacement demo"), "replacement.dem")
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(original_file.read_bytes(), b"previous saved demo")
        self.assertEqual(json.loads(self._snapshot()[1]["demo_file"]), [filename])
        self.assertNotIn('name="step" value="import_all"', response.get_data(as_text=True))

    def test_admin_can_download_saved_demo_without_an_unrelated_user_account(self):
        filename = "admin-audit.dem"
        Path(self.temp_dir.name, filename).write_bytes(b"local test demo")
        conn = get_db()
        conn.execute(
            "UPDATE matches SET demo_file=? WHERE id=?", (json.dumps([filename]), self.match_id)
        )
        conn.commit()
        conn.close()
        with patch("routes.match_assets.DEMOS_DIR", self.temp_dir.name):
            response = self.client.get(f"/matches/{self.match_id}/download-demo")
        try:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b"local test demo")
        finally:
            response.close()


if __name__ == "__main__":
    unittest.main()
