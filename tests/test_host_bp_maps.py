"""The original BP room and API operate on managed matches in an isolated SQLite DB."""

import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Barrier, Event
from unittest.mock import patch

from app import app
from config import Config
from models import get_db, init_tables
from site_core.events import public, registration
from site_core.host import write
from site_core.matches import maps, participants
from tests.entrant_slice_fixtures import DEADLINE, ORGANIZER_ID, REGISTRATION_TIME, seed_registrants
from utils.bp_manager import ALL_MAPS, init_bp_state
from utils.web_helpers import hash_bp_password


class HostedBPTests(unittest.TestCase):
    def setUp(self):
        sandbox = self.enterContext(tempfile.TemporaryDirectory(prefix="80gotv-host-bp-"))
        self.enterContext(patch.object(Config, "DATABASE", str(Path(sandbox) / "bp.sqlite")))
        self.enterContext(patch.dict(app.config, {"TESTING": True, "PROPAGATE_EXCEPTIONS": False}))
        init_tables()
        with closing(get_db()) as db:
            db.execute(
                "INSERT INTO admins(id,username,password_hash) VALUES(?,'bp-test-organizer','disabled')",
                (ORGANIZER_ID,),
            )
            self.people = seed_registrants(db, [360] * 11)
            db.execute("UPDATE users SET is_bashizhong_student=0")
            db.commit()
        self.admin = self._client(admin_id=ORGANIZER_ID)

    @staticmethod
    def _client(**session_data):
        client = app.test_client()
        with client.session_transaction() as browser:
            browser.update(session_data, csrf_token="host-bp-fixture")
        return client

    def _new_match(self, bo, *, pool=None, freeze=True, password=None, setup=None):
        with closing(get_db()) as db, write(db):
            event_id = db.execute(
                "INSERT INTO events(name,status,registration_open) VALUES(?,'upcoming',0)",
                (f"Test {bo}",),
            ).lastrowid
            assert event_id is not None
            registration.enable_event(
                db, event_id, DEADLINE, admin_id=ORGANIZER_ID, now=REGISTRATION_TIME
            )
            for name, people in (("Harbor", self.people[:5]), ("Copper", self.people[5:10])):
                group = registration.create_group(
                    db,
                    event_id,
                    people[0].account_id,
                    name,
                    now=REGISTRATION_TIME,
                )
                for slot, person in enumerate(people[1:], 1):
                    registration.join_group(
                        db, event_id, group, person.account_id, slot, now=REGISTRATION_TIME
                    )
            batch = public.form_due_event(db, event_id, now=DEADLINE)
            home, away = batch["entrant_ids"]
            public.confirm_initial_rosters(
                db,
                event_id,
                [home, away],
                expected_revision=batch["formation_revision"],
                admin_id=ORGANIZER_ID,
                now=DEADLINE + 1,
            )
            match_id = db.execute(
                """INSERT INTO matches(event_id,status,bo_format,map_pool,bp_password,match_time)
                   VALUES(?,'upcoming',?,?,?,'2027-01-16 13:00:00')""",
                (event_id, bo, json.dumps(pool) if pool is not None else None, password),
            ).lastrowid
            participants.bind(db, match_id, home, away)
            maps.sync_scheduled_maps(db, match_id, setup=setup)
            if freeze:
                participants.freeze_rosters(db, match_id, ORGANIZER_ID)
            return match_id

    @staticmethod
    def _post(client, match_id, endpoint, body):
        return client.post(
            f"/api/bp/{match_id}/{endpoint}",
            json=body,
            headers={"X-CSRF-Token": "host-bp-fixture"},
        )

    def _step(self, match_id, action, *, team="t1", revision=None, **extra):
        body = {"action": action, "team": team, **extra}
        if revision is not None:
            body["bp_revision"] = revision
        response = self._post(self.admin, match_id, "action", body)
        self.assertEqual(response.status_code, 200, response.get_json())
        result = response.get_json()
        self.assertTrue(result["ok"], result)
        return result["state"]

    def _choose_maps(self, match_id, moves):
        state = self._step(match_id, "start")
        with patch("utils.bp_manager.roll", side_effect=(83, 17)):
            state = self._step(match_id, "roll", revision=state["revision"])
            state = self._step(match_id, "roll", team="t2", revision=state["revision"])
        self.assertEqual(state["first_picker"], "t1")
        state = self._step(match_id, "choose_order", choice="first", revision=state["revision"])
        for action, team, map_name in moves:
            state = self._step(
                match_id, action, team=team, map=map_name, revision=state["revision"]
            )
        return state

    def _map_rows(self, match_id):
        with closing(get_db()) as db:
            return [dict(row) for row in maps.list_scheduled_maps(db, match_id)]

    @staticmethod
    def _old_maps(match_id):
        fields = [f"map{slot}{suffix}" for slot in range(1, 6) for suffix in ("", "_picked_by")]
        fields.extend(f"has_map{slot}" for slot in range(3, 6))
        with closing(get_db()) as db:
            return tuple(
                db.execute(
                    f"SELECT {','.join(fields)} FROM matches WHERE id=?", (match_id,)
                ).fetchone()
            )

    def test_bo1_uses_remaining_map_and_chooser_through_old_api(self):
        match_id = self._new_match("BO1", pool=["Mirage", "Nuke", "Ancient"])
        map_id = self._map_rows(match_id)[0]["scheduled_map_id"]
        original = self._old_maps(match_id)
        state = self._choose_maps(match_id, [("ban", "t1", "Mirage"), ("ban", "t1", "Nuke")])
        self.assertEqual(state["status"], "side_select")
        self.assertEqual(
            state["picks"],
            [{"map": "Ancient", "picked_by": "remaining", "side": None, "side_team": "t2"}],
        )
        self.assertIsNone(self._map_rows(match_id)[0]["map_name"])
        state = self._step(
            match_id, "choose_side", team="t2", map="Ancient", side="T", revision=state["revision"]
        )
        self.assertEqual(state["status"], "completed")
        (row,) = self._map_rows(match_id)
        self.assertEqual(
            (row["scheduled_map_id"], row["chooser_side"], row["starting_side"]),
            (map_id, "away", "T"),
        )
        self.assertEqual(self._old_maps(match_id), original)
        with closing(get_db()) as db:
            self.assertEqual(
                maps.broadcast_maps(db, match_id),
                [
                    {
                        "slot": 1,
                        "name": "de_ancient",
                        "picked_by": "decider",
                        "opening_ct_team": "t1",
                        "opening_side_source": "website_bp",
                    }
                ],
            )
            self.assertIsNone(
                db.execute(
                    "SELECT decider_start_side FROM matches WHERE id=?", (match_id,)
                ).fetchone()[0]
            )

    def test_broadcast_read_sees_one_revision_while_captain_finishes_bp(self):
        match_id = self._new_match("BO1", pool=["Mirage", "Nuke", "Ancient"])
        pending = self._choose_maps(match_id, [("ban", "t1", "Mirage"), ("ban", "t1", "Nuke")])
        reading, completed = Event(), Event()
        overlap = []

        def submit_final_side():
            try:
                self.assertTrue(reading.wait(5))
                return self._post(
                    self.admin,
                    match_id,
                    "action",
                    {
                        "action": "choose_side",
                        "team": "t2",
                        "map": "Ancient",
                        "side": "T",
                        "bp_revision": pending["revision"],
                    },
                )
            finally:
                completed.set()

        def pause_between_queries(sql):
            if not reading.is_set() and "select live_state from live_match_data" in sql.lower():
                reading.set()
                overlap.append(completed.wait(5))

        def reader():
            conn = get_db()
            conn.set_trace_callback(pause_between_queries)
            return conn

        url = f"/api/broadcast/matches/{match_id}"
        with ThreadPoolExecutor(max_workers=1) as pool:
            submission = pool.submit(submit_final_side)
            with patch("routes.broadcast.get_db", side_effect=reader):
                before = app.test_client().get(url).get_json()["match"]
            self.assertEqual(submission.result().status_code, 200)
        self.assertEqual(overlap, [True])
        after = app.test_client().get(url).get_json()["match"]
        self.assertEqual(
            (before["bp_revision"], before["bp"]["status"]), (pending["revision"], "side_select")
        )
        self.assertEqual(before["maps"][0]["opening_side_source"], "pending")
        self.assertEqual(
            (after["bp_revision"], after["bp"]["status"]), (pending["revision"] + 1, "completed")
        )
        self.assertEqual(
            (after["maps"][0]["name"], after["maps"][0]["opening_ct_team"]), ("de_ancient", "t1")
        )

    def test_bo3_and_bo5_use_original_order_and_leave_the_decider_side_pending(self):
        opening_bans = [("ban", "t1", "Dust2"), ("ban", "t2", "Mirage")]
        first_picks = [("pick", "t1", "Inferno"), ("pick", "t2", "Nuke")]
        for bo, moves, picks in (
            (
                "BO3",
                opening_bans + first_picks + [("ban", "t1", "Cache"), ("ban", "t2", "Ancient")],
                ["Inferno", "Nuke"],
            ),
            (
                "BO5",
                opening_bans + first_picks + [("pick", "t1", "Cache"), ("pick", "t2", "Ancient")],
                ["Inferno", "Nuke", "Cache", "Ancient"],
            ),
        ):
            with self.subTest(bo=bo):
                match_id = self._new_match(bo)
                original = self._old_maps(match_id)
                state = self._choose_maps(match_id, moves)
                self.assertEqual(state["initial_pool"], ALL_MAPS)
                self.assertEqual(state["map_order"], [*picks, "Anubis"])
                for index, name in enumerate(picks):
                    chooser = "t2" if index % 2 == 0 else "t1"
                    state = self._step(
                        match_id,
                        "choose_side",
                        team=chooser,
                        map=name,
                        side="T",
                        revision=state["revision"],
                    )
                self.assertEqual(state["status"], "completed")
                self.assertEqual(self._old_maps(match_id), original)
                with closing(get_db()) as db:
                    payload = maps.broadcast_maps(db, match_id)
                    self.assertEqual(
                        payload[-1],
                        {
                            "slot": len(picks) + 1,
                            "name": "de_anubis",
                            "picked_by": "decider",
                            "opening_ct_team": "",
                            "opening_side_source": "pending",
                        },
                    )
                    self.assertEqual(
                        [p["opening_ct_team"] for p in payload[:-1]],
                        (["t1", "t2"] * 2)[: len(picks)],
                    )
                    self.assertEqual(
                        [p["name"] for p in payload[:-1]], [f"de_{name.lower()}" for name in picks]
                    )
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM teams").fetchone()[0], 0)
                    self.assertEqual(
                        db.execute("SELECT COUNT(*) FROM match_stats").fetchone()[0], 0
                    )

    def test_undo_redo_keeps_identifiers_and_reset_rejects_prior_revision(self):
        match_id = self._new_match("BO1", pool=["Mirage", "Ancient"])
        before = self._choose_maps(match_id, [("ban", "t1", "Mirage")])
        completed = self._step(
            match_id,
            "choose_side",
            team="t2",
            map="Ancient",
            side="CT",
            revision=before["revision"],
        )
        map_id = self._map_rows(match_id)[0]["scheduled_map_id"]
        undo = self._post(self.admin, match_id, "undo", {"steps_back": 1}).get_json()
        self.assertTrue(undo["ok"], undo)
        self.assertEqual(undo["state"]["status"], "side_select")
        (cleared,) = self._map_rows(match_id)
        self.assertEqual((cleared["scheduled_map_id"], cleared["map_name"]), (map_id, None))
        redone = self._step(
            match_id,
            "choose_side",
            team="t2",
            map="Ancient",
            side="T",
            revision=undo["bp_revision"],
        )
        self.assertEqual(self._map_rows(match_id)[0]["scheduled_map_id"], map_id)
        self.assertGreater(redone["revision"], completed["revision"])
        self.assertTrue(self._post(self.admin, match_id, "reset", {}).get_json()["ok"])
        waiting = self.admin.get(f"/api/bp/{match_id}/state").get_json()
        self.assertEqual(
            waiting, {"ok": True, "state": None, "status": "waiting", "bp_can_start": True}
        )
        fresh = self._step(match_id, "start")
        self.assertGreater(fresh["revision"], redone["revision"])
        stale = self._post(
            self.admin, match_id, "action", {"team": "t1", "action": "roll", "bp_revision": 0}
        )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.get_json()["bp_revision"], fresh["revision"])

    def test_same_name_setup_keeps_per_slot_identity_and_is_read_only(self):
        match_id = self._new_match(
            "BO5",
            setup={
                "map1": "de_mirage",
                "map2": "de_mirage",
                "map1_picked_by": "t1",
                "map2_picked_by": "t2",
                "map5": "de_nuke",
                "has_map5": 0,
            },
        )
        rows = self._map_rows(match_id)
        self.assertNotEqual(rows[0]["scheduled_map_id"], rows[1]["scheduled_map_id"])
        with closing(get_db()) as db:
            old = db.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
            projected = maps.project_legacy_map_fields(db, old)
            self.assertEqual(
                (projected["map1"], projected["map2"], projected["has_map5"]),
                ("de_mirage", "de_mirage", 0),
            )
            self.assertEqual(
                (projected["map1_picked_by"], projected["map2_picked_by"]), ("t1", "t2")
            )
            self.assertEqual([m["slot"] for m in maps.broadcast_maps(db, match_id)], [1, 2, 3, 4])
            self.assertIsNone(old["map1"])
        with closing(get_db()) as db, write(db):
            db.execute("UPDATE matches SET bo_format='BO1' WHERE id=?", (match_id,))
            maps.sync_scheduled_maps(db, match_id, setup={"map1": "de_nuke"})
            db.execute("UPDATE matches SET bo_format='BO5' WHERE id=?", (match_id,))
            maps.sync_scheduled_maps(db, match_id, setup={"map1": "de_nuke", "map5": "de_mirage"})
        changed = self._map_rows(match_id)
        self.assertEqual(
            [r["scheduled_map_id"] for r in changed], [r["scheduled_map_id"] for r in rows]
        )
        self.assertEqual((changed[0]["map_name"], changed[4]["map_name"]), ("de_nuke", "de_mirage"))

    def test_member_seat_password_frozen_roster_and_csrf_are_preserved(self):
        match_id = self._new_match(
            "BO1", freeze=False, password=hash_bp_password("test-room-phrase")
        )
        member = self._client(user_id=self.people[1].account_id)
        teammate = self._client(user_id=self.people[2].account_id)
        outsider = self._client(user_id=self.people[-1].account_id)
        self.assertFalse(member.get(f"/api/bp/{match_id}/state").get_json()["bp_can_start"])
        self.assertEqual(
            self._post(self.admin, match_id, "action", {"action": "start"}).status_code, 409
        )
        with closing(get_db()) as db, write(db):
            participants.freeze_rosters(db, match_id, ORGANIZER_ID)
        self.assertEqual(outsider.get(f"/api/bp/{match_id}/state").status_code, 403)
        self.assertEqual(
            self._post(member, match_id, "action", {"action": "start"}).status_code, 403
        )
        for client in (member, teammate):
            verify = client.post(
                f"/bp/{match_id}/verify",
                json={"password": "test-room-phrase"},
                headers={"X-CSRF-Token": "host-bp-fixture"},
            )
            self.assertEqual(verify.get_json()["team"], "t1")
        self.assertEqual(
            member.post(f"/api/bp/{match_id}/action", json={"action": "start"}).status_code, 403
        )
        self.assertEqual(member.get(f"/bp/{match_id}").status_code, 200)
        self.assertTrue(
            self._post(member, match_id, "action", {"action": "start"}).get_json()["ok"]
        )
        wrong_side = self._post(
            member, match_id, "action", {"action": "roll", "team": "t2"}
        ).get_json()
        self.assertFalse(wrong_side["ok"])
        self.assertEqual(self._post(teammate, match_id, "heartbeat", {}).status_code, 409)
        self.assertEqual(
            self._post(member, match_id, "seat/release", {"team": "t1"}).status_code, 403
        )
        self.assertTrue(
            self._post(self.admin, match_id, "seat/release", {"team": "t1"}).get_json()["ok"]
        )
        self.assertEqual(self._post(teammate, match_id, "heartbeat", {}).get_json()["team"], "t1")

    def test_same_revision_on_two_connections_accepts_only_one_step(self):
        match_id = self._new_match("BO1")
        current = self._step(match_id, "start")["revision"]
        ready = Barrier(2)

        def send(_):
            client = self._client(admin_id=ORGANIZER_ID)
            ready.wait(timeout=5)
            return self._post(
                client, match_id, "action", {"action": "roll", "team": "t1", "bp_revision": current}
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(send, range(2)))
        self.assertEqual(sorted(result.status_code for result in results), [200, 409])
        stale = next(result.get_json() for result in results if result.status_code == 409)
        self.assertEqual(stale["bp_revision"], current + 1)
        self.assertEqual(stale["info"]["phase"], "rolling")

    def test_read_normalizes_only_in_memory_for_hosted_bp_and_scores_protect_plan(self):
        hosted = self._new_match("BO1")
        old_state = init_bp_state("BO1")
        old_state["state_version"] = 1
        old_state["turn_deadline"] = 30
        raw = json.dumps(old_state)
        with closing(get_db()) as db, write(db):
            db.execute("UPDATE matches SET bp_state=? WHERE id=?", (raw, hosted))
            legacy = db.execute(
                "INSERT INTO matches(status,bo_format,bp_state) VALUES('upcoming','BO1',?)",
                (raw,),
            ).lastrowid
        self.assertNotIn(
            "turn_deadline", self.admin.get(f"/api/bp/{hosted}/state").get_json()["state"]
        )
        self.assertNotIn(
            "turn_deadline", self.admin.get(f"/api/bp/{legacy}/state").get_json()["state"]
        )
        with closing(get_db()) as db, write(db):
            self.assertEqual(
                db.execute("SELECT bp_state FROM matches WHERE id=?", (hosted,)).fetchone()[0], raw
            )
            self.assertNotEqual(
                db.execute("SELECT bp_state FROM matches WHERE id=?", (legacy,)).fetchone()[0], raw
            )
            db.execute("UPDATE matches SET map1_t1=1 WHERE id=?", (hosted,))
        for endpoint, body in (("reset", {}), ("undo", {}), ("seat/release", {"team": "t1"})):
            self.assertEqual(self._post(self.admin, hosted, endpoint, body).status_code, 409)
        self.assertEqual(self._map_rows(hosted)[0]["map_name"], None)

    def test_database_failure_in_last_map_leaves_old_revision_and_all_map_slots_unchanged(self):
        match_id = self._new_match("BO3", pool=["Nuke", "Mirage", "Ancient"])
        state = self._choose_maps(match_id, [("pick", "t1", "Nuke"), ("pick", "t2", "Mirage")])
        state = self._step(
            match_id, "choose_side", team="t2", map="Nuke", side="CT", revision=state["revision"]
        )
        before = self._map_rows(match_id)
        last_step = {
            "action": "choose_side",
            "team": "t1",
            "map": "Mirage",
            "side": "T",
            "bp_revision": state["revision"],
        }
        with closing(get_db()) as db, write(db):
            db.execute("""CREATE TRIGGER fail_last_map BEFORE UPDATE OF map_name ON scheduled_maps
                          WHEN NEW.legacy_slot=3 BEGIN SELECT RAISE(ABORT,'synthetic final map'); END""")
        failed = self._post(self.admin, match_id, "action", last_step)
        self.assertEqual(failed.status_code, 500)
        self.assertEqual(self._map_rows(match_id), before)
        self.assertEqual(self.admin.get(f"/api/bp/{match_id}/state").get_json()["state"], state)
        with closing(get_db()) as db, write(db):
            db.execute("DROP TRIGGER fail_last_map")
        done = self._post(self.admin, match_id, "action", last_step).get_json()
        self.assertEqual(done["state"]["status"], "completed")
        self.assertEqual(
            [r["map_name"] for r in self._map_rows(match_id)],
            ["de_nuke", "de_mirage", "de_ancient"],
        )

    def test_database_rejects_pick_by_participant_from_another_match(self):
        match_id = self._new_match("BO1")
        other_match = self._new_match("BO1")
        with closing(get_db()) as db:
            other_id = db.execute(
                "SELECT match_participant_id FROM match_participants WHERE match_id=?",
                (other_match,),
            ).fetchone()[0]
            with self.assertRaises(sqlite3.IntegrityError), write(db):
                db.execute(
                    "UPDATE scheduled_maps SET picked_by_match_participant_id=? WHERE match_id=?",
                    (other_id, match_id),
                )
            self.assertEqual(list(db.execute("PRAGMA foreign_key_check")), [])
