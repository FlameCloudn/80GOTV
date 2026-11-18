"""Exercise the actual lifecycle against SQLite, with no web or Steam service."""

from __future__ import annotations

import json
import unittest

from entrant_slice import formation, registration, storage
from tests.entrant_slice_fixtures import (
    DEADLINE,
    ORGANIZER_ID,
    REGISTRATION_TIME,
    EntrantSandboxCase,
    seed_registrants,
)


class InitialRosterRuleTests(unittest.TestCase):
    def test_majority_is_against_five_distinct_initial_players_not_last_roster(self) -> None:
        initial = [101, 102, 103, 104, 105]
        legal_replacement = [101, 102, 103, 201, 202]
        would_pass_rolling_majority = [101, 102, 201, 202, 203]
        self.assertTrue(formation.keeps_initial_majority(initial, legal_replacement))
        self.assertTrue(
            formation.keeps_initial_majority(legal_replacement, would_pass_rolling_majority)
        )
        self.assertFalse(formation.keeps_initial_majority(initial, would_pass_rolling_majority))
        self.assertFalse(formation.keeps_initial_majority(initial, [101, 101, 102, 103, 201]))
        self.assertFalse(formation.keeps_initial_majority(initial, initial[:4]))


class RegistrationTests(EntrantSandboxCase):
    def test_one_player_one_application_and_edits_only_before_deadline(self) -> None:
        event_id = self.create_event()
        captain, member, solo, unused, rival_captain = seed_registrants(
            self.conn, [240, 360, 480, None, 600]
        )
        group_id = self.register_group(event_id, "Original entry", [captain, member])
        rival_group = self.register_group(event_id, "Independent group", [rival_captain])
        with self.assertRaises(storage.SliceError):
            self.command(
                registration.join_group,
                event_id,
                rival_group,
                member.account_id,
                1,
                now=DEADLINE - 1,
            )
        with self.assertRaises(storage.SliceError) as denied:
            self.command(
                registration.rename_group,
                event_id,
                group_id,
                member.account_id,
                "Not captain",
                now=DEADLINE - 1,
            )
        self.assertEqual(denied.exception.status, 403)
        self.command(
            registration.rename_group,
            event_id,
            group_id,
            captain.account_id,
            "Updated entry",
            now=DEADLINE - 1,
        )
        self.enroll_individuals(event_id, [solo])
        with self.assertRaises(storage.SliceError):
            self.command(
                registration.join_group, event_id, group_id, solo.account_id, 2, now=DEADLINE - 1
            )
        with self.assertRaises(storage.SliceError):
            self.command(
                registration.enroll, event_id, member.account_id, "individual", now=DEADLINE - 1
            )

        self.command(registration.withdraw, event_id, member.account_id, now=DEADLINE - 1)
        self.command(
            registration.enroll, event_id, member.account_id, "individual", now=DEADLINE - 1
        )
        for description, write in (
            (
                "join",
                lambda: self.command(
                    registration.join_group, event_id, group_id, unused.account_id, 1, now=DEADLINE
                ),
            ),
            (
                "new group",
                lambda: self.command(
                    registration.create_group, event_id, unused.account_id, "Too late", now=DEADLINE
                ),
            ),
            (
                "rename",
                lambda: self.command(
                    registration.rename_group,
                    event_id,
                    group_id,
                    captain.account_id,
                    "Too late",
                    now=DEADLINE,
                ),
            ),
            (
                "withdraw",
                lambda: self.command(
                    registration.withdraw, event_id, solo.account_id, now=DEADLINE
                ),
            ),
            (
                "solo",
                lambda: self.command(
                    registration.enroll, event_id, unused.account_id, "individual", now=DEADLINE
                ),
            ),
        ):
            with (
                self.subTest(description=description),
                self.assertRaises(storage.SliceError) as denied,
            ):
                write()
            self.assertEqual(denied.exception.status, 409)

        self.command(
            registration.enroll,
            event_id,
            unused.account_id,
            "independent_reserve",
            now=DEADLINE + 1,
        )

    def test_pending_account_and_mismatched_reservation_cannot_claim_a_slot(self) -> None:
        event_id = self.create_event()
        captain, reserved, stranger, pending = seed_registrants(self.conn, [600, 300, 300, 250])
        self.conn.execute(
            "UPDATE users SET approval_status='pending' WHERE id=?", (pending.account_id,)
        )
        self.conn.commit()
        group_id = self.command(
            registration.create_group,
            event_id,
            captain.account_id,
            "Reserved seats",
            reservations={1: ("Expected Steam user", reserved.steam_id), 2: ("Name only", "")},
            now=REGISTRATION_TIME,
        )
        for person, slot in ((stranger, 1), (stranger, 2), (pending, 3)):
            with self.subTest(slot=slot), self.assertRaises(storage.SliceError):
                self.command(
                    registration.join_group,
                    event_id,
                    group_id,
                    person.account_id,
                    slot,
                    now=REGISTRATION_TIME,
                )
        self.command(
            registration.join_group,
            event_id,
            group_id,
            reserved.account_id,
            1,
            now=REGISTRATION_TIME,
        )
        self.command(
            registration.enroll, event_id, stranger.account_id, "individual", now=REGISTRATION_TIME
        )
        claimed = self.conn.execute(
            "SELECT account_id,player_id FROM registration_entry WHERE registration_group_id=? AND roster_slot=1",
            (group_id,),
        ).fetchone()
        self.assertEqual(tuple(claimed), (reserved.account_id, reserved.player_id))

    def test_same_steam_identity_does_not_gain_a_second_slot_via_another_account(self) -> None:
        event_id = self.create_event()
        captain, alias = seed_registrants(self.conn, [600, 600])
        self.register_group(event_id, "Single membership", [captain])
        self.conn.execute(
            "UPDATE users SET steam_id64=? WHERE id=?", (captain.steam_id, alias.account_id)
        )
        self.conn.commit()
        with self.assertRaises(storage.SliceError):
            self.command(
                registration.enroll, event_id, alias.account_id, "individual", now=REGISTRATION_TIME
            )

    def test_dissolved_group_number_is_not_reused_for_legacy_consumers(self) -> None:
        event_id = self.create_event()
        retained, departing, arrival = seed_registrants(self.conn, [300] * 3)
        retained_group = self.register_group(event_id, "Retained group", [retained])
        removed_group = self.register_group(event_id, "Departing group", [departing])
        self.command(
            registration.manage_group,
            event_id,
            removed_group,
            departing.account_id,
            "dissolve",
            now=DEADLINE - 2,
        )
        arrival_group = self.command(
            registration.create_group,
            event_id,
            arrival.account_id,
            "Replacement group",
            now=DEADLINE - 1,
        )
        self.assertGreater(removed_group, retained_group)
        self.assertGreater(arrival_group, removed_group)
        self.assertEqual(
            [
                row[0]
                for row in self.conn.execute(
                    "SELECT registration_group_id FROM registration_group ORDER BY registration_group_id"
                )
            ],
            [retained_group, arrival_group],
        )


class FormationTests(EntrantSandboxCase):
    def test_three_confirmed_and_eight_solo_entries_fill_one_group_and_create_one(self) -> None:
        event_id = self.create_event()
        playtimes = [300, 300, 300, 600, 300, 300, 300, 0, 300, 300, 9_000]
        people = seed_registrants(self.conn, playtimes)
        fixed, solo = people[:3], people[3:]
        minutes = dict(zip((person.player_id for person in people), playtimes, strict=True))
        group_id = self.register_group(event_id, "Known three", fixed)
        self.enroll_individuals(event_id, solo)
        independent = seed_registrants(self.conn, [20_000])[0]
        self.command(
            registration.enroll,
            event_id,
            independent.account_id,
            "independent_reserve",
            now=REGISTRATION_TIME,
        )
        with self.assertRaises(storage.SliceError):
            self.command(formation.form_due_event, event_id, now=DEADLINE - 1)
        batch = self.command(formation.form_due_event, event_id, now=DEADLINE)
        self.assertEqual(batch["formed_at"], DEADLINE)
        self.assertEqual(len(batch["entrant_ids"]), 2)
        drafts = [
            formation.get_roster(self.conn, event_id, entrant_id)
            for entrant_id in batch["entrant_ids"]
        ]
        fixed_draft = next(draft for draft in drafts if draft["registration_group_id"] == group_id)
        self.assertLessEqual(
            {person.player_id for person in fixed}, set(fixed_draft["current_player_ids"])
        )
        for draft in drafts:
            self.assertFalse(draft["is_frozen"])
            self.assertEqual(draft["initial_player_ids"], [])
            self.assertEqual(len(set(draft["current_player_ids"])), 5)
            self.assertEqual(
                sum(minutes[player_id] for player_id in draft["current_player_ids"]), 1_500
            )
        self.assertCountEqual(
            [player_id for draft in drafts for player_id in draft["current_player_ids"]],
            [person.player_id for person in [*fixed, *solo[:-1]]],
        )
        self.assertEqual(self.command(formation.form_due_event, event_id, now=DEADLINE + 60), batch)

    def test_complete_group_and_multiple_generated_groups_use_distinct_members(self) -> None:
        event_id = self.create_event()
        people = seed_registrants(self.conn, [None] * 16)
        full_group, solo = people[:5], people[5:]
        group_id = self.register_group(event_id, "Complete five", full_group)
        self.enroll_individuals(event_id, solo)
        batch = self.command(formation.form_due_event, event_id, now=DEADLINE)
        self.assertEqual(len(batch["entrant_ids"]), 3)
        drafts = [
            formation.get_roster(self.conn, event_id, entrant_id)
            for entrant_id in batch["entrant_ids"]
        ]
        full_draft = next(draft for draft in drafts if draft["registration_group_id"] == group_id)
        self.assertCountEqual(
            full_draft["current_player_ids"], [player.player_id for player in full_group]
        )
        self.assertCountEqual(
            [player_id for draft in drafts for player_id in draft["current_player_ids"]],
            [person.player_id for person in people[:-1]],
        )

    def test_four_solo_people_become_reserves_without_a_phantom_team(self) -> None:
        solo_only = self.create_event()
        people = seed_registrants(self.conn, [300] * 4)
        self.enroll_individuals(solo_only, people)
        batch = self.command(formation.form_due_event, solo_only, now=DEADLINE)
        self.assertEqual(batch["entrant_ids"], [])
        candidates = [
            row[0]
            for row in self.conn.execute(
                "SELECT player_id FROM reserve_candidate WHERE event_id=?", (solo_only,)
            )
        ]
        self.assertCountEqual(candidates, [person.player_id for person in people])

    def test_unclaimed_named_seat_or_shortfall_rejects_a_partial_group(self) -> None:
        reserved_event = self.create_event("reserved-cup")
        shortfall = self.create_event("shortfall-cup")
        people = seed_registrants(self.conn, [300] * 11)
        self.command(
            registration.create_group,
            reserved_event,
            people[0].account_id,
            "Needs named member",
            reservations={1: ("Absent registrant", people[1].steam_id)},
            now=REGISTRATION_TIME,
        )
        self.enroll_individuals(reserved_event, people[2:])
        self.register_group(shortfall, "Needs two", people[:3])
        self.enroll_individuals(shortfall, people[3:4])
        for event_id in (reserved_event, shortfall):
            for time in (DEADLINE, DEADLINE + 60):
                with (
                    self.subTest(event_id=event_id, time=time),
                    self.assertRaises(storage.SliceError),
                ):
                    self.command(formation.form_due_event, event_id, now=time)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM event_entrant").fetchone()[0], 0)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM initial_roster_member").fetchone()[0], 0
        )

    def test_review_after_failed_cutoff_can_only_confirm_the_original_reserved_identity(
        self,
    ) -> None:
        event_id = self.create_event()
        captain, opener, anchor, reserved, suitable_solo, late_arrival = seed_registrants(
            self.conn, [300] * 6
        )
        group_id = self.register_group(
            event_id, "Three and a reservation", [captain, opener, anchor]
        )
        self.command(
            registration.set_reservation,
            event_id,
            group_id,
            captain.account_id,
            3,
            "Unverified reserved player",
            reserved.steam_id,
            now=DEADLINE - 1,
        )
        self.enroll_individuals(event_id, [suitable_solo])
        with self.assertRaises(storage.SliceError):
            self.command(formation.form_due_event, event_id, now=DEADLINE)
        with self.assertRaises(storage.SliceError):
            self.command(
                registration.join_group,
                event_id,
                group_id,
                reserved.account_id,
                3,
                now=DEADLINE + 1,
            )
        for slot, person, administrator, time in (
            (3, reserved, ORGANIZER_ID, DEADLINE - 1),
            (3, reserved, captain.account_id, DEADLINE + 1),
            (3, late_arrival, ORGANIZER_ID, DEADLINE + 1),
            (4, late_arrival, ORGANIZER_ID, DEADLINE + 1),
        ):
            with (
                self.subTest(slot=slot, administrator=administrator),
                self.assertRaises(storage.SliceError),
            ):
                self.command(
                    registration.review_reservation,
                    event_id,
                    group_id,
                    slot,
                    person.account_id,
                    admin_id=administrator,
                    reason="Check original identity",
                    now=time,
                )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM reservation_review").fetchone()[0], 0
        )
        self.command(
            registration.review_reservation,
            event_id,
            group_id,
            3,
            reserved.account_id,
            admin_id=ORGANIZER_ID,
            reason="Checked the Steam identity saved before cutoff",
            now=DEADLINE + 2,
        )
        batch = self.command(formation.form_due_event, event_id, now=DEADLINE + 3)
        self.assertEqual(self.command(formation.form_due_event, event_id, now=DEADLINE + 4), batch)
        (entrant_id,) = batch["entrant_ids"]
        roster = formation.get_roster(self.conn, event_id, entrant_id)
        self.assertFalse(roster["is_frozen"])
        self.assertCountEqual(
            roster["current_player_ids"],
            [person.player_id for person in (captain, opener, anchor, reserved, suitable_solo)],
        )
        self.assertEqual(
            [
                tuple(row)
                for row in self.conn.execute("""SELECT original_steam_id,verified_player_id,reviewed_by,reviewed_at,reason
                FROM reservation_review""")
            ],
            [
                (
                    reserved.steam_id,
                    reserved.player_id,
                    ORGANIZER_ID,
                    DEADLINE + 2,
                    "Checked the Steam identity saved before cutoff",
                )
            ],
        )

    def test_admin_adjusts_whole_draft_at_expected_revision_before_freezing(self) -> None:
        event_id = self.create_event()
        people = seed_registrants(self.conn, [500] * 10)
        self.enroll_individuals(event_id, people)
        batch = self.command(formation.form_due_event, event_id, now=DEADLINE)
        harbor, copper = batch["entrant_ids"]
        harbor_players = formation.get_roster(self.conn, event_id, harbor)["current_player_ids"]
        copper_players = formation.get_roster(self.conn, event_id, copper)["current_player_ids"]
        revised = {
            harbor: [copper_players[0], *harbor_players[1:]],
            copper: [harbor_players[0], *copper_players[1:]],
        }
        with self.assertRaises(storage.SliceError):
            self.command(
                formation.adjust_formation,
                event_id,
                {harbor: revised[harbor]},
                expected_revision=batch["formation_revision"],
                admin_id=ORGANIZER_ID,
                reason="Would put one player in both teams",
                now=DEADLINE + 1,
            )
        self.assertEqual(
            formation.get_roster(self.conn, event_id, harbor)["current_player_ids"], harbor_players
        )
        adjusted = self.command(
            formation.adjust_formation,
            event_id,
            revised,
            expected_revision=batch["formation_revision"],
            admin_id=ORGANIZER_ID,
            reason="Both teams agreed to exchange draft positions",
            now=DEADLINE + 2,
        )
        with self.assertRaises(storage.SliceError) as stale:
            self.command(
                formation.confirm_initial_rosters,
                event_id,
                [harbor, copper],
                expected_revision=batch["formation_revision"],
                admin_id=ORGANIZER_ID,
                now=DEADLINE + 3,
            )
        self.assertEqual(stale.exception.status, 409)
        self.command(
            formation.confirm_initial_rosters,
            event_id,
            [harbor, copper],
            expected_revision=adjusted["formation_revision"],
            admin_id=ORGANIZER_ID,
            now=DEADLINE + 4,
        )
        for entrant_id, player_ids in revised.items():
            frozen = formation.get_roster(self.conn, event_id, entrant_id)
            self.assertCountEqual(frozen["initial_player_ids"], player_ids)
            self.assertEqual(frozen["confirmed_by"], ORGANIZER_ID)

    def test_same_level_requires_admin_choice_and_independent_has_priority_over_remainder(
        self,
    ) -> None:
        event_id = self.create_event()
        captain, opener, anchor, first_solo, second_solo, remainder, earlier, chosen = (
            seed_registrants(
                self.conn,
                [300] * 8,
            )
        )
        group_id = self.register_group(event_id, "Needs two", [captain, opener, anchor])
        self.enroll_individuals(event_id, [first_solo, second_solo, remainder])
        for offset, reserve in enumerate((earlier, chosen)):
            self.command(
                registration.enroll,
                event_id,
                reserve.account_id,
                "independent_reserve",
                preferred_group_id=group_id,
                now=REGISTRATION_TIME + offset,
            )
        batch = self.command(formation.form_due_event, event_id, now=DEADLINE)
        (entrant_id,) = batch["entrant_ids"]
        revision = batch["formation_revision"]
        self.command(
            registration.enroll,
            event_id,
            remainder.account_id,
            "independent_reserve",
            preferred_group_id=group_id,
            now=DEADLINE + 1,
        )
        with self.assertRaises(storage.SliceError):
            self.command(
                formation.assign_reserve,
                event_id,
                entrant_id,
                remainder.player_id,
                expected_revision=revision,
                admin_id=ORGANIZER_ID,
                reason="Choose remainder without checking other candidates",
                now=DEADLINE + 1,
            )
        with self.assertRaises(storage.SliceError):
            self.command(
                formation.assign_reserve,
                event_id,
                entrant_id,
                chosen.player_id,
                expected_revision=revision,
                admin_id=ORGANIZER_ID,
                reason="",
                now=DEADLINE + 2,
            )
        assigned = self.command(
            formation.assign_reserve,
            event_id,
            entrant_id,
            chosen.player_id,
            expected_revision=revision,
            admin_id=ORGANIZER_ID,
            reason="Same priority; this candidate agreed to the time",
            now=DEADLINE + 3,
        )
        self.command(
            formation.assign_reserve,
            event_id,
            entrant_id,
            remainder.player_id,
            expected_revision=assigned["formation_revision"],
            admin_id=ORGANIZER_ID,
            reason="The remaining independent candidate declined",
            excluded_candidates={earlier.player_id: "Cannot attend this team's scheduled match"},
            now=DEADLINE + 4,
        )
        records = list(
            self.conn.execute(
                "SELECT admin_id, reason, after_json FROM formation_action WHERE event_entrant_id=? ORDER BY changed_at",
                (entrant_id,),
            )
        )
        reserve_actions = [
            (row["admin_id"], row["reason"], json.loads(row["after_json"])) for row in records
        ]
        self.assertEqual(
            [record[2]["player_id"] for record in reserve_actions],
            [chosen.player_id, remainder.player_id],
        )
        self.assertEqual(
            reserve_actions[0][:2],
            (ORGANIZER_ID, "Same priority; this candidate agreed to the time"),
        )
        self.assertEqual(
            reserve_actions[-1][2]["excluded_candidates"],
            {str(earlier.player_id): "Cannot attend this team's scheduled match"},
        )
        self.assertCountEqual(
            formation.get_roster(self.conn, event_id, entrant_id)["current_player_ids"],
            [person.player_id for person in (captain, opener, anchor, first_solo, second_solo)],
        )


class EntrantHistoryTests(EntrantSandboxCase):
    def test_organization_and_temporary_entries_keep_distinct_history_across_editions(self) -> None:
        first_event = self.create_event("previous-edition")
        next_event = self.create_event("following-edition")
        club_id = self.conn.execute(
            "INSERT INTO teams (name) VALUES ('Existing club') RETURNING id"
        ).fetchone()[0]
        self.conn.commit()
        *people, unused = seed_registrants(self.conn, [300] * 6)
        group_id = self.register_group(first_event, "Same public name", people)
        self.command(
            registration.link_club,
            first_event,
            group_id,
            club_id,
            admin_id=ORGANIZER_ID,
            now=REGISTRATION_TIME,
        )
        self.register_group(next_event, "Same public name", people)
        first = self.command(formation.form_due_event, first_event, now=DEADLINE)
        following = self.command(formation.form_due_event, next_event, now=DEADLINE)
        (first_entrant,) = first["entrant_ids"]
        (next_entrant,) = following["entrant_ids"]
        self.assertNotEqual(first_entrant, next_entrant)
        for event_id, entrant_id, batch in (
            (first_event, first_entrant, first),
            (next_event, next_entrant, following),
        ):
            self.command(
                formation.confirm_initial_rosters,
                event_id,
                [entrant_id],
                expected_revision=batch["formation_revision"],
                admin_id=ORGANIZER_ID,
                now=DEADLINE + 1,
            )
        self.assertEqual(
            [
                tuple(row)
                for row in self.conn.execute("""SELECT e.event_id, g.club_id FROM event_entrant e
                JOIN registration_group g USING(registration_group_id) ORDER BY e.event_id""")
            ],
            [(first_event, club_id), (next_event, None)],
        )
        self.command(
            registration.archive_event, next_event, admin_id=ORGANIZER_ID, now=DEADLINE + 2
        )
        with self.assertRaises(storage.SliceError):
            self.command(
                registration.enroll,
                next_event,
                unused.account_id,
                "independent_reserve",
                now=DEADLINE + 3,
            )
        with self.assertRaises(storage.SliceError):
            formation.get_roster(self.conn, first_event, next_entrant)
        for event_id, entrant_id in ((first_event, first_entrant), (next_event, next_entrant)):
            historical = formation.get_roster(self.conn, event_id, entrant_id)
            self.assertTrue(historical["is_frozen"])
            self.assertCountEqual(
                historical["initial_player_ids"], [person.player_id for person in people]
            )
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM player_medals").fetchone()[0], 0)

    def test_repeat_confirmation_and_later_replacements_never_rewrite_initial_five(self) -> None:
        event_id = self.create_event()
        people = seed_registrants(self.conn, [300] * 8)
        starting, reserves = people[:5], people[5:]
        self.register_group(event_id, "Stable identity", starting)
        batch = self.command(formation.form_due_event, event_id, now=DEADLINE)
        (entrant_id,) = batch["entrant_ids"]
        with self.assertRaises(storage.SliceError) as unauthorized:
            self.command(
                formation.confirm_initial_rosters,
                event_id,
                [entrant_id],
                expected_revision=batch["formation_revision"],
                admin_id=starting[0].account_id,
                now=DEADLINE + 1,
            )
        self.assertEqual(unauthorized.exception.status, 403)
        self.assertFalse(formation.get_roster(self.conn, event_id, entrant_id)["is_frozen"])
        confirmed = self.command(
            formation.confirm_initial_rosters,
            event_id,
            [entrant_id],
            expected_revision=batch["formation_revision"],
            admin_id=ORGANIZER_ID,
            now=DEADLINE + 1,
        )
        original = formation.get_roster(self.conn, event_id, entrant_id)
        self.assertTrue(original["is_frozen"])
        self.assertEqual(original["confirmed_at"], DEADLINE + 1)
        self.assertEqual(original["confirmed_by"], ORGANIZER_ID)
        self.assertCountEqual(
            original["initial_player_ids"], [person.player_id for person in starting]
        )
        repeated = self.command(
            formation.confirm_initial_rosters,
            event_id,
            [entrant_id],
            expected_revision=batch["formation_revision"],
            admin_id=ORGANIZER_ID,
            now=DEADLINE + 50,
        )
        self.assertEqual(repeated, confirmed)
        self.assertEqual(formation.get_roster(self.conn, event_id, entrant_id), original)

        for reserve in reserves:
            self.command(
                registration.enroll,
                event_id,
                reserve.account_id,
                "independent_reserve",
                now=DEADLINE + 2,
            )
        revision = formation.get_roster(self.conn, event_id, entrant_id)["formation_revision"]
        with self.assertRaises(storage.SliceError):
            self.command(
                formation.adjust_formation,
                event_id,
                {entrant_id: original["initial_player_ids"]},
                expected_revision=revision,
                admin_id=ORGANIZER_ID,
                reason="Cannot overwrite initial five",
                now=DEADLINE + 2,
            )
        with self.assertRaises(storage.SliceError):
            self.command(
                formation.replace_before_series,
                event_id,
                entrant_id,
                starting[3].player_id,
                reserves[0].player_id,
                expected_revision=revision,
                admin_id=ORGANIZER_ID,
                reason="Not assigned to this team yet",
                now=DEADLINE + 2,
            )
        for reserve in reserves:
            result = self.command(
                formation.assign_reserve,
                event_id,
                entrant_id,
                reserve.player_id,
                expected_revision=revision,
                admin_id=ORGANIZER_ID,
                reason="Attending reserve pool",
                now=DEADLINE + 3,
            )
            revision = result["formation_revision"]
        with self.assertRaises(storage.SliceError) as denied:
            self.command(
                formation.replace_before_series,
                event_id,
                entrant_id,
                starting[4].player_id,
                reserves[0].player_id,
                expected_revision=revision,
                admin_id=starting[0].account_id,
                reason="Not an organizer",
                now=DEADLINE + 4,
            )
        self.assertEqual(denied.exception.status, 403)
        for offset, (outgoing, incoming) in enumerate(
            zip(starting[3:], reserves[:2], strict=True), start=5
        ):
            changed = self.command(
                formation.replace_before_series,
                event_id,
                entrant_id,
                outgoing.player_id,
                incoming.player_id,
                expected_revision=revision,
                admin_id=ORGANIZER_ID,
                reason="Approved pre-series substitute",
                now=DEADLINE + offset,
            )
            revision = changed["formation_revision"]
        history = formation.get_roster(self.conn, event_id, entrant_id)
        with self.assertRaises(storage.SliceError):
            self.command(
                formation.replace_before_series,
                event_id,
                entrant_id,
                starting[2].player_id,
                reserves[2].player_id,
                expected_revision=revision,
                admin_id=ORGANIZER_ID,
                reason="Would leave only two originals",
                now=DEADLINE + 7,
            )
        self.assertEqual(formation.get_roster(self.conn, event_id, entrant_id), history)
        self.assertEqual(history["initial_player_ids"], original["initial_player_ids"])
        self.assertCountEqual(
            history["current_player_ids"],
            [person.player_id for person in [*starting[:3], *reserves[:2]]],
        )
        self.assertEqual(
            history["changes"],
            [
                {
                    "outgoing_player_id": outgoing.player_id,
                    "incoming_player_id": incoming.player_id,
                    "admin_id": ORGANIZER_ID,
                    "reason": "Approved pre-series substitute",
                    "changed_at": DEADLINE + offset,
                }
                for offset, (outgoing, incoming) in enumerate(
                    zip(starting[3:], reserves[:2], strict=True), start=5
                )
            ],
        )
        self.conn.execute("INSERT INTO matches(event_id,status) VALUES(?, 'live')", (event_id,))
        self.conn.commit()
        with self.assertRaises(storage.SliceError):
            self.command(
                formation.replace_before_series,
                event_id,
                entrant_id,
                reserves[0].player_id,
                reserves[2].player_id,
                expected_revision=revision,
                admin_id=ORGANIZER_ID,
                reason="Must not replace during live play",
                now=DEADLINE + 8,
            )
        self.assertEqual(formation.get_roster(self.conn, event_id, entrant_id), history)
