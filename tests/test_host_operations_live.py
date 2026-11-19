"""Exercise the original machine endpoints and real hosted match operations together."""

import json
import unittest
from threading import Thread
from unittest.mock import patch
from urllib.request import Request, urlopen

from werkzeug.serving import make_server

from config import Config
from site_core.matches import operations
from tests import test_host_prematch_chain


class HostLiveOperationsTests(unittest.TestCase):
    def setUp(self):
        chain = test_host_prematch_chain.HostPrematchChainTests()
        self.addCleanup(chain.doCleanups)
        chain.setUp()
        with patch.object(Config, "STEAM_WEB_API_KEY", ""):
            self.match_id = chain.prepare_through_host()
        self.enterContext(patch.object(Config, "GSI_TOKEN", "live-fixture-token"))
        self.enterContext(patch.object(Config, "GOTV_SECRET", "relay-fixture-token"))
        self.chain, self.db, self.client = chain, chain.db, chain.visitor
        self.url = f"/api/broadcast/matches/{self.match_id}"
        self.admin_url = f"/admin/matches/{self.match_id}/operations"
        self.headers = {"X-80GOTV-Token": "live-fixture-token"}
        match = self.match()
        self.plan = match["maps"][0]
        self.scheduled_id = self.plan["scheduled_map_id"]
        self.map_name = self.plan["name"]
        self.session = f"80gotv:{self.match_id}:1794960000000"
        self.fresh_session = f"80gotv:{self.match_id}:1794960030000"

    def body(self, response, status=200) -> dict:
        data = response.get_json()
        self.assertEqual(response.status_code, status, data)
        assert isinstance(data, dict), "接口应返回 JSON 对象"
        return data

    def match(self):
        return self.body(self.client.get(self.url))["match"]

    def authorize(self):
        self.assertTrue(self.operation("authorize", {})["ready_for_start"])

    def operation(self, name, body, status=200):
        response = self.chain.post(self.chain.admin, f"{self.admin_url}/{name}", json=body)
        return self.body(response, status)

    def gsi(self, seq=1794960000001, *, session=None, round_number=1, score=(1, 0)):
        players = {
            player["steam_id"]: {
                "name": player["nickname"],
                "team": side,
                "state": {"health": 100},
                "match_stats": {"kills": 0},
            }
            for team, side in (("team1", "CT"), ("team2", "T"))
            for player in self.match()[team]["players"]
        }
        return {
            "map": {
                "name": self.map_name,
                "mode": "competitive",
                "phase": "live",
                "round": round_number,
                "team_ct": {"score": score[0]},
                "team_t": {"score": score[1]},
            },
            "round": {"phase": "live"},
            "allplayers": players,
            "_80gotv": {
                "schema_version": 2,
                "session_id": session or self.session,
                "frame_seq": seq,
                "team_ct": "team1",
                "team_t": "team2",
                "round_events": [],
                "death_markers": [],
            },
        }

    def final(self, session=None, result_id="fixture-final", score=(13, 9)):
        return {
            "result_id": result_id,
            "session_id": session or self.session,
            "frame_seq": 1794960050000,
            "map_name": self.map_name,
            "map_slot": self.plan["slot"],
            "map_generation": 0,
            "team1_score": score[0],
            "team2_score": score[1],
            "series_complete": True,
            "players": [
                {
                    "steam_id": player["steam_id"],
                    "name": player["nickname"],
                    "team_side": team,
                    "roundsPlayed": sum(score),
                    "kills": 1,
                    "deaths": 1,
                }
                for team in ("team1", "team2")
                for player in self.match()[team]["players"]
            ],
        }

    def live(self, data, status=200):
        response = self.client.post(self.url + "/live", json=data, headers=self.headers)
        return self.body(response, status)

    def public_live(self):
        return self.body(self.client.get(f"/api/live/{self.match_id}"))

    def assert_public_team_names(self, public, broadcast):
        for side in (1, 2):
            team = f"team{side}"
            for label in ("name", "short_name"):
                self.assertNotIn(broadcast[team][label], ("TBD", "", None))
                self.assertEqual(public[team][label], broadcast[team][label])

    def result(self, data, status=200):
        response = self.client.post(self.url + "/map-result", json=data, headers=self.headers)
        return self.body(response, status)

    def relay(self, *, score=(1, 1), status=200):
        match = self.match()
        response = self.client.post(
            "/api/gotv/stats",
            headers={"X-GOTV-Secret": "relay-fixture-token"},
            json={
                "match_id": self.match_id,
                "map_name": self.map_name,
                "team_a_name": "队名不参与判定 A",
                "team_b_name": "队名不参与判定 B",
                "team_a_score": score[0],
                "team_b_score": score[1],
                "rounds_count": sum(score),
                "players": [
                    {  # Relay A is the website's away team.
                        "steam_id": match[team]["players"][0]["steam_id"],
                        "name": "中继测试选手",
                        "team_letter": letter,
                        "rounds_played": sum(score),
                        "kills": int(letter == "A"),
                    }
                    for team, letter in (("team2", "A"), ("team1", "B"))
                ],
            },
        )
        return self.body(response, status)

    def test_probe_and_warmup_do_not_start_then_old_director_gets_durable_receipts(self):
        self.db.execute("UPDATE matches SET match_time='2000-01-01' WHERE id=?", (self.match_id,))
        self.db.commit()
        self.assertEqual(self.match()["status"], "upcoming")
        self.assertIsNone(self.body(self.client.get("/api/broadcast/current"))["match"])
        path = self.url + "/connection-test"
        self.assertEqual(self.client.get(path).status_code, 403)
        self.assertFalse(self.body(self.client.get(path, headers=self.headers))["ready_for_start"])
        self.live(self.gsi(), 409)
        self.authorize()
        self.assertTrue(self.body(self.client.get(path, headers=self.headers))["ready_for_start"])
        self.assertEqual(
            self.body(self.client.get("/api/broadcast/current"))["match"]["status"], "upcoming"
        )
        warmup = self.gsi(round_number=0, score=(0, 0))
        warmup["map"]["phase"] = "warmup"
        self.assertFalse(self.live(warmup)["applied"])
        warmup["map"]["phase"] = "live"
        self.assertFalse(self.live(warmup)["applied"])
        self.result(self.final(), 409)
        self.assertIsNone(operations.current_run(self.db, self.scheduled_id))
        self.assertIsNone(self.db.execute("SELECT 1 FROM live_match_data").fetchone())

        data = self.gsi()
        data["auth"] = {"token": "不应入库"}
        data["_80gotv"]["round_events"] = [
            {"round_number": 1, "winner_side": "CT", "score_ct": 0, "score_t": 0}
        ]
        missing = next(iter(data["allplayers"]))
        del data["allplayers"][missing]
        recorded, unknown = list(data["allplayers"])[:2]
        data["allplayers"][recorded]["match_stats"] = dict(kills=0, deaths=0, assists=0, damage=0)
        del data["allplayers"][unknown]["match_stats"]
        run_id = self.live(data)["map_run_id"]
        self.assertTrue(self.live(data)["duplicate"])
        self.assertEqual(
            self.body(self.client.get("/api/broadcast/current"))["match"]["status"], "live"
        )
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM run_participations").fetchone()[0], 9
        )
        public = self.public_live()
        (event,) = public["round_history"]
        self.assertEqual(
            (event["round"], event["winner"], event["side"], event["score_ct"], event["score_t"]),
            (1, "t1", "ct", 1, 0),
        )
        players = {p["steamid"]: p for p in public["players_t1"] + public["players_t2"]}
        fields = ("kills", "assists", "deaths", "adr")
        self.assertEqual(tuple(players[recorded][field] for field in fields), (0, 0, 0, 0.0))
        self.assertEqual(tuple(players[unknown][field] for field in fields), (None,) * 4)
        self.assertNotIn(
            "不应入库", self.db.execute("SELECT live_state FROM live_match_data").fetchone()[0]
        )
        self.assertEqual(
            self.db.execute(
                "SELECT winner_side FROM map_run_rounds WHERE round_number=1"
            ).fetchone()[0],
            "home",
        )

        terminal = self.final()
        player = next(
            player
            for player in self.match()["team1"]["players"]
            if player["steam_id"] in data["allplayers"]
        )
        self.operation(
            "stats",
            {
                "map_run_id": run_id,
                "player_id": player["id"],
                "scope": "all",
                "fields": {"kills": 6},
                "expected_revision": 0,
                "reason": "人工核过击杀",
            },
        )
        reported = next(row for row in terminal["players"] if row["steam_id"] == player["steam_id"])
        reported.update(damage=220, deaths=0)
        self.db.execute("""CREATE TRIGGER reject_receipt BEFORE INSERT ON live_director_receipts
                           BEGIN SELECT raise(ABORT,'fixture receipt failure'); END""")
        with self.assertLogs("80gotv", level="ERROR"):
            self.assertFalse(self.result(terminal, 500)["ok"])
        self.assertEqual(operations.current_run(self.db, self.scheduled_id)["status"], "active")
        self.assertIsNone(self.db.execute("SELECT 1 FROM official_map_results").fetchone())
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM run_participations").fetchone()[0], 9
        )
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM run_stats_revisions").fetchone()[0], 1
        )
        self.db.execute("DROP TRIGGER reject_receipt")
        applied = self.result(terminal)
        self.assertEqual((applied["map_run_id"], applied["saved"]), (run_id, 10))
        self.assertTrue(applied["applied"])
        self.assertTrue(applied["series_complete"])
        report = next(row for row in applied["statistics"] if row["player_id"] == player["id"])
        self.assertEqual(
            report["conflicts"], {"kills": {"current": 6, "reported": 1, "source": "admin"}}
        )
        self.assertIn("damage", report["applied_fields"])
        fields = self.body(
            self.chain.admin.get(f"{self.admin_url}/runs/{run_id}/players/{player['id']}/stats")
        )["fields"]
        self.assertEqual(fields, {"rounds_played": 22, "kills": 6, "deaths": 0, "damage": 220})
        self.assertEqual(
            self.db.execute("SELECT terminal_receipt FROM official_map_results").fetchone()[0],
            terminal["result_id"],
        )
        self.assertIsNone(self.db.execute("SELECT 1 FROM series_settlements").fetchone())
        self.assertEqual(self.match()["status"], "live")
        self.assertTrue(self.match()["maps"][0]["map_finished"])
        duplicate = self.result(terminal)
        self.assertFalse(duplicate["applied"])
        self.assertFalse(duplicate["map_applied"])
        self.result(dict(terminal, team2_score=10), 409)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM map_run_rounds").fetchone()[0], 22)
        path = f"{self.admin_url}/runs/{run_id}/director-receipts"
        guest = self.client.get(path)
        self.assertEqual(guest.status_code, 302)
        self.assertIn("/admin/login", guest.location)
        receipt_query = self.chain.admin.get(path)
        (saved,) = self.body(receipt_query)["receipts"]
        self.assertEqual(saved["statistics"], applied["statistics"])
        self.assertEqual(len(saved["players_candidate"]), 10)

    def test_replay_binds_an_independent_old_app_session_and_rejects_late_unmatched_packets(self):
        outgoing = self.match()["team1"]["players"][0]
        replacement = self.db.execute(
            "SELECT p.id,p.steam_id FROM players p JOIN users u ON u.steam_id64=p.steam_id WHERE u.id=?",
            (self.chain.accounts[-1],),
        ).fetchone()
        self.assertEqual(
            tuple(
                self.db.execute(
                    "SELECT team1_id,team2_id FROM matches WHERE id=?", (self.match_id,)
                ).fetchone()
            ),
            (None, None),
        )
        self.db.execute(
            "UPDATE players SET avatar=? WHERE id=?",
            ("/static/logos/80gotv-mark.png", replacement["id"]),
        )
        self.db.commit()
        home = self.db.execute(
            "SELECT event_entrant_id FROM match_participants WHERE match_id=? AND side_key='home'",
            (self.match_id,),
        ).fetchone()[0]
        revision = self.body(self.chain.admin.get(self.chain.prefix))["formation_revision"]
        response = self.chain.post(
            self.chain.admin,
            self.chain.prefix + "/assign-reserve",
            json={
                "event_entrant_id": home,
                "player_id": replacement["id"],
                "expected_revision": revision,
                "reason": "已与候补确认本届席位",
            },
        )
        self.assertEqual(response.status_code, 200, response.json)
        self.authorize()
        original_data = self.gsi()
        original = self.live(original_data)["map_run_id"]
        self.assert_public_team_names(self.public_live(), self.match())
        old_result = self.final()
        self.assertTrue(self.result(old_result)["applied"])
        self.operation(
            "technical-replay",
            {
                "map_run_id": original,
                "reason": "合成故障：无法续局",
                "outgoing_player_id": outgoing["id"],
                "incoming_player_id": replacement["id"],
            },
        )
        broadcast = self.match()
        new_team = {player["steam_id"]: player for player in broadcast["team1"]["players"]}
        self.assertNotIn(outgoing["steam_id"], new_team)
        self.assertIn(replacement["steam_id"], new_team)
        self.assertFalse(self.public_live()["ok"])
        self.live(self.gsi(session=self.fresh_session), 409)
        self.assertIsNone(operations.current_run(self.db, self.scheduled_id))
        replay = self.operation(
            "start",
            {
                "scheduled_map_id": self.scheduled_id,
                "evidence": "隔离测试：现场确认已重打",
                "previous_map_run_id": original,
            },
        )["map_run_id"]
        empty = self.public_live()
        self.assert_public_team_names(empty, broadcast)
        self.assertEqual(empty["players_t1"] + empty["players_t2"], [])
        self.relay(status=409)
        self.live(self.gsi(session=self.fresh_session), 409)
        self.result(self.final(session=self.fresh_session, result_id="new-result"), 409)
        self.assertIn(
            "不能改绑",
            self.operation(
                "bind-director-session",
                {
                    "map_run_id": replay,
                    "session_id": self.session,
                    "reason": "故意测试禁止改绑",
                },
                409,
            )["error"],
        )
        binding = {
            "map_run_id": replay,
            "session_id": self.fresh_session,
            "reason": "核对另一台导播机器",
        }
        bound = self.operation("bind-director-session", binding)
        self.assertEqual(bound["map_run_id"], replay)
        self.assertFalse(bound["duplicate"])
        self.assertTrue(self.operation("bind-director-session", binding)["duplicate"])
        new_data = self.gsi(session=self.fresh_session, score=(1, 0))
        for player in new_data["allplayers"].values():
            player["team"] = "T" if player["team"] == "CT" else "CT"
        incoming = new_data["allplayers"].pop(replacement["steam_id"])
        incoming["name"] = "现场临时昵称"
        new_data["allplayers"][outgoing["steam_id"]] = original_data["allplayers"][
            outgoing["steam_id"]
        ]
        self.assertEqual(self.live(new_data)["map_run_id"], replay)
        first_frame = self.public_live()
        self.assert_public_team_names(first_frame, broadcast)
        self.assertEqual((first_frame["team1"]["side"], first_frame["team2"]["side"]), ("T", "CT"))
        self.assertEqual((first_frame["team1"]["score"], first_frame["team2"]["score"]), (0, 1))
        (event,) = first_frame["round_history"]
        self.assertEqual(
            (
                event["winner"],
                event["side"],
                event["score_ct"],
                event["score_t"],
                event["map_run_id"],
            ),
            ("t2", "ct", 1, 0, replay),
        )
        self.assertEqual(
            {player["steamid"] for player in first_frame["players_t1"]},
            new_team.keys() - {replacement["steam_id"]},
        )
        self.assertIsNone(
            self.db.execute(
                "SELECT 1 FROM run_participations WHERE map_run_id=? AND player_id=?",
                (replay, replacement["id"]),
            ).fetchone()
        )

        new_data["_80gotv"]["frame_seq"] += 1
        new_data["allplayers"][replacement["steam_id"]] = incoming
        self.live(new_data)
        current = self.public_live()
        for side in (1, 2):
            displayed = {player["steamid"]: player for player in current[f"players_t{side}"]}
            expected = {
                player["steam_id"]: player for player in broadcast[f"team{side}"]["players"]
            }
            self.assertEqual(displayed.keys(), expected.keys())
            for steam_id, player in displayed.items():
                self.assertEqual(
                    (player["player_id"], player["name"], player["avatar"], player["roster_slot"]),
                    tuple(expected[steam_id][key] for key in ("id", "nickname", "avatar", "slot")),
                )
        self.assertTrue(
            next(p for p in current["players_t1"] if p["steamid"] == replacement["steam_id"])[
                "is_substitute"
            ]
        )

        new_data["_80gotv"]["frame_seq"] += 1
        del new_data["allplayers"][replacement["steam_id"]]
        self.live(new_data)
        (missing,) = [p for p in self.public_live()["players_t1"] if p.get("missing")]
        self.assertEqual(missing["steamid"], replacement["steam_id"])
        self.assertEqual(
            tuple(missing[k] for k in ("kills", "assists", "deaths", "adr")), (None,) * 4
        )
        original_data["_80gotv"]["frame_seq"] = 1794960050001
        self.live(original_data, 409)
        self.result(dict(old_result, result_id="unseen-late-original"), 409)
        duplicate = self.result(old_result)
        self.assertEqual(
            (duplicate["map_run_id"], duplicate["duplicate"], duplicate["applied"]),
            (original, True, False),
        )
        terminal = self.final(session=self.fresh_session, result_id="new-result", score=(8, 13))
        self.assertEqual(self.result(terminal)["map_run_id"], replay)
        self.assertEqual(
            [
                tuple(row)
                for row in self.db.execute(
                    "SELECT map_run_id,winner_side FROM map_run_rounds WHERE round_number=1 ORDER BY map_run_id"
                )
            ],
            [(original, "home"), (replay, "away")],
        )
        self.assertEqual(
            [
                tuple(row)
                for row in self.db.execute(
                    "SELECT map_run_id,is_current FROM official_map_results ORDER BY map_run_id"
                )
            ],
            [(original, 0), (replay, 1)],
        )
        self.assertEqual(
            [
                row[0]
                for row in self.db.execute(
                    "SELECT map_run_id FROM live_run_events WHERE event_type='round' ORDER BY map_run_id"
                )
            ],
            [original, replay],
        )
        self.assertEqual(self.match()["maps"][0]["team2_score"], 13)

    def test_round_log_does_not_assign_new_sides_to_the_round_before_a_switch(self):
        self.authorize()
        before = self.gsi(round_number=11, score=(7, 4))
        before["_80gotv"]["round_events"] = [{"round_number": 3, "reason_code": "completed"}]
        self.live(before)
        after = self.gsi(seq=1794960000002, round_number=12, score=(4, 8))
        for player in after["allplayers"].values():
            player["team"] = "T" if player["team"] == "CT" else "CT"
        self.live(after)
        after["_80gotv"]["frame_seq"] += 1
        after["map"]["round"] = 13
        after["map"]["team_t"]["score"] = 9
        self.live(after)
        rounds = {item["round"]: item for item in self.public_live()["round_history"]}
        fields = ("winner", "side", "score_ct", "score_t")
        self.assertEqual(tuple(rounds[3].get(k) for k in fields), (None, "", None, None))
        self.assertEqual(tuple(rounds[12].get(k) for k in fields), ("t1", "", None, None))
        self.assertEqual(tuple(rounds[13].get(k) for k in fields), ("t1", "t", 4, 9))

        after["_80gotv"]["frame_seq"] += 1
        after["_80gotv"]["round_events"] = [
            {
                "round_number": 12,
                "winner_side": "CT",
                "score_ct": 8,
                "score_t": 4,
                "reason_code": "bomb_defused",
            }
        ]
        self.live(after)
        after["_80gotv"]["frame_seq"] += 1
        self.live(after)
        (enriched,) = [e for e in self.public_live()["round_history"] if e["round"] == 12]
        self.assertEqual(enriched["id"], rounds[12]["id"])
        self.assertEqual(tuple(enriched.get(k) for k in fields), ("t1", "ct", 8, 4))
        self.assertEqual(enriched["reason_code"], "bomb_defused")

    def test_gotv_and_direct_gsi_use_observed_teams_and_do_not_write_a_result(self):
        self.authorize()
        self.assertFalse(self.relay(score=(1, 0))["applied"])
        self.assertIsNone(operations.current_run(self.db, self.scheduled_id))
        receipt = self.relay(score=(2, 1))
        self.assertEqual(
            (receipt["map_slot"], receipt["players_imported"], receipt["players_created"]),
            (0, 2, 0),
        )
        self.assertEqual(self.match()["maps"][0]["team2_score"], 2)
        self.assertFalse(self.match()["maps"][0]["map_finished"])
        public = self.public_live()
        broadcast = self.match()
        self.assert_public_team_names(public, broadcast)
        self.assertEqual((public["team1"]["score"], public["team2"]["score"]), (1, 2))
        for side in (1, 2):
            (observed,) = public[f"players_t{side}"]
            listed = broadcast[f"team{side}"]["players"][0]
            self.assertEqual(
                (observed["steamid"], observed["name"], observed["avatar"]),
                (listed["steam_id"], listed["nickname"], listed["avatar"]),
            )
            self.assertEqual(
                tuple(observed[k] for k in ("kills", "assists", "deaths", "adr")),
                (side - 1, None, None, None),
            )
        self.assertIsNone(self.db.execute("SELECT 1 FROM official_map_results").fetchone())
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM map_run_rounds").fetchone()[0], 3)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM run_participations").fetchone()[0], 1
        )
        self.assertIsNone(self.db.execute("SELECT 1 FROM run_round_participations").fetchone())

        raw = self.gsi(round_number=3, score=(1, 2))
        raw.pop("_80gotv")
        raw["auth"] = {"token": "live-fixture-token"}
        response = self.client.post("/api/gsi/receive", json=raw)
        self.assertEqual(self.body(response)["map_run_id"], receipt["map_run_id"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM map_runs").fetchone()[0], 1)
        self.assertFalse(self.db.execute("PRAGMA foreign_key_check").fetchall())

    def test_old_director_posts_over_loopback_http_and_exact_retry_is_acknowledged(self):
        self.authorize()
        frame, terminal = self.gsi(), self.final()
        with make_server("127.0.0.1", 0, self.client.application) as server:
            worker = Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:

                def send(path, data):
                    request = Request(
                        f"http://127.0.0.1:{server.server_port}{self.url}/{path}",
                        data=json.dumps(data).encode("utf-8"),
                        headers={**self.headers, "Content-Type": "application/json"},
                        method="POST",
                    )
                    with urlopen(request, timeout=5) as reply:
                        self.assertEqual(reply.status, 200)
                        return json.load(reply)

                started = send("live", frame)
                receipt = send("map-result", terminal)
                duplicate = send("map-result", terminal)
            finally:
                server.shutdown()
                worker.join()
        self.assertEqual(receipt["map_run_id"], started["map_run_id"])
        self.assertEqual(
            (receipt["map_slot"], receipt["result_id"]),
            (terminal["map_slot"], terminal["result_id"]),
        )
        self.assertTrue(receipt["applied"])
        self.assertTrue(duplicate["duplicate"])
        self.assertFalse(duplicate["applied"])
