"""Verify isolation, constraints and atomic writes against independent SQLite connections."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Barrier
from typing import Callable

from entrant_slice import formation, registration, sandbox, storage
from tests.entrant_slice_fixtures import (
    DEADLINE,
    ORGANIZER_ID,
    REGISTRATION_TIME,
    SECOND_ORGANIZER_ID,
    EntrantSandboxCase,
    seed_registrants,
)


class EntrantTransactionTests(EntrantSandboxCase):
    def compete(self, *commands: Callable[[sqlite3.Connection], object]) -> list[object]:
        ready = Barrier(len(commands))

        def run(command: Callable[[sqlite3.Connection], object]) -> object:
            with closing(sandbox.connect(self.workspace)) as connection:
                ready.wait(timeout=5)
                try:
                    with storage.write(connection):
                        return command(connection)
                except storage.SliceError as exc:
                    return exc

        with ThreadPoolExecutor(max_workers=len(commands)) as pool:
            return list(pool.map(run, commands))

    def test_group_join_and_individual_enrollment_race_for_one_membership(self) -> None:
        event_id = self.create_event()
        captain, member = seed_registrants(self.conn, [300, 400])
        group_id = self.register_group(event_id, "Single membership", [captain])
        results = self.compete(
            lambda conn: registration.join_group(
                conn, event_id, group_id, member.account_id, 1, now=REGISTRATION_TIME
            ),
            lambda conn: registration.enroll(
                conn, event_id, member.account_id, "individual", now=REGISTRATION_TIME
            ),
        )
        conflicts = [result for result in results if isinstance(result, storage.SliceError)]
        self.assertEqual([exc.status for exc in conflicts], [409])
        rows = list(
            self.conn.execute(
                "SELECT player_id,registration_origin,registration_group_id,roster_slot FROM registration_entry "
                "WHERE event_id=? AND account_id=?",
                (event_id, member.account_id),
            )
        )
        expected = (
            ("individual", None, None)
            if isinstance(results[0], storage.SliceError)
            else ("group", group_id, 1)
        )
        self.assertEqual([tuple(row) for row in rows], [(member.player_id, *expected)])

    def test_two_cutoff_commands_return_one_saved_batch_and_never_confirm(self) -> None:
        event_id = self.create_event()
        people = seed_registrants(self.conn, [300] * 11)
        self.register_group(event_id, "Existing three", people[:3])
        self.enroll_individuals(event_id, people[3:])
        first, retry = self.compete(
            lambda conn: formation.form_due_event(conn, event_id, now=DEADLINE),
            lambda conn: formation.form_due_event(conn, event_id, now=DEADLINE + 1),
        )
        self.assertIsInstance(first, dict)
        self.assertEqual(first, retry)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM formation_batch").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM event_entrant").fetchone()[0], 2)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM entrant_member").fetchone()[0], 10)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM initial_roster").fetchone()[0], 0)
        self.assertEqual(
            self.conn.execute("SELECT player_id FROM reserve_candidate").fetchone()[0],
            people[-1].player_id,
        )

    def test_two_admins_at_same_revision_cannot_confirm_different_drafts(self) -> None:
        event_id = self.create_event()
        self.enroll_individuals(event_id, seed_registrants(self.conn, [300] * 10))
        batch = self.command(formation.form_due_event, event_id, now=DEADLINE)
        harbor, copper = batch["entrant_ids"]
        revision = batch["formation_revision"]
        results = self.compete(
            lambda conn: formation.confirm_initial_rosters(
                conn,
                event_id,
                [harbor],
                expected_revision=revision,
                admin_id=ORGANIZER_ID,
                now=DEADLINE + 1,
            ),
            lambda conn: formation.confirm_initial_rosters(
                conn,
                event_id,
                [copper],
                expected_revision=revision,
                admin_id=SECOND_ORGANIZER_ID,
                now=DEADLINE + 1,
            ),
        )
        self.assertEqual(
            [result.status for result in results if isinstance(result, storage.SliceError)], [409]
        )
        (success,) = [result for result in results if isinstance(result, dict)]
        if isinstance(results[0], storage.SliceError):
            winner, still_pending, organizer = copper, harbor, SECOND_ORGANIZER_ID
        else:
            winner, still_pending, organizer = harbor, copper, ORGANIZER_ID
        frozen = formation.get_roster(self.conn, event_id, winner)
        self.assertEqual(frozen["confirmed_by"], organizer)
        self.assertCountEqual(frozen["initial_player_ids"], frozen["current_player_ids"])
        self.assertFalse(formation.get_roster(self.conn, event_id, still_pending)["is_frozen"])
        confirmed = self.command(
            formation.confirm_initial_rosters,
            event_id,
            [still_pending],
            expected_revision=success["formation_revision"],
            admin_id=SECOND_ORGANIZER_ID,
            now=DEADLINE + 2,
        )
        self.assertGreater(confirmed["formation_revision"], success["formation_revision"])
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM initial_roster_member").fetchone()[0], 10
        )
        self.assertEqual(
            formation.get_roster(self.conn, event_id, winner)["confirmed_by"], organizer
        )

    def test_formation_failure_on_last_seat_restores_input_then_retries(self) -> None:
        event_id = self.create_event()
        people = seed_registrants(self.conn, [300] * 11)
        self.register_group(event_id, "Existing three", people[:3])
        self.enroll_individuals(event_id, people[3:])
        original = list(
            self.conn.execute("SELECT * FROM registration_entry ORDER BY registration_entry_id")
        )
        self.conn.execute("""CREATE TEMP TRIGGER stop_last_formation_seat BEFORE INSERT ON entrant_member
          WHEN (SELECT COUNT(*) FROM entrant_member WHERE event_id=NEW.event_id)=9
          BEGIN SELECT RAISE(ABORT, 'synthetic final formation seat'); END""")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "synthetic final formation seat"):
            self.command(formation.form_due_event, event_id, now=DEADLINE)
        with closing(sandbox.connect(self.workspace)) as reader:
            self.assertEqual(
                list(
                    reader.execute(
                        "SELECT * FROM registration_entry ORDER BY registration_entry_id"
                    )
                ),
                original,
            )
            self.assertEqual(
                reader.execute("SELECT COUNT(*) FROM registration_group").fetchone()[0], 1
            )
            self.assertEqual(
                reader.execute("SELECT COUNT(*) FROM formation_batch").fetchone()[0], 0
            )
            self.assertEqual(reader.execute("SELECT COUNT(*) FROM event_entrant").fetchone()[0], 0)
            self.assertEqual(
                reader.execute("SELECT COUNT(*) FROM reserve_candidate").fetchone()[0], 0
            )
        self.conn.execute("DROP TRIGGER stop_last_formation_seat")
        batch = self.command(formation.form_due_event, event_id, now=DEADLINE + 1)
        self.assertEqual(self.command(formation.form_due_event, event_id, now=DEADLINE + 2), batch)
        self.assertEqual(len(batch["entrant_ids"]), 2)

    def test_stale_confirmation_cannot_acknowledge_five_the_admin_never_saw(self) -> None:
        event = self.create_event()
        people = seed_registrants(self.conn, [300] * 6)
        self.register_group(event, "Original draft", people[:5])
        self.enroll_individuals(event, people[5:])
        first = self.command(formation.form_due_event, event, now=DEADLINE)
        (entrant,) = first["entrant_ids"]
        updated_five = [p.player_id for p in (*people[:4], people[5])]
        revised = self.command(
            formation.adjust_formation,
            event,
            {entrant: updated_five},
            expected_revision=first["formation_revision"],
            admin_id=SECOND_ORGANIZER_ID,
            reason="Verified pre-confirmation change",
            now=DEADLINE + 1,
        )
        frozen = self.command(
            formation.confirm_initial_rosters,
            event,
            [entrant],
            expected_revision=revised["formation_revision"],
            admin_id=SECOND_ORGANIZER_ID,
            now=DEADLINE + 2,
        )
        with self.assertRaises(storage.SliceError) as stale:
            self.command(
                formation.confirm_initial_rosters,
                event,
                [entrant],
                expected_revision=first["formation_revision"],
                admin_id=ORGANIZER_ID,
                now=DEADLINE + 3,
            )
        self.assertEqual(stale.exception.status, 409)
        retried = self.command(
            formation.confirm_initial_rosters,
            event,
            [entrant],
            expected_revision=revised["formation_revision"],
            admin_id=SECOND_ORGANIZER_ID,
            now=DEADLINE + 4,
        )
        self.assertEqual(retried, frozen)
        saved = formation.get_roster(self.conn, event, entrant)
        self.assertEqual(
            (saved["initial_player_ids"], saved["confirmed_by"], saved["confirmed_at"]),
            (updated_five, SECOND_ORGANIZER_ID, DEADLINE + 2),
        )

    def test_old_score_or_final_stats_block_late_freeze_and_regular_substitution(self) -> None:
        event = self.create_event()
        people = seed_registrants(self.conn, [300] * 11)
        home = self.register_group(event, "Confirmed", people[:5])
        away = self.register_group(event, "Still a draft", people[5:10])
        home_club, away_club = [
            self.conn.execute("INSERT INTO teams(name) VALUES(?) RETURNING id", (name,)).fetchone()[
                0
            ]
            for name in ("Home club", "Away club")
        ]
        for group, club in ((home, home_club), (away, away_club)):
            self.command(
                registration.link_club,
                event,
                group,
                club,
                admin_id=ORGANIZER_ID,
                now=REGISTRATION_TIME,
            )
        self.command(
            registration.enroll,
            event,
            people[-1].account_id,
            "independent_reserve",
            now=REGISTRATION_TIME,
        )
        batch = self.command(formation.form_due_event, event, now=DEADLINE)
        entrants = {
            r["registration_group_id"]: r["event_entrant_id"]
            for r in self.conn.execute("SELECT * FROM event_entrant")
        }
        frozen = self.command(
            formation.confirm_initial_rosters,
            event,
            [entrants[home]],
            expected_revision=batch["formation_revision"],
            admin_id=ORGANIZER_ID,
            now=DEADLINE + 1,
        )
        granted = self.command(
            formation.assign_reserve,
            event,
            entrants[home],
            people[-1].player_id,
            expected_revision=frozen["formation_revision"],
            admin_id=ORGANIZER_ID,
            reason="Confirmed availability",
            now=DEADLINE + 2,
        )
        before = [formation.get_roster(self.conn, event, e) for e in entrants.values()]
        match = self.conn.execute(
            """INSERT INTO matches(event_id,status,team1_id,team2_id,map1_t1)
                                  VALUES(?,'upcoming',?,?,13) RETURNING id""",
            (event, home_club, away_club),
        ).fetchone()[0]
        for evidence in ("recorded score", "final individual stats"):
            with self.subTest(evidence=evidence):
                if evidence == "final individual stats":
                    self.conn.execute("UPDATE matches SET map1_t1=0 WHERE id=?", (match,))
                    self.conn.execute(
                        "INSERT INTO match_stats(match_id,player_id,kills,data_status) VALUES(?,?,4,'final')",
                        (match, people[0].player_id),
                    )
                with self.assertRaises(storage.SliceError) as freeze:
                    self.command(
                        formation.confirm_initial_rosters,
                        event,
                        [entrants[away]],
                        expected_revision=granted["formation_revision"],
                        admin_id=ORGANIZER_ID,
                        now=DEADLINE + 3,
                    )
                with self.assertRaises(storage.SliceError) as swap:
                    self.command(
                        formation.replace_before_series,
                        event,
                        entrants[home],
                        people[0].player_id,
                        people[-1].player_id,
                        expected_revision=granted["formation_revision"],
                        admin_id=ORGANIZER_ID,
                        reason="Pre-series request",
                        now=DEADLINE + 3,
                    )
                self.assertEqual((freeze.exception.status, swap.exception.status), (409, 409))
                self.assertEqual(
                    [formation.get_roster(self.conn, event, e) for e in entrants.values()], before
                )

    def test_promoted_independent_cannot_erase_or_reopen_the_original_registration(self) -> None:
        event = self.create_event()
        people = seed_registrants(self.conn, [300] * 7)
        group = self.register_group(event, "Full five", people[:5])
        first, second = people[5:]
        for reserve in (first, second):
            self.command(
                registration.enroll,
                event,
                reserve.account_id,
                "independent_reserve",
                now=REGISTRATION_TIME,
            )
        batch = self.command(formation.form_due_event, event, now=DEADLINE)
        (entrant,) = batch["entrant_ids"]
        state = self.command(
            formation.confirm_initial_rosters,
            event,
            [entrant],
            expected_revision=batch["formation_revision"],
            admin_id=ORGANIZER_ID,
            now=DEADLINE + 1,
        )
        original = self.conn.execute(
            "SELECT * FROM registration_entry WHERE event_id=? AND player_id=?",
            (event, first.player_id),
        ).fetchone()
        for n, (outgoing, incoming) in enumerate(((people[0], first), (first, second))):
            assigned = self.command(
                formation.assign_reserve,
                event,
                entrant,
                incoming.player_id,
                expected_revision=state["formation_revision"],
                admin_id=ORGANIZER_ID,
                reason="Availability agreed with player",
                now=DEADLINE + 2 + n * 2,
            )
            state = self.command(
                formation.replace_before_series,
                event,
                entrant,
                outgoing.player_id,
                incoming.player_id,
                expected_revision=assigned["formation_revision"],
                admin_id=ORGANIZER_ID,
                reason="Approved pre-series change",
                now=DEADLINE + 3 + n * 2,
            )
            with self.subTest(first_is_current=n == 0):
                with self.assertRaises(storage.SliceError) as withdraw:
                    self.command(
                        registration.withdraw, event, first.account_id, now=DEADLINE + 4 + n * 2
                    )
                with self.assertRaises(storage.SliceError) as preference:
                    self.command(
                        registration.enroll,
                        event,
                        first.account_id,
                        "independent_reserve",
                        preferred_group_id=group,
                        now=DEADLINE + 4 + n * 2,
                    )
                self.assertEqual(
                    (withdraw.exception.status, preference.exception.status), (409, 409)
                )
                self.assertEqual(
                    self.conn.execute(
                        "SELECT * FROM registration_entry WHERE event_id=? AND player_id=?",
                        (event, first.player_id),
                    ).fetchone(),
                    original,
                )
        saved = formation.get_roster(self.conn, event, entrant)
        self.assertEqual(saved["initial_player_ids"], [p.player_id for p in people[:5]])
        self.assertEqual(
            [row["incoming_player_id"] for row in saved["changes"]],
            [first.player_id, second.player_id],
        )

    def test_confirmation_failure_on_second_roster_final_member_rolls_back_both(self) -> None:
        event_id = self.create_event()
        self.enroll_individuals(event_id, seed_registrants(self.conn, [300] * 10))
        batch = self.command(formation.form_due_event, event_id, now=DEADLINE)
        entrants = batch["entrant_ids"]
        drafts = [formation.get_roster(self.conn, event_id, entrant_id) for entrant_id in entrants]
        self.conn.execute("""CREATE TEMP TRIGGER stop_last_initial_member BEFORE INSERT ON initial_roster_member
          WHEN (SELECT COUNT(*) FROM initial_roster_member)=9
          BEGIN SELECT RAISE(ABORT, 'synthetic final initial member'); END""")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "synthetic final initial member"):
            self.command(
                formation.confirm_initial_rosters,
                event_id,
                entrants,
                expected_revision=batch["formation_revision"],
                admin_id=ORGANIZER_ID,
                now=DEADLINE + 1,
            )
        with closing(sandbox.connect(self.workspace)) as reader:
            self.assertEqual(
                [formation.get_roster(reader, event_id, entrant_id) for entrant_id in entrants],
                drafts,
            )
            self.assertEqual(
                reader.execute("SELECT COUNT(*) FROM initial_roster_member").fetchone()[0], 0
            )
        self.conn.execute("DROP TRIGGER stop_last_initial_member")
        self.command(
            formation.confirm_initial_rosters,
            event_id,
            entrants,
            expected_revision=batch["formation_revision"],
            admin_id=ORGANIZER_ID,
            now=DEADLINE + 2,
        )
        for entrant_id, draft in zip(entrants, drafts, strict=True):
            saved = formation.get_roster(self.conn, event_id, entrant_id)
            self.assertEqual(saved["confirmed_at"], DEADLINE + 2)
            self.assertEqual(saved["initial_player_ids"], draft["current_player_ids"])

    def test_database_rejects_duplicate_members_cross_event_binding_and_frozen_writes(self) -> None:
        event_id = self.create_event()
        other_event = self.create_event("other-event")
        *people, unused = seed_registrants(self.conn, [300] * 11)
        other_group = self.register_group(other_event, "Other event only", [unused])
        self.enroll_individuals(event_id, people)
        batch = self.command(formation.form_due_event, event_id, now=DEADLINE)
        primary, opposing = batch["entrant_ids"]
        self.command(
            formation.confirm_initial_rosters,
            event_id,
            [primary, opposing],
            expected_revision=batch["formation_revision"],
            admin_id=ORGANIZER_ID,
            now=DEADLINE + 1,
        )
        before = formation.get_roster(self.conn, event_id, primary)
        duplicate = formation.get_roster(self.conn, event_id, opposing)["current_player_ids"][0]
        for query, args in (
            (
                "INSERT INTO event_entrant(event_id,registration_group_id) VALUES(?,?)",
                (event_id, other_group),
            ),
            (
                "UPDATE entrant_member SET player_id=? WHERE event_entrant_id=? AND roster_slot=0",
                (duplicate, primary),
            ),
            (
                "UPDATE entrant_member SET event_id=? WHERE event_entrant_id=? AND roster_slot=0",
                (other_event, primary),
            ),
            (
                "INSERT INTO reserve_candidate(event_id,player_id) VALUES(?,?)",
                (event_id, unused.player_id),
            ),
            (
                "UPDATE initial_roster_member SET player_id=? WHERE event_entrant_id=? AND roster_slot=0",
                (unused.player_id, primary),
            ),
            (
                "DELETE FROM initial_roster_member WHERE event_entrant_id=? AND roster_slot=0",
                (primary,),
            ),
            (
                "UPDATE initial_roster SET confirmed_by=? WHERE event_entrant_id=?",
                (SECOND_ORGANIZER_ID, primary),
            ),
        ):
            with (
                self.subTest(query=query),
                self.assertRaises(sqlite3.IntegrityError),
                storage.write(self.conn),
            ):
                self.conn.execute(query, args)
        self.assertEqual(formation.get_roster(self.conn, event_id, primary), before)
        self.assertEqual(list(self.conn.execute("PRAGMA foreign_key_check")), [])

    def test_empty_database_rebuild_and_idempotent_migration_leave_legacy_rows_alone(self) -> None:
        people = seed_registrants(self.conn, [300] * 5)
        old_event_id = self.conn.execute(
            "INSERT INTO events(name) VALUES ('Unmanaged history') RETURNING id"
        ).fetchone()[0]
        self.conn.execute(
            "INSERT INTO event_registrations(id,event_id,team_name,creator_user_id) VALUES(900,?,'Historical team',?)",
            (old_event_id, people[0].account_id),
        )
        self.conn.commit()
        snapshots = {
            table: list(self.conn.execute(f"SELECT * FROM {table}"))
            for table in (
                "event_registrations",
                "event_registration_slots",
                "event_individual_registrations",
            )
        }
        event_id = self.create_event()
        self.assertGreater(self.register_group(event_id, "New competition", people), 900)
        batch = self.command(formation.form_due_event, event_id, now=DEADLINE)
        (entrant_id,) = batch["entrant_ids"]
        self.command(
            formation.confirm_initial_rosters,
            event_id,
            [entrant_id],
            expected_revision=batch["formation_revision"],
            admin_id=ORGANIZER_ID,
            now=DEADLINE + 1,
        )
        retained = formation.get_roster(self.conn, event_id, entrant_id)
        migration = self.conn.execute("SELECT * FROM entrant_schema_migration").fetchall()
        self.assertEqual([row["name"] for row in migration], [sandbox.MIGRATION])
        sandbox.initialize(self.workspace)
        with closing(sandbox.connect(self.workspace)) as reopened:
            self.assertEqual(formation.get_roster(reopened, event_id, entrant_id), retained)
            self.assertEqual(reopened.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(
                reopened.execute("SELECT * FROM entrant_schema_migration").fetchall(), migration
            )
            for table, before in snapshots.items():
                self.assertEqual(list(reopened.execute(f"SELECT * FROM {table}")), before)
        rebuilt = self.workspace.parent / "rebuilt"
        sandbox.initialize(rebuilt)
        sandbox.remove(rebuilt)
        self.assertFalse(rebuilt.exists())
        sandbox.initialize(rebuilt)
        with closing(sandbox.connect(rebuilt)) as empty:
            self.assertEqual(empty.execute("SELECT COUNT(*) FROM event_entrant").fetchone()[0], 0)
            self.assertEqual(empty.execute("SELECT COUNT(*) FROM events").fetchone()[0], 0)
            self.assertEqual(list(empty.execute("PRAGMA foreign_key_check")), [])

    def test_preexisting_unmarked_folder_is_not_opened_claimed_or_removed(self) -> None:
        unmarked = self.workspace.parent / "unmarked"
        unmarked.mkdir()
        sentinel = unmarked / sandbox.DB
        sentinel.write_bytes(b"Synthetic file outside the owned sandbox")
        for action in (sandbox.connect, sandbox.initialize, sandbox.remove):
            with self.subTest(action=action.__name__), self.assertRaises(ValueError):
                action(unmarked)
        self.assertEqual(sentinel.read_bytes(), b"Synthetic file outside the owned sandbox")
        self.assertFalse((unmarked / sandbox.MARKER).exists())
