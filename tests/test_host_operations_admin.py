"""原后台与新管理接口读写同一场，保留改前改后的记录。"""

import unittest
from contextlib import closing

from models import get_db
from site_core.host import write
from site_core.matches import operations
from tests import test_host_bp_maps as prematch
from tests import test_host_operations_results as decisions
from tests.entrant_slice_fixtures import ORGANIZER_ID


class ManagedAdminAuditTests(unittest.TestCase):
    def test_admin_can_keep_a_voted_downstream_slot_on_reviewed_technical_replay(self):
        fixture = decisions.SettlementTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        fixture.schedule("BO1")
        with write(fixture.db):
            target = fixture.next_match(both=True)
            operations.authorize(fixture.db, fixture.mid, ORGANIZER_ID)
            run = fixture.play(0)
            settled = fixture.settle()
            fixture.db.execute(
                "INSERT INTO match_votes(match_id,user_id,voted_for) VALUES(?,?,'t1')",
                (target, fixture.base.people[0].account_id),
            )
        admin = fixture.base.admin
        path = f"/admin/matches/{fixture.mid}/operations"
        links = admin.get(f"/admin/events/{fixture.eid}/operations/bracket").get_json()["links"]
        request = {
            "map_run_id": run,
            "expected_revision": settled["maps"][0]["revision"],
            "expected_series_revision": settled["revision"],
            "reason": "上游故障重赛；保留已开放竞猜的下游对阵",
        }
        headers = {"X-CSRF-Token": "host-bp-fixture"}
        blocked = admin.post(path + "/technical-replay", json=request, headers=headers)
        self.assertEqual(blocked.status_code, 409, blocked.get_json())
        self.assertEqual(admin.get(path + "/history").get_json()["retained"], [])
        request["retain_downstream"] = [
            {
                "target_match_id": target,
                "target_side": link["target_side"],
                "retained_entrant_id": link["event_entrant_id"],
                "proposed_entrant_id": None,
            }
            for link in links
        ]
        accepted = admin.post(path + "/technical-replay", json=request, headers=headers)
        self.assertEqual(accepted.status_code, 200, accepted.get_json())
        self.assertEqual(accepted.get_json()["void_map_run_id"], run)
        history = admin.get(path + "/history").get_json()
        self.assertEqual(history["series"][-1]["state"], "reopened")
        self.assertEqual(
            {
                (r["target_side"], r["retained_entrant_id"], r["proposed_entrant_id"])
                for r in history["retained"]
            },
            {(r["target_side"], r["event_entrant_id"], None) for r in links},
        )
        self.assertTrue(
            all(
                r["actor"] == ORGANIZER_ID and r["reason"] == request["reason"] and r["recorded_at"]
                for r in history["retained"]
            )
        )

    def test_old_forms_and_new_controls_share_revisions_and_audit(self):
        base = prematch.HostedBPTests()
        self.addCleanup(base.doCleanups)
        base.setUp()
        mid = base._new_match("BO1", setup={"map1": "Mirage"})
        url = f"/admin/matches/{mid}"
        db = self.enterContext(closing(get_db()))
        db.execute("UPDATE matches SET bp_state=? WHERE id=?", ('{"status":"completed"}', mid))
        db.commit()
        plan = base.admin.get(url + "/operations").get_json()["maps"][0]["scheduled_map_id"]
        headers = {"X-CSRF-Token": "host-bp-fixture"}

        def submit(path, **body):
            result = base.admin.post(url + path, headers=headers, json=body)
            self.assertEqual(result.status_code, 200, result.get_data(as_text=True))
            return result.get_json()

        self.assertNotEqual(base._client().get(url + "/operations/history").status_code, 200)
        self.assertNotEqual(
            base.admin.post(url + "/operations/authorize", json={}).status_code, 200
        )
        submit("/operations/authorize")
        run = submit("/operations/start", scheduled_map_id=plan, evidence="管理员核对首回合现场")[
            "map_run_id"
        ]
        player, team = db.execute(
            "SELECT player_id,match_participant_id FROM map_run_lineups WHERE map_run_id=? LIMIT 1",
            (run,),
        ).fetchone()
        submit(
            "/operations/participation",
            map_run_id=run,
            player_id=player,
            match_participant_id=team,
            reason="核对首回合出场",
        )
        submit(
            "/stats",
            map_run_id=run,
            player_id=player,
            fields={"kills": 0},
            expected_revision=0,
            reason="核对记分板",
        )
        fields = base.admin.get(
            f"{url}/operations/runs/{run}/players/{player}/stats?history=1"
        ).get_json()
        self.assertEqual((fields["fields"]["kills"], len(fields["history"])), (0, 1))
        first = submit(
            "/operations/confirm-map",
            scheduled_map_id=plan,
            map_run_id=run,
            score1=13,
            score2=8,
            expected_revision=0,
        )
        settled = submit("/complete", expected_revision=first["series_revision"])
        submit("/reopen", expected_revision=settled["revision"], reason="核对赛果记录")
        history = base.admin.get(url + "/operations/history").get_json()
        self.assertEqual([r["state"] for r in history["series"]], ["settled", "reopened"])
        self.assertEqual(history["series"][-1]["reason"], "核对赛果记录")
        self.assertEqual(
            history["series"][0]["map_result_ids"], [history["maps"][0]["official_map_result_id"]]
        )
        self.assertEqual((history["maps"][0]["score1"], history["maps"][0]["score2"]), (13, 8))
