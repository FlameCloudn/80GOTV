"""From the original signup form to the director's real HTTP contract; no prototype installation."""

import json
import sqlite3
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
from scripts.promote_event_teams import promote_event_teams
from site_core.events.public import run_due_events_once
from site_core.host import write


class HostPrematchChainTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = self.enterContext(tempfile.TemporaryDirectory(prefix="host-chain-"))
        self.enterContext(
            patch.object(Config, "DATABASE", str(Path(self.sandbox) / "synthetic.db"))
        )
        self.enterContext(patch.dict(app.config, {"TESTING": True, "SESSION_COOKIE_SECURE": False}))
        init_tables()
        self.db = self.enterContext(closing(get_db()))
        self.deadline = int(time.time()) + 3600
        with write(self.db):
            self.admin_id = self.db.execute(
                "INSERT INTO admins(username,password_hash) VALUES('host-chain-admin','disabled')"
            ).lastrowid
            self.accounts = []
            for slot in range(12):
                nickname = f"赛前测试选手{slot + 1:02}"
                steam = str(76561199000100200 + slot)
                account_id = self.db.execute(
                    """INSERT INTO users(username,email,password_hash,steam_id64,approval_status,
                               is_bashizhong_student) VALUES(?,?,'disabled',?,'approved',0)""",
                    (nickname, f"member-{slot}@example.invalid", steam),
                ).lastrowid
                self.db.execute(
                    """INSERT INTO players(nickname,steam_id,cs2_playtime_minutes,is_bashizhong_student)
                       VALUES(?,?,?,0)""",
                    (nickname, steam, slot * 60 if slot != 1 else None),
                )
                self.accounts.append(account_id)
        self.admin = self.client(admin_id=self.admin_id)
        self.visitor = app.test_client()

    @staticmethod
    def client(**identity):
        client = app.test_client()
        with client.session_transaction() as session:
            session.update(identity, csrf_token="prematch-test-form")
        return client

    @staticmethod
    def post(client, url, **kwargs):
        return client.post(
            url,
            headers={"X-CSRF-Token": "prematch-test-form", "X-Requested-With": "XMLHttpRequest"},
            **kwargs,
        )

    def prepare_through_host(self):
        ends = (date.today() + timedelta(days=10)).isoformat()
        res = self.post(
            self.admin,
            "/admin/events/add",
            data={
                "name": "宿主联调杯",
                "short_name": "HIC",
                "start_date": (date.today() + timedelta(days=1)).isoformat(),
                "end_date": ends,
                "registration_deadline": str(self.deadline),
            },
        )
        self.assertEqual(res.status_code, 302, res.get_data(as_text=True))
        event = self.db.execute("SELECT * FROM events WHERE name='宿主联调杯'").fetchone()
        self.event_id = event["id"]
        self.event_url = f"/events/{event['slug']}"
        self.prefix = f"/admin/events/{self.event_id}/registration-control"
        path = f"/events/{self.event_id}"
        members = [self.client(user_id=a) for a in self.accounts]
        self.assertEqual(
            self.post(
                members[0], path + "/register", data={"my_slot": 0, "team_name": "远岸"}
            ).status_code,
            302,
        )
        group_id = self.db.execute(
            "SELECT id FROM event_registrations WHERE event_id=?", (self.event_id,)
        ).fetchone()[0]
        for slot in (1, 2):
            self.assertTrue(
                self.post(members[slot], f"{path}/join/{group_id}/{slot}").get_json()["success"]
            )
        for client in members[3:11]:
            self.assertTrue(self.post(client, path + "/register-individual").get_json()["success"])
        self.assertTrue(self.post(members[11], path + "/register-substitute").get_json()["success"])
        # No page request or fixture-only allocation. This is exactly the worker's public command.
        formed, rejected = run_due_events_once(self.db, now=self.deadline)
        self.assertEqual(rejected, {})
        teams = formed[0]["entrant_ids"]
        self.assertEqual(len(teams), 2)
        self.assertEqual(run_due_events_once(self.db, now=self.deadline), ([], {}))
        confirmed = self.post(
            self.admin,
            self.prefix + "/confirm-initial",
            json={
                "event_entrant_ids": teams,
                "expected_revision": formed[0]["formation_revision"],
            },
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.get_data(as_text=True))
        self.lineups = self.admin.get(self.prefix).get_json()["entrants"]
        fields = {
            f"side{index}_p{slot}": player
            for index, t in enumerate(self.lineups, 1)
            for slot, player in enumerate(t["current_player_ids"])
        }
        res = self.post(
            self.admin,
            "/admin/matches/add",
            data={
                "event_id": self.event_id,
                "match_time": f"{ends}T18:00",
                "bo_format": "BO1",
                "side1_type": "players",
                "side2_type": "players",
                **fields,
            },
        )
        self.assertEqual(res.status_code, 302, res.get_data(as_text=True))
        self.match = self.db.execute(
            "SELECT * FROM matches WHERE event_id=?", (self.event_id,)
        ).fetchone()
        mid = self.match["id"]
        prior = self.visitor.get(f"/api/broadcast/matches/{mid}").get_json()["match"]
        self.assertFalse(prior["roster_locked"])
        self.assertFalse(prior["bp_can_start"])
        self.assertEqual(
            self.post(self.admin, f"/admin/matches/{mid}/freeze-rosters").status_code, 302
        )
        url = f"/api/bp/{mid}/action"

        def step(action, team="t1", **fields):
            response = self.post(self.admin, url, json={"action": action, "team": team, **fields})
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            self.assertTrue(response.get_json()["ok"], response.json)
            return response.get_json()["state"]

        state = step("start")
        state = step("roll", bp_revision=state["revision"])
        state = step("roll", "t2", bp_revision=state["revision"])
        while state["status"] == "rolling":
            for side in ("t1", "t2"):
                state = step("roll", side, bp_revision=state["revision"])
        picker = state["first_picker"]
        state = step("choose_order", picker, choice="first", bp_revision=state["revision"])
        while state["status"] == "bp":
            info = self.admin.get(f"/api/bp/{mid}/state").get_json()["info"]
            state = step("ban", info["team"], map=state["pool"][0], bp_revision=state["revision"])
        for pick in state["picks"]:
            if pick.get("side") is None:
                state = step(
                    "choose_side",
                    pick["side_team"],
                    map=pick["map"],
                    side="CT",
                    bp_revision=state["revision"],
                )
        self.assertEqual(state["status"], "completed", state)
        return mid

    def test_signup_to_broadcast_in_the_original_website(self):
        mid = self.prepare_through_host()
        legacy = self.db.execute(
            "INSERT INTO events(name,slug,registration_open) VALUES('旧联调杯','old-host-cup',1)"
        ).lastrowid
        self.db.execute(
            "INSERT INTO event_registrations(event_id,team_name,creator_user_id) VALUES(?,'旧队',?)",
            (legacy, self.accounts[0]),
        )
        self.db.commit()
        get = self.visitor.get
        display = get(f"/api/broadcast/matches/{mid}").get_json()["match"]
        self.assertTrue(display["roster_locked"])
        self.assertFalse(display["ready_for_start"])
        self.assertEqual(display["bp"]["status"], "completed")
        self.assertEqual(display["maps"][0]["opening_side_source"], "website_bp")
        self.assertFalse(display["maps"][0]["map_finished"])
        for key, team in zip(("team1", "team2"), self.lineups):
            self.assertIsNone(display[key]["id"])
            self.assertEqual(display[key]["source_id"], f"registration-{team['registration_id']}")
            self.assertEqual([p["id"] for p in display[key]["players"]], team["initial_player_ids"])
        self.assertEqual(len(display["substitutes"]), 2)
        self.assertCountEqual(
            [e["id"] for e in get("/api/broadcast/events").get_json()["events"]],
            [legacy, self.event_id],
        )
        event = get(f"/api/broadcast/events/{self.event_id}").get_json()["event"]
        self.assertCountEqual(
            [e["source_id"] for e in event["teams"]],
            [f"registration-{t['registration_id']}" for t in self.lineups],
        )
        self.assertEqual(get("/api/broadcast/matches").get_json()["matches"][0]["id"], mid)
        self.assertEqual(get("/api/broadcast/current").get_json()["match"]["id"], mid)
        self.assertEqual(
            get("/api/front/matches").get_json()["matches"][0]["team1"], display["team1"]["name"]
        )
        front = get(f"/api/front/events/{self.event_id}").get_json()
        self.assertEqual(len(front["teams"]), 2)
        self.assertEqual(front["event"]["team_count"], 2)
        self.assertTrue(all(t["id"] is None and t["url"] == self.event_url for t in front["teams"]))
        for url in (self.event_url, f"/matches/{mid}", f"/matches/{self.match['slug']}"):
            page = get(url, follow_redirects=True)
            self.assertEqual(page.status_code, 200)
            self.assertIn("远岸", page.get_data(as_text=True))
        with patch.object(Config, "GSI_TOKEN", "fixture-only"):
            headers = {"X-80GOTV-Token": "fixture-only"}
            probe = get(f"/api/broadcast/matches/{mid}/connection-test", headers=headers)
            self.assertFalse(probe.get_json()["ready_for_start"])
            blocked = self.visitor.post(
                f"/api/broadcast/matches/{mid}/live",
                headers=headers,
                json={"map": {"name": display["maps"][0]["name"]}},
            )
            self.assertEqual(blocked.status_code, 409, blocked.json)
            blocked = self.visitor.post(
                f"/api/broadcast/matches/{mid}/map-result",
                headers=headers,
                json={
                    "map_name": display["maps"][0]["name"],
                    "team1_score": 13,
                    "team2_score": 3,
                    "players": [{"name": "赛前样本", "team_side": "team1", "steam_id": "123"}],
                },
            )
            self.assertEqual(blocked.status_code, 409, blocked.json)
            self.assertFalse(blocked.get_json()["ok"])
        with self.assertRaises(ValueError):
            promote_event_teams(self.db, self.event_id, apply=True)
        for table in (
            "teams",
            "match_stats",
            "live_match_data",
            "event_registration_slots",
            "event_individual_registrations",
        ):
            self.assertEqual(
                self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0, table
            )
        self.assertFalse(self.db.execute("PRAGMA foreign_key_check").fetchall())
        with self.assertRaisesRegex(sqlite3.IntegrityError, "旧报名槽"), write(self.db):
            self.db.execute(
                "INSERT INTO event_registration_slots(registration_id,slot_index) VALUES(?,0)",
                (self.lineups[0]["registration_id"],),
            )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "旧个人报名"), write(self.db):
            self.db.execute(
                """INSERT INTO event_individual_registrations(event_id,user_id,player_name,steam_id)
                               VALUES(?,?,'过期脚本','fixture')""",
                (self.event_id, self.accounts[0]),
            )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "实战统计"), write(self.db):
            self.db.execute(
                "INSERT INTO match_stats(match_id,player_id) VALUES(?,?)",
                (mid, self.lineups[0]["initial_player_ids"][0]),
            )
        self.assertEqual(self.post(self.admin, self.prefix + "/archive", json={}).status_code, 200)
        self.assertFalse(get(f"/api/broadcast/matches/{mid}").get_json()["match"]["bp_can_start"])
        self.assertEqual(self.post(self.admin, f"/api/bp/{mid}/reset", json={}).status_code, 409)
        self.assertTrue(get(f"/api/broadcast/matches/{mid}").get_json()["match"]["roster_locked"])
        upcoming = self.db.execute(
            "INSERT INTO matches(event_id,match_time,status) VALUES(?,datetime('now','+2 days'),'upcoming')",
            (legacy,),
        ).lastrowid
        self.db.commit()
        self.assertEqual(get("/api/broadcast/current").get_json()["match"]["id"], upcoming)
        with write(self.db):
            self.db.execute(
                "UPDATE matches SET map1=?, status='live' WHERE id=?",
                (display["maps"][0]["name"], upcoming),
            )
        with patch.object(Config, "GSI_TOKEN", "fixture-only"):
            received = self.visitor.post(
                "/api/gsi/receive",
                json={
                    "auth": {"token": "fixture-only"},
                    "map": {"name": display["maps"][0]["name"]},
                },
            )
        self.assertEqual(received.status_code, 200, received.get_json())
        self.assertEqual(
            [row[0] for row in self.db.execute("SELECT match_id FROM live_match_data")],
            [upcoming],
        )

    def test_old_saved_bracket_without_matches_is_not_an_empty_new_event(self):
        event_id = self.db.execute("INSERT INTO events(name) VALUES('已有签表')").lastrowid
        self.db.commit()
        bracket = json.dumps(
            {
                "tournament": {
                    "teams": [{"id": "seed", "name": "旧种子"}],
                    "rounds": [{"matches": [{"id": "final", "team1": "seed"}]}],
                }
            }
        )
        url = f"/admin/events/{event_id}/bracket"
        self.assertEqual(
            self.post(self.admin, url, data={"bracket_data": bracket}).status_code, 302
        )
        response = self.post(
            self.admin,
            f"/admin/events/{event_id}/registration-control/enable",
            json={"registration_deadline": self.deadline},
        )
        self.assertEqual(response.status_code, 409, response.json)
        self.assertIsNone(
            self.db.execute(
                "SELECT 1 FROM event_registration_control WHERE event_id=?", (event_id,)
            ).fetchone()
        )
        self.assertEqual(
            self.post(self.admin, url, data={"bracket_data": bracket}).status_code, 302
        )

    def test_first_match_keeps_steam_identity_when_later_freeze_loses_its_account(self):
        mid = self.prepare_through_host()
        fields = {f"side{i}_id": team["event_entrant_id"] for i, team in enumerate(self.lineups, 1)}
        day = (date.today() + timedelta(days=12)).isoformat()
        self.assertEqual(
            self.post(
                self.admin,
                "/admin/matches/add",
                data={
                    "event_id": self.event_id,
                    "match_time": day + "T18:00",
                    "bo_format": "BO1",
                    "side1_type": "entrant",
                    "side2_type": "entrant",
                    **fields,
                },
            ).status_code,
            302,
        )
        later = self.db.execute(
            "SELECT max(id) FROM matches WHERE event_id=?", (self.event_id,)
        ).fetchone()[0]
        player = self.lineups[1]["current_player_ids"][-1]
        baseline = self.visitor.get(f"/api/broadcast/matches/{mid}").get_json()["match"]["team2"][
            "players"
        ]
        with write(self.db):
            self.db.execute("UPDATE players SET steam_id='76561199000876543' WHERE id=?", (player,))
        self.assertEqual(
            self.post(self.admin, f"/admin/matches/{later}/freeze-rosters").status_code, 409
        )
        self.assertEqual(
            self.db.execute(
                """SELECT count(*) FROM match_rosters r JOIN match_participants p
                            USING(match_participant_id) WHERE p.match_id=?""",
                (later,),
            ).fetchone()[0],
            0,
        )
        historical = self.visitor.get(f"/api/broadcast/matches/{mid}").get_json()["match"]["team2"][
            "players"
        ]
        self.assertEqual(baseline, historical)
