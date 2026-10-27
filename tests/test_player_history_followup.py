import json

from app import app
from services.player_service import merge_player_records
from tests.test_match_roster_linkage import RegisteredMatchCase
from tests.test_refactor_stats_consistency import StatsDatabaseCase, add_stat


class PlayerHistoryFollowupTests(StatsDatabaseCase):
    def test_merge_preserves_unrelated_and_empty_roster_slots(self):
        target = self.conn.execute("INSERT INTO players(nickname) VALUES('Retained')").lastrowid
        self.conn.execute(
            "UPDATE matches SET team1_players=?, team2_players=NULL WHERE id=?",
            (json.dumps([None, self.player_id, 0, None]), self.match_id),
        )
        unrelated = self.conn.execute(
            "INSERT INTO matches(team1_players, team2_players) VALUES(?,NULL)",
            ("[ 999, null, 0 ]",),
        ).lastrowid
        merge_player_records(self.conn, self.player_id, target)
        row = self.conn.execute(
            "SELECT team1_players,team2_players FROM matches WHERE id=?", (self.match_id,)
        ).fetchone()
        self.assertEqual(json.loads(row["team1_players"]), [None, target, 0, None])
        self.assertIsNone(row["team2_players"])
        row = self.conn.execute(
            "SELECT team1_players,team2_players FROM matches WHERE id=?", (unrelated,)
        ).fetchone()
        self.assertEqual(row["team1_players"], "[ 999, null, 0 ]")
        self.assertIsNone(row["team2_players"])

    def test_profile_table_score_follows_sorted_team_names(self):
        self.conn.execute("UPDATE teams SET short_name='ZZZ' WHERE id=?", (self.team1,))
        self.conn.execute("UPDATE teams SET short_name='AAA' WHERE id=?", (self.team2,))
        self.conn.execute(
            "UPDATE matches SET team1_score=2,team2_score=0 WHERE id=?", (self.match_id,)
        )
        add_stat(
            self.conn, self.match_id, self.player_id, self.team2, "Mirage", match_team_side="t2"
        )
        self.conn.commit()
        html = app.test_client().get(f"/players/{self.player_id}").get_data(as_text=True)
        section = html.split('id="matches"', 1)[1].split("</section>", 1)[0]
        self.assertLess(section.index("AAA"), section.index("ZZZ"))
        self.assertIn("0 : 2", section)

    def test_champion_snapshot_survives_transfer_and_does_not_include_new_member(self):
        from services.champion_service import player_championships, save_champion

        newcomer = self.conn.execute(
            "INSERT INTO players(nickname,team_id) VALUES('Newcomer',?)", (self.team2,)
        ).lastrowid
        add_stat(
            self.conn, self.match_id, self.player_id, self.team2, "Mirage", match_team_side="t2"
        )
        save_champion(self.conn, self.event_id, self.team2)
        self.conn.execute("UPDATE players SET team_id=? WHERE id=?", (self.team1, self.player_id))
        self.assertEqual(len(player_championships(self.conn, self.player_id)), 1)
        self.assertEqual(len(player_championships(self.conn, newcomer)), 0)
        self.conn.commit()
        for player_id, expected in ((self.player_id, True), (newcomer, False)):
            html = app.test_client().get(f"/players/{player_id}").get_data(as_text=True)
            trophies = html.split('id="trophies"', 1)[1].split("</section>", 1)[0]
            self.assertEqual("Audit Cup" in trophies, expected)

        save_champion(self.conn, self.event_id, self.team2)
        self.assertEqual(len(player_championships(self.conn, self.player_id)), 1)
        target = self.conn.execute("INSERT INTO players(nickname) VALUES('Merged')").lastrowid
        champion_id = self.conn.execute(
            "SELECT id FROM event_champions WHERE event_id=?", (self.event_id,)
        ).fetchone()[0]
        self.conn.execute(
            "INSERT INTO event_champion_players(champion_id,player_id) VALUES(?,?)",
            (champion_id, target),
        )
        merge_player_records(self.conn, self.player_id, target)
        self.assertEqual(len(player_championships(self.conn, target)), 1)
        save_champion(self.conn, self.event_id, None)
        self.assertEqual(len(player_championships(self.conn, target)), 0)

    def test_old_champion_backfill_is_one_time_and_ignores_current_team(self):
        from services.champion_service import backfill_champion_members, player_championships

        self.conn.execute(
            "INSERT INTO event_champions(event_id,team_id) VALUES(?,?)", (self.event_id, self.team2)
        )
        backfill_champion_members(self.conn)
        self.assertEqual(player_championships(self.conn, self.player_id), [])
        add_stat(
            self.conn, self.match_id, self.player_id, self.team2, "Mirage", match_team_side="t2"
        )
        backfill_champion_members(self.conn)
        self.assertEqual(player_championships(self.conn, self.player_id), [])

    def test_frozen_registration_roster_is_evidence_and_merge_changes_only_id(self):
        from services.champion_service import player_championships, save_champion

        snapshot = {
            "version": 1,
            "evidence": "confirmed_match",
            "teams": {
                "1": {"players": []},
                "2": {
                    "players": [
                        {
                            "id": self.player_id,
                            "slot": 1,
                            "nickname": "Original",
                            "roster_source": "registration",
                        }
                    ]
                },
            },
        }
        raw = json.dumps(snapshot)
        self.conn.execute("UPDATE matches SET roster_snapshot=? WHERE id=?", (raw, self.match_id))
        save_champion(self.conn, self.event_id, self.team2)
        self.assertEqual(len(player_championships(self.conn, self.player_id)), 1)
        target = self.conn.execute("INSERT INTO players(nickname) VALUES('Merged')").lastrowid
        merge_player_records(self.conn, self.player_id, target)
        actual = json.loads(
            self.conn.execute(
                "SELECT roster_snapshot FROM matches WHERE id=?", (self.match_id,)
            ).fetchone()[0]
        )
        snapshot["teams"]["2"]["players"][0]["id"] = target
        self.assertEqual(actual, snapshot)

    def test_conflicting_side_evidence_is_not_awarded(self):
        from services.champion_service import player_championships, save_champion

        add_stat(
            self.conn, self.match_id, self.player_id, self.team2, "Mirage", match_team_side="t2"
        )
        add_stat(self.conn, self.match_id, self.player_id, self.team1, "Nuke", match_team_side="t1")
        save_champion(self.conn, self.event_id, self.team2)
        self.assertEqual(player_championships(self.conn, self.player_id), [])

    def test_old_champion_explicit_match_lineup_is_backfilled(self):
        from services.champion_service import backfill_champion_members, player_championships

        self.conn.execute(
            "UPDATE matches SET team2_players=? WHERE id=?",
            (json.dumps([self.player_id]), self.match_id),
        )
        self.conn.execute(
            "INSERT INTO event_champions(event_id,team_id) VALUES(?,?)", (self.event_id, self.team2)
        )
        backfill_champion_members(self.conn)
        self.conn.execute("UPDATE matches SET team2_players=? WHERE id=?", ("[]", self.match_id))
        self.assertEqual(len(player_championships(self.conn, self.player_id)), 1)


class ChampionEvidenceFollowupTests(RegisteredMatchCase):
    def test_explicitly_confirmed_match_snapshot_awards_registered_member(self):
        from services.champion_service import player_championships, save_champion
        from services.match_roster_service import freeze_match_roster

        match = self.conn.execute("SELECT * FROM matches WHERE id=?", (self.match_id,)).fetchone()
        freeze_match_roster(self.conn, match, confirmed=True)
        self.conn.execute("UPDATE matches SET status='completed' WHERE id=?", (self.match_id,))
        snapshot = json.loads(
            self.conn.execute(
                "SELECT roster_snapshot FROM matches WHERE id=?", (self.match_id,)
            ).fetchone()[0]
        )
        self.assertEqual(snapshot["evidence"], "confirmed_match")
        save_champion(self.conn, self.event_id, self.team_ids[0])
        self.assertEqual(len(player_championships(self.conn, self.rosters[1][0]["id"])), 1)

    def test_post_match_registration_preservation_does_not_award_champion(self):
        from services.champion_service import player_championships, save_champion
        from services.match_roster_service import freeze_match_roster

        self.conn.execute("UPDATE matches SET status='completed' WHERE id=?", (self.match_id,))
        match = self.conn.execute("SELECT * FROM matches WHERE id=?", (self.match_id,)).fetchone()
        freeze_match_roster(self.conn, match)
        save_champion(self.conn, self.event_id, self.team_ids[0])
        self.assertEqual(player_championships(self.conn, self.rosters[1][0]["id"]), [])

    def test_preserved_team_id_without_recorded_match_side_does_not_award_champion(self):
        from services.champion_service import player_championships, save_champion
        from services.match_roster_service import freeze_match_roster

        self.conn.execute("UPDATE matches SET status='completed' WHERE id=?", (self.match_id,))
        player_id = self.rosters[1][0]["id"]
        add_stat(
            self.conn, self.match_id, player_id, self.team_ids[0], "Mirage", match_team_side=None
        )
        match = self.conn.execute("SELECT * FROM matches WHERE id=?", (self.match_id,)).fetchone()
        freeze_match_roster(self.conn, match)
        save_champion(self.conn, self.event_id, self.team_ids[0])
        self.assertEqual(player_championships(self.conn, player_id), [])

    def test_snapshot_without_confirmed_evidence_or_known_source_does_not_award(self):
        from services.champion_service import player_championships, save_champion

        self.conn.execute("UPDATE matches SET status='completed' WHERE id=?", (self.match_id,))
        snapshot = {
            "version": 1,
            "teams": {
                "1": {"team_id": self.team_ids[0], "players": [{"id": self.rosters[1][0]["id"]}]},
                "2": {"team_id": self.team_ids[1], "players": []},
            },
        }
        self.conn.execute(
            "UPDATE matches SET roster_snapshot=? WHERE id=?", (json.dumps(snapshot), self.match_id)
        )
        save_champion(self.conn, self.event_id, self.team_ids[0])
        self.assertEqual(player_championships(self.conn, self.rosters[1][0]["id"]), [])

    def test_preserved_explicit_admin_and_history_sources_are_retained(self):
        from services.champion_service import player_championships, save_champion

        self.conn.execute("UPDATE matches SET status='completed' WHERE id=?", (self.match_id,))
        first, second, third = (p["id"] for p in self.rosters[1][:3])
        snapshot = {
            "version": 1,
            "evidence": "preserved",
            "teams": {
                "1": {
                    "team_id": self.team_ids[0],
                    "players": [
                        {"id": first, "roster_source": "admin"},
                        {"id": second, "roster_source": "history"},
                        {"id": third, "roster_source": "registration"},
                    ],
                },
                "2": {"team_id": self.team_ids[1], "players": []},
            },
        }
        self.conn.execute(
            "UPDATE matches SET roster_snapshot=? WHERE id=?", (json.dumps(snapshot), self.match_id)
        )
        save_champion(self.conn, self.event_id, self.team_ids[0])
        self.assertEqual(len(player_championships(self.conn, first)), 1)
        self.assertEqual(len(player_championships(self.conn, second)), 1)
        self.assertEqual(player_championships(self.conn, third), [])
