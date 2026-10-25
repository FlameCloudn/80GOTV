import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from app import app
from config import Config
from models import get_db, init_tables
from services.performance_service import refresh_player_performance


class FrontApiRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        original = Config.DATABASE
        self.addCleanup(setattr, Config, "DATABASE", original)
        Config.DATABASE = str(Path(self.temp.name) / "front.db")
        original_config = dict(app.config)
        self.addCleanup(app.config.update, original_config)
        app.config.update(TESTING=True, PROPAGATE_EXCEPTIONS=False, SESSION_COOKIE_SECURE=False)
        init_tables()
        self.client = app.test_client()
        with closing(get_db()) as conn:
            self.team = conn.execute("INSERT INTO teams(name) VALUES('Alpha')").lastrowid
            self.other_team = conn.execute("INSERT INTO teams(name) VALUES('Bravo')").lastrowid
            self.event = conn.execute("INSERT INTO events(name) VALUES('Audit Cup')").lastrowid
            self.players = [
                conn.execute(
                    "INSERT INTO players(nickname,team_id) VALUES(?,?)", (name, self.team)
                ).lastrowid
                for name in ("First", "Second", "Reserve")
            ]
            self.match = conn.execute(
                """INSERT INTO matches(event_id,team1_id,team2_id,bo_format,status,
                   team1_score,team2_score,match_time) VALUES(?,?,?,'BO3','completed',2,0,
                   '2026-10-01 12:00:00')""",
                (self.event, self.team, self.other_team),
            ).lastrowid
            for player in self.players[:2]:
                for map_name, rounds, rating in (("de_mirage", 20, 1.0), ("de_nuke", 40, 2.0)):
                    conn.execute(
                        """INSERT INTO match_stats(match_id,player_id,team_id,map_name,
                           rounds_played,rating,adr,kills,deaths) VALUES(?,?,?,?,?,?,80,20,10)""",
                        (self.match, player, self.team, map_name, rounds, rating),
                    )
            self.news = conn.execute(
                "INSERT INTO news(title,content,publish_time) VALUES('News','Body','2026-10-01')"
            ).lastrowid
            user = conn.execute(
                "INSERT INTO users(username,password_hash,approval_status,is_bashizhong_student) "
                "VALUES('fixture-user','unused','approved',0)"
            ).lastrowid
            conn.execute(
                "INSERT INTO comments(target_type,target_id,user_id,content) VALUES('news',?,?,?)",
                (self.news, user, "A reply"),
            )
            refresh_player_performance(conn)
            conn.commit()

    def get_json(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertTrue(response.is_json)
        return response.json

    def test_team_maps_are_not_multiplied_by_roster_or_player_count(self):
        teams = self.get_json("/api/front/teams")["teams"]
        team = next(row for row in teams if row["id"] == self.team)
        self.assertEqual(team["players"], 3)
        self.assertEqual(team["maps"], 2)
        self.assertAlmostEqual(team["rating"], 1.67, places=2)

    def test_statistics_overview_counts_maps_instead_of_player_rows(self):
        data = self.get_json("/api/front/stats/overview")
        self.assertEqual(data["summary"]["player_maps"], 4)
        self.assertEqual(data["top_teams"][0]["maps"], 2)
        self.assertEqual({row["maps"] for row in data["top_maps"]}, {1})
        self.assertAlmostEqual(data["summary"]["avg_rating"], 1.67, places=2)

    def test_recent_matches_contains_each_series_once(self):
        data = self.get_json(f"/api/front/players/{self.players[0]}")
        self.assertEqual([row["id"] for row in data["recent_matches"]], [self.match])

    def test_news_list_returns_actual_comment_count(self):
        data = self.get_json("/api/front/news")
        self.assertEqual(data["news"][0]["comments"], 1)

    def test_huge_page_is_bad_request_not_sqlite_overflow(self):
        for endpoint in ("news", "results", "players", "forum"):
            with self.subTest(endpoint=endpoint):
                response = self.client.get(f"/api/front/{endpoint}?page={10**35}")
                self.assertEqual(response.status_code, 400)
                self.assertTrue(response.is_json)
                self.assertFalse(response.json["ok"])

    def test_match_pagination_and_month_filter_are_honored(self):
        with closing(get_db()) as conn:
            for time in ("2026-09-01 12:00:00", "2026-10-02 12:00:00", "2026-10-03 12:00:00"):
                conn.execute(
                    "INSERT INTO matches(event_id,team1_id,team2_id,status,match_time) "
                    "VALUES(?,?,?,'upcoming',?)",
                    (self.event, self.team, self.other_team, time),
                )
            conn.commit()
        data = self.get_json("/api/front/matches?month=2026-10&per_page=1&page=2")
        self.assertEqual(len(data["matches"]), 1)
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["page"], 2)
        self.assertEqual(data["matches"][0]["match_time"], "2026-10-03 12:00:00")

    def test_player_medal_filter_matches_existing_html_rule(self):
        with closing(get_db()) as conn:
            conn.execute(
                "INSERT INTO player_medals(player_id,event_id,type) VALUES(?,?,'MVP')",
                (self.players[1], self.event),
            )
            conn.commit()
        data = self.get_json("/api/front/players?filter=mvps")
        self.assertEqual([row["id"] for row in data["players"]], [self.players[1]])
        self.assertEqual(data["total"], 1)

    def test_top_players_excludes_players_without_recorded_maps(self):
        data = self.get_json("/api/front/players?filter=top10")
        self.assertEqual({row["id"] for row in data["players"]}, set(self.players[:2]))
        self.assertEqual(data["total"], 2)

    def test_player_initial_filter_is_not_ignored(self):
        data = self.get_json("/api/front/players?initial=f")
        self.assertEqual([row["id"] for row in data["players"]], [self.players[0]])

    def test_missing_metrics_stay_distinct_from_explicit_zero_across_apis(self):
        for value in (None, 0.0):
            with self.subTest(value=value):
                with closing(get_db()) as conn:
                    conn.execute(
                        "UPDATE match_stats SET rating=?,adr=?,headshot_percentage=?,kast=?,impact=?",
                        (value,) * 5,
                    )
                    refresh_player_performance(conn)
                    conn.commit()
                listing = self.get_json("/api/front/players")["players"]
                listed = next(row for row in listing if row["id"] == self.players[0])
                for field in ("rating", "adr", "hs"):
                    self.assertEqual(listed[field], value, field)
                summary = self.get_json(f"/api/front/players/{self.players[0]}")["summary"]
                for field in ("rating", "adr", "hs", "kast", "impact"):
                    self.assertEqual(summary[field], value, field)
                overview = self.get_json("/api/front/stats/overview")
                self.assertEqual(overview["summary"]["avg_rating"], value)
                for row in overview["top_maps"]:
                    self.assertEqual(row["rating"], value)

    def test_unknown_kill_death_assist_counts_do_not_become_zero(self):
        for value in (None, 0):
            with self.subTest(value=value):
                with closing(get_db()) as conn:
                    conn.execute("UPDATE match_stats SET kills=?,deaths=?,assists=?", (value,) * 3)
                    refresh_player_performance(conn)
                    conn.commit()
                listing = self.get_json("/api/front/players")["players"]
                player = next(row for row in listing if row["id"] == self.players[0])
                summary = self.get_json(f"/api/front/players/{self.players[0]}")["summary"]
                for field in ("kills", "deaths", "assists"):
                    self.assertEqual(player[field], value)
                    self.assertEqual(summary[field], value)
                overview = self.get_json("/api/front/stats/overview")
                self.assertEqual(overview["summary"]["kills"], value)
                for row in overview["top_players"]:
                    self.assertEqual(row["kills"], value)

    def test_home_refresh_preserves_server_rendered_team_abbreviations(self):
        with closing(get_db()) as conn:
            conn.execute("UPDATE teams SET short_name='ALP' WHERE id=?", (self.team,))
            conn.execute("UPDATE teams SET short_name='BRV' WHERE id=?", (self.other_team,))
            conn.commit()
        recent = self.get_json("/api/front/home")["recent_results"][0]
        self.assertEqual((recent["team1"], recent["team2"]), ("ALP", "BRV"))
        self.assertEqual((recent["team1_full"], recent["team2_full"]), ("Alpha", "Bravo"))

    def test_missing_rating_renders_as_unknown_on_html_pages(self):
        with closing(get_db()) as conn:
            conn.execute("UPDATE match_stats SET rating=NULL")
            refresh_player_performance(conn)
            conn.commit()
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertRegex(home.get_data(as_text=True), r"<small[^>]*>-</small>")
        profile = self.client.get(f"/players/{self.players[0]}")
        self.assertEqual(profile.status_code, 200)
        self.assertRegex(
            profile.get_data(as_text=True),
            r"<dt>RATING 2.0</dt>\s*<dd[^>]*>-</dd>",
        )

    def test_home_and_dashboard_comment_counts_match_news_page(self):
        for endpoint in ("home", "dashboard"):
            with self.subTest(endpoint=endpoint):
                data = self.get_json(f"/api/front/{endpoint}")
                self.assertEqual(data["news"][0]["comments"], 1)

    def test_prediction_reads_work_with_a_read_only_connection(self):
        with closing(get_db()) as conn:
            user = conn.execute("SELECT id FROM users WHERE username='fixture-user'").fetchone()[0]
            conn.execute(
                """INSERT INTO match_votes(match_id,user_id,voted_for,score1_guess,score2_guess,
                   scored,points_earned) VALUES(?,?,'t1',2,0,0,0)""",
                (self.match, user),
            )
            future = conn.execute(
                """INSERT INTO matches(event_id,team1_id,team2_id,status,match_time)
                   VALUES(?,?,?,'upcoming','2099-01-01 12:00:00')""",
                (self.event, self.team, self.other_team),
            ).lastrowid
            conn.commit()
        for endpoint, module in (
            ("/predictions", "routes.stats"),
            ("/api/front/predictions", "routes.front_api"),
        ):
            with self.subTest(endpoint=endpoint):
                conn = get_db()
                conn.execute("PRAGMA query_only=ON")
                with patch(f"{module}.get_db", return_value=conn):
                    response = self.client.get(endpoint)
                self.assertEqual(response.status_code, 200)
                if response.is_json:
                    self.assertEqual(response.json["leaderboard"][0]["points"], 8)
                    self.assertEqual(
                        [row["id"] for row in response.json["upcoming_matches"]], [future]
                    )
        with closing(get_db()) as conn:
            vote = conn.execute("SELECT scored,points_earned FROM match_votes").fetchone()
        self.assertEqual(tuple(vote), (0, 0))

    def test_initial_filter_is_applied_after_selecting_top_ten_like_html(self):
        with closing(get_db()) as conn:
            for index in range(11):
                nickname = f"AlphaRank{index}" if index < 10 else "BravoOutsideTopTen"
                player = conn.execute(
                    "INSERT INTO players(nickname) VALUES(?)", (nickname,)
                ).lastrowid
                conn.execute(
                    "INSERT INTO match_stats(player_id,match_id,map_name,rating,rounds_played) VALUES(?,?,'de_mirage',?,20)",
                    (player, self.match, 2.0 if index < 10 else 1.0),
                )
            refresh_player_performance(conn)
            conn.commit()
        data = self.get_json("/api/front/players?filter=top10&initial=b")
        self.assertEqual(data["players"], [])
        self.assertEqual(data["total"], 0)


if __name__ == "__main__":
    unittest.main()
