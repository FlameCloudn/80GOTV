"""End-to-end verification of the Phase 3 Slice 2 admin & match-prep frontend pages."""

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


class FrontendAdminWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = self.enterContext(tempfile.TemporaryDirectory(prefix="fe-workflow-"))
        self.enterContext(
            patch.object(Config, "DATABASE", str(Path(self.sandbox) / "test.db"))
        )
        self.enterContext(patch.dict(app.config, {"TESTING": True, "SESSION_COOKIE_SECURE": False}))
        init_tables()
        self.db = self.enterContext(closing(get_db()))
        self.now = int(time.time())
        self.future_deadline = self.now + 7200
        with write(self.db):
            self.admin_id = self.db.execute(
                "INSERT INTO admins(username,password_hash) VALUES('fe-admin','disabled')"
            ).lastrowid
            self.club_id = self.db.execute(
                "INSERT INTO teams(name,short_name) VALUES('远岸俱乐部','YA')"
            ).lastrowid
            self.accounts = []
            self.player_ids = []
            for idx in range(13):
                nick = f"联调选手{idx + 1:02}"
                steam = str(76561199001100000 + idx)
                uid = self.db.execute(
                    """INSERT INTO users(username,email,password_hash,steam_id64,approval_status,
                               group_username,is_bashizhong_student)
                       VALUES(?,?,'disabled',?,'approved',?,1)""",
                    (f"u{idx}", f"u{idx}@example.invalid", steam, nick),
                ).lastrowid
                pid = self.db.execute(
                    """INSERT INTO players(nickname,steam_id,cs2_playtime_minutes,is_bashizhong_student,team_id)
                       VALUES(?,?,?,1,?)""",
                    (nick, steam, 600 + idx * 30, self.club_id if idx < 5 else None),
                ).lastrowid
                self.accounts.append(uid)
                self.player_ids.append(pid)

            start_day = (date.today() + timedelta(days=1)).isoformat()
            end_day = (date.today() + timedelta(days=5)).isoformat()
            self.legacy_event_id = self.db.execute(
                """INSERT INTO events(name,short_name,slug,start_date,end_date,status,registration_open)
                   VALUES('往届传统杯','LEG','legacy-cup',?,?,'upcoming',1)""",
                (start_day, end_day),
            ).lastrowid
            other_club = self.db.execute(
                "INSERT INTO teams(name,short_name) VALUES('星火俱乐部','XH')"
            ).lastrowid
            future_match_time = (date.today() + timedelta(days=2)).isoformat() + " 19:30"
            self.legacy_match_id = self.db.execute(
                """INSERT INTO matches(event_id,team1_id,team2_id,match_time,bo_format,status,slug)
                   VALUES(?,?,?,?,'BO3','upcoming','legacy-ya-vs-xh')""",
                (self.legacy_event_id, self.club_id, other_club, future_match_time),
            ).lastrowid
        self.admin = self.client(admin_id=self.admin_id, admin_username="fe-admin")
        self.visitor = app.test_client()

    @staticmethod
    def client(**identity):
        client = app.test_client()
        with client.session_transaction() as session:
            session.update(identity, csrf_token="fe-test-csrf")
        return client

    @staticmethod
    def post(client, url, **kwargs):
        return client.post(
            url,
            headers={"X-CSRF-Token": "fe-test-csrf", "X-Requested-With": "XMLHttpRequest"},
            **kwargs,
        )

    def _prepare_managed_match(self):
        start_day = (date.today() + timedelta(days=1)).isoformat()
        end_day = (date.today() + timedelta(days=10)).isoformat()
        res = self.post(
            self.admin,
            "/admin/events/add",
            data={
                "name": "新流程春季杯",
                "short_name": "NFSC",
                "start_date": start_day,
                "end_date": end_day,
                "registration_deadline": str(self.future_deadline),
            },
        )
        self.assertEqual(res.status_code, 302)
        eid = self.db.execute("SELECT id FROM events WHERE short_name='NFSC'").fetchone()["id"]
        users = [self.client(user_id=u) for u in self.accounts]
        steam3 = self.db.execute(
            "SELECT steam_id64 FROM users WHERE id=?", (self.accounts[3],)
        ).fetchone()["steam_id64"]
        self.assertEqual(
            self.post(
                users[0],
                f"/events/{eid}/register",
                data={
                    "my_slot": 0,
                    "team_name": "远岸临时队",
                    "pname_3": "预留老四",
                    "psteam_3": steam3,
                    "pname_4": "待释放占坑",
                    "psteam_4": "",
                },
            ).status_code,
            302,
        )
        reg_id = self.db.execute(
            "SELECT id FROM event_registrations WHERE event_id=?", (eid,)
        ).fetchone()["id"]
        for slot in (1, 2):
            self.assertTrue(
                self.post(users[slot], f"/events/{eid}/join/{reg_id}/{slot}").get_json()["success"]
            )
        for idx in range(4, 13):
            endpoint = "/register-substitute" if idx == 11 else "/register-individual"
            self.assertTrue(self.post(users[idx], f"/events/{eid}{endpoint}").get_json()["success"])
        return eid, reg_id

    def test_event_admin_pages_enable_disable_and_blockers(self):
        add_page = self.admin.get("/admin/events/add")
        self.assertEqual(add_page.status_code, 200)
        add_html = add_page.get_data(as_text=True)
        self.assertIn("新报名管理（报名截止后自动分队）", add_html)
        self.assertIn('name="registration_deadline"', add_html)

        start_day = (date.today() + timedelta(days=1)).isoformat()
        end_day = (date.today() + timedelta(days=10)).isoformat()
        res = self.post(
            self.admin,
            "/admin/events/add",
            data={
                "name": "启停联调杯",
                "short_name": "TOG",
                "start_date": start_day,
                "end_date": end_day,
                "registration_deadline": str(self.future_deadline),
            },
        )
        self.assertEqual(res.status_code, 302)
        eid = self.db.execute("SELECT id FROM events WHERE short_name='TOG'").fetchone()["id"]

        list_html = self.admin.get("/admin/events").get_data(as_text=True)
        self.assertIn(f"/admin/events/{eid}/roster", list_html)
        self.assertIn("报名中", list_html)

        edit_html = self.admin.get(f"/admin/events/edit/{eid}").get_data(as_text=True)
        self.assertIn("新报名管理", edit_html)
        self.assertIn("停用新报名管理", edit_html)
        panel = edit_html.index('id="managedAwardsPanel"')
        self.assertLess(edit_html.index('</form>', edit_html.index('id="eventForm"')), panel)
        self.assertIn(f'data-championship-url="/admin/events/{eid}/operations/championship"', edit_html[panel:])
        self.assertIn(f'data-player-awards-url="/admin/events/{eid}/operations/player-awards"', edit_html[panel:])
        self.assertNotIn('name="champion_team_id"', edit_html)

        legacy_edit_html = self.admin.get(f"/admin/events/edit/{self.legacy_event_id}").get_data(
            as_text=True
        )
        self.assertIn("这届赛事不能改用新报名管理，原因：", legacy_edit_html)
        self.assertIn("已开放原报名开关", legacy_edit_html)
        self.assertIn('name="champion_team_id"', legacy_edit_html)
        self.assertNotIn('id="managedAwardsPanel"', legacy_edit_html)
        self.assertIn("已有 1 场比赛", legacy_edit_html)
        self.assertNotIn("一键迁移", legacy_edit_html)

        self.assertEqual(self.admin.get(f"/admin/events/{self.legacy_event_id}/roster").status_code, 302)

        self.assertEqual(
            self.post(
                self.admin, f"/admin/events/{eid}/registration-control/disable", json={}
            ).status_code,
            200,
        )
        disabled_edit = self.admin.get(f"/admin/events/edit/{eid}").get_data(as_text=True)
        self.assertIn("启用新报名管理", disabled_edit)
        self.assertEqual(
            self.post(
                self.admin,
                f"/admin/events/{eid}/registration-control/enable",
                json={"registration_deadline": self.future_deadline},
            ).status_code,
            200,
        )

    def test_roster_workbench_and_match_creation_and_freeze(self):
        eid, reg_id = self._prepare_managed_match()

        pre_roster_html = self.admin.get(f"/admin/events/{eid}/roster").get_data(as_text=True)
        self.assertIn("A. 截止与正式分队", pre_roster_html)
        self.assertIn("data-open-link-club", pre_roster_html)
        self.assertIn("预留老四", pre_roster_html)
        self.assertIn("待释放占坑", pre_roster_html)
        self.assertIn("截止后可复核", pre_roster_html)
        self.assertIn("@u3", pre_roster_html)
        self.assertIn("预留未填写 Steam ID，只能释放", pre_roster_html)

        with write(self.db):
            self.db.execute(
                "UPDATE event_registration_control SET registration_deadline=? WHERE event_id=?",
                (self.now - 10, eid),
            )
        due_roster_html = self.admin.get(f"/admin/events/{eid}/roster").get_data(as_text=True)
        self.assertIn("已截止 · 待分队", due_roster_html)
        self.assertNotIn("data-open-link-club", due_roster_html)
        late_link = self.post(self.admin, f"/admin/events/{eid}/registration-control/link-club",
                              json={"registration_id": reg_id, "club_id": self.club_id})
        self.assertEqual(late_link.status_code, 409)
        self.assertIn("认领", due_roster_html)
        self.assertIn("释放", due_roster_html)

        self.assertEqual(
            self.post(
                self.admin,
                f"/admin/events/{eid}/registration-control/review-reservation",
                json={
                    "registration_id": reg_id,
                    "roster_slot": 3,
                    "verified_account_id": self.accounts[3],
                    "reason": "队长核实本人",
                },
            ).status_code,
            200,
        )
        self.assertEqual(
            self.post(
                self.admin,
                f"/admin/events/{eid}/registration-control/review-reservation",
                json={"registration_id": reg_id, "roster_slot": 4, "reason": "未留 Steam，释放补齐"},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.post(self.admin, f"/admin/events/{eid}/registration-control/form-due", json={}).status_code,
            200,
        )

        formed_html = self.admin.get(f"/admin/events/{eid}/roster").get_data(as_text=True)
        self.assertIn("已分队 · 首五待确认", formed_html)
        self.assertIn("确认所选队伍的初始五人", formed_html)
        self.assertIn("调整分队", formed_html)
        self.assertIn("独立候补", formed_html)
        self.assertIn("个人报名未入队", formed_html)

        ctrl_json = self.admin.get(f"/admin/events/{eid}/registration-control").get_json()
        entrant_ids = [e["event_entrant_id"] for e in ctrl_json["entrants"]]
        rev = ctrl_json["formation_revision"]
        self.assertEqual(len(entrant_ids), 2)

        stale_res = self.post(
            self.admin,
            f"/admin/events/{eid}/registration-control/confirm-initial",
            json={"event_entrant_ids": entrant_ids, "expected_revision": rev + 99},
        )
        self.assertEqual(stale_res.status_code, 409)
        self.assertIn("名单已改变", stale_res.get_json()["error"])

        self.assertEqual(
            self.post(
                self.admin,
                f"/admin/events/{eid}/registration-control/confirm-initial",
                json={"event_entrant_ids": entrant_ids, "expected_revision": rev},
            ).status_code,
            200,
        )

        ctrl_json = self.admin.get(f"/admin/events/{eid}/registration-control").get_json()
        rev = ctrl_json["formation_revision"]
        indep_pid = self.player_ids[11]
        outgoing_pid = ctrl_json["entrants"][0]["current_player_ids"][4]
        self.assertEqual(
            self.post(
                self.admin,
                f"/admin/events/{eid}/registration-control/assign-reserve",
                json={
                    "event_entrant_id": entrant_ids[0],
                    "player_id": indep_pid,
                    "expected_revision": rev,
                    "reason": "优先补入独立候补",
                    "excluded_candidates": {},
                },
            ).status_code,
            200,
        )
        ctrl_json = self.admin.get(f"/admin/events/{eid}/registration-control").get_json()
        rev = ctrl_json["formation_revision"]
        self.assertEqual(
            self.post(
                self.admin,
                f"/admin/events/{eid}/registration-control/replace-before-series",
                json={
                    "event_entrant_id": entrant_ids[0],
                    "outgoing_player_id": outgoing_pid,
                    "incoming_player_id": indep_pid,
                    "expected_revision": rev,
                    "reason": "队员临时请假",
                },
            ).status_code,
            200,
        )
        post_replace_html = self.admin.get(f"/admin/events/{eid}/roster").get_data(as_text=True)
        self.assertIn("本届初始五人", post_replace_html)
        self.assertIn("当前阵容", post_replace_html)
        self.assertIn("已换出", post_replace_html)
        self.assertIn("换入", post_replace_html)
        self.assertIn("保留初始 4 / 5", post_replace_html)

        match_add_html = self.admin.get("/admin/matches/add").get_data(as_text=True)
        json_line = [
            line for line in match_add_html.splitlines() if "var MANAGED_EVENTS_DATA =" in line
        ][0]
        raw_json = json_line.split("var MANAGED_EVENTS_DATA =", 1)[1].strip().rstrip(";")
        managed_payload = json.loads(raw_json)
        entrant_names = [e["name"] for e in managed_payload[str(eid)]["entrants"]]
        self.assertIn("远岸临时队", entrant_names)
        self.assertIn("个人报名队 1", entrant_names)

        future_match_time = (date.today() + timedelta(days=3)).isoformat() + " 20:00"
        res = self.post(
            self.admin,
            "/admin/matches/add",
            data={
                "event_id": str(eid),
                "match_time": future_match_time,
                "bo_format": "BO1",
                "side1_type": "entrant",
                "side1_id": str(entrant_ids[0]),
                "side2_type": "entrant",
                "side2_id": str(entrant_ids[1]),
            },
        )
        self.assertEqual(res.status_code, 302)
        managed_match = self.db.execute("SELECT * FROM matches WHERE event_id=?", (eid,)).fetchone()
        mid = managed_match["id"]

        matches_html = self.admin.get("/admin/matches").get_data(as_text=True)
        self.assertIn("本场阵容未冻结", matches_html)
        legacy_row = matches_html.split(f'id="match-{self.legacy_match_id}"')[1].split("</tr>")[0]
        managed_row = matches_html.split(f'id="match-{mid}"')[1].split("</tr>")[0]
        self.assertIn("上传 Demo", legacy_row)
        self.assertIn("录入数据", legacy_row)
        self.assertNotIn("上传 Demo", managed_row)
        self.assertNotIn("录入数据", managed_row)
        self.assertNotIn("删除比赛", managed_row)
        self.assertIn("查看前台比赛页", managed_row)
        self.assertIn("打开 BP 房间", managed_row)

        edit_match_html = self.admin.get(f"/admin/matches/edit/{mid}").get_data(as_text=True)
        self.assertIn("本场阵容", edit_match_html)
        self.assertIn("确认冻结本场阵容", edit_match_html)
        self.assertIn("本届初始五人", edit_match_html)
        self.assertIn("本届当前阵容", edit_match_html)
        self.assertIn("冻结只记录本场参赛名单，不表示选手已到场或比赛已开始", edit_match_html)

        self.assertEqual(self.post(self.admin, f"/admin/matches/{mid}/freeze-rosters").status_code, 302)

        frozen_match_html = self.admin.get(f"/admin/matches/edit/{mid}").get_data(as_text=True)
        self.assertIn("本场阵容已冻结", frozen_match_html)
        self.assertIn("只读 · 已冻结", frozen_match_html)
        self.assertIn("本场双方十人已记录为只读状态", frozen_match_html)
        self.assertIn("fe-admin", frozen_match_html)
        self.assertNotIn('id="freezeMatchRostersBtn"', frozen_match_html)

        with write(self.db):
            self.db.execute(
                "UPDATE matches SET bp_state=? WHERE id=?",
                (json.dumps({"status": "in_progress"}), mid),
            )
        bp_started_html = self.admin.get(f"/admin/matches/edit/{mid}").get_data(as_text=True)
        self.assertIn("本场阵容", bp_started_html)
        self.assertIn("只读 · 已冻结", bp_started_html)

        matches_after_html = self.admin.get("/admin/matches").get_data(as_text=True)
        self.assertIn("本场阵容已冻结", matches_after_html)

        open_detail = self.visitor.get(f"/matches/{managed_match['slug']}").get_data(as_text=True)
        self.assertIn("后即可参与投票预测", open_detail)

        with write(self.db):
            self.db.execute(
                """INSERT INTO match_start_authorizations
                   (match_id,admin_id,authorized_at) VALUES(?,?,'2026-11-18T12:00:00')""",
                (mid, self.admin_id),
            )
        managed_detail = self.visitor.get(f"/matches/{managed_match['slug']}").get_data(as_text=True)
        self.assertIn("本场对阵未确定或已停止接受竞猜，暂不开放赛前预测。", managed_detail)
        self.assertNotIn("submitVote(this)", managed_detail)
        self.assertNotIn("后即可参与投票预测", managed_detail)

        legacy_detail = self.visitor.get("/matches/legacy-ya-vs-xh").get_data(as_text=True)
        self.assertIn("后即可参与投票预测", legacy_detail)

    def test_public_predictions_list_filters_by_managed_vote_open(self):
        eid, reg_id = self._prepare_managed_match()
        with write(self.db):
            self.db.execute(
                "UPDATE event_registration_control SET registration_deadline=? WHERE event_id=?",
                (self.now - 10, eid),
            )
        self.post(
            self.admin,
            f"/admin/events/{eid}/registration-control/review-reservation",
            json={
                "registration_id": reg_id,
                "roster_slot": 3,
                "verified_account_id": self.accounts[3],
                "reason": "核实",
            },
        )
        self.post(
            self.admin,
            f"/admin/events/{eid}/registration-control/review-reservation",
            json={"registration_id": reg_id, "roster_slot": 4, "reason": "释放"},
        )
        self.post(self.admin, f"/admin/events/{eid}/registration-control/form-due", json={})
        ctrl_json = self.admin.get(f"/admin/events/{eid}/registration-control").get_json()
        entrant_ids = [e["event_entrant_id"] for e in ctrl_json["entrants"]]
        self.post(
            self.admin,
            f"/admin/events/{eid}/registration-control/confirm-initial",
            json={"event_entrant_ids": entrant_ids, "expected_revision": ctrl_json["formation_revision"]},
        )
        future_match_time = (date.today() + timedelta(days=3)).isoformat() + " 20:00"
        self.post(
            self.admin,
            "/admin/matches/add",
            data={
                "event_id": str(eid),
                "match_time": future_match_time,
                "bo_format": "BO1",
                "side1_type": "entrant",
                "side1_id": str(entrant_ids[0]),
                "side2_type": "entrant",
                "side2_id": str(entrant_ids[1]),
            },
        )
        mid = self.db.execute("SELECT id FROM matches WHERE event_id=?", (eid,)).fetchone()["id"]

        open_api = self.visitor.get("/api/front/predictions").get_json()
        self.assertIn(mid, [item["id"] for item in open_api["upcoming_matches"]])

        with write(self.db):
            self.db.execute(
                """INSERT INTO match_start_authorizations
                   (match_id,admin_id,authorized_at) VALUES(?,?,'2026-11-18T12:00:00')""",
                (mid, self.admin_id),
            )
        pred_html = self.visitor.get("/predictions").get_data(as_text=True)
        self.assertIn("legacy-ya-vs-xh", pred_html)
        self.assertNotIn("远岸临时队", pred_html)

        pred_api = self.visitor.get("/api/front/predictions").get_json()
        upcoming_ids = [item["id"] for item in pred_api["upcoming_matches"]]
        self.assertIn(self.legacy_match_id, upcoming_ids)
        self.assertNotIn(mid, upcoming_ids)


if __name__ == "__main__":
    unittest.main()
