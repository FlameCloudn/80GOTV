"""Hosted statistics through the original website, on an isolated SQLite database."""

import json
import sqlite3
import unittest
from contextlib import closing

from flask import template_rendered

from app import app
from models import get_db
from services.bracket_service import configure_bracket_link, create_bracket_match
from services.performance_service import refresh_player_performance
from site_core.host import HostError, write
from site_core.matches import maps, operations, participants, results, statistics
from tests import test_host_bp_maps
from tests.entrant_slice_fixtures import ORGANIZER_ID
from utils.helpers import normalize_map_key


class HostOperationsStatsTests(unittest.TestCase):
    def setUp(self):
        base = test_host_bp_maps.HostedBPTests()
        self.addCleanup(base.doCleanups)
        base.setUp()
        self.admin = base.admin
        self.match = base._new_match(
            "BO3", setup={"map1": "de_mirage", "map2": "de_mirage", "map3": "de_nuke"}
        )
        self.db = self.enterContext(closing(get_db()))
        self.player, self.other, self.late, self.absent = (p.player_id for p in base.people[:4])
        with write(self.db):
            self.db.execute(
                """UPDATE matches SET slug='host-stats-fixture',bp_state='{"status":"completed"}'
                   WHERE id=?""",
                (self.match,),
            )
            # No Steam profile fetches are needed for the public requests.
            self.db.execute("UPDATE players SET avatar='fixture.png',real_name='fixture'")
            operations.authorize(self.db, self.match, ORGANIZER_ID)
        self.scheduled = [
            row["scheduled_map_id"] for row in results.read_results(self.db, self.match)["maps"]
        ]
        self.event = self.db.execute(
            "SELECT event_id FROM matches WHERE id=?", (self.match,)
        ).fetchone()[0]
        self.visitor = app.test_client()

    def _start(self, slot):
        return operations.observe_start(
            self.db, self.match, self.scheduled[slot], source="director", evidence="实际开图"
        )

    def _record(self, run, player):
        party = self.db.execute(
            "SELECT match_participant_id FROM map_run_lineups WHERE map_run_id=? AND player_id=?",
            (run, player),
        ).fetchone()[0]
        return operations.record_participation(self.db, run, player, party, source="director")

    def _apply(self, run, player, scope, fields):
        return statistics.apply_fields(
            self.db, run, player, scope, fields, source="director", actor="director"
        )

    def _confirm(self, slot, run, score1, score2):
        current = results.read_results(self.db, self.match)["maps"][slot]
        return results.confirm_map(
            self.db,
            self.match,
            self.scheduled[slot],
            run,
            score1,
            score2,
            actor=ORGANIZER_ID,
            source="admin",
            expected_revision=current["revision"],
        )

    def _page(self, path, template_name, *, with_html=False):
        rendered = []

        def capture(sender, template, context, **extra):
            if template.name == template_name:
                rendered.append(context)

        with template_rendered.connected_to(capture, app):
            response = self.visitor.get(path)
        self.assertEqual(response.status_code, 200, path)
        self.assertTrue(response.get_data())
        self.assertEqual(len(rendered), 1, path)
        return (rendered[0], response.get_data(as_text=True)) if with_html else rendered[0]

    def _summary(self, player):
        return self.db.execute(
            "SELECT * FROM player_performance_summary WHERE player_id=?", (player,)
        ).fetchone()

    def test_event_rankings_bracket_popups_and_home_read_official_samples(self):
        with write(self.db):
            pending = create_bracket_match(
                self.db,
                self.event,
                bo_format="BO1",
                stage="决赛",
                actor=ORGANIZER_ID,
            )["match_id"]
            configure_bracket_link(
                self.db,
                self.match,
                "winner",
                pending,
                "home",
                actor=ORGANIZER_ID,
            )
            old = self._start(0)
            self._record(old, self.absent)
            self._apply(old, self.absent, "all", {"rounds": 20, "rating": 3.5})
            self._confirm(0, old, 13, 7)
            operations.technical_replay(
                self.db,
                self.match,
                old,
                admin_id=ORGANIZER_ID,
                reason="原局作废",
            )
            first = self._start(0)
            self._record(first, self.player)
            self._apply(first, self.player, "all", {"rounds": 4, "damage": 0, "rating": 0})
            self._record(first, self.other)
            self._apply(
                first,
                self.other,
                "all",
                {"rounds": 4, "damage": 0, "kills": 0, "deaths": 2, "rating": 0, "kast": 0},
            )
            self._record(first, self.late)
            self._confirm(0, first, 13, 7)

            second = self._start(1)
            self._record(second, self.player)
            self._apply(second, self.player, "all", {"rounds": 12, "damage": 960, "rating": 1.6})
            self._confirm(1, second, 8, 13)

            third = self._start(2)
            self._record(third, self.player)
            self._apply(third, self.player, "all", {"rounds": 18})
            self._confirm(2, third, 13, 10)
            results.settle_series(self.db, self.match, actor=ORGANIZER_ID)

            extra = create_bracket_match(
                self.db,
                self.event,
                bo_format="BO1",
                stage="小组赛",
                actor=ORGANIZER_ID,
                match_time="2027-01-17T13:00:00",
            )["match_id"]
            fixed = dict(
                self.db.execute(
                    "SELECT side_key,event_entrant_id FROM match_participants WHERE match_id=?",
                    (self.match,),
                )
            )
            participants.bind(self.db, extra, fixed["home"], fixed["away"])
            participants.freeze_rosters(self.db, extra, ORGANIZER_ID)
            maps.sync_scheduled_maps(self.db, extra, setup={"map1": "de_ancient"})
            self.db.execute(
                """UPDATE matches SET bp_state='{"status":"completed"}' WHERE id=?""", (extra,)
            )
            operations.authorize(self.db, extra, ORGANIZER_ID)
            extra_map = maps.list_scheduled_maps(self.db, extra)[0]["scheduled_map_id"]
            extra_run = operations.observe_start(
                self.db,
                extra,
                extra_map,
                source="director",
                evidence="实际开图",
            )
            self._record(extra_run, self.player)
            self._apply(extra_run, self.player, "all", {"rounds": 16, "rating": 1.8})
            results.confirm_map(
                self.db,
                extra,
                extra_map,
                extra_run,
                13,
                8,
                source="admin",
                actor=ORGANIZER_ID,
                expected_revision=0,
            )

        path = f"/events/{self.event}"
        event_stats, html = self._page(f"{path}/stats", "event_stats.html", with_html=True)
        ranked = {row["id"]: row for row in event_stats["rankings"]}
        self.assertEqual(set(ranked), {self.player, self.other, self.late})
        self.assertEqual((ranked[self.player]["matches"], ranked[self.player]["maps"]), (2, 4))
        self.assertEqual(ranked[self.player]["team"], "Harbor")
        self.assertAlmostEqual(ranked[self.player]["rating"], 1.5)
        self.assertEqual(ranked[self.player]["adr"], 60)
        self.assertEqual((ranked[self.other]["kd"], ranked[self.other]["adr"]), (0, 0))
        self.assertEqual(ranked[self.late]["maps"], 1)
        self.assertIsNone(ranked[self.late]["rating"])
        self.assertIsNone(ranked[self.late]["adr"])
        by_map = {normalize_map_key(row["map_name"]): row for row in event_stats["map_stats"]}
        self.assertEqual(by_map["mirage"]["times_played"], 2)
        self.assertIsNone(by_map["nuke"]["avg_rating"])
        self.assertIn('<td data-val="60.0">60.0</td>', html)
        self.assertIn('<td data-val="0.0">0.00</td>', html)
        self.assertIn('<td data-val="None">-</td>', html)

        event, html = self._page(path, "event_detail.html", with_html=True)
        rosters = event["match_players_map"]
        final_ratings = {p["id"]: p["rating"] for p in rosters[self.match][1]}
        next_ratings = {p["id"]: p["rating"] for p in rosters[pending][1]}
        self.assertEqual((final_ratings[self.player], next_ratings[self.player]), (1.2, 1.5))
        self.assertEqual(final_ratings[self.other], 0)
        self.assertIsNone(final_ratings[self.absent])
        self.assertIn('class="bp-player-rating">1.20</span>', html)
        self.assertIn('class="bp-player-rating">1.50</span>', html)

        home, html = self._page("/", "index.html", with_html=True)
        top_players = {row["id"]: row["avg_rating"] for row in home["top_players"]}
        self.assertAlmostEqual(top_players[self.player], 1.5)
        self.assertEqual(top_players[self.other], 0)
        self.assertIsNone(top_players[self.late])
        self.assertIn('class="num rt-4">1.50</b>', html)

    def test_current_public_pages_count_same_name_slots_and_use_actual_side_rounds(self):
        with write(self.db):
            first = self._start(0)
            self._record(first, self.player)
            self._apply(first, self.player, "all", {"rounds": 20, "kills": 10, "damage": 600})
            self._apply(first, self.player, "ct", {"rounds": 4, "kills": 0, "damage": 0, "kast": 0})
            self.assertIsNone(self._summary(self.player))
            self._confirm(0, first, 13, 9)
            self._record(first, self.late)

            second = self._start(1)
            self._record(second, self.player)
            self._apply(second, self.player, "all", {"rounds": 20, "kills": 14, "damage": 1600})
            self._apply(
                second, self.player, "ct", {"rounds": 12, "kills": 12, "damage": 960, "kast": 80}
            )
            self._confirm(1, second, 8, 13)

            third = self._start(2)
            self._record(third, self.player)
            self._apply(third, self.player, "all", {"rounds": 18, "kills": 7, "damage": 900})
            self._confirm(2, third, 13, 10)
            results.settle_series(self.db, self.match, actor=ORGANIZER_ID)

        self.assertEqual(self._summary(self.player)["avg_ct_adr"], 60)
        self.assertEqual(self._summary(self.late)["maps"], 1)
        self.assertIsNone(self._summary(self.absent))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM match_stats").fetchone()[0], 0)
        all_rows = self._page("/stats?tab=players", "stats.html")["rankings"]
        all_rows = {row["id"]: row for row in all_rows}
        self.assertEqual((all_rows[self.player]["maps"], all_rows[self.player]["kills"]), (3, 31))
        self.assertEqual(all_rows[self.late]["maps"], 1)
        for key in ("kills", "deaths", "rounds", "rating", "adr"):
            self.assertIsNone(all_rows[self.late][key])

        ct_rows = self._page(f"/stats?tab=players&side=ct&event={self.event}", "stats.html")[
            "rankings"
        ]
        ct = next(row for row in ct_rows if row["id"] == self.player)
        self.assertEqual(
            (ct["maps"], ct["rounds"], ct["kills"], ct["adr"], ct["kast"]), (3, 16, 12, 60, 60)
        )
        detail = self._page(f"/stats/players/{self.player}?side=ct", "player_stats.html")["overall"]
        self.assertEqual(
            (detail["maps"], detail["rounds_played"], detail["avg_kpr"], detail["avg_adr"]),
            (3, 16, 0.75, 60),
        )
        profile = self._page(f"/players/{self.player}", "player_detail.html")
        self.assertEqual(profile["player_summary"]["maps"], 3)
        empty = self._page(f"/players/{self.late}", "player_detail.html")["player_summary"]
        self.assertEqual(empty["maps"], 1)
        self.assertIsNone(empty["kpr"])
        compare = self._page(
            f"/stats?tab=compare&side=ct&id1={self.player}&id2={self.late}", "stats.html"
        )["comparison"]["left"]
        self.assertEqual((compare["kpr"], compare["adr"]), (0.75, 60))

        maps = self._page("/stats?tab=maps&map=Mirage", "stats.html")["map_stats"]
        self.assertEqual([row["times_played"] for row in maps], [2])
        matches = self._page("/stats?tab=matches&map=Mirage", "stats.html")["matches"]
        self.assertEqual(next(row["maps"] for row in matches if row["id"] == self.match), 3)
        normal = self._page("/matches/host-stats-fixture/stats", "match_detail.html")
        self.assertEqual(
            [
                next(row["kills"] for row in m["team1_stats"] if row["player_id"] == self.player)
                for m in normal["map_scores"][:2]
            ],
            [10, 14],
        )
        expected = [(13, 9, 10), (8, 13, 14)]
        for slot, (score1, score2, kills) in enumerate(expected, 1):
            detailed = self._page(
                f"/matches/host-stats-fixture/detailed?map={slot}", "match_detailed.html"
            )
            actual = next(
                row for row in detailed["performance_rows"] if row["player_id"] == self.player
            )
            self.assertEqual(
                (detailed["score_t1"], detailed["score_t2"], actual["kills"]),
                (score1, score2, kills),
            )
            if slot == 1:
                self.assertEqual(actual["side_views"]["ct"]["kills"], 0)
        detailed = self._page("/matches/host-stats-fixture/detailed", "match_detailed.html")
        actual = next(
            row for row in detailed["performance_rows"] if row["player_id"] == self.player
        )
        self.assertEqual((actual["maps"], actual["ct_adr"]), (3, 60))

    def test_replay_is_read_only_and_withdrawn_participation_can_restore_its_own_stats(self):
        with write(self.db):
            old = self._start(0)
            self._record(old, self.player)
            self._record(old, self.other)
            self._apply(old, self.player, "all", {"rounds": 10, "kills": 8})
            self._apply(old, self.other, "all", {"kills": 99})
            self._confirm(0, old, 13, 7)
        self.assertEqual(self._summary(self.other)["total_kills"], 99)
        with write(self.db):
            operations.technical_replay(
                self.db, self.match, old, admin_id=ORGANIZER_ID, reason="重赛"
            )
        self.assertIsNone(self._summary(self.other))
        historical = statistics.read_fields(self.db, old, self.player, "all")
        self.assertEqual(
            (historical["run_status"], historical["editable"], historical["fields"]["kills"]),
            ("void", False, 8),
        )
        with self.assertRaises(HostError), write(self.db):
            statistics.apply_fields(
                self.db,
                old,
                self.player,
                "all",
                {"kills": 20},
                source="admin",
                actor=ORGANIZER_ID,
                reason="不可修改原局",
                expected=historical["revision"],
                confirm=True,
            )

        with write(self.db):
            replay = self._start(0)
            self._record(replay, self.player)
            new_participation = self._record(replay, self.late)
            self._apply(replay, self.player, "all", {"rounds": 20, "kills": 12})
            self._apply(replay, self.late, "all", {"rounds": 20, "kills": 0})
            self._confirm(0, replay, 13, 7)
        self.assertEqual(
            (self._summary(self.player)["maps"], self._summary(self.player)["avg_kpr"]), (1, 0.6)
        )
        with self.assertRaisesRegex(RuntimeError, "回滚"), write(self.db):
            operations.review_participation(
                self.db,
                self.match,
                new_participation,
                present=False,
                expected_revision=1,
                admin_id=ORGANIZER_ID,
                reason="核对误认",
            )
            self.assertIsNone(self._summary(self.late))
            raise RuntimeError("模拟调用方回滚")
        self.assertEqual(self._summary(self.late)["total_kills"], 0)
        with write(self.db):
            operations.review_participation(
                self.db,
                self.match,
                new_participation,
                present=False,
                expected_revision=1,
                admin_id=ORGANIZER_ID,
                reason="核对误认",
            )
        self.assertIsNone(self._summary(self.late))
        read = statistics.read_fields(self.db, replay, self.late, "all")
        self.assertEqual((read["editable"], read["fields"]["kills"]), (False, 0))
        with self.assertRaises(HostError), write(self.db):
            self._apply(replay, self.late, "all", {"assists": 2})
        with write(self.db):
            operations.review_participation(
                self.db,
                self.match,
                new_participation,
                present=True,
                expected_revision=2,
                admin_id=ORGANIZER_ID,
                reason="恢复已核实出场",
            )
        self.assertEqual(self._summary(self.late)["total_kills"], 0)
        detailed = self._page("/matches/host-stats-fixture/detailed?map=1", "match_detailed.html")
        self.assertEqual(
            {row["player_id"]: row["kills"] for row in detailed["performance_rows"]},
            {self.player: 12, self.late: 0},
        )

    def test_fields_diff_adoption_and_stale_admin_baseline(self):
        with write(self.db):
            run = self._start(0)
            self._record(run, self.player)
            self._confirm(0, run, 13, 7)
            with self.assertRaises(HostError):
                self._apply(run, self.absent, "all", {"kills": 5})
            old = self._apply(run, self.player, "all", {"rounds": 20, "kills": 13})
        prefix = f"/admin/matches/{self.match}/operations"
        read_url = f"{prefix}/runs/{run}/players/{self.player}/stats"
        read = self.admin.get(read_url).get_json()
        self.assertEqual(read["revision"], old["revision"])
        self.assertEqual(read["fields"], {"rounds_played": 20, "kills": 13})
        payload = {
            "map_run_id": run,
            "player_id": self.player,
            "fields": {"kills": 12},
            "expected_revision": read["revision"],
            "reason": "逐回合核对",
        }
        headers = {"X-CSRF-Token": "host-bp-fixture"}
        preview = self.admin.post(f"{prefix}/preview-stats", json=payload, headers=headers)
        self.assertEqual(preview.status_code, 200)
        self.assertFalse(preview.get_json()["applied"])
        self.assertEqual(preview.get_json()["changes"]["kills"]["before"], 13)
        self.assertEqual(self._summary(self.player)["total_kills"], 13)
        save = self.admin.post(f"{prefix}/stats", json=payload, headers=headers)
        self.assertEqual(save.status_code, 200)
        self.assertTrue(save.get_json()["applied"])
        stale = self.admin.post(
            f"{prefix}/stats", json={**payload, "fields": {"kills": 11}}, headers=headers
        )
        self.assertEqual((stale.status_code, stale.get_json()["status"]), (409, "stale"))

        source = {"kind": "demo", "ref": "demo:1/analysis:1", "method": "fixture-v1"}
        with write(self.db):
            result = statistics.apply_fields(
                self.db,
                run,
                self.player,
                "all",
                {"kills": 11, "damage": 0, "deaths": None},
                source=source,
                actor=ORGANIZER_ID,
            )
        self.assertEqual(set(result["changes"]), {"damage"})
        self.assertEqual(set(result["conflicts"]), {"kills"})
        state = statistics.read_fields(self.db, run, self.player, "all")
        self.assertEqual(state["field_sources"]["kills"]["actor"], ORGANIZER_ID)
        self.assertEqual(state["field_sources"]["damage"]["source_ref"], source["ref"])
        self.assertNotIn("deaths", state["fields"])
        self.assertEqual(self._summary(self.player)["avg_adr"], 0)
        audit = self.db.execute(
            "SELECT changes_json FROM run_stats_revisions WHERE map_run_id=? AND revision=?",
            (run, save.get_json()["revision"]),
        ).fetchone()[0]
        self.assertEqual(json.loads(audit)["kills"]["previous_source"]["source"], "director")
        with write(self.db):
            self.db.execute("UPDATE matches SET status='cancelled' WHERE id=?", (self.match,))
            self.assertFalse(statistics.read_fields(self.db, run, self.player, "all")["editable"])
            with self.assertRaises(HostError):
                self._apply(run, self.player, "all", {"assists": 2})
            self.db.execute("UPDATE matches SET status='live' WHERE id=?", (self.match,))
            self.db.execute(
                "UPDATE event_registration_control SET archived_at=1 WHERE event_id=?",
                (self.event,),
            )
            self.assertFalse(statistics.read_fields(self.db, run, self.player, "all")["editable"])
            with self.assertRaises(HostError):
                self._apply(run, self.player, "all", {"assists": 2})

    def test_legacy_writers_and_published_awards_remain_separate(self):
        with write(self.db):
            old_event = self.db.execute(
                "INSERT INTO events(name) VALUES('Legacy Fixture')"
            ).lastrowid
            legacy = self.db.execute(
                "INSERT INTO matches(event_id,map1,status) VALUES(?,'Mirage','completed')",
                (old_event,),
            ).lastrowid
            self.db.execute(
                """INSERT INTO match_stats(match_id,player_id,map_name,kills,rounds_played)
                   VALUES(?,?,'Mirage',5,10)""",
                (legacy, self.player),
            )
            self.db.execute(
                "INSERT INTO yearly_top_players(year,rank,player_id) VALUES(2025,1,?)",
                (self.other,),
            )
            self.db.execute(
                "INSERT INTO player_medals(player_id,event_id,type) VALUES(?,?,'MVP')",
                (self.other, old_event),
            )
            before = [
                tuple(self.db.execute(f"SELECT * FROM {table}").fetchone())
                for table in ("yearly_top_players", "player_medals")
            ]
            refresh_player_performance(self.db, [self.player])
            run = self._start(0)
            self._record(run, self.player)
            self._apply(run, self.player, "all", {"kills": 10, "rounds": 20})
            self._confirm(0, run, 13, 7)
        with self.assertRaises(sqlite3.IntegrityError), write(self.db):
            self.db.execute(
                "INSERT INTO match_stats(match_id,player_id,map_name) VALUES(?,?,'Mirage')",
                (self.match, self.player),
            )
        with self.assertRaises(sqlite3.IntegrityError), write(self.db):
            self.db.execute(
                "UPDATE match_stats SET match_id=? WHERE match_id=?", (self.match, legacy)
            )
        with self.assertRaises(sqlite3.IntegrityError), write(self.db):
            self.db.execute(
                "INSERT INTO match_stats(match_id,player_id,map_name) VALUES(?,?,'Mirage')",
                (legacy, self.player),
            )
        after = [
            tuple(self.db.execute(f"SELECT * FROM {table}").fetchone())
            for table in ("yearly_top_players", "player_medals")
        ]
        self.assertEqual(after, before)
        page = self._page("/stats?tab=players&map=Mirage", "stats.html")
        row = next(row for row in page["rankings"] if row["id"] == self.player)
        self.assertEqual((row["maps"], row["kills"], row["rounds"]), (2, 15, 30))

    def test_public_api_reports_partial_metric_coverage_without_diluting_adr(self):
        with write(self.db):
            first = self._start(0)
            self._record(first, self.player)
            self._apply(first, self.player, "all", {"rounds": 18})
            self._confirm(0, first, 13, 5)
            second = self._start(1)
            self._record(second, self.player)
            self._apply(second, self.player, "all", {"kills": 12, "damage": 1200, "rounds": 20})
            self._confirm(1, second, 7, 13)
            third = self._start(2)
            self._record(third, self.player)
            self._confirm(2, third, 13, 10)

        response = self.visitor.get(f"/api/front/players/{self.player}")
        self.assertEqual(response.status_code, 200)
        page = response.get_json()
        summary = page["summary"]
        self.assertEqual(
            tuple(summary[key] for key in ("maps", "rounds", "kills", "adr", "kpr", "deaths")),
            (3, 38, 12, 60, 0.6, None),
        )
        self.assertEqual(
            summary["coverage"],
            {
                "kills": {"maps": 1},
                "adr": {"maps": 1, "rounds": 20},
            },
        )
        self.assertEqual([row["id"] for row in page["recent_matches"]], [self.match])
        for path in (f"/players/{self.player}", f"/stats/players/{self.player}"):
            html = self.visitor.get(path).get_data(as_text=True)
            coverage = html.split('class="meta player-coverage">', 1)[1].split("</p>", 1)[0]
            self.assertIn("出场地图</span> 3", coverage)
            self.assertIn("已知击杀</span> 12", coverage)
            self.assertEqual(coverage.count("覆盖地图</span> 1"), 2)
            self.assertIn("已知回合</span> 20", coverage)
        match_stats = self.visitor.get(f"/api/front/matches/{self.match}").get_json()["stats"]
        self.assertEqual(
            [(row["scheduled_map_id"], row["map_slot"]) for row in match_stats],
            list(zip(self.scheduled, (1, 2, 3))),
        )
        with write(self.db):
            self._apply(third, self.player, "all", {"kills": 5, "adr": 80})
        summary = self.visitor.get(f"/api/front/players/{self.player}").get_json()["summary"]
        self.assertEqual((summary["kills"], summary["adr"], summary["kpr"]), (17, 60, 0.6))
        self.assertEqual(
            summary["coverage"],
            {
                "kills": {"maps": 2},
                "adr": {"maps": 1, "rounds": 20},
            },
        )
