import os
import tempfile
import unittest
from unittest.mock import patch

from app import app
from config import Config
from models import get_db, init_tables


class PlayerProfileRedesignTests(unittest.TestCase):
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
        conn.execute("INSERT INTO teams(name, short_name) VALUES('Alpha Team', 'ALP')")
        self.team_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO teams(name, short_name) VALUES('Beta Team', 'BET')")
        self.opponent_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO players(nickname, team_id, steam_id)
               VALUES('ProfileTester', ?, '111')""",
            (self.team_id,),
        )
        self.player_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO events(name, slug, start_date)
               VALUES('80 Major', '80-major', '2026-07-01')"""
        )
        event_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        for index, (team1_score, team2_score, slug) in enumerate(
            ((13, 9, "alpha-win"), (7, 13, "alpha-loss")), start=1
        ):
            conn.execute(
                """INSERT INTO matches(
                       event_id, team1_id, team2_id, team1_score, team2_score,
                       match_time, status, slug
                   ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    event_id,
                    self.team_id,
                    self.opponent_id,
                    team1_score,
                    team2_score,
                    f"2026-07-0{index} 12:00:00",
                    "completed",
                    slug,
                ),
            )
            match_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                """INSERT INTO match_stats(
                       match_id, player_id, team_id, map_name, kills, deaths,
                       assists, rating, adr, kast, headshot_percentage, kpr,
                       dpr, impact, t_rating, ct_rating, rounds_played,
                       first_kills, first_deaths,
                       multi2k, trade_kills, trade_deaths, clutches_won,
                       utility_damage, utility_damage_per_round
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    match_id,
                    self.player_id,
                    self.team_id,
                    "Mirage",
                    20,
                    14,
                    5,
                    1.24,
                    86.5,
                    73.2,
                    48.0,
                    0.8,
                    0.56,
                    1.16,
                    1.08,
                    1.31,
                    25,
                    4,
                    2,
                    3,
                    5,
                    4,
                    1,
                    70,
                    2.8,
                ),
            )

        conn.execute(
            """INSERT INTO player_medals(player_id, type, event_id)
               VALUES(?, 'MVP', ?)""",
            (self.player_id, event_id),
        )
        conn.execute(
            """INSERT INTO event_champions(event_id, team_id)
               VALUES(?, ?)""",
            (event_id, self.team_id),
        )
        conn.commit()
        conn.close()
        self.client = app.test_client()

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

    def test_profile_uses_real_data_without_unavailable_fields(self):
        response = self.client.get(f"/players/{self.player_id}")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        self.assertIn('class="pp-hero"', html)
        self.assertIn("<dt>比赛数</dt>", html)
        self.assertIn("<dt>选手荣誉</dt>", html)
        self.assertIn("<dt>SteamID</dt>", html)
        self.assertIn("<dt>胜负</dt>", html)
        self.assertIn("13 : 9", html)
        self.assertIn("7 : 13", html)
        self.assertNotIn(">年龄<", html)
        self.assertNotIn(">Top20<", html)
        self.assertNotIn(">狙击<", html)

    def test_profile_overview_uses_one_frame_with_two_columns(self):
        response = self.client.get(f"/players/{self.player_id}")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        self.assertEqual(html.count('class="pp-panel pp-overview-panel"'), 1)
        self.assertEqual(html.count('class="pp-overview-column'), 2)
        self.assertIn("<h2>数据统计</h2>", html)
        self.assertNotIn("ProfileTester</span> 数据统计", html)
        self.assertIn("<h2>近期比赛</h2>", html)

    def test_recent_match_score_uses_player_perspective(self):
        conn = get_db()
        loss_match = conn.execute("SELECT id FROM matches WHERE slug='alpha-loss'").fetchone()
        conn.execute(
            """UPDATE matches
               SET team1_id=?, team2_id=?, team1_score=2, team2_score=0
               WHERE id=?""",
            (self.opponent_id, self.team_id, loss_match["id"]),
        )
        conn.commit()
        conn.close()

        response = self.client.get(f"/players/{self.player_id}")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        self.assertIn('class="pp-match-row loss"', html)
        self.assertIn("<strong>0 : 2</strong>", html)

    def test_detailed_stats_keep_filters_and_remove_fake_sniper_data(self):
        response = self.client.get(f"/stats/players/{self.player_id}?time=all&map=all&side=both")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        self.assertIn('class="pd-summary"', html)
        self.assertIn('class="pd-filters"', html)
        self.assertIn('class="pd-category-grid"', html)
        self.assertIn("<th>比分</th>", html)
        self.assertIn("13 : 9", html)
        self.assertNotIn(">狙击<", html)
        self.assertNotIn("每回合狙击击杀", html)

    def test_detailed_stats_use_real_impact_and_half_gauges(self):
        response = self.client.get(f"/stats/players/{self.player_id}")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        self.assertEqual(html.count('class="pd-rating-gauge'), 3)
        self.assertIn("1.08", html)
        self.assertIn("1.31", html)
        self.assertIn('data-metric="impact"', html)
        self.assertIn("<b>1.16</b><span>IMPACT</span>", html)
        self.assertNotIn("ROUND SWING", html)

    def test_missing_impact_is_shown_as_unavailable(self):
        conn = get_db()
        conn.execute(
            "UPDATE match_stats SET impact=NULL WHERE player_id=?",
            (self.player_id,),
        )
        conn.commit()
        conn.close()

        response = self.client.get(f"/stats/players/{self.player_id}")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        impact_markup = html.split('data-metric="impact"', 1)[1]
        self.assertIn("<b>-</b><span>IMPACT</span>", impact_markup)

    def test_detailed_matches_group_multiple_maps_from_the_same_match(self):
        conn = get_db()
        match_id = conn.execute("SELECT id FROM matches WHERE slug='alpha-win'").fetchone()["id"]
        conn.execute(
            """INSERT INTO match_stats(
                   match_id, player_id, team_id, map_name,
                   kills, deaths, assists, rating, adr
               ) VALUES(?, ?, ?, 'Inferno', 18, 15, 4, 1.10, 79.0)""",
            (match_id, self.player_id, self.team_id),
        )
        conn.commit()
        conn.close()

        response = self.client.get(f"/stats/players/{self.player_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True).count("13 : 9"), 1)

    def test_profile_and_detailed_page_share_weighted_real_stats(self):
        conn = get_db()
        rows = conn.execute(
            "SELECT id FROM match_stats WHERE player_id=? ORDER BY id",
            (self.player_id,),
        ).fetchall()
        conn.execute(
            """UPDATE match_stats
               SET kills=8, deaths=7, rating=0.8, adr=50, kast=60,
                   headshot_percentage=40, impact=0.7, rounds_played=10,
                   clutches_won=0, utility_damage=20
               WHERE id=?""",
            (rows[0]["id"],),
        )
        conn.execute(
            """UPDATE match_stats
               SET kills=36, deaths=13, rating=1.4, adr=100, kast=80,
                   headshot_percentage=60, impact=1.3, rounds_played=30,
                   clutches_won=2, utility_damage=120
               WHERE id=?""",
            (rows[1]["id"],),
        )
        conn.commit()
        conn.close()

        profile_context = {}
        detail_context = {}

        def capture_profile(_template, **context):
            profile_context.update(context)
            return ""

        def capture_detail(_template, **context):
            detail_context.update(context)
            return ""

        with patch("routes.players.render_template", side_effect=capture_profile):
            profile_response = self.client.get(f"/players/{self.player_id}")
        with patch("routes.players.render_template", side_effect=capture_detail):
            detail_response = self.client.get(
                f"/stats/players/{self.player_id}?time=all&map=all&side=both"
            )

        self.assertEqual(profile_response.status_code, 200)
        self.assertEqual(detail_response.status_code, 200)
        self.assertAlmostEqual(profile_context["overall"]["avg_rating"], 1.25)
        self.assertAlmostEqual(profile_context["overall"]["avg_kpr"], 44 / 40)
        self.assertEqual(
            profile_context["overall"]["clutches_won"],
            detail_context["overall"]["clutches_won"],
        )
        self.assertAlmostEqual(
            profile_context["overall"]["avg_rating"],
            detail_context["overall"]["avg_rating"],
        )
        self.assertAlmostEqual(
            profile_context["overall"]["avg_kpr"],
            detail_context["overall"]["avg_kpr"],
        )
        self.assertEqual(
            profile_context["player_category_cards"],
            detail_context["player_category_cards"],
        )

    def test_player_styles_include_mobile_single_column_layout(self):
        css_path = os.path.join(app.root_path, "static", "css", "player_profile_refresh.css")
        with open(css_path, encoding="utf-8") as css_file:
            css = css_file.read()

        self.assertIn("@media (max-width: 760px)", css)
        self.assertIn(".pp-overview-panel", css)
        self.assertIn(".pd-rating-arc", css)
        self.assertIn("conic-gradient", css)
        self.assertIn(".pd-category-grid", css)
        self.assertIn("grid-template-columns: minmax(0, 1fr)", css)


if __name__ == "__main__":
    unittest.main()
