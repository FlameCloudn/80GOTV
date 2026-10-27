import json
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import patch

from flask import template_rendered

from app import app
from blueprints.admin_matches import _match_roster_options
from config import Config
from tests import test_broadcast_map_result as broadcast_tests
from tests.test_pro_logic_regressions import ProDatabaseCase
from utils.bp_manager import init_bp_state


class RegisteredMatchCase(ProDatabaseCase):
    def setUp(self):
        super().setUp()
        self.rosters = {1: [], 2: []}
        self.registrations = {}
        for side in (1, 2):
            registration = self.conn.execute(
                "INSERT INTO event_registrations(event_id,team_name,creator_user_id) VALUES(?,?,?)",
                (self.event_id, f"Pro Team {side - 1}", self.user_id),
            ).lastrowid
            self.registrations[side] = registration
            for slot in range(5):
                steam_id = "111" if (side, slot) == (1, 3) else str(200 + side * 10 + slot)
                player_id = (
                    self.player_id
                    if steam_id == "111"
                    else self.conn.execute(
                        "INSERT INTO players(nickname,steam_id,team_id) VALUES(?,?,?)",
                        (f"Side {side} Slot {slot + 1}", steam_id, self.team_ids[2 - side]),
                    ).lastrowid
                )
                self.rosters[side].append({"id": player_id, "steam_id": steam_id})
                self.conn.execute(
                    "INSERT INTO event_registration_slots(registration_id,slot_index,player_name,steam_id) VALUES(?,?,?,?)",
                    (registration, slot, f"Registered {side}-{slot + 1}", steam_id),
                )
        self.conn.execute("UPDATE users SET steam_id64='111' WHERE id=?", (self.user_id,))
        self.conn.execute(
            "UPDATE players SET team_id=? WHERE id=?", (self.team_ids[1], self.player_id)
        )
        self.conn.execute(
            "UPDATE matches SET status='upcoming',map1_t1=0,map1_t2=0,team1_score=0,team2_score=0 WHERE id=?",
            (self.match_id,),
        )
        self.conn.commit()

    def _snapshot(self):
        return {
            table: [
                tuple(row) for row in self.conn.execute(f"SELECT * FROM {table} ORDER BY rowid")
            ]
            for table in ("matches", "match_stats", "live_match_data", "players", "users")
        }

    def _seed_final_stats(self):
        for side, players in self.rosters.items():
            for player in players:
                self.conn.execute(
                    """INSERT INTO match_stats(match_id,player_id,team_id,match_team_side,
                           map_name,kills,deaths,rating,data_source,data_status,data_version)
                       VALUES(?,?,?,?,'de_nuke',20,10,1.25,'demo','final',3)""",
                    (self.match_id, player["id"], self.team_ids[side - 1], f"t{side}"),
                )
        self.conn.commit()

    def _result(self):
        return {
            "map_name": "de_nuke",
            "team1_score": 13,
            "team2_score": 7,
            "players": [
                broadcast_tests.BroadcastMapResultTests._player(
                    player["steam_id"], f"Result {side}-{index}", f"team{side}", 20, 12, 1800
                )
                for side, players in self.rosters.items()
                for index, player in enumerate(players)
            ],
        }

    def _post_result(self, payload):
        with (
            patch.object(Config, "GSI_TOKEN", "roster-linkage-test"),
            patch("routes.live_ingest.rate_limit", return_value=True),
            patch("services.demo_service.enrich_player_from_steam"),
        ):
            return self.client.post(
                f"/api/broadcast/matches/{self.match_id}/map-result",
                json=payload,
                headers={"X-80GOTV-Token": "roster-linkage-test"},
            )

    def _bp_post(self, client, action, match_id=None, **data):
        return client.post(
            f"/api/bp/{match_id or self.match_id}/action",
            json={"action": action, **data},
            headers={"X-CSRF-Token": "pro-logic-csrf"},
        )

    @contextmanager
    def _event_context(self):
        rendered = []

        def record(_sender, template, context, **_extra):
            if template.name == "event_detail.html":
                rendered.append(context)

        template_rendered.connect(record, app)
        try:
            response = self.client.get(f"/events/{self.event_id}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(rendered), 1)
            yield rendered[0]
        finally:
            template_rendered.disconnect(record, app)


class MatchRosterLinkageTests(RegisteredMatchCase):
    def test_swapping_explicit_match_teams_keeps_the_other_sides_selected_members(self):
        self.conn.execute("DELETE FROM event_registration_slots")
        self.conn.execute("DELETE FROM event_registrations")
        self.conn.execute(
            "UPDATE matches SET team1_players=?,team2_players=? WHERE id=?",
            (
                json.dumps([p["id"] for p in self.rosters[1]]),
                json.dumps([p["id"] for p in self.rosters[2]]),
                self.match_id,
            ),
        )
        self.conn.commit()
        values = {
            "side1_type": "team",
            "side2_type": "team",
            "side1_id": str(self.team_ids[1]),
            "side2_id": str(self.team_ids[0]),
        }
        for side, original_side in ((1, 2), (2, 1)):
            values.update(
                {
                    f"match_team{side}_p{index}": str(player["id"])
                    for index, player in enumerate(self.rosters[original_side])
                }
            )
        response = self._edit(status="upcoming", **values)
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True))
        row = self.conn.execute("SELECT * FROM matches WHERE id=?", (self.match_id,)).fetchone()
        self.assertEqual([row["team1_id"], row["team2_id"]], self.team_ids[1::-1])
        self.assertEqual(set(json.loads(row["team1_players"])), {p["id"] for p in self.rosters[2]})

    def test_admin_roster_choices_use_registered_members_not_permanent_teammates(self):
        match = self.conn.execute("SELECT * FROM matches WHERE id=?", (self.match_id,)).fetchone()
        options = _match_roster_options(self.conn, match, 1)
        self.assertEqual(
            {player["id"] for player in options}, {player["id"] for player in self.rosters[1]}
        )
        self.assertFalse(any(player["is_substitute"] for player in options))

    def test_registration_roster_is_equally_locked_in_details_and_connection_test(self):
        state = init_bp_state("BO3")
        state["status"] = "completed"
        self.conn.execute(
            "UPDATE matches SET bp_state=? WHERE id=?", (json.dumps(state), self.match_id)
        )
        self.conn.commit()
        detail = self.client.get(f"/api/broadcast/matches/{self.match_id}").get_json()["match"]
        before = self._snapshot()
        with (
            patch.object(Config, "GSI_TOKEN", "roster-linkage-test"),
            patch("routes.live_ingest.rate_limit", return_value=True),
        ):
            response = self.client.get(
                f"/api/broadcast/matches/{self.match_id}/connection-test",
                headers={"X-80GOTV-Token": "roster-linkage-test"},
            )
        self.assertEqual(response.status_code, 200)
        probe = response.get_json()
        self.assertTrue(detail["roster_locked"])
        self.assertTrue(detail["ready_for_start"])
        self.assertEqual(probe["roster_locked"], detail["roster_locked"])
        self.assertEqual(probe["ready_for_start"], detail["ready_for_start"])
        self.assertEqual(self._snapshot(), before)

    def test_one_registered_player_cannot_supersede_ten_formal_statistics(self):
        self._seed_final_stats()
        payload = self._result()
        payload["players"] = [payload["players"][3]]
        before = self._snapshot()
        response = self._post_result(payload)
        self.assertEqual(response.status_code, 409, response.get_data(as_text=True))
        self.assertEqual(self._snapshot(), before)

    def test_full_registered_result_is_final_and_ignores_permanent_team_membership(self):
        self._seed_final_stats()
        response = self._post_result(self._result())
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        rows = self.conn.execute(
            "SELECT * FROM match_stats WHERE data_status<>'superseded' ORDER BY id"
        ).fetchall()
        self.assertEqual(len(rows), 10)
        self.assertTrue(all(row["data_status"] == "final" for row in rows))
        self.assertTrue(all(row["data_source"] == "director_final" for row in rows))
        expected = {
            player["id"]: f"t{side}" for side, players in self.rosters.items() for player in players
        }
        self.assertEqual({row["player_id"]: row["match_team_side"] for row in rows}, expected)

    def test_wrong_side_outsider_and_duplicate_results_preserve_formal_statistics(self):
        self._seed_final_stats()
        for change in ("wrong_side", "outsider", "duplicate"):
            with self.subTest(change=change):
                payload = self._result()
                if change == "wrong_side":
                    payload["players"][0]["team_side"] = "team2"
                elif change == "outsider":
                    payload["players"][0]["steam_id"] = "unregistered-player"
                else:
                    payload["players"][0] = deepcopy(payload["players"][1])
                before = self._snapshot()
                self.assertEqual(self._post_result(payload).status_code, 409)
                self.assertEqual(self._snapshot(), before)

    def test_incomplete_effective_roster_never_replaces_formal_statistics(self):
        self._seed_final_stats()
        self.conn.execute("UPDATE matches SET team1_players='[]' WHERE id=?", (self.match_id,))
        self.conn.commit()
        before = self._snapshot()
        self.assertEqual(self._post_result(self._result()).status_code, 409)
        self.assertEqual(self._snapshot(), before)

    def test_bp_verification_and_seat_use_this_event_not_permanent_membership(self):
        client = self._user_client()
        response = client.post(
            f"/bp/{self.match_id}/verify", json={}, headers={"X-CSRF-Token": "pro-logic-csrf"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["team"], "t1")
        start = self._bp_post(client, "start", team="t2")
        self.assertEqual(start.status_code, 200)
        self.assertTrue(start.get_json()["ok"])
        seats = json.loads(
            self.conn.execute(
                "SELECT bp_state FROM matches WHERE id=?", (self.match_id,)
            ).fetchone()[0]
        )["controller_seats"]
        self.assertEqual(seats["t1"]["user_id"], self.user_id)
        self.assertNotIn("t2", seats)
        wrong = self._bp_post(client, "roll", team="t2")
        self.assertFalse(wrong.get_json()["ok"])

    def test_same_account_can_have_different_sides_in_two_matches(self):
        other = self.conn.execute(
            """INSERT INTO matches(event_id,status,bo_format,match_time,team1_players,team2_players)
               VALUES(?,'upcoming','BO1','2030-01-02T18:00','[]',?)""",
            (self.other_event_id, json.dumps([None, self.player_id])),
        ).lastrowid
        self.conn.commit()
        client = self._user_client()
        for match_id, expected in ((self.match_id, "t1"), (other, "t2")):
            with self.subTest(match_id=match_id):
                response = client.post(
                    f"/bp/{match_id}/verify", json={}, headers={"X-CSRF-Token": "pro-logic-csrf"}
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()["team"], expected)

    def test_permanent_team_member_outside_effective_roster_has_no_bp_permission(self):
        self.conn.execute("DELETE FROM event_registration_slots WHERE steam_id='111'")
        self.conn.commit()
        client = self._user_client()
        response = client.post(
            f"/bp/{self.match_id}/verify", json={}, headers={"X-CSRF-Token": "pro-logic-csrf"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.get_json()["ok"])

    def test_real_admin_slot_four_is_retained_in_bp_and_event_temp_team(self):
        created = self.client.post(
            "/admin/matches/add",
            data={
                "csrf_token": "pro-logic-csrf",
                "event_id": self.event_id,
                "match_time": "2030-01-02T18:00",
                "bo_format": "BO1",
                "status": "upcoming",
                "is_test_mode": "1",
                "side1_type": "players",
                "side1_p3": self.player_id,
                "side2_type": "players",
            },
        )
        self.assertEqual(created.status_code, 302)
        match_id = self.conn.execute("SELECT MAX(id) FROM matches").fetchone()[0]
        client = self._user_client()
        room = client.get(f"/bp/{match_id}")
        self.assertEqual(room.status_code, 200)
        verified = client.post(
            f"/bp/{match_id}/verify", json={}, headers={"X-CSRF-Token": "pro-logic-csrf"}
        )
        self.assertEqual(verified.status_code, 200)
        self.assertEqual(verified.get_json()["team"], "t1")
        with self._event_context() as context:
            temporary = [team for team in context["teams"] if team["is_temp"]]
            self.assertTrue(temporary)
            players = [
                player for team in temporary for player in team["players"] if player.get("id")
            ]
            self.assertIn(
                (self.player_id, 4), [(player["id"], player.get("slot")) for player in players]
            )

    def test_event_match_rosters_keep_admin_overrides_and_do_not_use_team_membership(self):
        selected = [self.rosters[1][4]["id"], None, self.player_id]
        self.conn.execute(
            "UPDATE matches SET team1_players=? WHERE id=?", (json.dumps(selected), self.match_id)
        )
        self.conn.commit()
        with self._event_context() as context:
            players = context.get("match_players_map", {}).get(self.match_id, {}).get(1, [])
            self.assertEqual(
                [(player.get("id"), player["slot"]) for player in players],
                [(selected[0], 1), (None, 2), (self.player_id, 3)],
            )
