import json
import unittest
from unittest.mock import patch

from app import app
from models import get_db
from services.performance_service import refresh_player_performance
from tests.test_refactor_stats_consistency import StatsDatabaseCase, add_stat


class AdminRouteRollbackTests(StatsDatabaseCase):
    def setUp(self):
        super().setUp()
        self.original_testing = app.config.get("TESTING")
        self.original_secure_cookie = app.config.get("SESSION_COOKIE_SECURE")
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self.conn.execute(
            "INSERT OR IGNORE INTO admins(id, username, password_hash) VALUES(1, 'rollback-test', 'x')"
        )
        self.conn.commit()
        self.client = app.test_client()
        with self.client.session_transaction() as browser_session:
            browser_session["admin_id"] = 1
            browser_session["admin_username"] = "rollback-test"
            browser_session["csrf_token"] = "rollback-test-token"

    def tearDown(self):
        app.config.update(
            TESTING=self.original_testing,
            SESSION_COOKIE_SECURE=self.original_secure_cookie,
        )
        super().tearDown()

    def _fresh_rows(self, sql, params=()):
        conn = get_db()
        try:
            return [tuple(row) for row in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    def test_demo_import_route_rolls_back_all_changes_after_late_failure(self):
        from services import demo_service

        teammate_id = self.conn.execute(
            "INSERT INTO players(nickname, steam_id, team_id) VALUES('Alpha Player', '222', ?)",
            (self.team1,),
        ).lastrowid
        self.conn.execute(
            """UPDATE matches SET status='live', map1_t1=11, map1_t2=10,
                   map_halves=?, team1_players=?, team2_players=? WHERE id=?""",
            (
                json.dumps({"0": {"opening_ct_team": "t1"}}),
                json.dumps([teammate_id]),
                "[]",
                self.match_id,
            ),
        )
        add_stat(
            self.conn,
            self.match_id,
            self.player_id,
            self.team2,
            "Mirage",
            kills=5,
            data_status="superseded",
            data_version=3,
        )
        add_stat(
            self.conn,
            self.match_id,
            self.player_id,
            self.team2,
            "Mirage",
            kills=12,
            data_status="final",
            data_version=4,
        )
        self.conn.execute(
            """INSERT INTO match_kill_events(
                   match_id, map_name, round_number, tick, killer_player_id, victim_player_id,
                   killer_steam_id, victim_steam_id, killer_name, victim_name
               ) VALUES(?, 'Mirage', 1, 100, ?, ?, '111', '222', 'Audit Player', 'Alpha Player')""",
            (self.match_id, self.player_id, teammate_id),
        )
        self.conn.execute(
            "INSERT INTO live_match_data(match_id, live_state) VALUES(?, ?)",
            (self.match_id, json.dumps({"unconfirmed_map_slots": [0, 1], "marker": "keep"})),
        )
        refresh_player_performance(self.conn, [self.player_id])
        self.conn.commit()

        demo_data = {
            "info": {
                "map_name": "Mirage",
                "team_a_name": "Alpha",
                "team_b_name": "Bravo",
                "team_a_score": 13,
                "team_b_score": 7,
                "halftime": {"h1_a": 8, "h1_b": 4, "h2_a": 5, "h2_b": 3},
            },
            "players": [
                {
                    "name": "Alpha Player",
                    "steam_id": "222",
                    "team_letter": "A",
                    "kills": 10,
                    "deaths": 8,
                    "assists": 2,
                    "rating": 1.1,
                    "rounds_played": 20,
                },
                {
                    "name": "Audit Player",
                    "steam_id": "111",
                    "team_letter": "B",
                    "kills": 12,
                    "deaths": 9,
                    "assists": 3,
                    "rating": 1.2,
                    "rounds_played": 20,
                },
            ],
            "performance_data": {
                "kill_events": [
                    {
                        "round_number": 2,
                        "tick": 250,
                        "killer_steam_id": "111",
                        "victim_steam_id": "222",
                        "killer_name": "Audit Player",
                        "victim_name": "Alpha Player",
                    }
                ],
                "flash_metrics": [],
            },
        }

        before = {
            "stats": self._fresh_rows(
                """SELECT id, player_id, kills, data_status, data_version
                   FROM match_stats WHERE match_id=? ORDER BY id""",
                (self.match_id,),
            ),
            "match": self._fresh_rows(
                """SELECT team1_score, team2_score, map1_t1, map1_t2, map_halves,
                          team1_players, team2_players FROM matches WHERE id=?""",
                (self.match_id,),
            ),
            "events": self._fresh_rows(
                """SELECT id, round_number, tick, killer_player_id, victim_player_id
                   FROM match_kill_events WHERE match_id=? ORDER BY id""",
                (self.match_id,),
            ),
            "aliases": self._fresh_rows(
                "SELECT player_id, nickname, source FROM player_nickname_history ORDER BY id"
            ),
            "live": self._fresh_rows(
                "SELECT live_state FROM live_match_data WHERE match_id=?", (self.match_id,)
            ),
            "summary": self._fresh_rows(
                """SELECT player_id, total_kills, total_deaths FROM player_performance_summary
                   WHERE player_id IN (?, ?) ORDER BY player_id""",
                (self.player_id, teammate_id),
            ),
        }

        original_refresh = demo_service.refresh_player_performance

        def refresh_then_fail(conn, player_ids=None):
            original_refresh(conn, player_ids)
            raise RuntimeError("测试注入的导入中途故障")

        with patch(
            "services.demo_service.refresh_player_performance", side_effect=refresh_then_fail
        ):
            response = self.client.post(
                f"/admin/matches/{self.match_id}/import-demo",
                data={
                    "csrf_token": "rollback-test-token",
                    "step": "import_single",
                    "map_slot": "0",
                    "demo_data": json.dumps(demo_data),
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self._fresh_rows(
                """SELECT id, player_id, kills, data_status, data_version
                   FROM match_stats WHERE match_id=? ORDER BY id""",
                (self.match_id,),
            ),
            before["stats"],
        )
        self.assertEqual(
            self._fresh_rows(
                """SELECT team1_score, team2_score, map1_t1, map1_t2, map_halves,
                          team1_players, team2_players FROM matches WHERE id=?""",
                (self.match_id,),
            ),
            before["match"],
        )
        self.assertEqual(
            self._fresh_rows(
                """SELECT id, round_number, tick, killer_player_id, victim_player_id
                   FROM match_kill_events WHERE match_id=? ORDER BY id""",
                (self.match_id,),
            ),
            before["events"],
        )
        self.assertEqual(
            self._fresh_rows(
                "SELECT player_id, nickname, source FROM player_nickname_history ORDER BY id"
            ),
            before["aliases"],
        )
        self.assertEqual(
            self._fresh_rows(
                "SELECT live_state FROM live_match_data WHERE match_id=?", (self.match_id,)
            ),
            before["live"],
        )
        self.assertEqual(
            self._fresh_rows(
                """SELECT player_id, total_kills, total_deaths FROM player_performance_summary
                   WHERE player_id IN (?, ?) ORDER BY player_id""",
                (self.player_id, teammate_id),
            ),
            before["summary"],
        )

    def test_player_merge_route_rolls_back_all_changes_after_late_failure(self):
        import services.player_service as player_service

        target_id = self.conn.execute(
            "INSERT INTO players(nickname, steam_id) VALUES('Retained Player', '222')"
        ).lastrowid
        self.conn.execute(
            "UPDATE matches SET team1_players=?, team2_players=? WHERE id=?",
            (json.dumps([self.player_id]), "[]", self.match_id),
        )
        add_stat(
            self.conn,
            self.match_id,
            self.player_id,
            self.team2,
            "Mirage",
            kills=8,
            data_status="final",
            data_version=2,
        )
        add_stat(
            self.conn,
            self.match_id,
            self.player_id,
            self.team2,
            "Nuke",
            kills=4,
            data_status="superseded",
            data_version=1,
        )
        add_stat(
            self.conn,
            self.match_id,
            target_id,
            self.team1,
            "Mirage",
            kills=10,
            data_status="final",
            data_version=3,
        )
        self.conn.execute(
            "INSERT INTO yearly_top_players(year, rank, player_id) VALUES(2026, 1, ?)",
            (self.player_id,),
        )
        self.conn.execute(
            "INSERT INTO player_medals(player_id, type, event_id, match_id) VALUES(?, 'MVP', ?, ?)",
            (self.player_id, self.event_id, self.match_id),
        )
        self.conn.execute(
            "INSERT INTO player_nickname_history(player_id, nickname, source) VALUES(?, 'Old Alias', 'demo')",
            (self.player_id,),
        )
        self.conn.execute(
            """INSERT INTO match_kill_events(
                   match_id, map_name, round_number, tick, killer_player_id, victim_player_id,
                   killer_steam_id, victim_steam_id, killer_name, victim_name
               ) VALUES(?, 'Mirage', 1, 100, ?, ?, '111', '222', 'Audit Player', 'Retained Player')""",
            (self.match_id, self.player_id, target_id),
        )
        refresh_player_performance(self.conn, [self.player_id, target_id])
        self.conn.commit()

        player_ids = (self.player_id, target_id)
        before = {
            "players": self._fresh_rows(
                """SELECT id, nickname, steam_id, team_id FROM players
                   WHERE id IN (?, ?) ORDER BY id""",
                player_ids,
            ),
            "stats": self._fresh_rows(
                """SELECT id, player_id, kills, data_status, data_version FROM match_stats
                   WHERE player_id IN (?, ?) ORDER BY id""",
                player_ids,
            ),
            "roster": self._fresh_rows(
                "SELECT team1_players, team2_players FROM matches WHERE id=?", (self.match_id,)
            ),
            "rankings": self._fresh_rows(
                "SELECT year, rank, player_id FROM yearly_top_players ORDER BY year, rank"
            ),
            "medals": self._fresh_rows(
                "SELECT player_id, type, event_id, match_id FROM player_medals ORDER BY id"
            ),
            "aliases": self._fresh_rows(
                "SELECT player_id, nickname, source FROM player_nickname_history ORDER BY id"
            ),
            "events": self._fresh_rows(
                """SELECT id, killer_player_id, victim_player_id, assister_player_id
                   FROM match_kill_events WHERE match_id=? ORDER BY id""",
                (self.match_id,),
            ),
            "summary": self._fresh_rows(
                """SELECT player_id, total_kills, total_deaths FROM player_performance_summary
                   WHERE player_id IN (?, ?) ORDER BY player_id""",
                player_ids,
            ),
        }

        original_refresh = player_service.refresh_player_performance

        def refresh_then_fail(conn, player_ids=None):
            original_refresh(conn, player_ids)
            raise RuntimeError("测试注入的合并中途故障")

        with patch(
            "services.player_service.refresh_player_performance", side_effect=refresh_then_fail
        ):
            response = self.client.post(
                "/admin/nicknames/merge",
                data={
                    "csrf_token": "rollback-test-token",
                    "source_id": str(self.player_id),
                    "target_id": str(target_id),
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self._fresh_rows(
                """SELECT id, nickname, steam_id, team_id FROM players
                   WHERE id IN (?, ?) ORDER BY id""",
                player_ids,
            ),
            before["players"],
        )
        self.assertEqual(
            self._fresh_rows(
                """SELECT id, player_id, kills, data_status, data_version FROM match_stats
                   WHERE player_id IN (?, ?) ORDER BY id""",
                player_ids,
            ),
            before["stats"],
        )
        self.assertEqual(
            self._fresh_rows(
                "SELECT team1_players, team2_players FROM matches WHERE id=?", (self.match_id,)
            ),
            before["roster"],
        )
        self.assertEqual(
            self._fresh_rows(
                "SELECT year, rank, player_id FROM yearly_top_players ORDER BY year, rank"
            ),
            before["rankings"],
        )
        self.assertEqual(
            self._fresh_rows(
                "SELECT player_id, type, event_id, match_id FROM player_medals ORDER BY id"
            ),
            before["medals"],
        )
        self.assertEqual(
            self._fresh_rows(
                "SELECT player_id, nickname, source FROM player_nickname_history ORDER BY id"
            ),
            before["aliases"],
        )
        self.assertEqual(
            self._fresh_rows(
                """SELECT id, killer_player_id, victim_player_id, assister_player_id
                   FROM match_kill_events WHERE match_id=? ORDER BY id""",
                (self.match_id,),
            ),
            before["events"],
        )
        self.assertEqual(
            self._fresh_rows(
                """SELECT player_id, total_kills, total_deaths FROM player_performance_summary
                   WHERE player_id IN (?, ?) ORDER BY player_id""",
                player_ids,
            ),
            before["summary"],
        )


if __name__ == "__main__":
    unittest.main()
