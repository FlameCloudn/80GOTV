import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

from app import app
from config import Config
from models import get_db, init_tables
from utils.stats_calc import calculate_impact, calculate_rating


class BroadcastMapResultTests(unittest.TestCase):
    def setUp(self):
        handle, self.database_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.original_database = Config.DATABASE
        self.original_gsi_token = Config.GSI_TOKEN
        self.original_testing = app.config.get("TESTING")
        self.original_secure_cookie = app.config.get("SESSION_COOKIE_SECURE")
        Config.DATABASE = self.database_path
        Config.GSI_TOKEN = "gsi-test-secret"
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        init_tables()
        self.client = app.test_client()

        conn = get_db()
        self.team1_id = conn.execute(
            "INSERT INTO teams(name, short_name) VALUES('Golden Eight', 'G8')"
        ).lastrowid
        self.team2_id = conn.execute(
            "INSERT INTO teams(name, short_name) VALUES('Ultimate Eight', 'U8')"
        ).lastrowid
        self.player1_id = conn.execute(
            "INSERT INTO players(nickname, team_id, steam_id) VALUES('False Emperor', ?, '111')",
            (self.team1_id,),
        ).lastrowid
        self.player2_id = conn.execute(
            "INSERT INTO players(nickname, team_id, steam_id) VALUES('Aurora', ?, '222')",
            (self.team2_id,),
        ).lastrowid
        event_id = conn.execute(
            "INSERT INTO events(name, status) VALUES('Test Event', 'ongoing')"
        ).lastrowid
        self.match_id = conn.execute(
            """INSERT INTO matches(
                   event_id, team1_id, team2_id, match_time, status,
                   bo_format, map1, map2, map3
               ) VALUES(?, ?, ?, ?, 'live', 'BO3', 'Nuke', 'Mirage', 'Dust2')""",
            (
                event_id,
                self.team1_id,
                self.team2_id,
                datetime.now().isoformat(timespec="seconds"),
            ),
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
    def _player(steam_id, name, team_side, kills, deaths, damage):
        return {
            "steam_id": steam_id,
            "name": name,
            "team_side": team_side,
            "kills": kills,
            "deaths": deaths,
            "assists": 6,
            "damage": damage,
            "damageTaken": 1500,
            "roundsPlayed": 20,
            "headshots": 9,
            "kastRounds": 16,
            "firstKills": 4,
            "firstDeaths": 2,
            "multi1k": 7,
            "multi2k": 4,
            "multi3k": 1,
            "multi4k": 0,
            "multi5k": 0,
            "clutchesWon": 1,
            "clutch1v1": 1,
            "tradeKills": 3,
            "tradeDeaths": 2,
            "mvpCount": 4,
            "utilityDamage": 210,
            "bombPlants": 2,
            "bombDefuses": 1,
            "flashAssists": 3,
            "rwsBasic": 10.8,
            "tStats": {
                "kills": 11,
                "deaths": 6,
                "adr": 94.2,
                "rating": 1.31,
            },
            "ctStats": {
                "kills": kills - 11,
                "deaths": deaths - 6,
                "adr": 85.8,
                "rating": 1.18,
            },
        }

    def _payload(self):
        return {
            "map_name": "de_nuke",
            "team1_score": 13,
            "team2_score": 7,
            "series_complete": False,
            "players": [
                self._player("111", "GSI Alias", "team1", 20, 12, 1800),
                self._player("222", "Aurora", "team2", 15, 16, 1420),
            ],
        }

    def _post(self, payload=None, token="gsi-test-secret"):
        with (
            patch("routes.live_ingest.rate_limit", return_value=True),
            patch("services.demo_service.enrich_player_from_steam"),
        ):
            return self.client.post(
                f"/api/broadcast/matches/{self.match_id}/map-result",
                json=payload or self._payload(),
                headers={"X-80GOTV-Token": token},
            )

    def test_rejects_bad_token_before_database_work(self):
        response = self._post(token="wrong")
        self.assertEqual(response.status_code, 403)

    def test_rejects_unknown_map_and_invalid_team_side(self):
        payload = self._payload()
        payload["map_name"] = "Cache"
        self.assertEqual(self._post(payload).status_code, 409)

        payload = self._payload()
        payload["players"][0]["team_side"] = "CT"
        self.assertEqual(self._post(payload).status_code, 400)

    def test_saves_detailed_rating_and_retry_is_idempotent(self):
        first = self._post()
        second = self._post()
        self.assertEqual(first.status_code, 200, first.get_data(as_text=True))
        self.assertEqual(second.status_code, 200, second.get_data(as_text=True))
        self.assertEqual(first.get_json()["saved"], 2)

        expected_impact = calculate_impact(4, 2, 5, 1, 20)
        expected_rating, expected_kpr, expected_dpr = calculate_rating(
            20,
            12,
            20,
            adr=90,
            kast=80,
            impact=expected_impact,
        )
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM match_stats WHERE match_id=? ORDER BY player_id",
            (self.match_id,),
        ).fetchall()
        match = conn.execute(
            "SELECT map1_t1, map1_t2, team1_score, team2_score FROM matches WHERE id=?",
            (self.match_id,),
        ).fetchone()
        live = conn.execute(
            "SELECT live_state FROM live_match_data WHERE match_id=?",
            (self.match_id,),
        ).fetchone()
        conn.close()

        self.assertEqual(len(rows), 2)
        row = rows[0]
        self.assertEqual(row["player_id"], self.player1_id)
        self.assertEqual(row["match_team_side"], "t1")
        self.assertEqual(row["kills"], 20)
        self.assertEqual(row["assists"], 6)
        self.assertEqual(row["rounds_played"], 20)
        self.assertEqual(row["trade_kills"], 3)
        self.assertEqual(row["flash_assists"], 3)
        self.assertEqual(row["clutch_1v1"], 1)
        self.assertAlmostEqual(row["adr"], 90)
        self.assertAlmostEqual(row["kast"], 80)
        self.assertAlmostEqual(row["impact"], expected_impact)
        self.assertAlmostEqual(row["rating"], expected_rating)
        self.assertAlmostEqual(row["kpr"], expected_kpr)
        self.assertAlmostEqual(row["dpr"], expected_dpr)
        self.assertEqual(
            (match["map1_t1"], match["map1_t2"], match["team1_score"], match["team2_score"]),
            (13, 7, 1, 0),
        )
        latest = json.loads(live["live_state"])["latest_map_result"]
        self.assertEqual(latest["map_name"], "Nuke")
        self.assertEqual(latest["players"][0]["name"], "False Emperor")
        self.assertEqual(latest["players"][0]["rating"], expected_rating)


if __name__ == "__main__":
    unittest.main()
