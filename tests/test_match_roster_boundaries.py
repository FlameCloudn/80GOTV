import json
from unittest.mock import patch

from config import Config
from services.champion_service import player_championships, save_champion
from services.match_roster_service import freeze_match_roster, resolve_match_roster
from tests.test_match_roster_linkage import RegisteredMatchCase
from utils.bp_manager import init_bp_state


class SelectedRosterBoundaryTests(RegisteredMatchCase):
    def _select(self, first, second=None):
        if second is None:
            second = [player["id"] for player in self.rosters[2]]
        self.conn.execute(
            "UPDATE matches SET team1_players=?,team2_players=? WHERE id=?",
            (json.dumps(first), json.dumps(second), self.match_id),
        )
        self.conn.commit()

    def _resolve(self):
        match = self.conn.execute("SELECT * FROM matches WHERE id=?", (self.match_id,)).fetchone()
        return resolve_match_roster(self.conn, match)

    def test_oversized_selection_is_invalid_in_resolver_details_probe_and_bp(self):
        state = init_bp_state("BO3")
        state["status"] = "completed"
        self.conn.execute(
            "UPDATE matches SET bp_state=? WHERE id=?", (json.dumps(state), self.match_id)
        )
        selected = [player["id"] for player in self.rosters[1]]
        for extra in (self.rosters[2][0]["id"], selected[0], None):
            with self.subTest(extra=extra):
                self._select([*selected, extra])
                before = self._snapshot()
                roster = self._resolve()
                self.assertFalse(roster["locked"])
                self.assertEqual(roster["players"][1], [])
                self.assertIn("team1_needs_five_players", roster["issues"])

                detail = self.client.get(f"/api/broadcast/matches/{self.match_id}").get_json()[
                    "match"
                ]
                self.assertFalse(detail["roster_locked"])
                self.assertFalse(detail["ready_for_start"])
                self.assertEqual(detail["team1"]["players"], [])
                with (
                    patch.object(Config, "GSI_TOKEN", "roster-boundary-test"),
                    patch("routes.live_ingest.rate_limit", return_value=True),
                ):
                    response = self.client.get(
                        f"/api/broadcast/matches/{self.match_id}/connection-test",
                        headers={"X-80GOTV-Token": "roster-boundary-test"},
                    )
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.get_json()["roster_locked"])
                self.assertFalse(response.get_json()["ready_for_start"])
                client = self._user_client()
                verification = client.post(
                    f"/bp/{self.match_id}/verify",
                    json={},
                    headers={"X-CSRF-Token": "pro-logic-csrf"},
                )
                self.assertEqual(verification.status_code, 403)
                self.assertEqual(self._snapshot(), before)

    def test_malformed_or_non_array_selection_does_not_use_registration_as_fallback(self):
        for raw in ("[", "{}", '"not-an-array"', "null", "42", "true"):
            with self.subTest(raw=raw):
                self.conn.execute(
                    "UPDATE matches SET team1_players=? WHERE id=?", (raw, self.match_id)
                )
                roster = self._resolve()
                self.assertFalse(roster["locked"])
                self.assertEqual(roster["players"][1], [])

    def test_five_slots_keep_valid_empty_and_duplicate_rules(self):
        selected = [player["id"] for player in self.rosters[1]]
        cases = (
            (selected, True),
            ([None, None, None, self.player_id, None], False),
            ([*selected[:4], selected[0]], False),
        )
        for first, locked in cases:
            with self.subTest(selected=first):
                self._select(first)
                roster = self._resolve()
                self.assertEqual(roster["locked"], locked)
                self.assertEqual(
                    [player["slot"] for player in roster["players"][1]], list(range(1, 6))
                )
                if first[0] is None:
                    self.assertEqual(roster["players"][1][3]["id"], self.player_id)
                if locked:
                    self.assertEqual(
                        {player["id"] for player in roster["players"][1]}, set(selected)
                    )

    def test_oversized_selection_cannot_replace_existing_formal_statistics(self):
        self._seed_final_stats()
        selected = {
            side: [player["id"] for player in players] for side, players in self.rosters.items()
        }
        for side in (1, 2):
            with self.subTest(side=side):
                rosters = {number: list(values) for number, values in selected.items()}
                rosters[side].append(rosters[3 - side][0])
                self._select(rosters[1], rosters[2])
                before = self._snapshot()
                response = self._post_result(self._result())
                self.assertEqual(response.status_code, 409, response.get_data(as_text=True))
                self.assertEqual(self._snapshot(), before)


class RosterTeamAssociationTests(RegisteredMatchCase):
    def _detail(self):
        response = self.client.get(f"/api/broadcast/matches/{self.match_id}")
        self.assertEqual(response.status_code, 200)
        return response.get_json()["match"]

    def _association(self):
        return tuple(
            self.conn.execute(
                """SELECT team1_id,team2_id,roster_snapshot,team1_registration_id,
                          team2_registration_id FROM matches WHERE id=?""",
                (self.match_id,),
            ).fetchone()
        )

    def _freeze(self):
        match = self.conn.execute("SELECT * FROM matches WHERE id=?", (self.match_id,)).fetchone()
        freeze_match_roster(self.conn, match, confirmed=match["status"] == "completed")
        self.conn.commit()

    def _change_team(self, status):
        return self._edit(
            status=status,
            side1_type="team",
            side1_id=str(self.team_ids[2]),
            side2_type="team",
            side2_id=str(self.team_ids[1]),
        )

    def test_finished_match_team_change_does_not_reassign_history_or_championship(self):
        self._seed_final_stats()
        self.conn.execute(
            """UPDATE matches SET status='completed',bo_format='BO1',team1_score=1,
                      team2_score=0,map1_t1=13,map1_t2=7 WHERE id=?""",
            (self.match_id,),
        )
        newcomer = self.conn.execute(
            "INSERT INTO players(nickname,steam_id,team_id) VALUES('New Team Member','999',?)",
            (self.team_ids[2],),
        ).lastrowid
        self._freeze()
        save_champion(self.conn, self.event_id, self.team_ids[0])
        self.conn.commit()
        before_association = self._association()
        before_detail = self._detail()
        before_statistics = [
            tuple(row) for row in self.conn.execute("SELECT * FROM match_stats ORDER BY id")
        ]
        player_id = self.rosters[1][0]["id"]
        before_championships = [tuple(row) for row in player_championships(self.conn, player_id)]
        self.assertEqual(len(before_championships), 1)

        response = self._change_team("completed")
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True))
        self.assertEqual(self._association(), before_association)
        after_detail = self._detail()
        for side in (1, 2):
            self.assertEqual(after_detail[f"team{side}"], before_detail[f"team{side}"])
        self.assertTrue(after_detail["roster_locked"])
        self.assertEqual(
            [tuple(row) for row in self.conn.execute("SELECT * FROM match_stats ORDER BY id")],
            before_statistics,
        )
        public = self.client.get(f"/matches/{self.match_id}", follow_redirects=True)
        self.assertEqual(public.status_code, 200)
        self.assertIn("Pro Team 0", public.get_data(as_text=True))
        self.assertNotIn("Pro Team 2", public.get_data(as_text=True))
        profile = self.client.get(f"/players/{player_id}")
        self.assertEqual(profile.status_code, 200)
        history = (
            profile.get_data(as_text=True).split('id="matches"', 1)[1].split("</section>", 1)[0]
        )
        self.assertIn("P0", history)
        self.assertNotIn("P2", history)
        save_champion(self.conn, self.event_id, self.team_ids[0])
        self.assertEqual(
            [tuple(row) for row in player_championships(self.conn, player_id)],
            before_championships,
        )
        self.assertEqual(player_championships(self.conn, newcomer), [])
        self.assertFalse(
            self.conn.execute(
                "SELECT 1 FROM match_stats WHERE match_id=? AND team_id=?",
                (self.match_id, self.team_ids[2]),
            ).fetchone()
        )

    def test_legal_pre_match_team_change_clears_snapshot_before_new_roster_is_read(self):
        self._freeze()
        self.assertIsNotNone(self._association()[2])
        old_players = {player["id"] for player in self.rosters[1]}
        response = self._change_team("upcoming")
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True))
        association = self._association()
        self.assertEqual(association[:2], (self.team_ids[2], self.team_ids[1]))
        self.assertIsNone(association[2])
        self.assertIsNone(association[3])
        self.assertEqual(association[4], self.registrations[2])
        detail = self._detail()
        self.assertEqual(detail["team1"]["players"], [])
        self.assertFalse(detail["roster_locked"])

        registration = self.conn.execute(
            "INSERT INTO event_registrations(event_id,team_name,creator_user_id) VALUES(?,?,?)",
            (self.event_id, "Pro Team 2", self.user_id),
        ).lastrowid
        new_players = set()
        for index in range(5):
            steam_id = str(9000 + index)
            player_id = self.conn.execute(
                "INSERT INTO players(nickname,steam_id,team_id) VALUES(?,?,?)",
                (f"New Player {index}", steam_id, self.team_ids[2]),
            ).lastrowid
            new_players.add(player_id)
            self.conn.execute(
                """INSERT INTO event_registration_slots(registration_id,slot_index,
                          player_name,steam_id) VALUES(?,?,?,?)""",
                (registration, index, f"New Player {index}", steam_id),
            )
        self.conn.commit()
        detail = self._detail()
        self.assertEqual(detail["team1"]["id"], self.team_ids[2])
        self.assertEqual({player["id"] for player in detail["team1"]["players"]}, new_players)
        self.assertFalse(old_players & new_players)
        self.assertTrue(detail["roster_locked"])
