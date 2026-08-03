import os
import tempfile
import unittest
from unittest.mock import patch

from app import app
from config import Config
from models import get_db, init_tables
from routes.stats import _flash_rankings, _top_weapons
from services.performance_service import (
    backfill_demo_performance,
    build_demo_performance_payload,
    persist_demo_performance_payload,
    refresh_player_performance,
)


class PerformanceStorageTests(unittest.TestCase):
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
        conn.execute("INSERT INTO teams(name, short_name) VALUES('Team A', 'TA')")
        self.team_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO players(nickname, team_id, steam_id)
               VALUES('Alpha', ?, '111')""",
            (self.team_id,),
        )
        self.alpha_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO players(nickname, team_id, steam_id)
               VALUES('Bravo', ?, '222')""",
            (self.team_id,),
        )
        self.bravo_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO events(name, slug) VALUES('Event', 'event')")
        event_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO matches(
                   event_id, team1_id, team2_id, match_time, status,
                   map1, map2, slug
               ) VALUES(?,?,?,?,?,?,?,?)""",
            (
                event_id,
                self.team_id,
                self.team_id,
                "2026-07-16 12:00:00",
                "completed",
                "Mirage",
                "Inferno",
                "team-a-vs-team-a",
            ),
        )
        self.match_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for map_name, kills, deaths, rating in (
            ("Mirage", 20, 10, 1.4),
            ("Inferno", 10, 10, 1.0),
        ):
            conn.execute(
                """INSERT INTO match_stats(
                       match_id, player_id, team_id, map_name,
                       kills, deaths, assists, rating, adr, kast,
                       headshot_percentage, kpr, dpr, impact,
                       rounds_played, flash_count
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.match_id,
                    self.alpha_id,
                    self.team_id,
                    map_name,
                    kills,
                    deaths,
                    5,
                    rating,
                    80,
                    75,
                    50,
                    0.75,
                    0.5,
                    1.1,
                    20,
                    4,
                ),
            )
        refresh_player_performance(conn)
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

    def test_career_summary_is_persisted(self):
        conn = get_db()
        row = conn.execute(
            "SELECT * FROM player_performance_summary WHERE player_id=?",
            (self.alpha_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(row["matches"], 1)
        self.assertEqual(row["maps"], 2)
        self.assertEqual(row["total_kills"], 30)
        self.assertAlmostEqual(row["avg_rating"], 1.2)

    def test_career_summary_weights_map_averages_by_real_rounds(self):
        conn = get_db()
        conn.execute(
            """UPDATE match_stats
               SET kills=10, deaths=8, rating=0.8, adr=50, kast=60,
                   headshot_percentage=40, impact=0.7, rounds_played=10,
                   utility_damage=20
               WHERE player_id=? AND map_name='Mirage'""",
            (self.alpha_id,),
        )
        conn.execute(
            """UPDATE match_stats
               SET kills=45, deaths=15, rating=1.4, adr=100, kast=80,
                   headshot_percentage=60, impact=1.3, rounds_played=30,
                   utility_damage=120
               WHERE player_id=? AND map_name='Inferno'""",
            (self.alpha_id,),
        )
        refresh_player_performance(conn, [self.alpha_id])
        conn.commit()
        row = conn.execute(
            """SELECT avg_rating, avg_adr, avg_kpr, avg_dpr,
                      avg_utility_damage_per_round
               FROM player_performance_summary WHERE player_id=?""",
            (self.alpha_id,),
        ).fetchone()
        conn.close()

        self.assertAlmostEqual(row["avg_rating"], 1.25)
        self.assertAlmostEqual(row["avg_adr"], 87.5)
        self.assertAlmostEqual(row["avg_kpr"], 55 / 40)
        self.assertAlmostEqual(row["avg_dpr"], 23 / 40)
        self.assertAlmostEqual(row["avg_utility_damage_per_round"], 140 / 40)

    def test_demo_details_feed_database_only_rankings(self):
        conn = get_db()
        affected = persist_demo_performance_payload(
            conn,
            self.match_id,
            "Mirage",
            {
                "kill_events": [
                    {
                        "round_number": 1,
                        "tick": 100,
                        "killer_steam_id": "111",
                        "victim_steam_id": "222",
                        "killer_name": "Alpha",
                        "victim_name": "Bravo",
                        "killer_side": "T",
                        "victim_side": "CT",
                        "weapon": "AK-47",
                        "headshot": 1,
                    }
                ],
                "flash_metrics": [
                    {
                        "steam_id": "111",
                        "name": "Alpha",
                        "blinded_seconds": 1.5,
                        "enemy_seconds": 3.5,
                        "flash_assists": 1,
                    }
                ],
            },
        )
        refresh_player_performance(conn, affected)
        conn.commit()

        filters = {"time": "all", "map": "all", "side": "both"}
        weapons = _top_weapons(conn, filters)
        flashes = _flash_rankings(conn, filters, 10)
        kill_count = conn.execute("SELECT COUNT(*) FROM match_kill_events").fetchone()[0]
        conn.close()

        self.assertEqual(kill_count, 1)
        self.assertEqual(weapons[0]["name"], "ak47")
        alpha_flash = next(row for row in flashes if row["id"] == self.alpha_id)
        self.assertGreater(alpha_flash["opp_flashed"], alpha_flash["blinded"])

    def test_enemy_flash_time_excludes_teammates(self):
        payload = build_demo_performance_payload(
            {
                "playersFlashed": [
                    {
                        "flasherSteamId": "111",
                        "flasherName": "Alpha",
                        "flasherSide": 2,
                        "flashedSteamId": "222",
                        "flashedName": "Bravo",
                        "flashedSide": 2,
                        "duration": 1.25,
                    },
                    {
                        "flasherSteamId": "111",
                        "flasherName": "Alpha",
                        "flasherSide": 2,
                        "flashedSteamId": "333",
                        "flashedName": "Charlie",
                        "flashedSide": 3,
                        "duration": 2.5,
                    },
                ]
            }
        )
        metrics = {row["steam_id"]: row for row in payload["flash_metrics"]}
        self.assertEqual(metrics["111"]["enemy_seconds"], 2.5)
        self.assertEqual(metrics["222"]["blinded_seconds"], 1.25)
        self.assertEqual(metrics["333"]["blinded_seconds"], 2.5)

    def test_backfill_follows_transferred_historical_identity(self):
        conn = get_db()
        conn.execute(
            "UPDATE players SET nickname='AAA' WHERE id=?",
            (self.alpha_id,),
        )
        conn.execute("INSERT INTO players(nickname, steam_id) VALUES('正在开往延雪平', '333')")
        source_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO player_nickname_history(player_id, nickname, source)
               VALUES(?, '正在开往延雪平', 'stats-transfer')""",
            (self.alpha_id,),
        )
        conn.execute(
            """UPDATE match_stats
               SET clutches_won=16, clutch_1v5=16
               WHERE match_id=? AND map_name='Mirage' AND player_id=?""",
            (self.match_id, self.alpha_id),
        )

        parsed_stats = [
            {
                "steam_id": "333",
                "name": "正在开往延雪平",
                "clutch_1v1": 0,
                "clutch_1v2": 1,
                "clutch_1v3": 0,
                "clutch_1v4": 0,
                "clutch_1v5": 0,
                "clutches_won": 1,
                "rws_basic": 3.5,
            }
        ]
        payload = {
            "kill_events": [
                {
                    "round_number": 1,
                    "tick": 100,
                    "killer_steam_id": "333",
                    "victim_steam_id": "222",
                    "killer_name": "正在开往延雪平",
                    "victim_name": "Bravo",
                    "killer_side": "T",
                    "victim_side": "CT",
                    "weapon": "AK-47",
                }
            ],
            "flash_metrics": [
                {
                    "steam_id": "333",
                    "name": "正在开往延雪平",
                    "blinded_seconds": 1.25,
                    "enemy_seconds": 2.5,
                    "flash_assists": 1,
                }
            ],
        }
        with (
            patch("utils.demo_parser.parse_player_stats", return_value=parsed_stats),
            patch(
                "services.performance_service.build_demo_performance_payload",
                return_value=payload,
            ),
        ):
            backfill_demo_performance(conn, self.match_id, "Mirage", {})
        conn.commit()

        target = conn.execute(
            """SELECT clutches_won, clutch_1v2, clutch_1v5,
                      rws_basic, flash_assists
               FROM match_stats
               WHERE match_id=? AND map_name='Mirage' AND player_id=?""",
            (self.match_id, self.alpha_id),
        ).fetchone()
        event = conn.execute(
            """SELECT killer_player_id FROM match_kill_events
               WHERE match_id=? AND map_name='Mirage'""",
            (self.match_id,),
        ).fetchone()
        source_rows = conn.execute(
            "SELECT COUNT(*) FROM match_stats WHERE player_id=?",
            (source_id,),
        ).fetchone()[0]
        conn.close()

        self.assertEqual(tuple(target), (1, 1, 0, 3.5, 1))
        self.assertEqual(event["killer_player_id"], self.alpha_id)
        self.assertEqual(source_rows, 0)

    def test_stats_pages_do_not_scan_parser_cache_files(self):
        with patch(
            "routes.stats._csda_flash_stats",
            side_effect=AssertionError("cache scan must not run"),
        ):
            overview = self.client.get("/stats")
            players = self.client.get("/stats?tab=players")
        self.assertEqual(overview.status_code, 200)
        self.assertEqual(players.status_code, 200)

    def test_versioned_assets_are_immutable(self):
        response = self.client.get("/static/css/style_v2.css?v=performance-test")
        self.assertEqual(response.status_code, 200)
        self.assertIn("immutable", response.headers["Cache-Control"])
        response.close()


if __name__ == "__main__":
    unittest.main()
