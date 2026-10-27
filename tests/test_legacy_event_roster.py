import json

from services.match_roster_service import freeze_match_roster, resolve_match_roster
from tests.test_match_roster_linkage import RegisteredMatchCase
from utils.match_display import match_opponents


class LegacyEventRosterTests(RegisteredMatchCase):
    def setUp(self):
        super().setUp()
        self.conn.execute("DELETE FROM event_registration_slots")
        self.conn.execute("DELETE FROM event_registrations")
        self.conn.commit()
        self.conn.execute("PRAGMA foreign_keys=OFF")
        first = [player["id"] for player in self.rosters[1]]
        second = [player["id"] for player in self.rosters[2]]
        self.old_selections = (json.dumps(first + second[:1]), json.dumps(second[1:]))
        self.conn.execute(
            """UPDATE matches SET team1_id=-1,team2_id=-2,team1_players=?,team2_players=?,
                      status='completed',team1_score=2,team2_score=0,map1='de_mirage',
                      map2='de_inferno',map1_t1=13,map1_t2=4,map2_t1=13,map2_t2=9
               WHERE id=?""",
            (*self.old_selections, self.match_id),
        )
        for side, players in self.rosters.items():
            for player in players:
                for map_name in ("de_mirage", "de_inferno"):
                    self.conn.execute(
                        """INSERT INTO match_stats(match_id,player_id,team_id,match_team_side,
                                  map_name,kills,deaths,rating,data_source,data_status)
                           VALUES(?,?,NULL,?,?,20,10,1.25,'legacy','final')""",
                        (self.match_id, player["id"], f"t{side}", map_name),
                    )
        self.conn.commit()

    def _match(self):
        return self.conn.execute("SELECT * FROM matches WHERE id=?", (self.match_id,)).fetchone()

    def _assert_played_members(self, players):
        for side in (1, 2):
            self.assertEqual(
                {player["id"] for player in players[side]},
                {player["id"] for player in self.rosters[side]},
            )
            self.assertEqual(len(players[side]), 5)

    def test_completed_formal_five_by_five_overrides_old_six_by_four_selection(self):
        before = self._snapshot()
        roster = resolve_match_roster(self.conn, self._match())
        self.assertTrue(roster["locked"])
        self._assert_played_members(roster["players"])
        self.assertTrue(
            all(player["roster_source"] == "history" for player in roster["players"][1])
        )
        self.assertEqual(self._snapshot(), before)

    def test_event_keeps_both_temporary_sides_and_all_ten_actual_players(self):
        before = self._snapshot()
        with self._event_context() as context:
            self.assertEqual(len(context["teams"]), 2)
            self.assertEqual(sorted(len(team["players"]) for team in context["teams"]), [5, 5])
            self._assert_played_members(context["match_players_map"][self.match_id])
        self.assertEqual(self._snapshot(), before)

    def test_confirmed_historical_names_freeze_without_rewriting_scores_or_old_selection(self):
        before_stats = [
            tuple(row) for row in self.conn.execute("SELECT * FROM match_stats ORDER BY id")
        ]
        match = dict(self._match())
        match.update(team1_name="Team 4", team2_name="Team 3", t1s="T4", t2s="T3")
        freeze_match_roster(self.conn, match, confirmed=True)
        self.conn.commit()
        saved = self._match()
        self.assertEqual((saved["team1_players"], saved["team2_players"]), self.old_selections)
        self.assertEqual((saved["team1_score"], saved["team2_score"]), (2, 0))
        self.assertEqual(
            [tuple(row) for row in self.conn.execute("SELECT * FROM match_stats ORDER BY id")],
            before_stats,
        )
        with self._event_context() as context:
            self.assertEqual({team["name"] for team in context["teams"]}, {"Team 3", "Team 4"})
            self._assert_played_members(context["match_players_map"][self.match_id])
            self.assertEqual(
                [
                    (opponent["name"], opponent["score"])
                    for opponent in match_opponents(context["matches"][0])
                ],
                [("Team 3", 0), ("Team 4", 2)],
            )
        response = self.client.get(f"/api/broadcast/matches/{self.match_id}")
        self.assertEqual(response.status_code, 200)
        detail = response.get_json()["match"]
        self.assertEqual((detail["team1"]["name"], detail["team2"]["name"]), ("Team 4", "Team 3"))
        self.assertTrue(detail["roster_locked"])

    def test_live_match_cannot_use_completed_history_exception_to_bypass_bad_selection(self):
        self.conn.execute("UPDATE matches SET status='live' WHERE id=?", (self.match_id,))
        self.conn.commit()
        roster = resolve_match_roster(self.conn, self._match())
        self.assertFalse(roster["locked"])
        self.assertEqual(roster["players"][1], [])

    def test_incomplete_or_conflicting_history_does_not_replace_known_admin_roster(self):
        first = [player["id"] for player in self.rosters[1]]
        second = [player["id"] for player in self.rosters[2]]
        self.conn.execute(
            "UPDATE matches SET team1_players=?,team2_players=? WHERE id=?",
            (json.dumps(first), json.dumps(second), self.match_id),
        )
        self.conn.execute(
            "UPDATE match_stats SET match_team_side='t2' WHERE player_id=? AND map_name='de_inferno'",
            (first[0],),
        )
        roster = resolve_match_roster(self.conn, self._match())
        self.assertTrue(roster["locked"])
        self._assert_played_members(roster["players"])
        self.assertTrue(all(player["roster_source"] == "admin" for player in roster["players"][1]))
