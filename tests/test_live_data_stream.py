import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

from app import app
from config import Config
from models import get_db, init_tables
from services.live_service import _round_win_reason_code


class LiveDataStreamTests(unittest.TestCase):
    def setUp(self):
        handle, self.database_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.original_database = Config.DATABASE
        self.original_gsi_token = Config.GSI_TOKEN
        self.original_testing = app.config.get("TESTING")
        self.original_secure_cookie = app.config.get("SESSION_COOKIE_SECURE")
        Config.DATABASE = self.database_path
        Config.GSI_TOKEN = "stream-secret"
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        init_tables()
        self.client = app.test_client()

        conn = get_db()
        team1_id = conn.execute(
            "INSERT INTO teams(name, short_name) VALUES('Golden Eight', 'G8')"
        ).lastrowid
        team2_id = conn.execute(
            "INSERT INTO teams(name, short_name) VALUES('Ultimate Eight', 'U8')"
        ).lastrowid
        conn.execute(
            "INSERT INTO players(nickname, team_id, steam_id) VALUES('False Emperor', ?, '111')",
            (team1_id,),
        )
        conn.execute(
            "INSERT INTO players(nickname, team_id, steam_id) VALUES('Aurora', ?, '222')",
            (team2_id,),
        )
        event_id = conn.execute(
            "INSERT INTO events(name, status) VALUES('Live Event', 'ongoing')"
        ).lastrowid
        self.match_id = conn.execute(
            """INSERT INTO matches(event_id, team1_id, team2_id, match_time, status, map1, map2)
               VALUES(?, ?, ?, ?, 'live', 'de_nuke', 'de_mirage')""",
            (event_id, team1_id, team2_id, datetime.now().isoformat(timespec="seconds")),
        ).lastrowid
        conn.commit()
        conn.close()

    def tearDown(self):
        Config.DATABASE = self.original_database
        Config.GSI_TOKEN = self.original_gsi_token
        app.config.update(
            TESTING=self.original_testing,
            SESSION_COOKIE_SECURE=self.original_secure_cookie,
        )
        try:
            os.remove(self.database_path)
        except OSError:
            pass

    @staticmethod
    def _player(name, team, kills, deaths, health):
        return {
            "name": name,
            "team": team,
            "state": {
                "health": health,
                "armor": 80,
                "helmet": True,
                "money": 4200,
            },
            "match_stats": {
                "kills": kills,
                "assists": 2,
                "deaths": deaths,
                "damage": 900,
            },
            "weapons": {"weapon_0": {"name": "weapon_ak47", "type": "Rifle", "state": "active"}},
        }

    def _payload(self, win_team=""):
        payload = {
            "map": {
                "name": "de_nuke",
                "mode": "competitive",
                "phase": "live",
                "round": 12,
                "team_ct": {
                    "name": "Ultimate Eight",
                    "score": 5,
                    "timeouts_remaining": 2,
                },
                "team_t": {
                    "name": "Golden Eight",
                    "score": 7,
                    "timeouts_remaining": 1,
                },
                "round_wins": {"12": "t_win_bomb"} if win_team else {},
            },
            "allplayers": {
                "111": self._player("Wrong GSI Name", "T", 14, 7, 100),
                "222": self._player("Aurora", "CT", 10, 10, 0),
            },
            "bomb": {"state": "planted"},
            "round": {"phase": "live", "win_team": win_team},
            "previously": {"round": {}, "bomb": {}},
            "phase_countdowns": {"phase": "timeout_t", "phase_ends_in": "24.4"},
            "_80gotv": {"team_ct": "team2", "team_t": "team1"},
        }
        return payload

    def _post(self, payload):
        with patch("routes.live_ingest.rate_limit", return_value=True):
            return self.client.post(
                f"/api/broadcast/matches/{self.match_id}/live",
                json=payload,
                headers={"X-80GOTV-Token": Config.GSI_TOKEN},
            )

    def test_live_api_keeps_team_identity_after_side_switch(self):
        response = self._post(self._payload())
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))

        live = self.client.get(f"/api/live/{self.match_id}").get_json()
        self.assertTrue(live["ok"])
        self.assertEqual(live["team1"]["name"], "Golden Eight")
        self.assertEqual(live["team1"]["side"], "T")
        self.assertEqual(live["team1"]["score"], 7)
        self.assertEqual(live["team2"]["name"], "Ultimate Eight")
        self.assertEqual(live["team2"]["side"], "CT")
        self.assertEqual(live["team2"]["score"], 5)
        self.assertEqual(live["players_t1"][0]["name"], "False Emperor")
        self.assertEqual(live["players_t2"][0]["name"], "Aurora")
        self.assertEqual(live["timer"], "0:25")
        self.assertEqual(live["round"], 13)
        self.assertTrue(live["paused"])
        self.assertEqual(live["pause_type"], "tactical")

        html = self.client.get(f"/matches/{self.match_id}/live").get_data(as_text=True)
        self.assertIn("战术暂停", html)
        self.assertIn("技术暂停", html)

    def test_round_history_uses_match_team_and_bomb_icon_reason(self):
        self.assertEqual(self._post(self._payload()).status_code, 200)
        finished = self._payload(win_team="T")
        finished["previously"]["round"] = {"phase": "live", "win_team": "T"}
        self.assertEqual(self._post(finished).status_code, 200)

        conn = get_db()
        row = conn.execute(
            "SELECT live_state FROM live_match_data WHERE match_id=?",
            (self.match_id,),
        ).fetchone()
        conn.close()
        history = json.loads(row["live_state"])["round_history"]
        self.assertEqual(history[-1]["winner"], "t1")
        self.assertEqual(history[-1]["side"], "t")
        self.assertEqual(history[-1]["reason_code"], "bomb_exploded")

    def test_first_round_is_recorded_as_round_one(self):
        first_round = self._payload(win_team="CT")
        first_round["map"]["round"] = 0
        first_round["map"]["round_wins"] = {"1": "ct_win_elimination"}
        first_round["previously"]["round"] = {"phase": "live", "win_team": "CT"}
        self.assertEqual(self._post(first_round).status_code, 200)

        conn = get_db()
        row = conn.execute(
            "SELECT live_state FROM live_match_data WHERE match_id=?",
            (self.match_id,),
        ).fetchone()
        conn.close()
        history = json.loads(row["live_state"])["round_history"]
        self.assertEqual(history[-1]["round"], 1)
        self.assertEqual(history[-1]["round_number"], 1)

    def test_app_round_event_infers_winner_from_side_mapping(self):
        payload = self._payload()
        payload["_80gotv"]["round_events"] = [
            {"id": "round-1-t", "round_number": 1, "winner": "", "winner_side": "T"}
        ]
        self.assertEqual(self._post(payload).status_code, 200)

        live = self.client.get(f"/api/live/{self.match_id}").get_json()
        self.assertEqual(live["latest_round_result"]["winner"], "t1")
        self.assertEqual(live["latest_round_result"]["round_number"], 1)

        html = self.client.get(f"/matches/{self.match_id}/live").get_data(as_text=True)
        self.assertIn("bomb_exploded.svg", html)
        self.assertIn("bomb_defused.svg", html)
        self.assertIn("time_expired", html)
        self.assertIn("ct_win.svg", html)
        self.assertIn("t_win.svg", html)
        self.assertIn("['ct', 't'].forEach", html)
        self.assertIn("round-side-label", html)
        self.assertIn("roundNumber < 24", html)
        self.assertNotIn("overflow-x:auto", html)
        self.assertIn("grid-template-rows:repeat(2,21px)", html)
        self.assertIn("grid-template-columns:repeat(24,minmax(0,1fr))", html)
        self.assertIn("roundIndex < 24", html)

    def test_overtime_rounds_are_not_added_to_round_history(self):
        regulation = self._payload(win_team="T")
        regulation["previously"]["round"] = {"phase": "live", "win_team": "T"}
        self.assertEqual(self._post(regulation).status_code, 200)

        overtime = self._payload(win_team="CT")
        overtime["map"]["round"] = 25
        overtime["map"]["round_wins"] = {"25": "ct_win_elimination"}
        overtime["previously"]["round"] = {"phase": "live", "win_team": "CT"}
        self.assertEqual(self._post(overtime).status_code, 200)

        conn = get_db()
        row = conn.execute(
            "SELECT live_state FROM live_match_data WHERE match_id=?",
            (self.match_id,),
        ).fetchone()
        conn.close()
        history = json.loads(row["live_state"])["round_history"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["round"], 12)
        overtime_history = json.loads(row["live_state"])["overtime_history"]
        self.assertEqual(len(overtime_history), 1)
        self.assertEqual(overtime_history[0]["round"], 25)

        live = self.client.get(f"/api/live/{self.match_id}").get_json()
        self.assertEqual(live["round_history"][-1]["round"], 12)
        self.assertEqual(live["overtime_history"][-1]["round"], 25)

    def test_new_map_clears_previous_map_live_events(self):
        self.assertEqual(self._post(self._payload()).status_code, 200)

        next_map = self._payload()
        next_map["map"]["name"] = "de_mirage"
        next_map["map"]["round"] = 0
        next_map["map"]["round_wins"] = {}
        next_map["bomb"] = {"state": "carried"}
        self.assertEqual(self._post(next_map).status_code, 200)

        conn = get_db()
        row = conn.execute(
            "SELECT live_state FROM live_match_data WHERE match_id=?",
            (self.match_id,),
        ).fetchone()
        conn.close()
        state = json.loads(row["live_state"])
        self.assertEqual(state["gsi"]["map"]["name"], "de_mirage")
        self.assertEqual(state.get("round_history"), [])
        self.assertEqual(state.get("kill_markers"), [])
        self.assertEqual(state.get("kill_events"), [])
        self.assertEqual(state.get("bomb_events"), [])

    def test_every_round_win_code_selects_the_correct_icon_reason(self):
        cases = {
            "ct_win_elimination": "elimination",
            "t_win_elimination": "elimination",
            "ct_win_defuse": "bomb_defused",
            "t_win_bomb": "bomb_exploded",
            "ct_win_time": "time_expired",
        }
        for game_code, expected in cases.items():
            with self.subTest(game_code=game_code):
                payload = self._payload()
                payload["map"]["round_wins"] = {"12": game_code}
                winner = "T" if game_code.startswith("t_") else "CT"
                self.assertEqual(_round_win_reason_code(payload, {}, winner), expected)


if __name__ == "__main__":
    unittest.main()
