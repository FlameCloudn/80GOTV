"""Verify flash availability through parser payload, SQLite and the rankings."""

import os
import tempfile
import unittest
from contextlib import closing

from app import app
from config import Config
from models import get_db, init_tables
from routes.stats import _flash_rankings
from services.performance_service import (
    build_demo_performance_payload,
    persist_demo_performance_payload,
)


class FlashRecordingReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_database = Config.DATABASE
        Config.DATABASE = os.path.join(self.temp.name, "flash.db")
        init_tables()
        with closing(get_db()) as conn:
            self.match_id = conn.execute(
                "INSERT INTO matches(status,match_time) VALUES('completed','2026-10-20')"
            ).lastrowid
            self.ids = {}
            for steam, name in (("11", "Quiet"), ("22", "Thrower")):
                player_id = conn.execute(
                    "INSERT INTO players(nickname,steam_id) VALUES(?,?)", (name, steam)
                ).lastrowid
                self.ids[steam] = player_id
                conn.execute(
                    "INSERT INTO match_stats(match_id,player_id,map_name,rounds_played) "
                    "VALUES(?,?,'de_mirage',20)",
                    (self.match_id, player_id),
                )
            conn.commit()

    def tearDown(self):
        Config.DATABASE = self.original_database
        self.temp.cleanup()

    def import_flashes(self, conn, explosions):
        payload = build_demo_performance_payload(
            {
                "players": {"11": {"name": "Quiet"}, "22": {"name": "Thrower"}},
                "playersFlashed": [],
                "flashbangsExplode": explosions,
            }
        )
        persist_demo_performance_payload(conn, self.match_id, "de_mirage", payload)
        conn.commit()

    def rankings(self, conn):
        rows = _flash_rankings(conn, {"time": "all", "map": "all", "side": "both"})
        return {row["id"]: row for row in rows}

    def test_recorded_zero_is_not_missing_and_reimport_replaces_previous_count(self):
        with closing(get_db()) as conn:
            self.import_flashes(conn, [{"throwerSteamId": "22", "throwerName": "Thrower"}])
            self.assertEqual(self.rankings(conn)[self.ids["11"]]["thrown"], 0.0)
            self.assertEqual(self.rankings(conn)[self.ids["22"]]["thrown"], 1.0)
            self.import_flashes(conn, [])
            self.assertEqual(self.rankings(conn)[self.ids["11"]]["thrown"], 0.0)
            self.assertEqual(self.rankings(conn)[self.ids["22"]]["thrown"], 0.0)

    def test_one_players_positive_count_does_not_prove_another_players_zero(self):
        with closing(get_db()) as conn:
            conn.execute(
                "UPDATE match_stats SET flash_count=4 WHERE player_id=?", (self.ids["22"],)
            )
            rows = self.rankings(conn)
            self.assertIsNone(rows[self.ids["11"]]["thrown"])
            self.assertEqual(rows[self.ids["22"]]["thrown"], 4.0)

    def test_known_zero_contributes_to_average_but_legacy_missing_does_not(self):
        with closing(get_db()) as conn:
            self.import_flashes(conn, [])
            conn.execute(
                "INSERT INTO match_stats(match_id,player_id,map_name,flash_count) VALUES(?,?,'de_nuke',4)",
                (self.match_id, self.ids["22"]),
            )
            conn.execute(
                "INSERT INTO match_stats(match_id,player_id,map_name) VALUES(?,?,'de_dust2')",
                (self.match_id, self.ids["22"]),
            )
            self.assertEqual(self.rankings(conn)[self.ids["22"]]["thrown"], 2.0)

    def test_existing_database_gets_availability_column_without_changing_old_data(self):
        with closing(get_db()) as conn:
            conn.execute("ALTER TABLE match_stats DROP COLUMN flash_count_recorded")
            old_columns = [row[1] for row in conn.execute("PRAGMA table_info(match_stats)")]
            old_rows = [tuple(row) for row in conn.execute("SELECT * FROM match_stats ORDER BY id")]
            conn.commit()
        init_tables()
        init_tables()
        with closing(get_db()) as conn:
            self.assertIn(
                "flash_count_recorded",
                [row[1] for row in conn.execute("PRAGMA table_info(match_stats)")],
            )
            select = ",".join('"' + column + '"' for column in old_columns)
            self.assertEqual(
                [
                    tuple(row)
                    for row in conn.execute(f"SELECT {select} FROM match_stats ORDER BY id")
                ],
                old_rows,
            )
            self.assertEqual(
                {row[0] for row in conn.execute("SELECT flash_count_recorded FROM match_stats")},
                {0},
            )

    def test_missing_events_do_not_overwrite_previously_recorded_throws(self):
        with closing(get_db()) as conn:
            self.import_flashes(conn, [{"throwerSteamId": "22", "throwerName": "Thrower"}])
            payload = build_demo_performance_payload(
                {
                    "playersFlashed": [
                        {
                            "flasherSteamId": "22",
                            "flasherName": "Thrower",
                            "flashedSteamId": "11",
                            "flashedName": "Quiet",
                            "duration": 1.0,
                        }
                    ]
                }
            )
            persist_demo_performance_payload(conn, self.match_id, "de_mirage", payload)
            self.assertEqual(self.rankings(conn)[self.ids["22"]]["thrown"], 1.0)

    def test_reimport_does_not_rewrite_the_superseded_stats_version(self):
        with closing(get_db()) as conn:
            conn.execute(
                "UPDATE match_stats SET data_status='superseded',flash_count=7 WHERE player_id=?",
                (self.ids["22"],),
            )
            conn.execute(
                "INSERT INTO match_stats(match_id,player_id,map_name,data_version) VALUES(?,?,'de_mirage',2)",
                (self.match_id, self.ids["22"]),
            )
            self.import_flashes(conn, [{"throwerSteamId": "22", "throwerName": "Thrower"}] * 2)
            history = conn.execute(
                "SELECT flash_count FROM match_stats WHERE player_id=? AND data_status='superseded'",
                (self.ids["22"],),
            ).fetchone()
            self.assertEqual(history["flash_count"], 7)
            self.assertEqual(self.rankings(conn)[self.ids["22"]]["thrown"], 2.0)

    def test_malformed_events_are_rejected_instead_of_becoming_known_zero(self):
        for events in ({"bad": "data"}, ["invalid event"]):
            with (
                self.subTest(events=events),
                self.assertRaisesRegex(ValueError, "闪光弹事件格式无效"),
            ):
                build_demo_performance_payload(
                    {"players": {"11": {"name": "Quiet"}}, "flashbangsExplode": events}
                )

    def test_flash_table_names_the_map_ratio_instead_of_claiming_per_throw_success(self):
        response = app.test_client().get("/stats/overview/flashes")
        self.assertEqual(response.status_code, 200)
        self.assertIn("有效地图占比", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
