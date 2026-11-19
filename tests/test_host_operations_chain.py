"""Original-site BO3 preparation and old-edition compatibility in an isolated database."""

import json
import re
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from config import Config
from services.performance_service import refresh_player_performance
from tests import test_host_bp_maps, test_host_operations_live, test_host_prematch_chain


class HostOperationsChainTests(unittest.TestCase):
    def setUp(self):
        self.site = test_host_prematch_chain.HostPrematchChainTests(
            "test_signup_to_broadcast_in_the_original_website"
        )
        self.addCleanup(self.site.doCleanups)
        self.site.setUp()

    def prepare_bo3(self):
        site = self.site
        site.prepare_through_host()
        control = site.admin.get(site.prefix).get_json()
        home = control["entrants"][0]
        reserve = next(
            row for row in control["reserve_candidates"]
            if row["registration_origin"] == "independent_reserve"
        )
        grant = site.post(
            site.admin,
            site.prefix + "/assign-reserve",
            json={
                "event_entrant_id": home["event_entrant_id"],
                "player_id": reserve["player_id"],
                "expected_revision": control["formation_revision"],
                "reason": "赛前确认本队候补席",
            },
        )
        self.assertEqual(grant.status_code, 200, grant.get_data(as_text=True))
        current = site.admin.get(site.prefix).get_json()
        self.assertEqual(
            next(r for r in current["reserve_candidates"] if r["player_id"] == reserve["player_id"])[
                "assigned_entrant_id"
            ],
            home["event_entrant_id"],
        )

        fields = {
            f"side{index}_id": team["event_entrant_id"]
            for index, team in enumerate(current["entrants"], 1)
        }
        created = site.post(
            site.admin,
            "/admin/matches/add",
            data={
                "event_id": site.event_id,
                "match_time": (date.today() + timedelta(days=12)).isoformat() + "T18:00",
                "bo_format": "BO3",
                "side1_type": "entrant",
                "side2_type": "entrant",
                **fields,
            },
        )
        self.assertEqual(created.status_code, 302, created.get_data(as_text=True))
        match_id = site.db.execute(
            "SELECT max(id) FROM matches WHERE event_id=?", (site.event_id,)
        ).fetchone()[0]
        frozen = site.post(site.admin, f"/admin/matches/{match_id}/freeze-rosters")
        self.assertEqual(frozen.status_code, 302, frozen.get_data(as_text=True))

        bp = test_host_bp_maps.HostedBPTests(
            "test_bo3_and_bo5_use_original_order_and_leave_the_decider_side_pending"
        )
        bp.admin = bp._client(admin_id=site.admin_id)
        state = bp._choose_maps(
            match_id,
            [
                ("ban", "t1", "Dust2"),
                ("ban", "t2", "Mirage"),
                ("pick", "t1", "Inferno"),
                ("pick", "t2", "Nuke"),
                ("ban", "t1", "Cache"),
                ("ban", "t2", "Ancient"),
            ],
        )
        for map_name, side in (("Inferno", "t2"), ("Nuke", "t1")):
            state = bp._step(
                match_id, "choose_side", team=side, map=map_name, side="T",
                revision=state["revision"],
            )
        self.assertEqual(state["status"], "completed")
        participants = {
            row["side_key"]: dict(row)
            for row in site.db.execute(
                "SELECT * FROM match_participants WHERE match_id=?", (match_id,)
            )
        }
        self.assertEqual(participants["home"]["event_entrant_id"], home["event_entrant_id"])
        plans = [
            dict(row) for row in site.db.execute(
                "SELECT * FROM scheduled_maps WHERE match_id=? AND is_enabled=1 ORDER BY map_order",
                (match_id,),
            )
        ]
        return {
            "match_id": match_id,
            "event_id": site.event_id,
            "participants": participants,
            "plans": plans,
            "outgoing": home["current_player_ids"][-1],
            "incoming": reserve["player_id"],
        }

    def seed_legacy_result(self):
        db = self.site.db
        team1 = db.execute("INSERT INTO teams(name) VALUES('旧届海岸队')").lastrowid
        team2 = db.execute("INSERT INTO teams(name) VALUES('旧届铜山队')").lastrowid
        event = db.execute("INSERT INTO events(name,slug) VALUES('旧届验收杯','old-acceptance-cup')").lastrowid
        player = db.execute(
            "INSERT INTO players(nickname,team_id) VALUES('旧届验收选手',?)", (team1,)
        ).lastrowid
        match = db.execute(
            """INSERT INTO matches(event_id,team1_id,team2_id,bo_format,status,team1_score,
               team2_score,match_time,map1,map1_t1,map1_t2,map2,map2_t1,map2_t2)
               VALUES(?,?,?,'BO3','completed',2,0,'2026-10-01 12:00:00',
                      'de_mirage',13,7,'de_nuke',13,8)""",
            (event, team1, team2),
        ).lastrowid
        db.executemany(
            """INSERT INTO match_stats(match_id,player_id,team_id,map_name,rounds_played,
               rating,adr,kills,deaths) VALUES(?,?,?,?,20,1.2,80,20,10)""",
            [(match, player, team1, name) for name in ("de_mirage", "de_nuke")],
        )
        refresh_player_performance(db)
        db.commit()
        return {"event_id": event, "match_id": match, "player_id": player}

    def test_real_signup_roster_freeze_and_bo3_bp(self):
        case = self.prepare_bo3()
        self.assertEqual([row["map_name"] for row in case["plans"]],
                         ["de_inferno", "de_nuke", "de_anubis"])
        self.assertEqual(len(case["participants"]), 2)
        broadcast = self.site.visitor.get(
            f"/api/broadcast/matches/{case['match_id']}"
        ).get_json()["match"]
        self.assertTrue(broadcast["roster_locked"])
        self.assertEqual(broadcast["bp"]["status"], "completed")
        self.assertEqual([row["name"] for row in broadcast["maps"]],
                         ["de_inferno", "de_nuke", "de_anubis"])
        self.assertFalse(broadcast["ready_for_start"])

    def test_old_edition_pages_and_front_contract(self):
        legacy = self.seed_legacy_result()
        visitor = self.site.visitor
        for url, expected in (
            ("/results", "旧届海岸队"),
            (f"/matches/{legacy['match_id']}", "旧届海岸队"),
            (f"/players/{legacy['player_id']}", "旧届验收选手"),
        ):
            with self.subTest(url=url):
                response = visitor.get(url, follow_redirects=True)
                self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
                self.assertIn(expected, response.get_data(as_text=True))
        result = visitor.get("/api/front/results").get_json()
        row = next(row for row in result["results"] if row["id"] == legacy["match_id"])
        self.assertEqual((row["score1"], row["score2"]), (2, 0))
        detail = visitor.get(f"/api/front/players/{legacy['player_id']}").get_json()
        self.assertEqual(detail["summary"]["maps"], 2)

    def test_operations_read_available_after_real_bo3_prematch(self):
        case = self.prepare_bo3()
        url = f"/admin/matches/{case['match_id']}/operations"
        visitor = self.site.visitor.get(url, headers={"X-Requested-With": "XMLHttpRequest"})
        self.assertEqual(visitor.status_code, 401)
        member = self.site.client(user_id=self.site.accounts[0])
        self.assertEqual(self.site.post(member, url + "/authorize", json={}).status_code, 401)
        self.assertEqual(self.site.admin.post(url + "/authorize", json={}).status_code, 403)
        response = self.site.admin.get(url)
        self.assertEqual(response.status_code, 200, f"办赛管理读取接口返回 {response.status_code}")
        self.assertFalse(response.get_json()["authorized"])
        self.assertEqual(
            [(row["scheduled_map_id"], row["map_order"]) for row in response.get_json()["maps"]],
            [(row["scheduled_map_id"], row["map_order"]) for row in case["plans"]],
        )
        self.assertTrue(all("effective_roster" in row and "runs" in row
                            for row in response.get_json()["maps"]))

    def complete_bo3(self, case, *, director_live=False):
        db, site = self.site.db, self.site
        prefix = f"/admin/matches/{case['match_id']}/operations"
        plans = [row["scheduled_map_id"] for row in case["plans"]]
        home = case["participants"]["home"]["match_participant_id"]
        original = [
            dict(row) for row in db.execute(
                """SELECT m.player_id,m.match_participant_id FROM match_roster_members m
                   JOIN match_participants p USING(match_participant_id)
                   WHERE p.match_id=? ORDER BY p.side_key,m.roster_slot""",
                (case["match_id"],),
            )
        ]
        self.assertEqual(len(original), 10)
        self.assertIn({"player_id": case["outgoing"], "match_participant_id": home}, original)
        self.assertNotIn(case["incoming"], [row["player_id"] for row in original])
        anchor = next(row["player_id"] for row in original
                      if row["match_participant_id"] == home and row["player_id"] != case["outgoing"])

        def post(action, body, status=200):
            response = site.post(site.admin, f"{prefix}/{action}", json=body)
            self.assertEqual(response.status_code, status,
                             f"{action}: {response.get_data(as_text=True)[:600]}")
            if status == 200:
                self.assertTrue(response.get_json()["ok"], response.get_json())
            return response

        def start(plan, evidence, *, previous_run=None):
            body = {"scheduled_map_id": plan, "evidence": evidence}
            if previous_run is not None:
                body["previous_map_run_id"] = previous_run
            response = post("start", body)
            run_id = response.get_json()["map_run_id"]
            self.assertEqual(run_id, db.execute(
                "SELECT map_run_id FROM map_runs WHERE scheduled_map_id=? ORDER BY attempt_no DESC LIMIT 1",
                (plan,),
            ).fetchone()[0])
            return run_id

        def record_players(run_id, *, replacement=False):
            for row in original:
                player = (case["incoming"] if replacement and row["player_id"] == case["outgoing"]
                          else row["player_id"])
                response = post("participation", {
                    "map_run_id": run_id, "player_id": player,
                    "match_participant_id": row["match_participant_id"],
                    "reason": "现场核对实际出场",
                })
                self.assertEqual(response.get_json()["participation_id"], db.execute(
                    "SELECT participation_id FROM run_participations WHERE map_run_id=? AND player_id=?",
                    (run_id, player),
                ).fetchone()[0])

        def record_stats(run_id, fields):
            response = post("stats", {
                "map_run_id": run_id, "player_id": anchor, "scope": "all",
                "fields": fields,
                "expected_revision": 0, "reason": "依据现场记录核对个人数据",
            })
            self.assertTrue(response.get_json()["applied"], response.get_json())

        def confirm(plan, run, score1, score2):
            post("confirm-map", {
                "scheduled_map_id": plan, "map_run_id": run,
                "score1": score1, "score2": score2, "expected_revision": 0,
            })

        voters = [(site.accounts[0], "t1", "2", "1"), (site.accounts[1], "t2", "1", "2")]
        for account, side, score1, score2 in voters:
            response = site.post(
                site.client(user_id=account), f"/matches/{case['match_id']}/vote",
                data={"voted_for": side, "score1": score1, "score2": score2},
            )
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:600])
            self.assertTrue(response.get_json()["ok"], response.get_json())
        self.assertEqual(
            [tuple(row) for row in db.execute(
                """SELECT scored,points_earned FROM match_votes
                   WHERE match_id=? AND user_id IN (?,?) ORDER BY user_id""",
                (case["match_id"], site.accounts[0], site.accounts[1]),
            )],
            [(0, 0), (0, 0)],
        )

        post("authorize", {})
        first = start(plans[0], "现场证实第一图已经开打")
        if director_live:
            live = test_host_operations_live.HostLiveOperationsTests()
            live.chain, live.db, live.client = site, db, site.visitor
            live.match_id = case["match_id"]
            live.url = f"/api/broadcast/matches/{case['match_id']}"
            live.map_name = case["plans"][0]["map_name"]
            live.session = f"80gotv:{case['match_id']}:1794960000000"
            live.headers = {"X-80GOTV-Token": "synthetic-live-fixture"}
            with patch.object(Config, "GSI_TOKEN", "synthetic-live-fixture"):
                receipt = live.live(live.gsi())
            self.assertTrue(receipt["applied"], receipt)
            self.assertEqual(receipt["map_run_id"], first)
            self.assertEqual(tuple(db.execute(
                """SELECT winner_side,source FROM map_run_rounds
                   WHERE map_run_id=? AND round_number=1""", (first,),
            ).fetchone()), ("home", "gsi"))
        record_players(first)
        record_stats(first, {"rounds_played": 18})
        confirm(plans[0], first, 13, 7)

        interrupted = start(plans[1], "现场证实第二图已经开打")
        record_players(interrupted)
        record_stats(interrupted, {"kills": 8, "rounds_played": 10, "damage": 800})
        self.assertEqual(tuple(db.execute(
            "SELECT kills,rounds_played,damage FROM run_player_stats WHERE map_run_id=? AND player_id=? AND scope='all'",
            (interrupted, anchor),
        ).fetchone()), (8, 10, 800))
        self.assertEqual(start(plans[1], "断流修复后继续原局"), interrupted)
        self.assertEqual(db.execute(
            "SELECT count(*) FROM map_runs WHERE scheduled_map_id=?", (plans[1],)
        ).fetchone()[0], 1)
        self.assertFalse(db.execute(
            "SELECT 1 FROM official_stat_participants WHERE scheduled_map_id=?", (plans[1],)
        ).fetchone())
        approval = post("technical-replay", {
            "map_run_id": interrupted, "outgoing_player_id": case["outgoing"],
            "incoming_player_id": case["incoming"], "reason": "技术故障无法继续，批准替换重赛",
        })
        self.assertEqual(approval.get_json()["void_map_run_id"], interrupted)
        self.assertEqual(db.execute(
            "SELECT count(*) FROM map_runs WHERE scheduled_map_id=?", (plans[1],)
        ).fetchone()[0], 1)
        post("start", {
            "scheduled_map_id": plans[1], "evidence": "现场证实第二图已经开打",
        }, status=409)
        post("start", {
            "scheduled_map_id": plans[1], "evidence": "现场证实第二图已重新开打",
            "previous_map_run_id": first,
        }, status=409)
        self.assertEqual(db.execute(
            "SELECT count(*) FROM map_runs WHERE scheduled_map_id=?", (plans[1],)
        ).fetchone()[0], 1)
        replay = start(plans[1], "现场证实第二图已重新开打", previous_run=interrupted)
        self.assertNotEqual(replay, interrupted)
        self.assertEqual(db.execute(
            "SELECT previous_map_run_id FROM map_runs WHERE map_run_id=?", (replay,)
        ).fetchone()[0], interrupted)
        record_players(replay, replacement=True)
        record_stats(replay, {"kills": 12, "rounds_played": 20, "damage": 1200})
        confirm(plans[1], replay, 7, 13)

        decider = start(plans[2], "现场证实决胜图已经开打")
        post("participation", {
            "map_run_id": decider, "player_id": case["outgoing"],
            "match_participant_id": home, "reason": "核对换出选手不能继续出场",
        }, status=409)
        record_players(decider, replacement=True)
        confirm(plans[2], decider, 13, 10)
        self.assertEqual(
            [tuple(row) for row in db.execute(
                """SELECT scored,points_earned FROM match_votes
                   WHERE match_id=? AND user_id IN (?,?) ORDER BY user_id""",
                (case["match_id"], site.accounts[0], site.accounts[1]),
            )],
            [(0, 0), (0, 0)],
        )
        post("settle", {})
        self.assertEqual(
            [tuple(row) for row in db.execute(
                """SELECT scored,points_earned FROM match_votes
                   WHERE match_id=? AND user_id IN (?,?) ORDER BY user_id""",
                (case["match_id"], site.accounts[0], site.accounts[1]),
            )],
            [(1, 8), (1, 0)],
        )
        return {"first": first, "interrupted": interrupted, "replay": replay,
                "decider": decider, "anchor": anchor}

    def test_bo3_continuation_technical_replay_and_three_map_result(self):
        case = self.prepare_bo3()
        db, site = self.site.db, self.site
        event_path = f"/admin/events/{case['event_id']}/operations/bracket"
        created = site.post(site.admin, event_path, json={"bo_format": "BO3", "stage": "下轮验收"})
        self.assertEqual(created.status_code, 201, created.get_data(as_text=True))
        target = created.get_json()["match_id"]
        linked = site.post(
            site.admin, f"/admin/matches/{case['match_id']}/operations/bracket-link",
            json={"outcome": "winner", "target_match_id": target, "target_side": "home"},
        )
        self.assertEqual(linked.status_code, 200, linked.get_data(as_text=True))
        links = site.admin.get(event_path).get_json()["links"]
        self.assertEqual(
            [(row["target_match_id"], row["target_side"], row["event_entrant_id"]) for row in links],
            [(target, "home", None)],
        )
        self.assertFalse(db.execute(
            "SELECT 1 FROM match_participants WHERE match_id=?", (target,),
        ).fetchone())

        runs = self.complete_bo3(case, director_live=True)
        first, interrupted, replay, decider, anchor = (
            runs[key] for key in ("first", "interrupted", "replay", "decider", "anchor")
        )
        plans = [row["scheduled_map_id"] for row in case["plans"]]
        winner = case["participants"]["home"]["event_entrant_id"]
        self.assertEqual(
            [tuple(row) for row in db.execute(
                """SELECT p.event_id,p.event_entrant_id,p.side_key,g.club_id,m.team1_id,m.team2_id
                   FROM match_participants p JOIN matches m ON m.id=p.match_id
                   JOIN event_entrants e ON e.event_entrant_id=p.event_entrant_id
                   JOIN event_registration_groups g ON g.registration_id=e.registration_id
                   WHERE p.match_id=?""", (target,),
            )],
            [(case["event_id"], winner, "home", None, None, None)],
        )
        links = site.admin.get(event_path).get_json()["links"]
        self.assertEqual(
            [(row["target_match_id"], row["target_side"], row["event_entrant_id"]) for row in links],
            [(target, "home", winner)],
        )
        event_page = site.visitor.get(site.event_url, follow_redirects=True)
        self.assertEqual(event_page.status_code, 200)
        self.assertRegex(event_page.get_data(as_text=True),
                         r'(?s)class="bracket-card-header">\s*下轮验收\s*</div>.*?'
                         r'class="bracket-name[^\"]*">\s*远岸\s*</span>')
        admin_page = site.admin.get(f"/admin/events/{case['event_id']}/bracket")
        self.assertEqual(admin_page.status_code, 200)
        embedded = re.search(r"window\._eventMatches\s*=\s*(\[.*?\]);", admin_page.get_data(as_text=True))
        self.assertIsNotNone(embedded)
        target_match = next(row for row in json.loads(embedded.group(1)) if row["id"] == target)
        self.assertEqual((target_match["t1_name"], target_match["team1_id"]), ("远岸", None))
        counted = [dict(row) for row in db.execute(
            """SELECT scheduled_map_id,map_run_id,player_id FROM official_stat_participants
               WHERE match_id=? AND player_id IN (?,?) ORDER BY scheduled_map_id,player_id""",
            (case["match_id"], case["outgoing"], case["incoming"]),
        )]
        self.assertEqual(
            {(row["scheduled_map_id"], row["map_run_id"], row["player_id"]) for row in counted},
            {(plans[0], first, case["outgoing"]), (plans[1], replay, case["incoming"]),
             (plans[2], decider, case["incoming"])},
        )
        self.assertFalse(db.execute(
            "SELECT 1 FROM site_player_map_stats WHERE match_id=? AND map_run_id=?",
            (case["match_id"], interrupted),
        ).fetchone())
        self.assertEqual(tuple(db.execute(
            """SELECT count(DISTINCT match_id),count(DISTINCT player_id),count(*),sum(kills)
               FROM site_player_map_stats WHERE match_id=?""", (case["match_id"],),
        ).fetchone()), (1, 11, 30, 12))
        self.assertEqual(
            [tuple(row) for row in db.execute(
                """SELECT map_run_id,rounds_played,kills,adr FROM site_player_map_stats
                   WHERE match_id=? AND player_id=? ORDER BY legacy_slot""",
                (case["match_id"], anchor),
            )],
            [(first, 18, None, None), (replay, 20, 12, 60.0),
             (decider, None, None, None)],
        )
        self.assertEqual(tuple(db.execute(
            """SELECT maps,rounds_played,total_kills,avg_adr,avg_kpr
               FROM player_performance_summary WHERE player_id=?""", (anchor,),
        ).fetchone()), (3, 38, 12, 60.0, 0.6))
        for player, maps in ((case["outgoing"], 1), (case["incoming"], 2)):
            with self.subTest(player=player):
                summary = site.visitor.get(f"/api/front/players/{player}").get_json()["summary"]
                self.assertEqual(summary["maps"], maps)
                self.assertIsNone(summary["kills"])
                self.assertIsNone(summary["adr"])
                self.assertEqual(summary["coverage"]["kills"]["maps"], 0)
                self.assertEqual(summary["coverage"]["adr"], {"maps": 0, "rounds": None})
        with self.subTest(player=anchor):
            summary = site.visitor.get(f"/api/front/players/{anchor}").get_json()["summary"]
            self.assertEqual(
                (summary["maps"], summary["rounds"], summary["kills"], summary["adr"], summary["kpr"]),
                (3, 38, 12, 60.0, 0.6),
            )
            self.assertEqual(summary["coverage"]["kills"], {"maps": 1})
            self.assertEqual(summary["coverage"]["adr"], {"maps": 1, "rounds": 20})
        with self.subTest(page="player leaderboard"):
            players = site.visitor.get("/api/front/players?filter=top10").get_json()["players"]
            player = next(row for row in players if row["id"] == anchor)
            self.assertEqual((player["maps"], player["kills"], player["adr"]), (3, 12, 60.0))
        with self.subTest(page="statistics overview"):
            summary = site.visitor.get("/api/front/stats/overview").get_json()["summary"]
            self.assertEqual(
                (summary["matches"], summary["players"], summary["player_maps"], summary["kills"]),
                (1, 11, 30, 12),
            )
        with self.subTest(page="results"):
            results = site.visitor.get("/api/front/results").get_json()["results"]
            row = next(row for row in results if row["id"] == case["match_id"])
            self.assertEqual((row["score1"], row["score2"]), (2, 1))


if __name__ == "__main__":
    unittest.main()
