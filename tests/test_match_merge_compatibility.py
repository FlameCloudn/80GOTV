import os
import re
import tempfile
import unittest

from flask import template_rendered

from app import app
from config import Config
from models import get_db, init_tables


class MatchMergeCompatibilityTests(unittest.TestCase):
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
        try:
            team1 = conn.execute("INSERT INTO teams(name) VALUES('Merge Alpha')").lastrowid
            team2 = conn.execute("INSERT INTO teams(name) VALUES('Merge Bravo')").lastrowid
            self.player_id = conn.execute(
                "INSERT INTO players(nickname,team_id) VALUES('Merge Player',?)", (team1,)
            ).lastrowid
            self.match_id = conn.execute(
                """INSERT INTO matches(team1_id,team2_id,status,bo_format,team1_score,team2_score,
                           map1,map1_t1,map1_t2)
                   VALUES(?,?,'completed','BO1',1,0,'de_mirage',13,7)""",
                (team1, team2),
            ).lastrowid
            self.team1_id = team1
            conn.commit()
        finally:
            conn.close()
        self.client = app.test_client()

    def tearDown(self):
        Config.DATABASE = self.original_database
        app.config.update(
            TESTING=self.original_testing, SESSION_COOKIE_SECURE=self.original_secure_cookie
        )
        os.remove(self.database_path)

    def _save_stat(self, value):
        conn = get_db()
        try:
            conn.execute(
                """INSERT INTO match_stats(match_id,player_id,team_id,map_name,
                           kills,deaths,assists,adr,kast,rating,rounds_played)
                   VALUES(?,?,?,'de_mirage',?,?,?,?,?,?,20)""",
                (self.match_id, self.player_id, self.team1_id, *([value] * 6)),
            )
            fields = (
                "kpr",
                "dpr",
                "impact",
                "rws_basic",
                "headshot_percentage",
                "first_kills",
                "first_deaths",
                "multi2k",
                "multi3k",
                "multi4k",
                "multi5k",
                "clutches_won",
                "clutch_1v1",
                "clutch_1v2",
                "clutch_1v3",
                "clutch_1v4",
                "clutch_1v5",
                "trade_kills",
                "trade_deaths",
                "enemies_flashed",
                "utility_damage",
                "damage_delta_per_round",
                "t_kills",
                "t_deaths",
                "t_adr",
                "t_rating",
                "ct_kills",
                "ct_deaths",
                "ct_adr",
                "ct_rating",
            )
            conn.execute(
                "UPDATE match_stats SET " + ",".join(f"{field}=?" for field in fields),
                (value,) * len(fields),
            )
            conn.commit()
            return tuple(conn.execute("SELECT * FROM match_stats").fetchone())
        finally:
            conn.close()

    def _report(self):
        response = self.client.get(f"/matches/{self.match_id}/report")
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def _detailed(self, map_index):
        contexts = []

        def capture(_sender, template, context, **_extra):
            if template.name == "match_detailed.html":
                contexts.append(context)

        with template_rendered.connected_to(capture, app):
            response = self.client.get(
                f"/matches/{self.match_id}/detailed?map={map_index}&tab=performance"
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(contexts), 1)
        return contexts[0], response.get_data(as_text=True)

    def test_new_report_accepts_unknown_stats_without_formatting_them_as_zero(self):
        before = self._save_stat(None)
        html = self._report()
        self.assertEqual(
            re.findall(r'class="best-player-rating[^\"]*">([^<]*)</span>', html), ["-"]
        )
        self.assertIn("K-D ---", html)
        self.assertIn("ADR -", html)
        mvp_values = re.findall(r'class="mvp-stat-val[^\"]*">([^<]*)</div>', html)
        self.assertEqual(mvp_values, ["-", "---", "-", "-"])
        conn = get_db()
        try:
            self.assertEqual(tuple(conn.execute("SELECT * FROM match_stats").fetchone()), before)
        finally:
            conn.close()

    def test_new_report_keeps_recorded_zero_stats_visible(self):
        self._save_stat(0)
        html = self._report()
        self.assertEqual(
            re.findall(r'class="best-player-rating[^\"]*">([^<]*)</span>', html), ["0.00"]
        )
        self.assertIn("K-D 0-0", html)
        self.assertIn("ADR 0.0", html)
        mvp_values = re.findall(r'class="mvp-stat-val[^\"]*">([^<]*)</div>', html)
        self.assertEqual(mvp_values, ["0.00", "0-0", "0.0", "0.0%"])

    def test_main_match_and_stats_pages_accept_missing_side_metrics_after_slug_redirect(self):
        self._save_stat(None)
        conn = get_db()
        try:
            conn.execute(
                "UPDATE matches SET slug='merge-compat-series' WHERE id=?", (self.match_id,)
            )
            conn.commit()
        finally:
            conn.close()
        for path in (f"/matches/{self.match_id}", "/matches/merge-compat-series/stats"):
            with self.subTest(view=path):
                response = self.client.get(path, follow_redirects=True)
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                if path.endswith("/stats"):
                    self.assertIn('class="panel match-stats-hero-card"', html)
                for side in ("t", "ct"):
                    cells = re.findall(rf'<td class="kd-cell col-{side}">([^<]*)</td>', html)
                    self.assertTrue(cells)
                    self.assertEqual(cells[-1], "---")

    def test_main_match_and_stats_pages_keep_real_zero_side_metrics(self):
        self._save_stat(0)
        for suffix in ("", "/stats"):
            with self.subTest(view=suffix or "match"):
                response = self.client.get(
                    f"/matches/{self.match_id}{suffix}", follow_redirects=True
                )
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                for side in ("t", "ct"):
                    cells = re.findall(rf'<td class="kd-cell col-{side}">([^<]*)</td>', html)
                    self.assertTrue(cells)
                    self.assertTrue(all(cell == "0-0" for cell in cells))

    def test_new_performance_route_preserves_unknown_metrics_on_all_and_one_map(self):
        before = self._save_stat(None)
        for map_index in ("all", "1"):
            with self.subTest(map=map_index):
                context, html = self._detailed(map_index)
                row = context["team1_rows"][0]
                for field in (
                    "kills",
                    "deaths",
                    "assists",
                    "adr",
                    "kast",
                    "rating",
                    "impact",
                    "kpr",
                    "dpr",
                    "mk_rating",
                    "rws",
                    "first_kills",
                    "first_deaths",
                    "multi_kills",
                    "headshot_kills",
                    "opening_diff",
                ):
                    self.assertIsNone(row[field], field)
                self.assertEqual([bar["text"] for bar in row["perf_bars"]], ["-"] * 7)
                self.assertTrue(all(bar["pct"] == 0 for bar in row["perf_bars"]))
                self.assertTrue(all(bar["tier"] != "perf-top" for bar in row["perf_bars"]))
                self.assertIn('class="perf-kd" title="击杀-死亡">---', html)
        conn = get_db()
        try:
            self.assertEqual(tuple(conn.execute("SELECT * FROM match_stats").fetchone()), before)
        finally:
            conn.close()

    def test_new_performance_route_keeps_measured_zero_on_all_and_one_map(self):
        self._save_stat(0)
        for map_index in ("all", "1"):
            with self.subTest(map=map_index):
                context, html = self._detailed(map_index)
                row = context["team1_rows"][0]
                for field in ("kills", "deaths", "rating", "kpr", "dpr", "adr", "kast", "rws"):
                    self.assertEqual(row[field], 0, field)
                self.assertEqual(
                    [bar["text"] for bar in row["perf_bars"]],
                    ["0.00", "0.00", "0.0%", "0.00", "0.00", "0.0", "0.00"],
                )
                self.assertIn('class="perf-kd" title="击杀-死亡">0-0', html)

    def test_new_performance_averages_only_recorded_values_without_changing_weights(self):
        self._save_stat(None)
        conn = get_db()
        try:
            conn.execute(
                "UPDATE matches SET bo_format='BO3',team1_score=2,map2='de_nuke' WHERE id=?",
                (self.match_id,),
            )
            conn.execute(
                """INSERT INTO match_stats(match_id,player_id,team_id,map_name,
                           kills,deaths,assists,rating,adr,kast,kpr,dpr,impact,rws_basic,rounds_played)
                   VALUES(?,?,?,'de_nuke',20,10,5,2.0,100,80,1.0,0.5,1.2,10,40)""",
                (self.match_id, self.player_id, self.team1_id),
            )
            conn.commit()
        finally:
            conn.close()
        context, _html = self._detailed("all")
        row = context["team1_rows"][0]
        self.assertEqual(
            (row["rating"], row["adr"], row["kpr"], row["dpr"]), (2.0, 100.0, 1.0, 0.5)
        )
        self.assertEqual((row["kills"], row["deaths"], row["assists"]), (20, 10, 5))
        conn = get_db()
        try:
            conn.execute(
                "UPDATE match_stats SET rating=0,adr=0,kpr=0,dpr=0 WHERE map_name='de_mirage'"
            )
            conn.commit()
        finally:
            conn.close()
        context, _html = self._detailed("all")
        row = context["team1_rows"][0]
        self.assertEqual(
            (row["rating"], row["adr"], row["kpr"], row["dpr"]), (1.33, 66.7, 0.67, 0.33)
        )


if __name__ == "__main__":
    unittest.main()
