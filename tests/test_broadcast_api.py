import json
import os
import tempfile
import unittest

from app import app
from config import Config
from models import get_db, init_tables


class BroadcastApiTests(unittest.TestCase):
    def setUp(self):
        handle, self.database_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.original_database = Config.DATABASE
        self.original_testing = app.config.get("TESTING")
        self.original_secure_cookie = app.config.get("SESSION_COOKIE_SECURE")
        Config.DATABASE = self.database_path
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        init_tables()
        self.client = app.test_client()

        conn = get_db()
        event_id = conn.execute(
            """INSERT INTO events(name, short_name, start_date, end_date, status)
               VALUES('2026 Summer 80 Major', '80 MAJOR', '2026-07-01', '2026-08-01', 'ongoing')"""
        ).lastrowid
        team1_id = conn.execute(
            "INSERT INTO teams(name, short_name, logo) VALUES('Team Eighty', '80', 'team80.png')"
        ).lastrowid
        team2_id = conn.execute(
            "INSERT INTO teams(name, short_name) VALUES('Summer Five', 'SF')"
        ).lastrowid
        self.match_id = conn.execute(
            """INSERT INTO matches(
                   event_id, team1_id, team2_id, match_time, bo_format, stage, status,
                   map1, map1_picked_by, map2, map2_picked_by, map3
               ) VALUES(?, ?, ?, '2026-07-16T18:00', 'BO3', 'Group A', 'live',
                        'de_mirage', 't1', 'de_inferno', 't2', 'de_nuke')""",
            (event_id, team1_id, team2_id),
        ).lastrowid
        player_id = conn.execute(
            """INSERT INTO players(nickname, group_username_override, team_id, steam_id, avatar)
               VALUES('FlameCloud_', 'FlameCloud', ?, '76561198000000001', 'flame.png')""",
            (team1_id,),
        ).lastrowid
        self.reserve_player_id = conn.execute(
            """INSERT INTO players(
                   nickname, group_username_override, steam_id, avatar,
                   is_bashizhong_student
               ) VALUES('ReserveOne', 'Reserve Group', '76561198000000002',
                        'reserve.png', 1)"""
        ).lastrowid
        reserve_user_id = conn.execute(
            """INSERT INTO users(
                   username, password_hash, steam_id64, approval_status,
                   group_username, avatar, is_bashizhong_student
               ) VALUES('ReserveOne', 'test-hash', '76561198000000002',
                        'approved', 'Reserve Group', 'reserve.png', 1)"""
        ).lastrowid
        conn.execute(
            """INSERT INTO event_individual_registrations(
                   event_id, user_id, player_name, steam_id, assignment_status
               ) VALUES(?, ?, 'ReserveOne', '76561198000000002', 'reserve')""",
            (event_id, reserve_user_id),
        )
        registration_id = conn.execute(
            """INSERT INTO event_registrations(
                   event_id, team_name, team_logo, creator_user_id, status
               ) VALUES(?, 'Registered Five', 'five.png', ?, 'pending')""",
            (event_id, reserve_user_id),
        ).lastrowid
        conn.execute(
            """INSERT INTO event_registration_slots(
                   registration_id, slot_index, user_id, player_name, steam_id
               ) VALUES(?, 0, ?, 'RegisteredNickname', '76561198000000002')""",
            (registration_id, reserve_user_id),
        )
        conn.execute(
            """UPDATE matches
               SET team1_players=?, bp_state=?,
                   decider_knife_winner='t1', decider_start_side='CT'
               WHERE id=?""",
            (
                json.dumps([player_id]),
                json.dumps(
                    {
                        "status": "completed",
                        "bans": ["Dust2"],
                        "picks": [{"map": "Mirage", "picked_by": "t1", "side": "CT"}],
                    }
                ),
                self.match_id,
            ),
        )
        conn.commit()
        conn.close()

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

    def test_current_match_returns_public_hud_metadata(self):
        response = self.client.get(
            "/api/broadcast/current", headers={"Origin": "http://localhost:1349"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "*")
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["match"]["id"], self.match_id)
        self.assertEqual(payload["match"]["event"]["short_name"], "80 MAJOR")
        self.assertEqual(payload["match"]["team1"]["short_name"], "80")
        self.assertEqual(payload["match"]["maps"][0]["name"], "de_mirage")
        self.assertEqual(payload["match"]["team1"]["logo"], "/static/uploads/team80.png")
        self.assertEqual(payload["match"]["team1"]["players"][0]["nickname"], "FlameCloud_")
        self.assertEqual(
            payload["match"]["team1"]["players"][0]["avatar"], "/static/avatars/flame.png"
        )
        self.assertEqual(payload["match"]["substitute_count"], 1)
        self.assertEqual(payload["match"]["substitutes"][0]["id"], self.reserve_player_id)
        self.assertEqual(payload["match"]["substitutes"][0]["nickname"], "ReserveOne")
        self.assertEqual(payload["match"]["substitutes"][0]["role"], "substitute")
        self.assertEqual(payload["match"]["bp"]["bans"], ["Dust2"])
        self.assertEqual(payload["match"]["decider"]["knife_winner"], "t1")
        self.assertEqual(payload["match"]["decider"]["start_side"], "CT")
        self.assertEqual(payload["match"]["live_api"], f"/api/live/{self.match_id}")
        self.assertEqual(
            payload["match"]["live_ingest_api"],
            f"/api/broadcast/matches/{self.match_id}/live",
        )

    def test_manager_can_list_matches(self):
        response = self.client.get("/api/broadcast/matches")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["matches"][0]["id"], self.match_id)

    def test_manager_can_load_event_rosters_and_substitutes(self):
        response = self.client.get("/api/broadcast/events")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        roster = payload["events"][0]
        self.assertEqual(roster["team_count"], 1)
        self.assertEqual(roster["teams"][0]["name"], "Registered Five")
        self.assertEqual(roster["teams"][0]["logo"], "/static/uploads/team_logos/five.png")
        self.assertEqual(roster["teams"][0]["players"][0]["role"], "captain")
        self.assertEqual(roster["teams"][0]["players"][0]["nickname"], "RegisteredNickname")
        self.assertEqual(roster["substitute_count"], 1)
        self.assertEqual(roster["substitutes"][0]["nickname"], "ReserveOne")

        detail = self.client.get(f"/api/broadcast/events/{roster['id']}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.get_json()["event"]["teams"][0]["short_name"], "RF")

    def test_match_can_be_selected_by_id(self):
        response = self.client.get(f"/api/broadcast/matches/{self.match_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["match"]["stage"], "Group A")

        missing = self.client.get("/api/broadcast/matches/9999")
        self.assertEqual(missing.status_code, 404)
        self.assertFalse(missing.get_json()["ok"])


if __name__ == "__main__":
    unittest.main()
