"""正式裁定的真实 SQLite 事务，使用 Slice 2 已确认的两支临时队。"""

import sqlite3
import unittest
from contextlib import closing

from models import get_db
from services import bracket_service as bracket
from services.match_service import get_prediction_leaderboard, managed_vote_open, score_predictions
from site_core.host import HostError, write
from site_core.matches import maps, operations, participants, results
from tests import test_host_bp_maps as prematch
from tests.entrant_slice_fixtures import ORGANIZER_ID


class SettlementTests(unittest.TestCase):
    def setUp(self):
        base = prematch.HostedBPTests()
        self.addCleanup(base.doCleanups)
        base.setUp()
        self.base = base
        self.db = self.enterContext(closing(get_db()))

    def schedule(self, bo):
        self.mid = self.base._new_match(bo, setup={f"map{i}": "Mirage" for i in range(1, 6)})
        self.eid = self.db.execute(
            "SELECT event_id FROM matches WHERE id=?", (self.mid,)
        ).fetchone()[0]
        self.slots = [
            m["scheduled_map_id"] for m in results.read_results(self.db, self.mid)["maps"]
        ]
        self.db.execute(
            """UPDATE matches SET bp_state='{"status":"completed"}' WHERE id=?""", (self.mid,)
        )
        self.db.commit()

    def seed_votes(self):
        for i, (side, a, b) in enumerate((("t1", 1, 0), ("t2", 0, 1), ("t1", None, None))):
            self.db.execute(
                "INSERT INTO match_votes(match_id,user_id,voted_for,score1_guess,score2_guess) VALUES(?,?,?,?,?)",
                (self.mid, self.base.people[i].account_id, side, a, b),
            )

    def play(self, index, a=13, b=7, *, participant=False):
        run = operations.observe_start(
            self.db, self.mid, self.slots[index], source="director", evidence="实际开图"
        )
        if participant:
            p = self.db.execute(
                "SELECT player_id,match_participant_id FROM map_run_lineups WHERE map_run_id=? LIMIT 1",
                (run,),
            ).fetchone()
            operations.record_participation(
                self.db, run, *p, source="director", round_number=1, side="CT"
            )
        result = results.confirm_map(
            self.db,
            self.mid,
            self.slots[index],
            run,
            a,
            b,
            actor="director",
            source="director",
            terminal_receipt=f"match-end-{run}",
        )
        self.assertTrue(result["applied"])
        return run

    def next_match(self, both=False, bo_format="BO3"):
        target = bracket.create_bracket_match(
            self.db, self.eid, bo_format=bo_format, stage="决赛", actor=ORGANIZER_ID
        )["match_id"]
        bracket.configure_bracket_link(
            self.db, self.mid, "winner", target, "home", actor=ORGANIZER_ID
        )
        if both:
            bracket.configure_bracket_link(
                self.db, self.mid, "loser", target, "away", actor=ORGANIZER_ID
            )
        return target

    def settle(self, **values):
        return results.settle_series(self.db, self.mid, actor=ORGANIZER_ID, **values)

    def correct(self, run, a, b, *, revision=None, index=0):
        return results.confirm_map(
            self.db,
            self.mid,
            self.slots[index],
            run,
            a,
            b,
            actor=ORGANIZER_ID,
            source="admin",
            reason="管理员核对原件",
            expected_revision=revision,
        )

    def points(self):
        return list(
            map(
                tuple,
                self.db.execute(
                    "SELECT scored,points_earned FROM match_votes WHERE match_id=? ORDER BY id",
                    (self.mid,),
                ),
            )
        )

    def test_two_temp_teams_bracket_score_history_and_explicit_reopen(self):
        self.schedule("BO1")
        with write(self.db):
            target = self.next_match(both=True)
            self.seed_votes()
            self.assertFalse(managed_vote_open(self.db, target))
            operations.authorize(self.db, self.mid, ORGANIZER_ID)
            run = self.play(0)
            self.assertEqual(self.points(), [(0, 0)] * 3)
            self.assertEqual(
                [r["event_entrant_id"] for r in bracket.get_bracket_links(self.db, self.eid)],
                [None, None],
            )
            before = results.read_results(self.db, self.mid)
            self.assertEqual((before["score1"], before["series"]), (1, None))
            settled = self.settle(expected_revision=before["revision"])
            self.assertFalse(self.settle(expected_revision=before["revision"])["applied"])
            self.assertEqual(self.points(), [(1, 8), (1, 0), (1, 3)])
            self.assertTrue(managed_vote_open(self.db, target))
            old = bracket.get_bracket_links(self.db, self.eid)
            self.assertTrue(all(link["event_entrant_id"] for link in old))
            self.assertEqual(settled["series"]["state"], "settled")
            self.assertEqual(settled["series"]["winner_side"], "home")
            self.assertEqual(
                settled["series"]["winner_event_entrant_id"],
                next(link["event_entrant_id"] for link in old if link["outcome"] == "winner"),
            )
            self.correct(run, 7, 13, revision=1)
            self.assertEqual(self.points(), [(1, 0), (1, 8), (1, 0)])
            new = bracket.get_bracket_links(self.db, self.eid)
            self.assertEqual(
                [r["event_entrant_id"] for r in new], [r["event_entrant_id"] for r in old][::-1]
            )
            self.assertTrue(
                {r["match_participant_id"] for r in new}.isdisjoint(
                    r["match_participant_id"] for r in old
                )
            )
            self.assertEqual(
                tuple(
                    self.db.execute(
                        "SELECT map1_t1,map1_t2,team1_score,team2_score FROM matches WHERE id=?",
                        (self.mid,),
                    ).fetchone()
                ),
                (7, 13, 0, 1),
            )
            self.assertFalse(self.correct(run, 7, 13, revision=1)["applied"])
            with self.assertRaises(HostError), write(self.db):
                self.correct(run, 13, 0, revision=1)
            history = self.db.execute(
                "SELECT old_points,new_points FROM prediction_settlement_changes ORDER BY settlement_id,vote_id"
            ).fetchall()
            self.assertEqual(
                list(map(tuple, history)), [(0, 8), (0, 0), (0, 3), (8, 0), (0, 8), (3, 0)]
            )
            self.db.execute(
                "UPDATE matches SET team1_score=1,team2_score=0 WHERE id=?", (self.mid,)
            )
            score_predictions(self.db)
            self.assertEqual(self.points(), [(1, 0), (1, 8), (1, 0)])
            self.assertEqual(
                get_prediction_leaderboard(self.db)[0]["user_id"], self.base.people[1].account_id
            )
            reopened = results.reopen_series(self.db, self.mid, actor=ORGANIZER_ID, reason="重审")
            self.assertEqual((reopened["series"]["state"], reopened["score2"]), ("reopened", 1))
            self.assertEqual(self.points(), [(0, 0)] * 3)
            self.assertFalse(managed_vote_open(self.db, self.mid))
            self.assertFalse(
                self.db.execute(
                    "SELECT 1 FROM match_participants WHERE match_id=?", (target,)
                ).fetchone()
            )
            self.assertEqual(self.settle()["status"], "completed")

    def test_score_replay_contributions_and_late_packet(self):
        self.schedule("BO1")
        with write(self.db):
            self.next_match()
            self.seed_votes()
            operations.authorize(self.db, self.mid, ORGANIZER_ID)
            old_run = self.play(0, participant=True)
            self.settle()
            self.assertEqual(
                self.db.execute("SELECT count(*) FROM official_player_map_stats").fetchone()[0], 1
            )
            operations.technical_replay(
                self.db, self.mid, old_run, admin_id=ORGANIZER_ID, reason="设备无法恢复"
            )
            state = results.read_results(self.db, self.mid)
            self.assertEqual(
                (state["status"], state["score1"], state["maps"][0]["official_map_result_id"]),
                ("live", 0, None),
            )
            self.assertEqual(self.points(), [(0, 0)] * 3)
            self.assertFalse(self.db.execute("SELECT 1 FROM official_player_map_stats").fetchone())
            self.assertIsNone(bracket.get_bracket_links(self.db, self.eid)[0]["event_entrant_id"])
            with self.assertRaises(HostError), write(self.db):
                self.correct(old_run, 13, 0)
            new_run = self.play(0, 0, 13, participant=True)
            self.assertNotEqual(new_run, old_run)
            self.assertEqual(
                tuple(
                    self.db.execute(
                        "SELECT map_run_id,stats_revision FROM official_player_map_stats"
                    ).fetchone()
                ),
                (new_run, 0),
            )
            self.assertEqual(self.settle()["score2"], 1)
            self.assertEqual(self.points(), [(1, 0), (1, 8), (1, 0)])
            self.assertEqual(
                tuple(
                    self.db.execute(
                        "SELECT is_current,revoked_by,revoke_reason FROM official_map_results WHERE map_run_id=?",
                        (old_run,),
                    ).fetchone()
                ),
                (0, ORGANIZER_ID, "设备无法恢复"),
            )

    def test_bo3_correction_reopens_incomplete_series_no_backward_replay(self):
        self.schedule("BO3")
        with write(self.db):
            target = self.next_match()
            operations.authorize(self.db, self.mid, ORGANIZER_ID)
            first = self.play(0)
            with self.assertRaises(HostError), write(self.db):
                self.settle()
            self.play(1)
            self.assertEqual(self.settle()["score1"], 2)
            with self.assertRaisesRegex(HostError, "后续"), write(self.db):
                results.revoke_for_replay(
                    self.db, self.mid, self.slots[0], first, actor=ORGANIZER_ID, reason="测试"
                )
            self.correct(first, 6, 13)
            state = results.read_results(self.db, self.mid)
            self.assertEqual((state["status"], state["score1"], state["score2"]), ("live", 1, 1))
            self.assertFalse(
                self.db.execute(
                    "SELECT 1 FROM match_participants WHERE match_id=?", (target,)
                ).fetchone()
            )
            self.play(2)
            self.assertEqual(self.settle()["score1"], 2)
            with self.assertRaisesRegex(HostError, "决胜"), write(self.db):
                self.correct(first, 13, 1)
            self.assertEqual(results.read_results(self.db, self.mid)["maps"][0]["score1"], 6)

    def test_bo5_must_reach_three_and_reject_wrong_run_machine_and_tie(self):
        self.schedule("BO5")
        with write(self.db):
            operations.authorize(self.db, self.mid, ORGANIZER_ID)
            run = self.play(0)
            for slot, a, b in [(0, 13, 13), (1, 13, 1), (0, 7, 13)]:
                with (
                    self.subTest(slot=slot, a=a, b=b),
                    self.assertRaises(HostError),
                    write(self.db),
                ):
                    results.confirm_map(
                        self.db,
                        self.mid,
                        self.slots[slot],
                        run,
                        a,
                        b,
                        source="director",
                        actor="director",
                        terminal_receipt=f"match-end-{run}",
                    )
            self.play(1)
            with self.assertRaises(HostError), write(self.db):
                self.settle()
            self.play(2, 1, 13)
            self.play(3, 1, 13)
            self.play(4)
            self.assertEqual((self.settle()["score1"], self.settle()["score2"]), (3, 2))

    def test_protection_and_failure_in_last_step_rollback_entire_correction(self):
        self.schedule("BO1")
        with write(self.db):
            target = self.next_match(both=True)
            self.seed_votes()
            operations.authorize(self.db, self.mid, ORGANIZER_ID)
            run = self.play(0, participant=True)
            self.settle()
        before = results.read_results(self.db, self.mid)
        bindings = bracket.get_bracket_links(self.db, self.eid)
        protected = (
            ("UPDATE matches SET bp_state='{}' WHERE id=?", (target,)),
            ("UPDATE matches SET status='live' WHERE id=?", (target,)),
            (
                "INSERT INTO match_rosters(match_participant_id,frozen_by,team_name,short_name,team_logo) VALUES(?,?,'队','队','')",
                (bindings[0]["match_participant_id"], ORGANIZER_ID),
            ),
            (
                "INSERT INTO match_votes(match_id,user_id,voted_for) VALUES(?,?,'t2')",
                (target, self.base.people[0].account_id),
            ),
        )
        for sql, args in protected:
            with self.subTest(sql=sql), self.assertRaisesRegex(HostError, "下游"), write(self.db):
                self.db.execute(sql, args)
                self.correct(run, 0, 13)
            self.assertEqual(results.read_results(self.db, self.mid), before)
            self.assertEqual(bracket.get_bracket_links(self.db, self.eid), bindings)
            self.assertEqual(self.points(), [(1, 8), (1, 0), (1, 3)])
        with self.assertRaisesRegex(sqlite3.IntegrityError, "最后一票"), write(self.db):
            self.db.execute("""CREATE TEMP TRIGGER refuse_last BEFORE UPDATE ON match_votes
                WHEN NEW.id=(SELECT max(id) FROM match_votes)
                BEGIN SELECT RAISE(ABORT,'最后一票拒写'); END""")
            self.correct(run, 0, 13)
        self.assertEqual(results.read_results(self.db, self.mid), before)
        self.assertEqual(bracket.get_bracket_links(self.db, self.eid), bindings)
        self.assertEqual(self.points(), [(1, 8), (1, 0), (1, 3)])
        self.assertEqual(
            self.db.execute(
                "SELECT official_map_result_id FROM official_player_map_stats"
            ).fetchone()[0],
            before["maps"][0]["official_map_result_id"],
        )
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(), [])
        with write(self.db):
            self.db.execute("UPDATE matches SET status='live' WHERE id=?", (target,))
            self.correct(run, 13, 6)
            self.assertEqual(bracket.get_bracket_links(self.db, self.eid), bindings)
        with self.assertRaisesRegex(HostError, "下游"), write(self.db):
            operations.technical_replay(
                self.db, self.mid, run, admin_id=ORGANIZER_ID, reason="故障重打"
            )
        self.assertEqual(
            self.db.execute("SELECT status FROM map_runs WHERE map_run_id=?", (run,)).fetchone()[0],
            "closed",
        )
        self.assertEqual(self.points(), [(1, 8), (1, 0), (1, 3)])

    def test_terminal_proof_and_regulation_overtime_or_exception(self):
        self.schedule("BO3")
        with write(self.db):
            operations.authorize(self.db, self.mid, ORGANIZER_ID)
            run = operations.observe_start(
                self.db, self.mid, self.slots[0], source="director", evidence="开图"
            )
            for a, b, receipt in [
                (13, 7, None),
                (6, 5, "mid"),
                (13, 12, "not-yet"),
                (15, 13, "not-yet"),
                (16, 15, "not-yet"),
                (17, 15, "not-yet"),
                (19, 14, "impossible"),
            ]:
                with self.subTest(score=(a, b)), self.assertRaises(HostError), write(self.db):
                    results.confirm_map(
                        self.db,
                        self.mid,
                        self.slots[0],
                        run,
                        a,
                        b,
                        actor="director",
                        source="director",
                        terminal_receipt=receipt,
                    )
            with self.assertRaisesRegex(HostError, "理由"), write(self.db):
                results.confirm_map(
                    self.db, self.mid, self.slots[0], run, 5, 7, actor=ORGANIZER_ID, source="admin"
                )
            self.assertEqual(
                results.read_results(self.db, self.mid)["maps"][0]["run_status"], "active"
            )
            accepted = self.correct(run, 5, 7)
            self.assertEqual((accepted["source"], accepted["reason"]), ("admin", "管理员核对原件"))
            self.play(1, 16, 12)
            self.play(2, 17, 19)
            self.assertEqual(self.settle()["score2"], 2)
            self.assertEqual(
                results.read_results(self.db, self.mid)["maps"][2]["terminal_receipt"],
                "match-end-3",
            )

    def test_bracket_cannot_form_cycle_steal_seed_or_cross_events(self):
        self.schedule("BO1")
        other = self.base._new_match("BO1")
        with write(self.db):
            target = self.next_match()
            for dest, side in [(self.mid, "away"), (target, "away")]:
                with self.assertRaises(HostError), write(self.db):
                    bracket.configure_bracket_link(
                        self.db, target, "winner", dest, side, actor=ORGANIZER_ID
                    )
            with self.assertRaises(HostError), write(self.db):
                bracket.configure_bracket_link(
                    self.db, self.mid, "loser", target, "home", actor=ORGANIZER_ID
                )
            with self.assertRaisesRegex(HostError, "同一赛事"), write(self.db):
                bracket.configure_bracket_link(
                    self.db, other, "winner", target, "away", actor=ORGANIZER_ID
                )
            self.assertEqual(len(bracket.get_bracket_links(self.db, self.eid)), 1)

    def test_admin_routes_create_empty_target_and_read_its_link(self):
        self.schedule("BO1")
        admin = self.base.admin
        headers = {"X-CSRF-Token": "host-bp-fixture"}
        event_path = f"/admin/events/{self.eid}/operations/bracket"
        match_path = f"/admin/matches/{self.mid}/operations"
        created = admin.post(
            event_path, json={"bo_format": "BO3", "stage": "决赛"}, headers=headers
        )
        self.assertEqual(created.status_code, 201, created.get_json())
        target = created.get_json()["match_id"]
        link = admin.post(
            match_path + "/bracket-link",
            json={"outcome": "winner", "target_match_id": target, "target_side": "away"},
            headers=headers,
        )
        self.assertEqual(link.status_code, 200, link.get_json())
        actual = admin.get(event_path).get_json()["links"]
        self.assertEqual(
            [
                (row["target_match_id"], row["target_side"], row["event_entrant_id"])
                for row in actual
            ],
            [(target, "away", None)],
        )
        self.assertEqual(admin.get(match_path).get_json()["results"]["revision"], 0)

    def test_retain_completed_downstream_exactly_once_without_touching_its_result_or_vote(self):
        self.schedule("BO1")
        with write(self.db):
            target = self.next_match(both=True, bo_format="BO1")
            self.seed_votes()
            operations.authorize(self.db, self.mid, ORGANIZER_ID)
            run = self.play(0, participant=True)
            upstream = self.settle()
            links = bracket.get_bracket_links(self.db, self.eid)
            claims = [
                {
                    "target_match_id": target,
                    "target_side": link["target_side"],
                    "retained_entrant_id": link["event_entrant_id"],
                    "proposed_entrant_id": other["event_entrant_id"],
                }
                for link, other in zip(links, reversed(links))
            ]
            self.db.execute(
                "INSERT INTO match_votes(match_id,user_id,voted_for,score1_guess,score2_guess) VALUES(?,?,'t1',1,0)",
                (target, self.base.people[0].account_id),
            )
            maps.sync_scheduled_maps(self.db, target, setup={"map1": "Mirage"})
            participants.freeze_rosters(self.db, target, ORGANIZER_ID)
            self.db.execute(
                """UPDATE matches SET bp_state='{"status":"completed"}' WHERE id=?""", (target,)
            )
            operations.authorize(self.db, target, ORGANIZER_ID)
            slot = results.read_results(self.db, target)["maps"][0]["scheduled_map_id"]
            down_run = operations.observe_start(
                self.db, target, slot, source="director", evidence="决赛开打"
            )
            results.confirm_map(
                self.db, target, slot, down_run, 13, 8, actor=ORGANIZER_ID, source="admin"
            )
            results.settle_series(self.db, target, actor=ORGANIZER_ID)
        downstream = results.read_results(self.db, target)
        old_vote = dict(
            self.db.execute("SELECT * FROM match_votes WHERE match_id=?", (target,)).fetchone()
        )
        self.assertEqual(old_vote["points_earned"], 8)
        note = "保留已完成决赛的实际对阵、原票和结果"

        def correct(
            entries,
            *,
            actor=ORGANIZER_ID,
            source="admin",
            reason=note,
            expected_revision=upstream["maps"][0]["revision"],
            expected_series_revision=upstream["revision"],
        ):
            return results.confirm_map(
                self.db,
                self.mid,
                self.slots[0],
                run,
                7,
                13,
                retain_downstream=entries,
                actor=actor,
                source=source,
                reason=reason,
                expected_revision=expected_revision,
                expected_series_revision=expected_series_revision,
            )

        for entries, overrides in [
            (claims[:1], {}),
            (claims + [dict(claims[0], target_match_id=self.mid)], {}),
            ([claims[0], claims[0]], {}),
            ([claims[0], dict(claims[1], retained_entrant_id=99999)], {}),
            ([dict(claims[0], proposed_entrant_id=None), claims[1]], {}),
            (claims, {"expected_series_revision": upstream["revision"] - 1}),
            (claims, {"expected_revision": 0}),
            (claims, {"expected_series_revision": None}),
            (claims, {"expected_revision": None}),
            (claims, {"reason": " "}),
            (claims, {"actor": "director", "source": "director"}),
        ]:
            with (
                self.subTest(entries=entries, overrides=overrides),
                self.assertRaises(HostError),
                write(self.db),
            ):
                correct(entries, **overrides)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "上游积分拒写"), write(self.db):
            self.db.execute("""CREATE TEMP TRIGGER fail_upstream BEFORE UPDATE ON match_votes
                               BEGIN SELECT RAISE(ABORT,'上游积分拒写'); END""")
            correct(claims)
        self.assertEqual(results.read_results(self.db, self.mid)["revision"], upstream["revision"])
        self.assertEqual(bracket.get_bracket_links(self.db, self.eid), links)
        self.assertEqual(self.points(), [(1, 8), (1, 0), (1, 3)])
        self.assertFalse(self.db.execute("SELECT 1 FROM bracket_retention_decisions").fetchone())

        with write(self.db):
            correct(claims)
        self.assertEqual(self.points(), [(1, 0), (1, 8), (1, 0)])
        current = results.read_results(self.db, self.mid)["series"]
        self.assertEqual(current["winner_side"], "away")
        history = self.db.execute(
            """SELECT d.*,s.reason,s.actor FROM bracket_retention_decisions d
               JOIN series_settlements s USING(settlement_id) ORDER BY outcome"""
        ).fetchall()
        self.assertEqual(len(history), 2)
        for old, new, decision, claim in zip(
            links, bracket.get_bracket_links(self.db, self.eid), history, claims
        ):
            self.assertEqual(
                new, dict(old, detached=1, detached_settlement_id=current["settlement_id"])
            )
            self.assertEqual(tuple(decision[key] for key in claim), tuple(claim.values()))
            self.assertEqual(
                (
                    decision["source_match_id"],
                    decision["outcome"],
                    decision["retained_participant_id"],
                    decision["actor"],
                    decision["reason"],
                ),
                (
                    self.mid,
                    old["outcome"],
                    old["match_participant_id"],
                    ORGANIZER_ID,
                    note,
                ),
            )
        with self.assertRaises(HostError), write(self.db):
            correct(claims)
        with write(self.db):
            results.reopen_series(self.db, self.mid, actor=ORGANIZER_ID, reason="重新确认上游")
            self.settle()
        self.assertEqual(results.read_results(self.db, target), downstream)
        self.assertEqual(
            dict(
                self.db.execute("SELECT * FROM match_votes WHERE match_id=?", (target,)).fetchone()
            ),
            old_vote,
        )
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM bracket_retention_decisions").fetchone()[0], 2
        )
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_reopen_or_replay_retains_only_voted_target_and_clears_mutable_loser(self):
        for action in ("reopen", "replay"):
            with self.subTest(action=action):
                self.schedule("BO1")
                with write(self.db):
                    target = self.next_match()
                    other = bracket.create_bracket_match(
                        self.db, self.eid, bo_format="BO1", stage="败者组", actor=ORGANIZER_ID
                    )["match_id"]
                    bracket.configure_bracket_link(
                        self.db, self.mid, "loser", other, "away", actor=ORGANIZER_ID
                    )
                    self.seed_votes()
                    operations.authorize(self.db, self.mid, ORGANIZER_ID)
                    run = self.play(0)
                    up = self.settle()
                    # 主位来自晋级，另一侧为该届已排定的对手：有完整两方才接受旧票。
                    self.db.execute(
                        """INSERT INTO match_participants(match_id,event_id,event_entrant_id,side_key)
                           SELECT ?,event_id,event_entrant_id,'away' FROM match_participants
                           WHERE match_id=? AND side_key='away'""",
                        (target, self.mid),
                    )
                    self.assertTrue(managed_vote_open(self.db, target))
                    self.db.execute(
                        "INSERT INTO match_votes(match_id,user_id,voted_for) VALUES(?,?,'t1')",
                        (target, self.base.people[0].account_id),
                    )
                # 模拟仍未完赛且已有旧票的下游；不让票随固定边改投。
                loser, winner = bracket.get_bracket_links(self.db, self.eid)
                claim = {
                    "target_match_id": target,
                    "target_side": "home",
                    "retained_entrant_id": winner["event_entrant_id"],
                    "proposed_entrant_id": None,
                }
                common = dict(
                    actor=ORGANIZER_ID, reason="保留下游原对阵和旧票", retain_downstream=[claim]
                )
                with self.assertRaises(HostError), write(self.db):
                    results.reopen_series(
                        self.db,
                        self.mid,
                        **(
                            common
                            | {
                                "retain_downstream": [
                                    claim,
                                    dict(
                                        claim,
                                        target_match_id=other,
                                        target_side="away",
                                        retained_entrant_id=loser["event_entrant_id"],
                                    ),
                                ]
                            }
                        ),
                        expected_revision=up["revision"],
                    )
                with write(self.db):
                    if action == "reopen":
                        results.reopen_series(
                            self.db, self.mid, **common, expected_revision=up["revision"]
                        )
                    else:
                        results.revoke_for_replay(
                            self.db,
                            self.mid,
                            self.slots[0],
                            run,
                            **common,
                            expected_revision=up["maps"][0]["revision"],
                            expected_series_revision=up["revision"],
                        )
                loser_now, winner_now = bracket.get_bracket_links(self.db, self.eid)
                self.assertEqual((loser_now["detached"], loser_now["event_entrant_id"]), (0, None))
                self.assertEqual(
                    (winner_now["detached"], winner_now["match_participant_id"]),
                    (1, winner["match_participant_id"]),
                )
                audit = self.db.execute(
                    "SELECT proposed_entrant_id FROM bracket_retention_decisions WHERE source_match_id=?",
                    (self.mid,),
                ).fetchone()
                self.assertIsNone(audit[0])
                self.assertEqual(self.points(), [(0, 0)] * 3)
                self.assertEqual(
                    results.read_results(self.db, self.mid)["series"]["state"], "reopened"
                )
