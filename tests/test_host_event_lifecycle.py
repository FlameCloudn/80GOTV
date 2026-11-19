"""Original routes, admin handles and automatic cutoff share one synthetic on-disk DB."""

import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from app import app
from config import Config
from models import get_db, init_tables
from site_core.events import public, registration
from site_core.host import HostError, write
from tests.entrant_slice_fixtures import ORGANIZER_ID, seed_registrants


class HostEventsTests(unittest.TestCase):
    def setUp(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory(prefix="80gotv-host-events-"))
        self.enterContext(patch.object(Config, "DATABASE", str(Path(tmp) / "synthetic.sqlite")))
        self.enterContext(patch.object(Config, "STEAM_WEB_API_KEY", ""))
        self.enterContext(patch.dict(app.config, {"TESTING": True, "SESSION_COOKIE_SECURE": False}))
        init_tables()
        self.deadline = int(time.time()) + 600
        with closing(get_db()) as db:
            db.execute(
                "INSERT INTO admins(id,username,password_hash) VALUES(?,'test-organizer','disabled')",
                (ORGANIZER_ID,),
            )
            self.people = seed_registrants(
                db, [0, 350, None, 100, 0, 200, 300, 400, 500, 10, 50, 32, 420]
            )
            db.execute("UPDATE users SET is_bashizhong_student=0")
            self.event = db.execute(
                "INSERT INTO events(name,slug,status,registration_open) VALUES('Host','host-new','upcoming',0) RETURNING id"
            ).fetchone()[0]
            self.legacy = db.execute(
                "INSERT INTO events(name,slug,status,registration_open) VALUES('Old','old','upcoming',1)"
            ).lastrowid
            db.commit()
        self.admin = self.client(admin_id=ORGANIZER_ID)
        self.prefix = f"/admin/events/{self.event}/registration-control"
        self.assertEqual(
            self.post(
                self.admin, self.prefix + "/enable", json={"registration_deadline": self.deadline}
            ).status_code,
            200,
        )

    def client(self, **identity):
        client = app.test_client()
        with client.session_transaction() as browser:
            browser.update(identity, csrf_token="event-fixture")
        return client

    def state(self):
        response = self.admin.get(self.prefix)
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        assert isinstance(body, dict)
        return body

    @staticmethod
    def post(client, path, **kwargs):
        return client.post(
            path,
            headers={"X-CSRF-Token": "event-fixture", "X-Requested-With": "XMLHttpRequest"},
            **kwargs,
        )

    def test_original_web_forms_share_true_ids_but_not_members_with_old_event(self):
        user = self.client(user_id=self.people[0].account_id)
        for event, name in ((self.legacy, "Old A"), (self.event, "New A")):
            response = self.post(
                user, f"/events/{event}/register", data={"team_name": name, "my_slot": "0"}
            )
            self.assertEqual(response.status_code, 302)
        other = self.client(user_id=self.people[1].account_id)
        response = self.post(
            other, f"/events/{self.legacy}/register", data={"team_name": "Old B", "my_slot": "0"}
        )
        self.assertEqual(response.status_code, 302)
        with closing(get_db()) as db:
            groups = db.execute(
                "SELECT id,event_id FROM event_registrations ORDER BY id"
            ).fetchall()
            self.assertEqual([g[1] for g in groups], [self.legacy, self.event, self.legacy])
            old_id, new_id, _ = [g[0] for g in groups]
            self.assertEqual(
                db.execute(
                    "SELECT count(*) FROM event_registration_slots WHERE registration_id=?",
                    (new_id,),
                ).fetchone()[0],
                0,
            )
        self.assertEqual(self.post(other, f"/events/{self.event}/join/{old_id}/1").status_code, 404)
        response = self.post(other, f"/events/{self.event}/join/{new_id}/1")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertTrue(response.json["success"])
        self.assertIn("New A", response.json["html"])
        third = self.client(user_id=self.people[2].account_id)
        success = self.post(third, f"/events/{self.event}/register-individual")
        self.assertEqual(success.status_code, 200, success.get_data(as_text=True))
        self.assertTrue(success.json["success"])
        self.assertEqual(
            self.post(third, f"/events/{self.event}/register-individual").status_code, 409
        )
        with closing(get_db()) as db:
            self.assertEqual(
                db.execute(
                    "SELECT count(*) FROM event_individual_registrations WHERE event_id=?",
                    (self.event,),
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                db.execute(
                    "SELECT count(*) FROM event_signup_entries WHERE event_id=?", (self.event,)
                ).fetchone()[0],
                3,
            )
            self.assertFalse(db.execute("PRAGMA foreign_key_check").fetchall())

    def test_worker_repeat_conflict_review_and_form_rollback(self):
        with closing(get_db()) as db, write(db):
            group = registration.create_group(
                db,
                self.event,
                self.people[0].account_id,
                "Mixed",
                now=self.deadline - 1,
                reservations={1: ("Held", self.people[1].steam_id)},
            )
            for p in self.people[2:6]:
                registration.enroll(
                    db, self.event, p.account_id, "individual", now=self.deadline - 1
                )
        with closing(get_db()) as db:
            formed, blocked = public.run_due_events_once(db, now=self.deadline)
            self.assertEqual(formed, [])
            self.assertIn(self.event, blocked)
            self.assertFalse(db.execute("SELECT 1 FROM event_formation_batches").fetchone())
            with write(db):
                registration.review_reservation(
                    db,
                    self.event,
                    group,
                    1,
                    self.people[1].account_id,
                    admin_id=ORGANIZER_ID,
                    reason="核对最初预留",
                    now=self.deadline,
                )
                db.execute("""CREATE TRIGGER host_injected_failure BEFORE INSERT ON event_current_members
                     BEGIN SELECT RAISE(ABORT,'injected'); END""")
            with self.assertRaises(sqlite3.IntegrityError):
                public.run_due_events_once(db, now=self.deadline)
            self.assertFalse(db.execute("SELECT 1 FROM event_formation_batches").fetchone())
            self.assertEqual(
                db.execute(
                    "SELECT registration_open FROM events WHERE id=?", (self.event,)
                ).fetchone()[0],
                1,
            )
            db.execute("DROP TRIGGER host_injected_failure")
            db.commit()
        together = Barrier(2)

        def tick(_):
            with closing(get_db()) as db:
                together.wait(timeout=5)
                return public.run_due_events_once(db, now=self.deadline)

        with ThreadPoolExecutor(2) as pool:
            ticks = list(pool.map(tick, range(2)))
        self.assertTrue(all(not blocked for _, blocked in ticks))
        with closing(get_db()) as db:
            self.assertEqual(
                db.execute("SELECT count(*) FROM event_formation_batches").fetchone()[0], 1
            )
            self.assertEqual(
                db.execute("SELECT count(*) FROM event_current_members").fetchone()[0], 5
            )
            self.assertEqual(
                db.execute("SELECT count(*) FROM event_reserve_candidates").fetchone()[0], 1
            )
            self.assertEqual(
                db.execute(
                    "SELECT minutes FROM event_formation_inputs WHERE player_id=?",
                    (self.people[0].player_id,),
                ).fetchone()[0],
                0,
            )
            self.assertIsNone(
                db.execute(
                    "SELECT minutes FROM event_formation_inputs WHERE player_id=?",
                    (self.people[2].player_id,),
                ).fetchone()[0]
            )

    def test_admin_freeze_reserve_priority_and_nonrolling_three(self):
        with closing(get_db()) as db, write(db):
            for p in self.people[:6]:
                registration.enroll(
                    db, self.event, p.account_id, "individual", now=self.deadline - 1
                )
            batch = public.form_due_event(db, self.event, now=self.deadline)
            for p in self.people[6:9]:
                registration.enroll(
                    db, self.event, p.account_id, "independent_reserve", now=self.deadline
                )
            (team,) = batch["entrant_ids"]
            remainder = db.execute(
                """SELECT player_id FROM event_reserve_candidates WHERE event_id=?
                AND player_id NOT IN (?,?,?)""",
                (self.event, *(p.player_id for p in self.people[6:9])),
            ).fetchone()[0]
        self.assertEqual(self.state()["entrants"][0]["initial_player_ids"], [])
        confirmed = {"event_entrant_ids": [team], "expected_revision": 1}
        freeze = self.post(
            self.admin,
            f"/admin/events/edit/{self.event}",
            data={
                "registration_action": "confirm-initial",
                "event_entrant_ids": f"[{team}]",
                "expected_revision": "1",
            },
        )
        self.assertEqual(freeze.status_code, 200, freeze.get_data(as_text=True))
        self.assertEqual(
            self.post(self.admin, self.prefix + "/confirm-initial", json=confirmed).json,
            freeze.json,
        )
        original = self.state()["entrants"][0]["initial_player_ids"]
        rev = freeze.json["formation_revision"]

        def change(action, **fields):
            return self.post(
                self.admin,
                self.prefix + "/" + action,
                json=dict(
                    event_entrant_id=team,
                    expected_revision=rev,
                    reason="现场已协商资格、意愿及候补席位",
                    **fields,
                ),
            )

        self.assertEqual(change("assign-reserve", player_id=remainder).status_code, 409)
        for pos, p in enumerate(self.people[6:9]):
            granted = change("assign-reserve", player_id=p.player_id)
            self.assertEqual(granted.status_code, 200, granted.get_data(as_text=True))
            rev = granted.json["formation_revision"]
            replaced = change(
                "replace-before-series",
                outgoing_player_id=original[pos],
                incoming_player_id=p.player_id,
            )
            if pos == 2:
                self.assertEqual(replaced.status_code, 409, replaced.get_data(as_text=True))
            else:
                self.assertEqual(replaced.status_code, 200, replaced.get_data(as_text=True))
                rev = replaced.json["formation_revision"]
        facts = self.state()["entrants"][0]
        self.assertEqual(facts["initial_player_ids"], original)
        self.assertEqual(len(set(facts["current_player_ids"]) & set(original)), 3)
        self.assertEqual(len(facts["changes"]), 2)
        self.assertEqual(self.post(self.admin, self.prefix + "/archive", json={}).status_code, 200)
        self.assertEqual(
            self.post(
                self.admin,
                self.prefix + "/assign-reserve",
                json={
                    "event_entrant_id": team,
                    "player_id": remainder,
                    "expected_revision": rev,
                    "reason": "已协商",
                },
            ).status_code,
            409,
        )
        self.assertEqual(
            self.state()["entrants"][0]["current_player_ids"],
            facts["current_player_ids"],
        )

    def test_opt_in_cannot_adopt_legacy_or_be_inferred_from_get(self):
        with closing(get_db()) as db, write(db):
            with self.assertRaises(HostError):
                registration.enable_event(
                    db, self.legacy, self.deadline, admin_id=ORGANIZER_ID, now=self.deadline - 1
                )
            db.execute(
                "UPDATE event_registration_control SET registration_deadline=? WHERE event_id=?",
                (int(time.time()) - 1, self.event),
            )
        visitor = self.client()
        self.assertEqual(visitor.get("/events/host-new").status_code, 200)
        self.assertEqual(visitor.get("/events").status_code, 200)
        person = self.client(user_id=self.people[0].account_id)
        self.assertEqual(
            self.post(person, f"/events/{self.event}/register-individual").status_code, 409
        )
        self.assertEqual(
            self.post(person, f"/events/{self.event}/register-substitute").status_code, 200
        )
        with closing(get_db()) as db:
            self.assertFalse(db.execute("SELECT 1 FROM event_formation_batches").fetchone())
            self.assertEqual(
                db.execute("SELECT count(*) FROM event_registration_control").fetchone()[0], 1
            )
            public.run_due_events_once(db)
            self.assertEqual(
                db.execute("SELECT count(*) FROM event_reserve_candidates").fetchone()[0], 1
            )

    def test_zero_write_can_revert_withdrawn_first_write_cannot(self):
        self.assertEqual(self.post(self.admin, self.prefix + "/disable", json={}).status_code, 200)
        self.assertEqual(self.admin.get(self.prefix).status_code, 404)
        with closing(get_db()) as db:
            self.assertEqual(
                db.execute(
                    "SELECT registration_open FROM events WHERE id=?", (self.event,)
                ).fetchone()[0],
                0,
            )
        self.assertEqual(
            self.post(
                self.admin, self.prefix + "/enable", json={"registration_deadline": self.deadline}
            ).status_code,
            200,
        )
        user = self.client(user_id=self.people[0].account_id)
        self.assertEqual(
            self.post(user, f"/events/{self.event}/register-individual").status_code, 200
        )
        self.assertEqual(
            self.post(user, f"/events/{self.event}/individual-registration/withdraw").status_code,
            200,
        )
        self.assertEqual(self.post(self.admin, self.prefix + "/disable", json={}).status_code, 409)
        with closing(get_db()) as db:
            self.assertFalse(
                db.execute(
                    "SELECT 1 FROM event_signup_entries WHERE event_id=?", (self.event,)
                ).fetchone()
            )
            self.assertIsNotNone(
                db.execute(
                    "SELECT first_write_at FROM event_registration_control WHERE event_id=?",
                    (self.event,),
                ).fetchone()[0]
            )

    def test_original_admin_add_opts_in_atomically_and_preserves_deadline_owner(self):
        form = dict(
            name="Summer Cup",
            short_name="Summer",
            slug="summer-cup",
            start_date="2090-08-01",
            end_date="2090-08-03",
            registration_open="1",
        )
        self.assertEqual(
            self.post(
                self.admin, "/admin/events/add", data=dict(form, registration_deadline="bad")
            ).status_code,
            400,
        )
        with closing(get_db()) as db:
            self.assertFalse(db.execute("SELECT 1 FROM events WHERE slug='summer-cup'").fetchone())
        self.assertEqual(
            self.post(
                self.admin,
                "/admin/events/add",
                data=dict(form, registration_deadline=str(self.deadline)),
            ).status_code,
            302,
        )
        with closing(get_db()) as db:
            event = db.execute("SELECT id FROM events WHERE slug='summer-cup'").fetchone()[0]
            self.assertEqual(
                db.execute(
                    "SELECT registration_deadline FROM event_registration_control WHERE event_id=?",
                    (event,),
                ).fetchone()[0],
                self.deadline,
            )
        self.assertEqual(
            self.post(
                self.admin, f"/admin/events/edit/{event}", data=dict(form, registration_open="0")
            ).status_code,
            302,
        )
        with closing(get_db()) as db:
            self.assertEqual(
                db.execute("SELECT registration_open FROM events WHERE id=?", (event,)).fetchone()[
                    0
                ],
                1,
            )
        self.assertEqual(
            self.post(
                self.admin, f"/admin/events/{event}/bracket/api/save", json={"format": "single"}
            ).status_code,
            409,
        )
        self.assertEqual(
            self.post(
                self.admin, f"/admin/events/{event}/bracket", data={"bracket_data": "{}"}
            ).status_code,
            409,
        )
        self.assertEqual(
            self.post(
                self.client(user_id=self.people[0].account_id), self.prefix + "/archive", json={}
            ).status_code,
            401,
        )
        self.assertEqual(
            self.admin.post(
                self.prefix + "/archive", json={}, headers={"X-Requested-With": "XMLHttpRequest"}
            ).status_code,
            403,
        )

    def test_steam_refresh_never_holds_a_writer_and_all_cutoff_entries_preserve_frozen_input(self):
        at = int(time.time()) - 2
        for mode in ("worker", "original", "admin"):
            with self.subTest(mode=mode), closing(get_db()) as db:
                with write(db):
                    event = db.execute(
                        "INSERT INTO events(name,status,registration_open) VALUES(?,'upcoming',0) RETURNING id",
                        (mode,),
                    ).fetchone()[0]
                    registration.enable_event(db, event, at, admin_id=ORGANIZER_ID, now=at - 60)
                    for p in self.people[:5]:
                        registration.enroll(db, event, p.account_id, "individual", now=at - 1)
                    registration.enroll(
                        db, event, self.people[5].account_id, "independent_reserve", now=at - 1
                    )
                    db.execute(
                        "UPDATE players SET playtime_status='public',playtime_checked_at=?",
                        (datetime.fromtimestamp(at, timezone.utc).isoformat(),),
                    )
                    db.execute(
                        "UPDATE players SET playtime_checked_at=NULL WHERE id IN (?,?,?)",
                        (
                            self.people[0].player_id,
                            self.people[1].player_id,
                            self.people[5].player_id,
                        ),
                    )
                acquired = []

                def external(steam, _key):
                    with closing(get_db()) as other:
                        other.execute("PRAGMA busy_timeout=300")
                        other.execute("BEGIN IMMEDIATE")
                        acquired.append(steam)
                        other.rollback()
                    return (
                        {"status": "public", "minutes": 0}
                        if steam == self.people[0].steam_id
                        else {"status": "private", "minutes": None}
                    )

                from services import steam_playtime_service

                admin_url = f"/admin/events/{event}/registration-control/form-due"
                old_url = f"/events/{event}/individual-registration/finalize"
                with (
                    patch.object(Config, "STEAM_WEB_API_KEY", "synthetic-only"),
                    patch.object(
                        steam_playtime_service, "fetch_cs2_playtime_minutes", side_effect=external
                    ) as remote,
                ):
                    if mode == "worker":
                        self.assertIn(
                            event,
                            [b["event_id"] for b in public.run_due_events_once(db, now=at)[0]],
                        )
                    elif mode == "original":
                        self.assertEqual(self.post(self.admin, old_url).status_code, 200)
                    else:
                        self.assertEqual(self.post(self.admin, admin_url, json={}).status_code, 200)
                    self.assertCountEqual(
                        acquired, [self.people[0].steam_id, self.people[1].steam_id]
                    )
                    db.execute(
                        "UPDATE players SET cs2_playtime_minutes=99999,playtime_checked_at=NULL"
                    )
                    db.commit()
                    self.assertEqual(self.post(self.admin, admin_url, json={}).status_code, 200)
                    self.assertEqual(self.post(self.admin, old_url).status_code, 200)
                    self.assertEqual(remote.call_count, 2)
                inputs = {
                    r["player_id"]: (r["minutes"], r["playtime_status"])
                    for r in db.execute(
                        "SELECT * FROM event_formation_inputs WHERE event_id=?", (event,)
                    )
                }
                self.assertEqual(inputs[self.people[0].player_id], (0, "public"))
                self.assertEqual(inputs[self.people[1].player_id], (None, "private"))
                self.assertNotIn(self.people[5].player_id, inputs)

    def test_unknown_old_match_with_actual_scores_is_not_a_prematch_roster_window(self):
        with closing(get_db()) as db, write(db):
            for person in self.people[:5]:
                registration.enroll(
                    db, self.event, person.account_id, "individual", now=self.deadline - 1
                )
            (team,) = public.form_due_event(db, self.event, now=self.deadline)["entrant_ids"]
            db.execute(
                "INSERT INTO matches(event_id,match_time,status,map5_t2) VALUES(?,'2090-10-10','upcoming',1)",
                (self.event,),
            )
            with self.assertRaisesRegex(HostError, "实战"):
                public.confirm_initial_rosters(
                    db,
                    self.event,
                    [team],
                    expected_revision=1,
                    admin_id=ORGANIZER_ID,
                    now=self.deadline,
                )
            db.execute("UPDATE matches SET status='completed'")
            public.confirm_initial_rosters(
                db,
                self.event,
                [team],
                expected_revision=1,
                admin_id=ORGANIZER_ID,
                now=self.deadline,
            )
            self.assertTrue(public.roster(db, self.event, team)["is_frozen"])

    def test_archiving_one_team_preserves_old_snapshot_and_other_team(self):
        from site_core.matches import participants

        with closing(get_db()) as db, write(db):
            for p in self.people[:10]:
                registration.enroll(
                    db, self.event, p.account_id, "individual", now=self.deadline - 1
                )
            batch = public.form_due_event(db, self.event, now=self.deadline)
            home, away = batch["entrant_ids"]
            public.confirm_initial_rosters(
                db,
                self.event,
                [home, away],
                expected_revision=1,
                admin_id=ORGANIZER_ID,
                now=self.deadline,
            )
            match = db.execute(
                "INSERT INTO matches(event_id,status,match_time) VALUES(?,'upcoming','2090-06-01 12:00')",
                (self.event,),
            ).lastrowid
            participants.bind(db, match, home, away)
            participants.freeze_rosters(db, match, ORGANIZER_ID)
            before = public.roster(db, self.event, home)
        payload = {"event_entrant_id": home, "reason": "该队已退出后续赛程"}
        self.assertEqual(
            self.post(self.admin, self.prefix + "/archive-team", json=payload).status_code, 409
        )
        with closing(get_db()) as db, write(db):
            db.execute("UPDATE matches SET status='completed' WHERE id=?", (match,))
        self.assertEqual(
            self.post(self.admin, self.prefix + "/archive-team", json=payload).status_code, 200
        )
        with closing(get_db()) as db:
            self.assertEqual(
                before["initial_player_ids"],
                public.roster(db, self.event, home)["initial_player_ids"],
            )
            self.assertIsNotNone(public.roster(db, self.event, home)["team_archived_at"])
            self.assertIsNone(public.roster(db, self.event, away)["team_archived_at"])
            self.assertEqual(
                db.execute("SELECT count(*) FROM match_roster_members").fetchone()[0], 10
            )
            self.assertTrue(
                db.execute(
                    "SELECT team_name FROM event_registrations WHERE id=?",
                    (before["registration_id"],),
                ).fetchone()[0]
            )
            with self.assertRaises(HostError), write(db):
                registration.enroll(
                    db,
                    self.event,
                    self.people[10].account_id,
                    "independent_reserve",
                    now=self.deadline,
                    preferred_registration_id=before["registration_id"],
                )
