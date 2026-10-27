import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from services.match_roster_service import freeze_match_roster
from tests.test_match_roster_linkage import RegisteredMatchCase
from utils.bp_manager import init_bp_state


class RosterHistoryFollowupTests(RegisteredMatchCase):
    def _detail(self):
        response = self.client.get(f"/api/broadcast/matches/{self.match_id}")
        self.assertEqual(response.status_code, 200)
        return response.get_json()["match"]

    def _finish(self):
        self.conn.execute("UPDATE matches SET status='completed' WHERE id=?", (self.match_id,))
        self.conn.commit()

    def _identity(self, detail):
        return {
            side: (
                detail[f"team{side}"]["name"],
                {player["steam_id"] for player in detail[f"team{side}"]["players"]},
            )
            for side in (1, 2)
        }

    def _post(self, path, **values):
        response = self.client.post(
            path,
            data={"csrf_token": "pro-logic-csrf", **values},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertIn(response.status_code, (200, 302), response.get_data(as_text=True))
        return response

    def test_finished_match_keeps_roster_and_team_identity_after_permanent_team_rename(self):
        self._finish()
        before = self._identity(self._detail())
        self._post(
            f"/admin/teams/edit/{self.team_ids[0]}", name="New Permanent Name", short_name="NP"
        )
        self.assertEqual(self._identity(self._detail()), before)

        page = self.client.get(f"/matches/{self.match_id}")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn("New Permanent Name", page.get_data(as_text=True))

    def test_upcoming_match_keeps_registration_association_after_permanent_team_rename(self):
        before = self._identity(self._detail())
        self._post(
            f"/admin/teams/edit/{self.team_ids[0]}", name="New Permanent Name", short_name="NP"
        )
        detail = self._detail()
        self.assertTrue(detail["roster_locked"])
        self.assertEqual(self._identity(detail), before)

    def test_finished_match_survives_registration_rename_then_dissolve(self):
        self._finish()
        before = self._identity(self._detail())
        path = f"/events/{self.event_id}/registrations/{self.registrations[1]}"
        self._post(path + "/rename", team_name="Changed Event Team")
        self.assertEqual(self._identity(self._detail()), before)
        self._post(path + "/dissolve")
        self.assertEqual(self._identity(self._detail()), before)
        self.assertTrue(self._detail()["roster_locked"])

    def test_finished_match_survives_registration_member_edit_and_removal(self):
        self._finish()
        before = self._identity(self._detail())
        path = f"/events/{self.event_id}/registrations/{self.registrations[1]}"
        self._post(
            path + "/slots/0/update", player_name="Replacement", steam_id="76561198000009999"
        )
        self._post(path + "/slots/1/remove")
        self.assertEqual(self._identity(self._detail()), before)

    def test_reads_do_not_create_or_replace_roster_snapshots(self):
        before = tuple(
            self.conn.execute(
                "SELECT roster_snapshot,team1_registration_id,team2_registration_id FROM matches WHERE id=?",
                (self.match_id,),
            ).fetchone()
        )
        self._detail()
        self.client.get(f"/events/{self.event_id}")
        after = tuple(
            self.conn.execute(
                "SELECT roster_snapshot,team1_registration_id,team2_registration_id FROM matches WHERE id=?",
                (self.match_id,),
            ).fetchone()
        )
        self.assertEqual(after, before)

    def test_successful_map_settlement_freezes_the_played_roster_without_changing_permanent_teams(
        self,
    ):
        permanent = [
            tuple(row) for row in self.conn.execute("SELECT id,team_id FROM players ORDER BY id")
        ]
        response = self._post_result(self._result())
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        saved = self.conn.execute(
            "SELECT roster_snapshot FROM matches WHERE id=?", (self.match_id,)
        ).fetchone()[0]
        self.assertTrue(saved)
        snapshot = json.loads(saved)
        self.assertEqual(snapshot["version"], 1)
        self.assertEqual(
            {player["steam_id"] for player in snapshot["teams"]["1"]["players"]},
            {player["steam_id"] for player in self.rosters[1]},
        )
        self.assertEqual(
            [tuple(row) for row in self.conn.execute("SELECT id,team_id FROM players ORDER BY id")],
            permanent,
        )

    def test_historical_statistics_are_evidence_even_after_registration_is_already_gone(self):
        self._seed_final_stats()
        self._finish()
        before = self._identity(self._detail())
        self.conn.execute("DELETE FROM event_registration_slots")
        self.conn.execute("DELETE FROM event_registrations")
        self.conn.commit()
        self.assertEqual(self._identity(self._detail()), before)

    def test_changed_current_registration_cannot_replace_existing_formal_map_members(self):
        self._seed_final_stats()
        self.conn.execute("UPDATE matches SET status='live' WHERE id=?", (self.match_id,))
        new_steam_id = "76561198000009999"
        self.conn.execute(
            "UPDATE event_registration_slots SET steam_id=? WHERE registration_id=? AND slot_index=3",
            (new_steam_id, self.registrations[1]),
        )
        self.conn.commit()
        payload = self._result()
        payload["players"][3]["steam_id"] = new_steam_id
        before = self._snapshot()
        self.assertEqual(self._post_result(payload).status_code, 409)
        self.assertEqual(self._snapshot(), before)

    def test_registration_change_does_not_freeze_unrelated_or_incomplete_bp_match(self):
        other_registrations = []
        for side in (2, 3):
            registration = self.conn.execute(
                "INSERT INTO event_registrations(event_id,team_name,creator_user_id) VALUES(?,?,?)",
                (self.event_id, f"Pro Team {side}", self.user_id),
            ).lastrowid
            other_registrations.append(registration)
            for slot in range(5):
                self.conn.execute(
                    "INSERT INTO event_registration_slots(registration_id,slot_index,player_name,steam_id,filled_by_creator) VALUES(?,?,?,?,1)",
                    (
                        registration,
                        slot,
                        f"Other {side}-{slot}",
                        "" if (side, slot) == (2, 4) else str(76561198000010000 + side * 10 + slot),
                    ),
                )
        other_match = self.conn.execute(
            """INSERT INTO matches(event_id,team1_id,team2_id,status,bo_format,match_time,bp_state)
               VALUES(?,?,?,'upcoming','BO3','2030-01-04T18:00',?)""",
            (self.event_id, self.team_ids[2], self.team_ids[3], json.dumps(init_bp_state("BO3"))),
        ).lastrowid
        self.conn.commit()
        self._post(
            f"/events/{self.event_id}/registrations/{self.registrations[1]}/rename",
            team_name="Changed A Only",
        )
        row = self.conn.execute("SELECT * FROM matches WHERE id=?", (other_match,)).fetchone()
        self.assertIsNone(row["roster_snapshot"])
        self.assertIsNone(row["team1_registration_id"])
        self._post(
            f"/events/{self.event_id}/registrations/{other_registrations[0]}/slots/4/update",
            player_name="Filled Player",
            steam_id="76561198000010024",
        )
        detail = self.client.get(f"/api/broadcast/matches/{other_match}").get_json()["match"]
        self.assertTrue(detail["roster_locked"])

    def test_dissolving_registration_does_not_delete_a_historical_team_logo(self):
        self._finish()
        filename = "historical-team.png"
        self.conn.execute(
            "UPDATE event_registrations SET team_logo=? WHERE id=?",
            (filename, self.registrations[1]),
        )
        self.conn.commit()
        with tempfile.TemporaryDirectory() as root:
            image = Path(root) / "static/uploads/team_logos" / filename
            image.parent.mkdir(parents=True)
            Image.new("RGBA", (4, 4)).save(image)
            with patch("routes.events.BASE_DIR", root):
                self._post(
                    f"/events/{self.event_id}/registrations/{self.registrations[1]}/dissolve"
                )
            self.assertTrue(image.is_file())
        detail = self._detail()
        self.assertIn(filename, detail["team1"]["logo"])

    def test_admin_completion_freezes_roster_with_confirmed_evidence(self):
        self.conn.execute(
            """UPDATE matches SET status='live',map1_t1=13,map1_t2=7,map2='de_mirage',
                   map2_t1=13,map2_t2=8,team1_score=2,team2_score=0 WHERE id=?""",
            (self.match_id,),
        )
        self.conn.commit()
        self._post(f"/admin/matches/{self.match_id}/complete")
        row = self.conn.execute("SELECT * FROM matches WHERE id=?", (self.match_id,)).fetchone()
        self.assertEqual(row["status"], "completed")
        self.assertEqual(json.loads(row["roster_snapshot"])["evidence"], "confirmed_match")

    def test_explicit_upcoming_roster_edit_does_not_reuse_stale_snapshot(self):
        match = self.conn.execute("SELECT * FROM matches WHERE id=?", (self.match_id,)).fetchone()
        freeze_match_roster(self.conn, match)
        self.conn.commit()
        selected = [player["id"] for player in self.rosters[1]][::-1]
        response = self._edit(
            status="upcoming",
            **{f"match_team1_p{index}": str(player_id) for index, player_id in enumerate(selected)},
        )
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True))
        saved = self.conn.execute("SELECT * FROM matches WHERE id=?", (self.match_id,)).fetchone()
        self.assertIsNone(saved["roster_snapshot"])
        self.assertEqual(set(json.loads(saved["team1_players"])), set(selected))
