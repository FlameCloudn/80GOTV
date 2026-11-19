"""2026-10-20 实测问题的回归测试：测试比赛编辑、赛事统计口径、闪光弹数据缺失、比赛页筛选等。"""

import json
import os
import tempfile
import unittest
import uuid
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from flask import template_rendered

from app import app
from config import Config
from models import get_db, init_tables
from services.performance_service import build_demo_performance_payload
from services.public_stat_evidence import pistol_match_teams


class SiteReviewFixTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_database = Config.DATABASE
        self.original_config = {
            key: app.config.get(key)
            for key in ("TESTING", "SESSION_COOKIE_SECURE", "PROPAGATE_EXCEPTIONS")
        }
        Config.DATABASE = os.path.join(self.temp.name, "site.db")
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False, PROPAGATE_EXCEPTIONS=False)
        init_tables()
        self.client = app.test_client()
        with closing(get_db()) as conn:
            self.admin_id = conn.execute(
                "INSERT INTO admins(username,password_hash) VALUES(?, 'not-used')",
                ("review-admin-" + uuid.uuid4().hex,),
            ).lastrowid
            self.team_a = conn.execute(
                "INSERT INTO teams(name,short_name) VALUES('Review Alpha','RA')"
            ).lastrowid
            self.team_b = conn.execute(
                "INSERT INTO teams(name,short_name) VALUES('Review Beta','RB')"
            ).lastrowid
            self.player_id = conn.execute(
                "INSERT INTO players(nickname,team_id) VALUES('Review Player',?)", (self.team_a,)
            ).lastrowid
            self.event_id = conn.execute(
                "INSERT INTO events(name,slug,start_date) VALUES('Review Cup','review-cup','2026-10-01')"
            ).lastrowid
            self.other_event = conn.execute(
                "INSERT INTO events(name,slug,start_date) VALUES('Other Cup','other-cup','2026-10-01')"
            ).lastrowid
            self.match_ids = []
            for index in range(3):
                match_id = conn.execute(
                    """INSERT INTO matches(event_id,team1_id,team2_id,status,team1_score,team2_score,match_time,slug)
                       VALUES(?,?,?,'completed',2,0,?,?)""",
                    (
                        self.event_id,
                        self.team_a,
                        self.team_b,
                        f"2026-10-0{index + 1}T12:00",
                        f"review-{index}",
                    ),
                ).lastrowid
                self.match_ids.append(match_id)
                self.add_stat(conn, match_id, "de_mirage")
            # 第一场打了两张图：3 场比赛、4 张地图
            self.add_stat(conn, self.match_ids[0], "de_nuke")
            conn.commit()

    def tearDown(self):
        Config.DATABASE = self.original_database
        app.config.update(self.original_config)
        self.temp.cleanup()

    def add_stat(self, conn, match_id, map_name, flash_count=0, enemy_seconds=3.5):
        conn.execute(
            """INSERT INTO match_stats(match_id,player_id,team_id,map_name,rating,rounds_played,kills,deaths,
                                       flash_count,flash_enemy_seconds,flash_assists)
               VALUES(?,?,?,?,1.2,20,18,12,?,?,1)""",
            (match_id, self.player_id, self.team_a, map_name, flash_count, enemy_seconds),
        )

    def login_admin(self):
        with self.client.session_transaction() as browser:
            browser["admin_id"] = self.admin_id
            browser["admin_username"] = "review-admin"
            browser["csrf_token"] = "review-token"

    def rendered(self, path):
        contexts = []

        def record(sender, template, context, **extra):
            contexts.append(context)

        with template_rendered.connected_to(record, app):
            response = self.client.get(path)
        self.assertEqual(response.status_code, 200, path)
        return contexts[-1], response.get_data(as_text=True)

    def test_test_mode_match_can_be_edited_without_teams(self):
        with closing(get_db()) as conn:
            match_id = conn.execute(
                """INSERT INTO matches(event_id,status,match_time,bo_format,is_test_mode,slug)
                   VALUES(?,'upcoming','2026-10-21T14:00','BO1',1,'review-test-match')""",
                (self.event_id,),
            ).lastrowid
            conn.commit()
        self.login_admin()
        page = self.client.get(f"/admin/matches/edit/{match_id}").get_data(as_text=True)
        self.assertIn("不要求填写参赛队伍或选手", page)
        self.assertIn("function isTestMatch()", page)
        # 不依赖表单里的测试标记：以数据库里的“测试比赛”为准
        response = self.client.post(
            f"/admin/matches/edit/{match_id}",
            data={
                "csrf_token": "review-token",
                "event_id": str(self.event_id),
                "match_time": "2026-10-21T14:00",
                "bo_format": "BO1",
                "stage": "半决赛 1",
                "status": "upcoming",
                "side1_type": "team",
                "side1_id": "",
                "side2_type": "team",
                "side2_id": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        with closing(get_db()) as conn:
            row = conn.execute(
                "SELECT stage, team1_id, team2_id FROM matches WHERE id=?", (match_id,)
            ).fetchone()
        self.assertEqual((row["stage"], row["team1_id"], row["team2_id"]), ("半决赛 1", None, None))

    def test_event_stats_count_matches_and_maps_separately(self):
        context, html = self.rendered("/events/review-cup/stats")
        player = context["rankings"][0]
        self.assertEqual((player["matches"], player["maps"]), (3, 4))
        self.assertEqual(context["team_count"], 2)
        self.assertIn("<th>比赛数</th><th>地图数</th>", html)

    def test_flash_payload_counts_throws_and_keeps_missing_data_unknown(self):
        flashed = {
            "flasherSteamId": "11",
            "flasherName": "A",
            "flasherSide": 2,
            "flashedSteamId": "22",
            "flashedName": "B",
            "flashedSide": 3,
            "duration": 2.0,
        }
        explosions = [{"throwerSteamId": "11", "throwerName": "A"}] * 3
        payload = build_demo_performance_payload(
            {"playersFlashed": [flashed], "flashbangsExplode": explosions}
        )
        counts = {item["steam_id"]: item["flash_count"] for item in payload["flash_metrics"]}
        self.assertEqual(counts, {"11": 3, "22": 0})
        legacy = build_demo_performance_payload({"playersFlashed": [flashed]})
        self.assertTrue(all(item["flash_count"] is None for item in legacy["flash_metrics"]))

    def test_flash_ranking_shows_missing_throws_as_no_data(self):
        _, html = self.rendered("/stats/overview/flashes")
        self.assertIn('<span class="stat-missing">暂无数据</span>', html)
        with closing(get_db()) as conn:
            conn.execute(
                "UPDATE match_stats SET flash_count=4 WHERE match_id=? AND map_name='de_mirage'",
                (self.match_ids[1],),
            )
            conn.commit()
        context, _ = self.rendered("/stats/overview/flashes")
        self.assertAlmostEqual(context["rows"][0]["thrown"], 4.0)

    def test_matches_completed_hint_respects_event_filter(self):
        context, _ = self.rendered(f"/matches?event={self.other_event}&date=2026-10-01")
        self.assertEqual(context["completed_on_selected_date"], 0)
        context, html = self.rendered(f"/matches?event={self.event_id}&date=2026-10-01")
        self.assertEqual(context["completed_on_selected_date"], 1)
        self.assertIn(f"/results?event={self.event_id}", html)
        # 日历和“全部日期”链接都保留赛事条件
        self.assertIn(f"event={self.event_id}&amp;month=2026-10", html)

    def test_pistol_rounds_prefer_reviewed_rounds_and_do_not_revive_unofficial_cache(self):
        mid, legacy, managed = self.match_ids
        root = Path(self.temp.name)
        cache, analysis = root / "csda_cache", root / "static/demos/analysis"
        cache.mkdir()
        analysis.mkdir(parents=True)
        pistol = {
            "number": 1,
            "teamAEconomyType": "pistol",
            "teamASide": 3,
            "teamBSide": 2,
            "winnerSide": 3,
        }
        rounds = [pistol, {"number": 2, "teamASide": 3, "teamBSide": 2, "winnerSide": 2}]
        for match, slot, name in (
            (mid, 0, "Mirage"),
            (legacy, 0, "Mirage"),
            (legacy, 1, "Vertigo"),
            (managed, 0, "Mirage"),
        ):
            (cache / f"match_{match}_slot_{slot}.json").write_text(
                json.dumps({"mapName": name, "teamA": {"name": "Review Alpha"}, "rounds": rounds}),
                encoding="utf-8",
            )
        filename = "f" * 32 + ".json"
        (analysis / filename).write_text(
            json.dumps({"raw_events": {"rounds": rounds}}), encoding="utf-8"
        )
        with closing(get_db()) as conn:
            conn.execute("UPDATE matches SET map1='Mirage', map2='Vertigo'")
            conn.execute("UPDATE matches SET event_id=? WHERE id=?", (self.other_event, managed))
            conn.execute(
                """INSERT INTO event_registration_control(event_id,registration_deadline,enabled_by,enabled_at)
                   VALUES(?,2,?,1)""",
                (self.other_event, self.admin_id),
            )
            conn.execute(
                "UPDATE matches SET map_halves=? WHERE id=?",
                (
                    json.dumps(
                        {
                            "0": {
                                "analysis": {
                                    "snapshot": f"analysis/{filename}",
                                    "data_version": 1,
                                    "demo_a_to_t1": False,
                                }
                            }
                        }
                    ),
                    mid,
                ),
            )
            conn.commit()
        self.addCleanup(setattr, app, "static_folder", app.static_folder)
        app.static_folder = str(root / "static")
        with patch.object(app, "instance_path", str(root)):
            path = "/stats/overview/pistol-rounds"
            context, _ = self.rendered(path)
            rows = {r["team_name"]: r for r in context["rows"]}
            self.assertEqual(
                [(r["maps"], r["won"], r["lost"]) for r in rows.values()], [(2, 1, 1)] * 2
            )
            ct, _ = self.rendered(path + "?side=ct")
            self.assertEqual(
                [(r["maps"], r["won"], r["lost"]) for r in ct["rows"]], [(1, 1, 0)] * 2
            )
            for query in (f"event={self.other_event}", "map=Vertigo"):
                self.assertEqual(self.rendered(path + "?" + query)[0]["rows"], [])

    def test_weapon_chart_filters_the_killers_side_event_and_game_ownership(self):
        legacy, other, managed = self.match_ids
        with closing(get_db()) as conn:
            managed_event = conn.execute("INSERT INTO events(name) VALUES('托管赛')").lastrowid
            conn.execute("UPDATE matches SET event_id=? WHERE id=?", (self.other_event, other))
            conn.execute("UPDATE matches SET event_id=? WHERE id=?", (managed_event, managed))
            conn.execute(
                """INSERT INTO event_registration_control(event_id,registration_deadline,enabled_by,enabled_at)
                   VALUES(?,2,?,1)""",
                (managed_event, self.admin_id),
            )
            conn.executemany(
                "INSERT INTO match_kill_events(match_id,map_name,killer_side,weapon) VALUES(?,'de_mirage',?,?)",
                [
                    (legacy, "CT", "m4a1"),
                    (legacy, "T", "ak47"),
                    (other, "CT", "awp"),
                    (managed, "CT", "deagle"),
                ],
            )
            conn.commit()
        path = f"/stats?map=Mirage&side=ct&event={self.event_id}"
        context, _ = self.rendered(path)
        self.assertEqual([w["name"] for w in context["overview"]["top_weapons"]], ["m4a1"])
        context, _ = self.rendered("/stats")
        self.assertEqual(
            {w["name"] for w in context["overview"]["top_weapons"]}, {"m4a1", "ak47", "awp"}
        )

    def test_unnamed_temp_teams_do_not_invent_side_names(self):
        with closing(get_db()) as conn:
            match_id = conn.execute(
                """INSERT INTO matches(event_id,team1_players,team2_players,status,team1_score,team2_score,match_time,slug)
                   VALUES(?,?,?,'completed',2,0,'2026-10-05T12:00','review-temp')""",
                (self.event_id, json.dumps([self.player_id, 98]), json.dumps([97, 96])),
            ).lastrowid
            conn.commit()
            names = pistol_match_teams(conn, {match_id})[match_id]
        self.assertEqual((names["t1_name"], names["t2_name"]), ("TBD", "TBD"))
        self.login_admin()
        page = self.client.get("/admin/news/add").get_data(as_text=True)
        self.assertIn("TBD 2:0 TBD", page)
        self.assertNotIn("TEAM 1 2:0 TEAM 2", page)

    def test_team_links_and_headers_point_to_the_right_place(self):
        _, overview = self.rendered("/stats")
        self.assertIn(f'href="/teams/{self.team_a}" class="overview-rank-row"', overview)
        _, top_events = self.rendered("/stats/overview/top-events")
        self.assertIn("<th>冠军队伍</th>", top_events)
        self.assertNotIn("冠军选手", top_events)

    def test_compare_side_tabs_keep_selected_players(self):
        _, html = self.rendered(f"/stats?tab=compare&id1={self.player_id}&id2={self.player_id}")
        self.assertIn(f"side=ct&id1={self.player_id}&id2={self.player_id}", html)

    def test_bracket_editor_loads_dialog_helpers_first(self):
        self.login_admin()
        page = self.client.get(f"/admin/events/{self.event_id}/bracket").get_data(as_text=True)
        self.assertLess(page.index("js/site_dialogs.js"), page.index("js/bracket_editor.js"))


if __name__ == "__main__":
    unittest.main()
