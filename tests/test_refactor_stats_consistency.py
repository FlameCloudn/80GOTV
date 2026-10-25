import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from services.performance_service import refresh_player_performance, weighted_rate_sql
from utils.stats_calc import aggregate_player_stats, calculate_rating


class StatsDatabaseCase(unittest.TestCase):
    def setUp(self):
        from config import Config
        from models import get_db, init_tables

        self.temp_dir = tempfile.TemporaryDirectory(prefix="refactor-stats-")
        self.database_patch = patch.object(
            Config, "DATABASE", os.path.join(self.temp_dir.name, "stats.db")
        )
        self.database_patch.start()
        init_tables()
        self.conn = get_db()
        conn = self.conn
        self.event_id = conn.execute("INSERT INTO events(name) VALUES('Audit Cup')").lastrowid
        self.team1 = conn.execute(
            "INSERT INTO teams(name, short_name) VALUES('Alpha', 'A')"
        ).lastrowid
        self.team2 = conn.execute(
            "INSERT INTO teams(name, short_name) VALUES('Bravo', 'B')"
        ).lastrowid
        self.player_id = conn.execute(
            "INSERT INTO players(nickname, steam_id, team_id) VALUES('Audit Player', '111', ?)",
            (self.team2,),
        ).lastrowid
        self.match_id = conn.execute(
            """INSERT INTO matches(event_id, team1_id, team2_id, status, bo_format, map1, map2)
               VALUES(?, ?, ?, 'completed', 'BO3', 'Mirage', 'Nuke')""",
            (self.event_id, self.team1, self.team2),
        ).lastrowid
        self.stats_database = (
            conn,
            self.event_id,
            self.match_id,
            self.player_id,
            self.team1,
            self.team2,
        )

    def tearDown(self):
        self.conn.close()
        self.database_patch.stop()
        self.temp_dir.cleanup()


def add_stat(conn, match_id, player_id, team_id, map_name, **values):
    values = {
        "match_id": match_id,
        "player_id": player_id,
        "team_id": team_id,
        "map_name": map_name,
        **values,
    }
    columns = ",".join(values)
    conn.execute(
        f"INSERT INTO match_stats({columns}) VALUES({','.join('?' for _ in values)})",
        tuple(values.values()),
    )


class StatsCalculationTests(unittest.TestCase):
    def test_python_aggregation_uses_same_recorded_weights_as_sql(self):
        rows = [
            {
                "kills": 10,
                "deaths": 8,
                "assists": 1,
                "rounds_played": 10,
                "adr": 50,
                "rating": 0.8,
                "kast": 60,
                "headshot_percentage": 40,
            },
            {
                "kills": 45,
                "deaths": 15,
                "assists": 2,
                "rounds_played": 30,
                "adr": 100,
                "rating": 1.4,
                "kast": None,
                "headshot_percentage": 60,
            },
            {
                "kills": 0,
                "deaths": 0,
                "assists": 0,
                "rounds_played": 0,
                "adr": 1000,
                "rating": 3,
                "kast": 100,
                "headshot_percentage": 100,
            },
        ]
        result = aggregate_player_stats(rows)
        self.assertEqual(result["avg_rating"], 1.25)
        self.assertEqual(result["avg_adr"], 87.5)
        self.assertEqual(result["avg_kast"], 60)
        self.assertEqual(result["avg_headshot_percentage"], 56.4)

    def test_weighted_rate_does_not_turn_unknown_numerator_into_zero(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE stats(kills INTEGER, rounds INTEGER)")
        conn.executemany("INSERT INTO stats VALUES(?, ?)", [(10, 10), (None, 30)])
        expression = weighted_rate_sql("kills", "rounds")
        result = conn.execute(f"SELECT {expression} FROM stats").fetchone()[0]
        conn.close()
        self.assertEqual(result, 1.0)

    def test_rating_matches_documented_csda_estimate(self):
        impact = 2.13 * (20 / 20) + 0.42 * (5 / 20) - 0.41
        expected = round(
            0.0073 * 75 + 0.3591 - 0.5329 * 0.5 + 0.2372 * impact + 0.0032 * 80 + 0.1587, 2
        )
        self.assertEqual(calculate_rating(20, 10, 20, adr=80, kast=75, impact=impact)[0], expected)

    def test_rating_no_recorded_rounds_never_divides_by_zero(self):
        for rounds in (None, -1, 0, "0"):
            with self.subTest(rounds=rounds):
                self.assertEqual(calculate_rating(2, 1, rounds), (0, 0, 0))


class StatsConsistencyTests(StatsDatabaseCase):
    def _player_context(self, detailed=False):
        from routes.players import player_detail, player_stats_detail
        from web_app import app

        with app.test_request_context(f"/players/{self.player_id}"):
            with (
                patch("routes.players.get_db", return_value=self.conn),
                patch("routes.players.render_template") as render,
            ):
                with patch("routes.players.enrich_player_from_steam", return_value=False):
                    (player_stats_detail if detailed else player_detail)(self.player_id)
        return render.call_args.kwargs

    def test_player_profile_recent_match_and_chart_use_round_weights(self):
        add_stat(
            self.conn,
            self.match_id,
            self.player_id,
            self.team1,
            "Mirage",
            rounds_played=10,
            kills=10,
            deaths=8,
            rating=0.8,
            adr=50,
        )
        add_stat(
            self.conn,
            self.match_id,
            self.player_id,
            self.team1,
            "Nuke",
            rounds_played=30,
            kills=45,
            deaths=15,
            rating=1.4,
            adr=100,
        )
        context = self._player_context()
        self.assertAlmostEqual(context["recent_matches"][0]["rating"], 1.25)
        self.assertEqual(json.loads(context["chart_data"])["rating"], [1.25])

    def test_player_statistics_recent_match_uses_same_weights(self):
        add_stat(
            self.conn,
            self.match_id,
            self.player_id,
            self.team1,
            "Mirage",
            rounds_played=10,
            kills=10,
            deaths=8,
            rating=0.8,
            adr=50,
        )
        add_stat(
            self.conn,
            self.match_id,
            self.player_id,
            self.team1,
            "Nuke",
            rounds_played=30,
            kills=45,
            deaths=15,
            rating=1.4,
            adr=100,
        )
        context = self._player_context(detailed=True)
        self.assertAlmostEqual(context["recent_matches"][0]["rating"], 1.25)

    def test_actual_zero_rating_is_retained_in_player_chart(self):
        add_stat(
            self.conn,
            self.match_id,
            self.player_id,
            self.team1,
            "Mirage",
            rounds_played=10,
            kills=0,
            deaths=10,
            rating=0,
            adr=0,
        )
        context = self._player_context()
        self.assertEqual(json.loads(context["chart_data"])["rating"], [0])

    def test_summary_preserves_missing_and_actual_zero_metrics(self):
        from routes.stats import _player_rankings

        conn, _, match_id, player_id, team1, _ = self.stats_database
        add_stat(
            conn,
            match_id,
            player_id,
            team1,
            "Mirage",
            rounds_played=20,
            impact=None,
            kast=None,
            adr=None,
            rating=None,
        )
        refresh_player_performance(conn, [player_id])
        # 缓存列兼容旧表的 NOT NULL；公开读取不能把该占位值显示成真实零分。
        filters = {"time": "all", "map": "all", "side": "both"}
        row = _player_rankings(conn, filters)[0]
        self.assertIsNone(row["impact"])
        self.assertIsNone(row["rating"])
        conn.execute("UPDATE match_stats SET impact=0, rating=0 WHERE player_id=?", (player_id,))
        refresh_player_performance(conn, [player_id])
        row = _player_rankings(conn, filters)[0]
        self.assertEqual(row["impact"], 0)
        self.assertEqual(row["rating"], 0)

    def test_filtered_rankings_and_comparison_match_career_weights(self):
        from routes.stats import _comparison_profile, _player_rankings

        conn, event_id, match_id, player_id, team1, _ = self.stats_database
        add_stat(
            conn,
            match_id,
            player_id,
            team1,
            "Mirage",
            rounds_played=10,
            kills=10,
            deaths=8,
            rating=0.8,
            adr=50,
            kast=60,
            impact=0.7,
            headshot_percentage=40,
        )
        add_stat(
            conn,
            match_id,
            player_id,
            team1,
            "Nuke",
            rounds_played=30,
            kills=45,
            deaths=15,
            rating=1.4,
            adr=100,
            kast=80,
            impact=1.3,
            headshot_percentage=60,
        )
        filters = {"time": "all", "map": "all", "side": "both", "event": str(event_id)}
        profile = _comparison_profile(conn, player_id, filters)
        ranking = _player_rankings(conn, filters)[0]
        for row in (profile, ranking):
            self.assertAlmostEqual(row["rating"], 1.25)
            self.assertAlmostEqual(row["kast"], 75)
            self.assertAlmostEqual(row["impact"], 1.15)
            self.assertAlmostEqual(row["hs"], 3100 / 55)

    def test_event_rankings_weight_maps_and_use_played_team(self):
        from routes.events import event_stats
        from web_app import app

        conn, event_id, match_id, player_id, team1, _ = self.stats_database
        add_stat(
            conn,
            match_id,
            player_id,
            team1,
            "Mirage",
            rounds_played=10,
            kills=10,
            deaths=8,
            rating=0.8,
            adr=50,
            kast=60,
            impact=0.7,
        )
        add_stat(
            conn,
            match_id,
            player_id,
            team1,
            "Nuke",
            rounds_played=30,
            kills=45,
            deaths=15,
            rating=1.4,
            adr=100,
            kast=80,
            impact=1.3,
        )
        with app.test_request_context(f"/events/{event_id}/stats"):
            with (
                patch("routes.events.get_db", return_value=conn),
                patch("routes.events.render_template") as render,
            ):
                with patch("routes.events._event_team_count", return_value=2):
                    event_stats(str(event_id))
        row = render.call_args.kwargs["rankings"][0]
        self.assertAlmostEqual(row["rating"], 1.25)
        self.assertAlmostEqual(row["impact"], 1.15)
        self.assertEqual(row["team"], "A")

    def test_award_averages_exclude_missing_metric_rounds(self):
        from services.award_service import build_event_award_poster

        conn, event_id, match_id, player_id, team1, _ = self.stats_database
        add_stat(
            conn,
            match_id,
            player_id,
            team1,
            "Mirage",
            rounds_played=10,
            kills=10,
            deaths=8,
            rating=0.8,
            impact=1.2,
        )
        add_stat(
            conn,
            match_id,
            player_id,
            team1,
            "Nuke",
            rounds_played=30,
            kills=45,
            deaths=15,
            rating=1.4,
            impact=None,
        )
        with patch("services.award_service.generate_award_poster") as generate:
            build_event_award_poster(conn, ".", event_id, player_id)
        self.assertAlmostEqual(generate.call_args.args[3]["impact"], 1.2)
        self.assertEqual(generate.call_args.args[1]["team_short"], "A")
