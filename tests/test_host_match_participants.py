"""原 Flask 后台的固定对阵和本场名单，只使用合成参赛数据。"""

import sqlite3

from services.match_roster_service import (
    freeze_match_roster,
    managed_match_teams,
    match_registration,
    resolve_match_roster,
)
from site_core.events import public as events
from site_core.events.registration import (
    archive_event,
    create_group,
    enable_event,
    enroll,
    join_group,
    link_club,
)
from site_core.host import write
from site_core.matches.participants import rosters_frozen, sides
from tests.test_pro_logic_regressions import ProDatabaseCase


class HostMatchParticipantTests(ProDatabaseCase):
    NOW = 1893456000
    TOKEN = "pro-logic-csrf"

    def _new_event(self, *, club_ids=(None, None), confirm=True, reserve=False):
        with write(self.conn):
            event_id = self.conn.execute(
                "INSERT INTO events(name,short_name) VALUES('Host Cup','HC')"
            ).lastrowid
            assert event_id is not None
            enable_event(self.conn, event_id, self.NOW + 60, admin_id=1, now=self.NOW)
            groups, members = [], []
            for side in range(2):
                member_ids = []
                for slot in range(5):
                    user_id, player_id = self._add_identity(event_id, side * 5 + slot)
                    member_ids.append(player_id)
                    if slot == 0:
                        group = create_group(
                            self.conn, event_id, user_id, f"Host Team {side + 1}", now=self.NOW
                        )
                        groups.append(group)
                    else:
                        join_group(self.conn, event_id, group, user_id, slot, now=self.NOW)
                members.append(member_ids)
            for group, club_id in zip(groups, club_ids):
                if club_id is not None:
                    link_club(self.conn, event_id, group, club_id, admin_id=1, now=self.NOW)
            reserve_id = None
            if reserve:
                account_id, reserve_id = self._add_identity(event_id, 10)
                enroll(self.conn, event_id, account_id, "independent_reserve", now=self.NOW)
            batch = events.form_due_event(self.conn, event_id, now=self.NOW + 60)
            ids = dict(
                self.conn.execute(
                    "SELECT registration_id,event_entrant_id FROM event_entrants WHERE event_id=?",
                    (event_id,),
                ).fetchall()
            )
            entrants = [ids[group] for group in groups]
            if confirm:
                batch = events.confirm_initial_rosters(
                    self.conn,
                    event_id,
                    entrants,
                    expected_revision=batch["formation_revision"],
                    admin_id=1,
                    now=self.NOW + 61,
                )
        return event_id, entrants, groups, members, reserve_id, batch["formation_revision"]

    def _add_identity(self, event_id, index):
        nickname = f"Host player {event_id}-{index}"
        steam_id = str(76561199000000000 + event_id * 100 + index)
        player_id = self.conn.execute(
            "INSERT INTO players(nickname,steam_id) VALUES(?,?)", (nickname, steam_id)
        ).lastrowid
        account_id = self.conn.execute(
            """INSERT INTO users(username,password_hash,steam_id64,group_username,approval_status)
               VALUES(?,'fixture',?,?,'approved')""",
            (nickname, steam_id, nickname),
        ).lastrowid
        assert account_id is not None and player_id is not None
        return account_id, player_id

    def _create(self, event_id, sides_payload, **fields):
        return self.client.post(
            "/admin/matches/add",
            data={
                "csrf_token": self.TOKEN,
                "event_id": event_id,
                "match_time": "2030-01-01T18:00",
                "bo_format": "BO3",
                "map1": "de_mirage",
                **sides_payload,
                **fields,
            },
        )

    def _by_entrants(self, entrants):
        return {
            f"side{side}_{field}": value
            for side, entrant in enumerate(entrants, 1)
            for field, value in (("type", "entrant"), ("id", entrant))
        }

    def _by_players(self, members):
        return {
            **{f"side{side}_type": "players" for side in (1, 2)},
            **{
                f"side{side}_p{slot}": player_id
                for side, players in enumerate(members, 1)
                for slot, player_id in enumerate(players)
            },
        }

    def _match(self, event_id):
        return self.conn.execute(
            "SELECT * FROM matches WHERE event_id=? ORDER BY id DESC LIMIT 1", (event_id,)
        ).fetchone()

    def _post(self, path, **values):
        return self.client.post(path, data={"csrf_token": self.TOKEN, **values})

    def test_existing_form_binds_two_temporary_teams_without_second_store(self):
        event_id, entrants, groups, members, _, _ = self._new_event()
        response = self._create(event_id, self._by_players([members[0][::-1], members[1]]))
        self.assertEqual(response.status_code, 302)
        match = self._match(event_id)
        self.assertTrue(match["slug"])
        self.assertIsNone(match["map1"])
        for side in (1, 2):
            for field in ("id", "players", "registration_id"):
                self.assertIsNone(match[f"team{side}_{field}"])
        self.assertIsNone(match["roster_snapshot"])

        roster = resolve_match_roster(self.conn, match)
        self.assertFalse(roster["locked"])
        groups_view = managed_match_teams(self.conn, match)
        assert groups_view is not None
        for side, key in enumerate(("home", "away"), 1):
            self.assertEqual(groups_view[str(side)]["side_key"], key)
            self.assertEqual(groups_view[str(side)]["event_entrant_id"], entrants[side - 1])
            registration = match_registration(self.conn, match, side)
            assert registration is not None
            self.assertEqual(registration["id"], groups[side - 1])
            self.assertEqual([p["id"] for p in roster["players"][side]], members[side - 1])
            self.assertEqual([p["slot"] for p in roster["players"][side]], [1, 2, 3, 4, 5])

        freeze_path = f"/admin/matches/{match['id']}/freeze-rosters"
        self.assertEqual(self.client.get(freeze_path).status_code, 405)
        self.client.post(freeze_path)
        self._user_client().post(freeze_path, data={"csrf_token": self.TOKEN})
        self.assertFalse(rosters_frozen(self.conn, match["id"]))
        self.assertEqual(self._post(freeze_path).status_code, 302)
        before = [tuple(row) for row in self.conn.execute("SELECT * FROM match_rosters")]
        self.assertEqual(self._post(freeze_path).status_code, 302)
        self.assertEqual(
            before, [tuple(row) for row in self.conn.execute("SELECT * FROM match_rosters")]
        )
        self.assertTrue(resolve_match_roster(self.conn, match)["locked"])
        with write(self.conn):
            self.assertFalse(freeze_match_roster(self.conn, match, force=True, confirmed=True))
        self.assertIsNone(self._match(event_id)["roster_snapshot"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0], 4)

    def test_cross_event_unconfirmed_and_reversed_duplicates_are_rejected(self):
        event_id, entrants, _, _, _, _ = self._new_event()
        _, outside, _, _, _, _ = self._new_event()
        self.assertEqual(
            self._create(event_id, self._by_entrants([entrants[0], outside[1]])).status_code, 409
        )
        self.assertIsNone(self._match(event_id))
        unconfirmed_id, unconfirmed, _, _, _, _ = self._new_event(confirm=False)
        self.assertEqual(
            self._create(unconfirmed_id, self._by_entrants(unconfirmed)).status_code, 409
        )
        self.assertIsNone(self._match(unconfirmed_id))
        self.assertEqual(self._create(event_id, self._by_entrants(entrants)).status_code, 302)
        self.assertEqual(
            self._create(
                event_id, self._by_entrants(entrants[::-1]), match_time="2030-01-01 18:00:00"
            ).status_code,
            409,
        )
        match = self._match(event_id)
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM matches WHERE event_id=?", (event_id,)
            ).fetchone()[0],
            1,
        )
        with self.assertRaises(sqlite3.IntegrityError), write(self.conn):
            self.conn.execute(
                "UPDATE match_participants SET event_entrant_id=? WHERE match_id=? AND side_key='home'",
                (outside[0], match["id"]),
            )
        self.assertEqual(sides(self.conn, match["id"])[1]["event_entrant_id"], entrants[0])
        self.assertEqual(self.conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_mixed_team_form_edits_metadata_but_cannot_swap_or_write_results(self):
        club_id = self.team_ids[2]
        event_id, entrants, _, members, _, _ = self._new_event(club_ids=(None, club_id))
        self.assertEqual(
            self._create(
                event_id,
                {
                    **self._by_players(members),
                    "side2_type": "team",
                    "side2_id": club_id,
                },
            ).status_code,
            302,
        )
        match = self._match(event_id)
        match_id, previous_slug = match["id"], match["slug"]
        edit = f"/admin/matches/edit/{match_id}"
        self.assertEqual(self.client.get(edit).status_code, 200)
        self.assertEqual(self._post(edit, **self._by_entrants(entrants[::-1])).status_code, 409)
        self.assertEqual(self._post(edit, event_id=self.other_event_id).status_code, 409)
        self.assertEqual(self._post(edit, team1_score=2).status_code, 409)
        self.assertEqual(self._post(edit, status="live").status_code, 409)
        self.assertEqual(self._post(edit, status="completed").status_code, 409)
        for path in (
            f"/admin/matches/delete/{match_id}",
            f"/admin/matches/{match_id}/complete",
            f"/admin/matches/{match_id}/reopen",
            f"/admin/matches/{match_id}/stats",
            f"/admin/matches/{match_id}/import-demo",
        ):
            self.assertEqual(self._post(path).status_code, 409, path)
        self.assertEqual(
            self._post(
                edit, match_time="2030-01-02T19:15", map1="de_nuke", freeze_rosters="1"
            ).status_code,
            302,
        )
        match = self._match(event_id)
        self.assertEqual(match["status"], "upcoming")
        self.assertEqual((match["team1_score"], match["team2_score"]), (0, 0))
        self.assertIsNone(match["team2_id"])
        self.assertIsNone(match["map1"])
        self.assertNotEqual(match["slug"], previous_slug)
        self.assertEqual(
            self.conn.execute(
                "SELECT match_id FROM match_slug_aliases WHERE slug=?", (previous_slug,)
            ).fetchone()[0],
            match_id,
        )
        fixed = sides(self.conn, match_id)
        self.assertIsNone(fixed[1]["team_id"])
        self.assertEqual(fixed[2]["team_id"], club_id)
        self.assertTrue(rosters_frozen(self.conn, match_id))
        self.assertEqual(
            self.conn.execute(
                "SELECT map_name FROM scheduled_maps WHERE match_id=? AND legacy_slot=1",
                (match_id,),
            ).fetchone()[0],
            "de_nuke",
        )

    def test_approved_current_change_affects_only_the_next_frozen_match(self):
        event_id, entrants, _, members, reserve, revision = self._new_event(reserve=True)
        self.assertEqual(self._create(event_id, self._by_entrants(entrants)).status_code, 302)
        first = self._match(event_id)["id"]
        self.assertEqual(self._post(f"/admin/matches/{first}/freeze-rosters").status_code, 302)
        with write(self.conn):
            batch = events.assign_reserve(
                self.conn,
                event_id,
                entrants[0],
                reserve,
                expected_revision=revision,
                admin_id=1,
                reason="后续场次替补席确认",
                now=self.NOW + 62,
            )
            events.replace_before_series(
                self.conn,
                event_id,
                entrants[0],
                members[0][0],
                reserve,
                expected_revision=batch["formation_revision"],
                admin_id=1,
                reason="替补只用于尚未确认的场次",
                now=self.NOW + 63,
            )
        current = events.roster(self.conn, event_id, entrants[0])
        self.assertEqual(current["initial_player_ids"], members[0])
        self.assertEqual(current["current_player_ids"], [reserve, *members[0][1:]])
        self.assertEqual([p["id"] for p in sides(self.conn, first)[1]["players"]], members[0])
        self.assertEqual(
            self._create(
                event_id, self._by_entrants(entrants), match_time="2030-01-01T19:30"
            ).status_code,
            302,
        )
        second = self._match(event_id)["id"]
        self.assertEqual(self._post(f"/admin/matches/{second}/freeze-rosters").status_code, 302)
        home = sides(self.conn, second)[1]
        self.assertNotEqual(
            home["match_participant_id"], sides(self.conn, first)[1]["match_participant_id"]
        )
        self.assertEqual([p["id"] for p in home["players"]], [reserve, *members[0][1:]])
        self.assertTrue(home["players"][0]["is_substitute"])

    def test_freeze_with_bad_evidence_never_leaves_one_side_frozen(self):
        event_id, entrants, _, members, _, _ = self._new_event()
        self.assertEqual(self._create(event_id, self._by_entrants(entrants)).status_code, 302)
        match_id = self._match(event_id)["id"]
        with write(self.conn):
            self.conn.execute("UPDATE players SET steam_id=NULL WHERE id=?", (members[1][-1],))
        self.assertEqual(self._post(f"/admin/matches/{match_id}/freeze-rosters").status_code, 409)
        for table in ("match_rosters", "match_roster_members"):
            self.assertEqual(self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
        self.assertEqual(len(sides(self.conn, match_id)), 2)

    def test_two_clubs_use_existing_club_picker_but_archived_team_is_not_selectable(self):
        clubs = self.team_ids[:2]
        event_id, entrants, _, _, _, _ = self._new_event(club_ids=clubs)
        form = {
            f"side{side}_{key}": value
            for side, club in enumerate(clubs, 1)
            for key, value in (("type", "team"), ("id", club))
        }
        self.assertEqual(self._create(event_id, form).status_code, 302)
        saved = sides(self.conn, self._match(event_id)["id"])
        self.assertEqual([saved[side]["team_id"] for side in (1, 2)], clubs)
        self.assertEqual([saved[side]["event_entrant_id"] for side in (1, 2)], entrants)

        archived_id, archived_entrants, groups, _, _, _ = self._new_event(club_ids=clubs)
        with write(self.conn):
            events.archive_team(
                self.conn,
                archived_id,
                groups[0],
                admin_id=1,
                now=self.NOW + 62,
                reason="该队主动退出",
            )
        self.assertEqual(self._create(archived_id, form).status_code, 409)
        self.assertEqual(
            self._create(archived_id, self._by_entrants(archived_entrants)).status_code, 409
        )
        self.assertIsNone(self._match(archived_id))

    def test_archived_event_does_not_allow_a_first_freeze_but_keeps_older_snapshot(self):
        event_id, entrants, _, _, _, _ = self._new_event()
        self.assertEqual(self._create(event_id, self._by_entrants(entrants)).status_code, 302)
        first = self._match(event_id)["id"]
        first_path = f"/admin/matches/{first}/freeze-rosters"
        self.assertEqual(self._post(first_path).status_code, 302)
        self.assertEqual(
            self._create(
                event_id, self._by_entrants(entrants), match_time="2030-01-02T19:30"
            ).status_code,
            302,
        )
        second = self._match(event_id)["id"]
        with write(self.conn):
            archive_event(self.conn, event_id, admin_id=1, now=self.NOW + 62)
        self.assertEqual(self._post(first_path).status_code, 302)
        self.assertEqual(len(sides(self.conn, first)[1]["players"]), 5)
        self.assertEqual(self._post(f"/admin/matches/{second}/freeze-rosters").status_code, 409)
        self.assertFalse(rosters_frozen(self.conn, second))
        self.assertEqual(
            self._create(
                event_id, self._by_entrants(entrants), match_time="2030-01-03T19:30"
            ).status_code,
            409,
        )
