"""End-to-end verification of Phase 3 Slice 3 frontend match operations, managed bracket, and live fixes."""

import io
import json
import tempfile
import time
import unittest
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from app import app
from config import Config
from models import get_db, init_tables
from site_core.host import write
from site_core.matches import demo_storage


class FrontendSlice3OperationsTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = self.enterContext(tempfile.TemporaryDirectory(prefix="fe-slice3-"))
        self.demo_root = Path(self.sandbox) / "demo_originals"
        self.demo_root.mkdir(parents=True, exist_ok=True)
        self.enterContext(
            patch.object(Config, "DATABASE", str(Path(self.sandbox) / "test.db"))
        )
        self.enterContext(
            patch.object(demo_storage, "private_root", return_value=self.demo_root)
        )
        self.enterContext(
            patch.dict(app.config, {"TESTING": True, "SESSION_COOKIE_SECURE": False})
        )
        init_tables()
        self.db = self.enterContext(closing(get_db()))
        self.now = int(time.time())
        with write(self.db):
            self.admin_id = self.db.execute(
                "INSERT INTO admins(username,password_hash) VALUES('s3-admin','disabled')"
            ).lastrowid
            self.accounts = []
            self.player_ids = []
            for idx in range(13):
                nick = f"运营选手{idx + 1:02}"
                steam = str(76561199002200000 + idx)
                uid = self.db.execute(
                    """INSERT INTO users(username,email,password_hash,steam_id64,approval_status,
                               group_username,is_bashizhong_student)
                       VALUES(?,?,'disabled',?,'approved',?,1)""",
                    (f"s3u{idx}", f"s3u{idx}@example.invalid", steam, nick),
                ).lastrowid
                pid = self.db.execute(
                    """INSERT INTO players(nickname,steam_id,cs2_playtime_minutes,is_bashizhong_student)
                       VALUES(?,?,?,1)""",
                    (nick, steam, 800 + idx * 25),
                ).lastrowid
                self.accounts.append(uid)
                self.player_ids.append(pid)

            club_a = self.db.execute(
                "INSERT INTO teams(name,short_name) VALUES('旧俱乐部A','LA')"
            ).lastrowid
            club_b = self.db.execute(
                "INSERT INTO teams(name,short_name) VALUES('旧俱乐部B','LB')"
            ).lastrowid
            start_day = (date.today() + timedelta(days=1)).isoformat()
            end_day = (date.today() + timedelta(days=7)).isoformat()
            self.legacy_event_id = self.db.execute(
                """INSERT INTO events(name,short_name,slug,start_date,end_date,status,registration_open)
                   VALUES('往届旧赛','OLD','old-event',?,?,'upcoming',1)""",
                (start_day, end_day),
            ).lastrowid
            self.legacy_match_id = self.db.execute(
                """INSERT INTO matches(event_id,team1_id,team2_id,match_time,bo_format,status,slug)
                   VALUES(?,?,?,?,'BO1','upcoming','old-la-vs-lb')""",
                (self.legacy_event_id, club_a, club_b, f"{start_day} 19:00"),
            ).lastrowid

        self.admin = self._client(admin_id=self.admin_id, admin_username="s3-admin")
        self.visitor = app.test_client()

    @staticmethod
    def _client(**identity):
        client = app.test_client()
        with client.session_transaction() as sess:
            sess.update(identity, csrf_token="s3-fe-csrf")
        return client

    @staticmethod
    def _post(client, url, **kwargs):
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("X-CSRF-Token", "s3-fe-csrf")
        headers.setdefault("X-Requested-With", "XMLHttpRequest")
        return client.post(url, headers=headers, **kwargs)

    def _prepare_bo3_match(self):
        start_day = (date.today() + timedelta(days=1)).isoformat()
        end_day = (date.today() + timedelta(days=10)).isoformat()
        res = self._post(
            self.admin,
            "/admin/events/add",
            data={
                "name": "Slice3 运营杯",
                "short_name": "S3OP",
                "start_date": start_day,
                "end_date": end_day,
                "registration_deadline": str(self.now + 7200),
            },
        )
        self.assertEqual(res.status_code, 302)
        eid = self.db.execute("SELECT id FROM events WHERE short_name='S3OP'").fetchone()["id"]
        users = [self._client(user_id=u) for u in self.accounts]
        for idx in range(10):
            self.assertTrue(
                self._post(users[idx], f"/events/{eid}/register-individual").get_json()["success"]
            )
        self.assertTrue(
            self._post(users[10], f"/events/{eid}/register-substitute").get_json()["success"]
        )
        with write(self.db):
            self.db.execute(
                "UPDATE event_registration_control SET registration_deadline=? WHERE event_id=?",
                (self.now - 10, eid),
            )
        self.assertEqual(
            self._post(self.admin, f"/admin/events/{eid}/registration-control/form-due", json={}).status_code,
            200,
        )
        ctrl = self.admin.get(f"/admin/events/{eid}/registration-control").get_json()
        entrant_ids = [e["event_entrant_id"] for e in ctrl["entrants"]]
        self.assertEqual(len(entrant_ids), 2)
        self.assertEqual(
            self._post(
                self.admin,
                f"/admin/events/{eid}/registration-control/confirm-initial",
                json={"event_entrant_ids": entrant_ids, "expected_revision": ctrl["formation_revision"]},
            ).status_code,
            200,
        )
        ctrl = self.admin.get(f"/admin/events/{eid}/registration-control").get_json()
        reserve_pid = self.player_ids[10]
        self.assertEqual(
            self._post(
                self.admin,
                f"/admin/events/{eid}/registration-control/assign-reserve",
                json={
                    "event_entrant_id": entrant_ids[0],
                    "player_id": reserve_pid,
                    "expected_revision": ctrl["formation_revision"],
                    "reason": "分配技术替补席",
                    "excluded_candidates": {},
                },
            ).status_code,
            200,
        )
        res = self._post(
            self.admin,
            "/admin/matches/add",
            data={
                "event_id": str(eid),
                "match_time": f"{start_day} 20:00",
                "bo_format": "BO3",
                "stage": "半决赛",
                "side1_type": "entrant",
                "side1_id": str(entrant_ids[0]),
                "side2_type": "entrant",
                "side2_id": str(entrant_ids[1]),
                "map1": "de_mirage",
                "map2": "de_inferno",
                "map3": "de_ancient",
            },
        )
        self.assertEqual(res.status_code, 302)
        mid = self.db.execute("SELECT id FROM matches WHERE event_id=?", (eid,)).fetchone()["id"]
        self.assertEqual(
            self._post(self.admin, f"/admin/matches/{mid}/freeze-rosters").status_code, 302
        )
        with write(self.db):
            self.db.execute(
                "UPDATE matches SET bp_state=? WHERE id=?",
                (json.dumps({"status": "completed"}), mid),
            )
            # 两位观众在授权开赛前提交赛前预测（1 位命中 2:1 得 8 分，1 位猜错得 0 分）
            self.db.execute(
                """INSERT INTO match_votes(match_id,user_id,voted_for,score1_guess,score2_guess)
                   VALUES(?,?,'t1',2,1)""",
                (mid, self.accounts[11]),
            )
            self.db.execute(
                """INSERT INTO match_votes(match_id,user_id,voted_for,score1_guess,score2_guess)
                   VALUES(?,?,'t2',0,2)""",
                (mid, self.accounts[12]),
            )
        return eid, mid, entrant_ids, reserve_pid

    def test_operate_page_routes_guards_and_redirects(self):
        eid, mid, _, _ = self._prepare_bo3_match()

        # Anonymous blocked
        self.assertEqual(self.visitor.get(f"/admin/matches/{mid}/operate").status_code, 302)
        self.assertEqual(
            self.visitor.get(
                f"/admin/matches/{mid}/operations/panel-context",
                headers={"X-Requested-With": "XMLHttpRequest"},
            ).status_code,
            401,
        )

        # Legacy match redirects away from /operate cleanly
        legacy_res = self.admin.get(f"/admin/matches/{self.legacy_match_id}/operate")
        self.assertEqual(legacy_res.status_code, 302)
        self.assertIn(f"/admin/matches/edit/{self.legacy_match_id}", legacy_res.headers["Location"])

        # Managed match /stats and /import-demo GET redirect to /operate tabs
        stats_red = self.admin.get(f"/admin/matches/{mid}/stats")
        self.assertEqual(stats_red.status_code, 302)
        self.assertTrue(stats_red.headers["Location"].endswith(f"/admin/matches/{mid}/operate#stats"))
        demo_red = self.admin.get(f"/admin/matches/{mid}/import-demo")
        self.assertEqual(demo_red.status_code, 302)
        self.assertTrue(demo_red.headers["Location"].endswith(f"/admin/matches/{mid}/operate#demos"))

        # Admin matches list & match edit show Match Operations link for managed match only
        list_html = self.admin.get("/admin/matches").get_data(as_text=True)
        managed_row = list_html.split(f'id="match-{mid}"')[1].split("</tr>")[0]
        legacy_row = list_html.split(f'id="match-{self.legacy_match_id}"')[1].split("</tr>")[0]
        self.assertIn(f"/admin/matches/{mid}/operate", managed_row)
        self.assertIn("比赛运营", managed_row)
        self.assertNotIn(f"/admin/matches/{self.legacy_match_id}/operate", legacy_row)

        edit_html = self.admin.get(f"/admin/matches/edit/{mid}").get_data(as_text=True)
        self.assertIn(f"/admin/matches/{mid}/operate", edit_html)
        self.assertIn("进入比赛运营", edit_html)

        # Match operations page renders all 4 tabs and initial embedded bundle
        op_res = self.admin.get(f"/admin/matches/{mid}/operate")
        self.assertEqual(op_res.status_code, 200)
        op_html = op_res.get_data(as_text=True)
        self.assertIn("window.MATCH_OPS_BUNDLE =", op_html)
        for tab_name in ("runs", "demos", "results", "stats"):
            self.assertIn(f'data-ops-tab="{tab_name}"', op_html)

        # Managed event bracket page renders managed UI while preserving window._eventMatches
        br_res = self.admin.get(f"/admin/events/{eid}/bracket")
        self.assertEqual(br_res.status_code, 200)
        br_html = br_res.get_data(as_text=True)
        self.assertIn("托管赛事晋级管理", br_html)
        self.assertRegex(br_html, r"window\._eventMatches\s*=\s*\[")

    def test_full_slice3_ui_workflow_panel_context_and_retention(self):
        eid, mid, entrant_ids, reserve_pid = self._prepare_bo3_match()
        base = f"/admin/matches/{mid}/operations"

        # 1. Pre-auth panel-context check
        snap = self.admin.get(base + "/panel-context").get_json()
        self.assertTrue(snap["ok"])
        self.assertTrue(snap["overview"]["eligible"])
        self.assertFalse(snap["overview"]["authorized"])
        self.assertTrue(snap["context"]["predictions"]["vote_open"])
        self.assertEqual(snap["context"]["predictions"]["total_votes"], 2)
        self.assertEqual(len(snap["overview"]["maps"]), 3)
        self.assertEqual(
            [r["player_id"] for r in snap["context"]["participants"][0]["assigned_reserves"]],
            [reserve_pid],
        )

        # 2. Authorize start
        auth = self._post(self.admin, base + "/authorize", json={})
        self.assertEqual(auth.status_code, 200)
        snap = self.admin.get(base + "/panel-context").get_json()
        self.assertTrue(snap["overview"]["ready_for_start"])
        self.assertFalse(snap["context"]["predictions"]["vote_open"])

        maps = snap["overview"]["maps"]
        home_party = snap["context"]["participants"][0]
        outgoing_pid = home_party["players"][4]["id"]

        # 3. Map 1 start, participation, withdraw/restore, director binding, receipts, confirm
        r1 = self._post(
            self.admin,
            base + "/start",
            json={"scheduled_map_id": maps[0]["scheduled_map_id"], "evidence": "图一开局核对"},
        ).get_json()["map_run_id"]
        part1 = self._post(
            self.admin,
            base + "/participation",
            json={
                "map_run_id": r1,
                "player_id": outgoing_pid,
                "match_participant_id": home_party["match_participant_id"],
                "round_number": 1,
                "side": "CT",
                "reason": "首回合出场",
            },
        ).get_json()["participation_id"]
        # Withdraw then restore
        w = self._post(
            self.admin,
            base + "/review-participation",
            json={"participation_id": part1, "present": False, "expected_revision": 1, "reason": "误登核销"},
        ).get_json()
        self.assertFalse(w["present"])
        rst = self._post(
            self.admin,
            base + "/review-participation",
            json={"participation_id": part1, "present": True, "expected_revision": w["revision"], "reason": "复核确认上场"},
        ).get_json()
        self.assertTrue(rst["present"])

        # Bind independent director session & read receipts
        bind = self._post(
            self.admin,
            base + "/bind-director-session",
            json={"map_run_id": r1, "session_id": "dir-s3-map1", "reason": "核对导播端会话"},
        )
        self.assertEqual(bind.status_code, 200)
        receipts = self.admin.get(f"{base}/runs/{r1}/director-receipts").get_json()
        self.assertTrue(receipts["ok"])
        self.assertEqual(receipts["receipts"], [])

        # Confirm Map 1 (13:8)
        cm1 = self._post(
            self.admin,
            base + "/confirm-map",
            json={
                "scheduled_map_id": maps[0]["scheduled_map_id"],
                "map_run_id": r1,
                "score1": 13,
                "score2": 8,
                "expected_revision": 0,
                "reason": "图一终局确认",
            },
        )
        self.assertEqual(cm1.status_code, 200)

        # 4. Map 2 start -> upload demo -> technical replay with substitute -> replay run
        r2_void = self._post(
            self.admin,
            base + "/start",
            json={"scheduled_map_id": maps[1]["scheduled_map_id"], "evidence": "图二首次开局"},
        ).get_json()["map_run_id"]
        up_void = self._post(
            self.admin,
            f"/admin/matches/{mid}/api/demos",
            data={
                "scheduled_map_id": str(maps[1]["scheduled_map_id"]),
                "map_run_id": str(r2_void),
                "demo": (io.BytesIO(b"PBDEMS2\x00VOID-ARCHIVE"), "map2_void.dem"),
            },
        )
        self.assertEqual(up_void.status_code, 201)
        void_demo_id = up_void.get_json()["original"]["demo_id"]

        tr = self._post(
            self.admin,
            base + "/technical-replay",
            json={
                "map_run_id": r2_void,
                "reason": "图二服务器崩溃且原队员断线",
                "outgoing_player_id": outgoing_pid,
                "incoming_player_id": reserve_pid,
            },
        )
        self.assertEqual(tr.status_code, 200)

        # Void run original demo remains downloadable for admin audit
        with self.admin.get(f"/admin/matches/{mid}/api/demos/{void_demo_id}/file") as dl:
            self.assertEqual(dl.status_code, 200)
            self.assertEqual(dl.data, b"PBDEMS2\x00VOID-ARCHIVE")

        # Start Map 2 replay with previous_map_run_id
        r2 = self._post(
            self.admin,
            base + "/start",
            json={
                "scheduled_map_id": maps[1]["scheduled_map_id"],
                "previous_map_run_id": r2_void,
                "evidence": "图二重赛新局",
            },
        ).get_json()["map_run_id"]
        self.assertEqual(
            self._post(
                self.admin,
                base + "/confirm-map",
                json={
                    "scheduled_map_id": maps[1]["scheduled_map_id"],
                    "map_run_id": r2,
                    "score1": 9,
                    "score2": 13,
                    "expected_revision": 0,
                },
            ).status_code,
            200,
        )

        # 5. Map 3 carries substitute automatically & confirms 13:10 (still NOT auto-settled!)
        r3 = self._post(
            self.admin,
            base + "/start",
            json={"scheduled_map_id": maps[2]["scheduled_map_id"], "evidence": "图三开局"},
        ).get_json()["map_run_id"]
        self.assertEqual(
            self._post(
                self.admin,
                base + "/confirm-map",
                json={
                    "scheduled_map_id": maps[2]["scheduled_map_id"],
                    "map_run_id": r3,
                    "score1": 13,
                    "score2": 10,
                    "expected_revision": 0,
                },
            ).status_code,
            200,
        )
        snap = self.admin.get(base + "/panel-context").get_json()
        self.assertEqual(snap["overview"]["results"]["score1"], 2)
        self.assertEqual(snap["overview"]["results"]["score2"], 1)
        self.assertIsNone(snap["overview"]["results"]["series"])
        map3_eff_ids = {p["player_id"] for p in snap["overview"]["maps"][2]["effective_roster"]}
        self.assertIn(reserve_pid, map3_eff_ids)
        self.assertNotIn(outgoing_pid, map3_eff_ids)

        # 6. Create downstream match & link winner via managed bracket APIs
        downstream = self._post(
            self.admin,
            f"/admin/events/{eid}/operations/bracket",
            json={"stage": "总决赛", "bo_format": "BO3"},
        )
        self.assertEqual(downstream.status_code, 201)
        target_mid = downstream.get_json()["match_id"]
        link = self._post(
            self.admin,
            base + "/bracket-link",
            json={"outcome": "winner", "target_match_id": target_mid, "target_side": "home"},
        )
        self.assertEqual(link.status_code, 200)

        # 7. Explicitly settle series -> predictions get exact backend 8 / 0 pts & downstream placed
        settle = self._post(
            self.admin,
            base + "/settle",
            json={
                "expected_revision": snap["overview"]["results"]["revision"],
                "reason": "核对三图比分后正式完赛",
            },
        )
        self.assertEqual(settle.status_code, 200)
        snap = self.admin.get(base + "/panel-context").get_json()
        self.assertEqual(snap["context"]["match"]["status"], "completed")
        pts = sorted(v["points_earned"] for v in snap["context"]["predictions"]["votes"])
        self.assertEqual(pts, [0, 8])
        self.assertEqual(snap["context"]["downstream_links"][0]["event_entrant_id"], entrant_ids[0])
        self.assertFalse(snap["context"]["downstream_links"][0]["protected"])
        options = snap["context"]["map_change_options"]
        self.assertEqual(options[str(maps[2]["scheduled_map_id"])]["away"]["winner"], entrant_ids[1])
        self.assertIn("error", options[str(maps[0]["scheduled_map_id"])]["away"])

        # 8. Protect downstream slot with a user vote, confirm panel-context surfaces protection & reopen requires explicit retain_downstream
        with write(self.db):
            self.db.execute(
                "INSERT INTO match_votes(match_id,user_id,voted_for) VALUES(?,?,'t1')",
                (target_mid, self.accounts[11]),
            )
        snap = self.admin.get(base + "/panel-context").get_json()
        dl_link = snap["context"]["downstream_links"][0]
        self.assertTrue(dl_link["protected"])
        self.assertIn("竞猜", dl_link["protection_reason"])

        blocked = self._post(
            self.admin,
            base + "/reopen",
            json={"expected_revision": snap["overview"]["results"]["revision"], "reason": "核对图三争议"},
        )
        self.assertEqual(blocked.status_code, 409)

        reopened = self._post(
            self.admin,
            base + "/reopen",
            json={
                "expected_revision": snap["overview"]["results"]["revision"],
                "reason": "核对图三争议并保留下游已开猜签位",
                "retain_downstream": [
                    {
                        "target_match_id": target_mid,
                        "target_side": "home",
                        "retained_entrant_id": entrant_ids[0],
                        "proposed_entrant_id": None,
                    }
                ],
            },
        )
        self.assertEqual(reopened.status_code, 200)
        hist = self.admin.get(base + "/history").get_json()
        self.assertEqual(len(hist["retained"]), 1)

        # 9. Stats Revision Workbench: explicit 0 vs null, touched-only submit, stale revision 409
        prev = self._post(
            self.admin,
            base + "/preview-stats",
            json={
                "map_run_id": r1,
                "player_id": outgoing_pid,
                "scope": "all",
                "fields": {"kills": 0, "deaths": 12},
                "expected_revision": 0,
                "reason": "核对记分板零击杀",
            },
        )
        self.assertEqual(prev.status_code, 200)
        self.assertEqual(prev.get_json()["changes"]["kills"]["after"], 0)

        saved = self._post(
            self.admin,
            base + "/stats",
            json={
                "map_run_id": r1,
                "player_id": outgoing_pid,
                "scope": "all",
                "fields": {"kills": 0, "deaths": 12},
                "expected_revision": 0,
                "reason": "核对记分板零击杀",
            },
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.get_json()["revision"], 1)

        stale = self._post(
            self.admin,
            base + "/stats",
            json={
                "map_run_id": r1,
                "player_id": outgoing_pid,
                "scope": "all",
                "fields": {"assists": 3},
                "expected_revision": 0,
                "reason": "过期版本测试",
            },
        )
        self.assertEqual(stale.status_code, 409)

        read_back = self.admin.get(
            f"{base}/runs/{r1}/players/{outgoing_pid}/stats?scope=all&history=1"
        ).get_json()
        self.assertEqual(read_back["fields"]["kills"], 0)
        self.assertEqual(read_back["fields"]["deaths"], 12)
        self.assertIsNone(read_back["fields"].get("assists"))
        self.assertEqual(len(read_back["history"]), 1)

    def test_live_templates_handle_map_run_void_and_null_vs_zero(self):
        _, mid, _, _ = self._prepare_bo3_match()
        with write(self.db):
            self.db.execute("UPDATE matches SET status='live' WHERE id=?", (mid,))

        detail_html = self.visitor.get(f"/matches/{mid}", follow_redirects=True).get_data(as_text=True)
        self.assertIn("data.reason==='map_run_void'", detail_html)
        self.assertIn("clearLiveForVoid", detail_html)
        self.assertIn("liveMetric(player.kills)", detail_html)
        self.assertIn("event.score_ct!=null&&event.score_t!=null", detail_html)
        self.assertNotIn("Number(player.kills||0)", detail_html)

        live_tpl = Path("templates/match_live.html").read_text(encoding="utf-8")
        self.assertIn("d.reason === 'map_run_void'", live_tpl)
        self.assertIn("clearLiveForVoid()", live_tpl)
        self.assertIn("p && p.kills != null ? p.kills : '-'", live_tpl)
        self.assertNotIn("p.kills ?? 0", live_tpl)


if __name__ == "__main__":
    unittest.main()
