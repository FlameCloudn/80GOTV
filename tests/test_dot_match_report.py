import json
import os
import tempfile
import unittest
from contextlib import closing

from flask import template_rendered

from app import app
from config import Config
from models import get_db, init_tables


class DotMatchReportTests(unittest.TestCase):
    def setUp(self):
        handle, self.database_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.original_database = Config.DATABASE
        self.original_config = {
            key: app.config.get(key)
            for key in ("TESTING", "SESSION_COOKIE_SECURE", "PROPAGATE_EXCEPTIONS")
        }
        Config.DATABASE = self.database_path
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False, PROPAGATE_EXCEPTIONS=True)
        init_tables()
        self.client = app.test_client()

    def tearDown(self):
        Config.DATABASE = self.original_database
        app.config.update(self.original_config)
        os.remove(self.database_path)

    def _match(self, *, temporary=False):
        with closing(get_db()) as conn:
            event_id = conn.execute("INSERT INTO events(name) VALUES('Dot report test')").lastrowid
            team1_id = team2_id = None
            if not temporary:
                team1_id = conn.execute(
                    "INSERT INTO teams(name,short_name) VALUES('Report Alpha','RA')"
                ).lastrowid
                team2_id = conn.execute(
                    "INSERT INTO teams(name,short_name) VALUES('Report Beta','RB')"
                ).lastrowid
                wrong1_id = conn.execute(
                    "INSERT INTO teams(name,short_name) VALUES('Stored Alpha','SA')"
                ).lastrowid
                wrong2_id = conn.execute(
                    "INSERT INTO teams(name,short_name) VALUES('Stored Beta','SB')"
                ).lastrowid
            else:
                wrong1_id = wrong2_id = None

            players = {
                name: conn.execute("INSERT INTO players(nickname) VALUES(?)", (name,)).lastrowid
                for name in ("Side One", "Side Two", "Legacy One", "Unknown")
            }
            match_id = conn.execute(
                """INSERT INTO matches(event_id,team1_id,team2_id,team1_players,team2_players,
                           status,bo_format,team1_score,team2_score,map1,map1_t1,map1_t2)
                   VALUES(?,?,?,?,?,'completed','BO1',1,0,'de_nuke',13,7)""",
                (
                    event_id,
                    team1_id,
                    team2_id,
                    json.dumps([players["Side One"]]) if temporary else None,
                    json.dumps([players["Side Two"]]) if temporary else None,
                ),
            ).lastrowid
            conn.commit()
        return match_id, players, team1_id, team2_id, wrong1_id, wrong2_id

    def _stat(
        self,
        match_id,
        player_id,
        team_id,
        side,
        *,
        kills,
        deaths,
        adr,
        kast,
        rating,
        status="final",
        map_name="de_nuke",
        rounds_played=0,
    ):
        with closing(get_db()) as conn:
            conn.execute(
                """INSERT INTO match_stats(match_id,player_id,team_id,match_team_side,
                           map_name,kills,deaths,adr,kast,rating,data_status,rounds_played)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    match_id,
                    player_id,
                    team_id,
                    side,
                    map_name,
                    kills,
                    deaths,
                    adr,
                    kast,
                    rating,
                    status,
                    rounds_played,
                ),
            )
            conn.commit()

    def _context(self, path, template_name):
        captured = []

        def capture(sender, template, context, **extra):
            if template.name == template_name:
                captured.append(context.copy())

        template_rendered.connect(capture, app)
        try:
            response = self.client.get(path)
        finally:
            template_rendered.disconnect(capture, app)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(captured), 1)
        return captured[0], response.get_data(as_text=True)

    def test_report_uses_explicit_side_and_preserves_known_zero_and_unknown(self):
        match_id, players, team1_id, team2_id, wrong1_id, wrong2_id = self._match()
        self._stat(
            match_id,
            players["Side One"],
            wrong1_id,
            "t1",
            kills=0,
            deaths=3,
            adr=0,
            kast=None,
            rating=0,
        )
        self._stat(
            match_id,
            players["Side Two"],
            wrong2_id,
            "t2",
            kills=20,
            deaths=10,
            adr=None,
            kast=75,
            rating=None,
        )
        self._stat(
            match_id,
            players["Side One"],
            wrong1_id,
            "t1",
            kills=999,
            deaths=999,
            adr=999,
            kast=99,
            rating=9.99,
            status="superseded",
        )

        report, html = self._context(f"/matches/{match_id}/report", "match_report.html")
        stats = report["team_stats"]
        self.assertEqual((stats["t1_k"], stats["t2_k"]), (0, 20))
        self.assertEqual((stats["t1_d"], stats["t2_d"]), (3, 10))
        self.assertEqual(stats["t1_rating"], 0)
        self.assertEqual(stats["t1_adr"], 0)
        self.assertIsNone(stats["t2_rating"])
        self.assertIsNone(stats["t2_adr"])
        map_report = report["map_reports"][0]
        self.assertEqual(map_report["t1_best"]["nickname"], "Side One")
        self.assertEqual(map_report["t2_best"]["nickname"], "Side Two")
        self.assertIn("0.00", html)
        self.assertGreaterEqual(html.count('class="match-detailed-compare-right">-</span>'), 2)

        detail, _ = self._context(f"/matches/{match_id}/detailed", "match_detailed.html")
        map_card = detail["map_cards"][0]
        self.assertEqual(
            {row["nickname"] for row in map_card["team1_stats"]},
            {"Side One"},
        )
        self.assertEqual([row["nickname"] for row in map_card["team2_stats"]], ["Side Two"])

    def test_legacy_real_team_id_rows_still_fill_the_matching_side(self):
        match_id, players, team1_id, _, _, _ = self._match()
        self._stat(
            match_id,
            players["Legacy One"],
            team1_id,
            None,
            kills=5,
            deaths=2,
            adr=80,
            kast=70,
            rating=1.1,
        )

        report, _ = self._context(f"/matches/{match_id}/report", "match_report.html")
        self.assertEqual(report["team_stats"]["t1_k"], 5)
        self.assertIsNone(report["team_stats"]["t2_k"])
        self.assertEqual(report["map_reports"][0]["t1_best"]["nickname"], "Legacy One")
        self.assertIsNone(report["map_reports"][0]["t2_best"])

        detail, _ = self._context(f"/matches/{match_id}/detailed", "match_detailed.html")
        map_card = detail["map_cards"][0]
        self.assertEqual([row["nickname"] for row in map_card["team1_stats"]], ["Legacy One"])
        self.assertEqual(map_card["team2_stats"], [])

    def test_known_zero_and_unknown_map_scores_stay_distinct(self):
        match_id, players, _, _, wrong1_id, _ = self._match()
        with closing(get_db()) as conn:
            conn.execute("UPDATE matches SET map1_t1=0,map1_t2=NULL WHERE id=?", (match_id,))
            conn.commit()
        self._stat(
            match_id,
            players["Side One"],
            wrong1_id,
            "t1",
            kills=0,
            deaths=0,
            adr=0,
            kast=0,
            rating=0,
        )

        report, html = self._context(f"/matches/{match_id}/report", "match_report.html")
        map_report = report["map_reports"][0]
        self.assertEqual((map_report["t1"], map_report["t2"]), (0, None))
        self.assertTrue(map_report["played"])
        self.assertFalse(map_report["t1_winner"])
        self.assertFalse(map_report["t2_winner"])
        self.assertRegex(
            html,
            r'<span class="map-report-score">\s*<span[^>]*>0</span>\s*'
            r'<span class="sep">:</span>\s*<span[^>]*>-</span>',
        )
        self.assertIn("de_nuke: Report Alpha 0-? Report Beta", html)

    def test_temporary_sides_with_null_team_ids_do_not_match_each_other_or_unknown_rows(self):
        match_id, players, *_ = self._match(temporary=True)
        self._stat(
            match_id,
            players["Side One"],
            None,
            "t1",
            kills=10,
            deaths=5,
            adr=50,
            kast=70,
            rating=1.5,
        )
        self._stat(
            match_id,
            players["Side Two"],
            None,
            "t2",
            kills=20,
            deaths=10,
            adr=60,
            kast=75,
            rating=1.2,
        )
        self._stat(
            match_id,
            players["Unknown"],
            None,
            None,
            kills=999,
            deaths=999,
            adr=999,
            kast=99,
            rating=9.99,
        )

        report, _ = self._context(f"/matches/{match_id}/report", "match_report.html")
        self.assertEqual((report["team_stats"]["t1_k"], report["team_stats"]["t2_k"]), (10, 20))
        self.assertEqual(report["map_reports"][0]["t1_best"]["nickname"], "Side One")
        self.assertEqual(report["map_reports"][0]["t2_best"]["nickname"], "Side Two")
        self.assertEqual(report["mvp"]["nickname"], "Side One")

        detail, _ = self._context(f"/matches/{match_id}/detailed", "match_detailed.html")
        self.assertEqual([row["nickname"] for row in detail["team1_rows"]], ["Side One"])
        self.assertEqual([row["nickname"] for row in detail["team2_rows"]], ["Side Two"])

    def test_multimap_legacy_and_explicit_rows_are_one_player_with_weighted_metrics(self):
        match_id, players, team1_id, _, wrong1_id, _ = self._match()
        with closing(get_db()) as conn:
            conn.execute(
                "UPDATE matches SET bo_format='BO3',map2='de_mirage',map2_t1=13,map2_t2=9 WHERE id=?",
                (match_id,),
            )
            conn.commit()
        for player, first_rating, first_adr, second_rating, second_adr in (
            ("Side One", 2.0, 100, 1.0, 40),
            ("Legacy One", 1.2, 60, 1.2, 60),
        ):
            self._stat(
                match_id,
                players[player],
                team1_id,
                None,
                kills=10,
                deaths=5,
                adr=first_adr,
                kast=80,
                rating=first_rating,
                rounds_played=10,
            )
            self._stat(
                match_id,
                players[player],
                wrong1_id,
                " T1 ",
                kills=20,
                deaths=10,
                adr=second_adr,
                kast=80,
                rating=second_rating,
                map_name="de_mirage",
                rounds_played=20,
            )

        report, _ = self._context(f"/matches/{match_id}/report", "match_report.html")
        self.assertEqual(report["mvp"]["nickname"], "Side One")
        self.assertEqual(report["mvp"]["kills"], 30)
        self.assertEqual(report["mvp"]["rating"], 1.33)
        self.assertEqual(report["team_stats"]["t1_k"], 60)
        self.assertEqual(report["team_stats"]["t1_rating"], 1.27)
        self.assertEqual(report["team_stats"]["t1_adr"], 60)
        self.assertEqual(report["map_reports"][1]["t1_best"]["nickname"], "Legacy One")

    def test_partial_unknown_metrics_are_not_reported_as_complete_totals(self):
        match_id, players, team1_id, *_ = self._match()
        self._stat(
            match_id,
            players["Side One"],
            team1_id,
            "t1",
            kills=None,
            deaths=0,
            adr=None,
            kast=None,
            rating=None,
            rounds_played=20,
        )
        self._stat(
            match_id,
            players["Side One"],
            team1_id,
            "t1",
            kills=15,
            deaths=0,
            adr=50,
            kast=70,
            rating=1.0,
            map_name="de_mirage",
            rounds_played=20,
        )

        report, _ = self._context(f"/matches/{match_id}/report", "match_report.html")
        self.assertIsNone(report["team_stats"]["t1_k"])
        self.assertIsNone(report["team_stats"]["t1_adr"])
        self.assertIsNone(report["team_stats"]["t1_rating"])
        self.assertEqual(report["team_stats"]["t1_d"], 0)


if __name__ == "__main__":
    unittest.main()
