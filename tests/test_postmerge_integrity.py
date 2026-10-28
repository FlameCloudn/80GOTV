"""Post-merge checks for Demo replacement and manual review provenance."""

import json
import sqlite3

from services.demo_service import import_demo_data
from tests.test_pro_logic_regressions import ProDatabaseCase
from tests.test_review_data_roundtrip import ReviewDataRoundtripTests as ExistingCases
from utils.stats_calc import calculate_rating


class PostMergeIntegrityTests(ProDatabaseCase):
    _prepare = ExistingCases._prepare
    _all = ExistingCases._all
    _active = ExistingCases._active
    _form = ExistingCases._form
    _post = ExistingCases._post

    def _low(self, status="final"):
        self._prepare(snapshot_only=True)
        self.conn.execute(
            """UPDATE match_stats SET kills=0,assists=0,impact=0,rating=0.32,
                kpr=0,clutches_won=0,first_kills=0,multi2k=0,trade_kills=0,flash_assists=0,
                t_kills=0,ct_kills=0,headshot_percentage=0,data_status=?,data_source='gotv_relay'
               WHERE match_id=? AND player_id=?""",
            (status, self.match_id, self.player_id),
        )
        self.conn.commit()

    def _target(self):
        return next(row for row in self._active() if row["player_id"] == self.player_id)

    def _demo(self, selected=None):
        match = dict(
            self.conn.execute("SELECT * FROM matches WHERE id=?", (self.match_id,)).fetchone()
        )
        match.update(team1_name="Orion", team2_name="Lyra")
        profiles = {row["id"]: dict(row) for row in self.conn.execute("SELECT * FROM players")}
        saved = {row["player_id"]: row for row in self._active()}
        ids = self.ids if selected is None else selected
        players = [
            dict(
                saved[player_id],
                steam_id=profiles[player_id]["steam_id"],
                name=profiles[player_id]["nickname"],
                team_letter="A" if self.ids.index(player_id) < 5 else "B",
            )
            for player_id in ids
        ]
        data = {
            "info": {
                "team_a_name": "Counter-Terrorists",
                "team_b_name": "Terrorists",
                "team_a_score": 13,
                "team_b_score": 7,
                "rounds_count": 20,
                "map_name": "de_nuke",
            },
            "players": players,
        }
        return match, data

    def test_noop_twice_preserves_all_columns_and_versions(self):
        self._prepare(snapshot_only=True)
        before = self._all()
        for _ in range(2):
            self.assertEqual(self._post().status_code, 302)
            self.assertEqual(self._all(), before)

    def test_failure_mid_insert_rolls_back_superseding_and_new_rows(self):
        self._prepare()
        self.conn.execute(
            f"""CREATE TRIGGER fail_second_player BEFORE INSERT ON match_stats
                WHEN NEW.player_id={self.ids[1]} AND NEW.data_version>1
                BEGIN SELECT RAISE(ABORT,'isolated insertion failure'); END"""
        )
        self.conn.commit()
        before = self._all()
        form = self._form()
        form[f"deaths_{self.player_id}"] = "11"
        self.assertEqual(self._post(form).status_code, 400)
        self.assertEqual(self._all(), before)

    def test_closed_match_after_form_open_rejects_save(self):
        self._prepare()
        form = self._form()
        form[f"deaths_{self.player_id}"] = "11"
        self.conn.execute("UPDATE matches SET status='completed' WHERE id=?", (self.match_id,))
        self.conn.commit()
        before = self._all()
        self.assertEqual(self._post(form).status_code, 302)
        self.assertEqual(self._all(), before)

    def test_out_of_range_and_missing_fields_leave_all_versions_unchanged(self):
        self._prepare()
        before = self._all()
        for key, value in [
            ("kast", "100.1"),
            ("hs", "-1"),
            ("adr", "nan"),
            ("impact", "inf"),
            ("kills", "1.5"),
        ]:
            with self.subTest(field=key, value=value):
                form = self._form()
                form[f"{key}_{self.player_id}"] = value
                self.assertEqual(self._post(form).status_code, 400)
                self.assertEqual(self._all(), before)
        form = self._form()
        del form[f"assists_{self.ids[-1]}"]
        self.assertEqual(self._post(form).status_code, 400)
        self.assertEqual(self._all(), before)

    def test_final_low_impact_survives_two_real_edits(self):
        self._low()
        for deaths in [11, 12]:
            form = self._form()
            form[f"deaths_{self.player_id}"] = str(deaths)
            self.assertEqual(self._post(form).status_code, 302)
            expected = calculate_rating(0, deaths, 20, adr=50, kast=50, impact=-0.41)[0]
            self.assertEqual(self._target()["rating"], expected)

    def test_provisional_confirmation_retains_rating_method_for_next_edit(self):
        self._low("provisional")
        self.assertEqual(self._post().status_code, 302)
        confirmed = self._target()
        self.assertEqual(confirmed["data_status"], "final")
        self.assertEqual(confirmed["rating"], 0.32)
        form = self._form()
        form[f"deaths_{self.player_id}"] = "11"
        self.assertEqual(self._post(form).status_code, 302)
        actual = self._target()
        expected = calculate_rating(0, 11, 20, adr=50, kast=50, impact=-0.41)[0]
        self.assertEqual(actual["rating"], expected)

    def test_migration_adds_nullable_metadata_idempotently(self):
        from models import _ensure_match_stats_data_version_columns

        db = sqlite3.connect(":memory:")
        try:
            db.execute("CREATE TABLE match_stats (id INTEGER, impact REAL, rating REAL)")
            db.execute("INSERT INTO match_stats VALUES(1,0,0.32)")
            _ensure_match_stats_data_version_columns(db.cursor())
            _ensure_match_stats_data_version_columns(db.cursor())
            row = db.execute(
                "SELECT impact,rating,impact_method,rating_impact FROM match_stats"
            ).fetchone()
            self.assertEqual(row, (0.0, 0.32, None, None))
        finally:
            db.close()

    def test_sparse_one_vs_one_legacy_still_saves(self):
        self._prepare()
        chosen = [self.ids[0], self.ids[-1]]
        self.conn.execute("DELETE FROM match_stats WHERE player_id NOT IN (?,?)", chosen)
        self.conn.execute(
            """UPDATE matches SET roster_snapshot=NULL,team1_players=?,team2_players=?
               WHERE id=?""",
            (json.dumps([None, chosen[0]]), json.dumps([None, None, chosen[1]]), self.match_id),
        )
        self.conn.commit()
        form = self._form()
        form[f"deaths_{self.player_id}"] = "11"
        self.assertEqual(self._post(form).status_code, 302)
        self.assertEqual(len(self._active()), 2)

    def test_complete_demo_after_transfer_keeps_side_and_score(self):
        self._prepare(snapshot_only=True)
        for index, player_id in enumerate(self.ids):
            self.conn.execute(
                "UPDATE players SET team_id=? WHERE id=?",
                (self.team_ids[1 if index < 5 else 0], player_id),
            )
        self.conn.commit()
        match, data = self._demo()
        count, message = import_demo_data(self.conn, self.match_id, match, json.dumps(data), 0)
        self.assertEqual(count, 10, message)
        row = self.conn.execute(
            "SELECT map1_t1,map1_t2,team1_score,team2_score FROM matches WHERE id=?",
            (self.match_id,),
        ).fetchone()
        self.assertEqual(tuple(row), (13, 7, 1, 0))
        self.assertTrue(
            all(
                row["match_team_side"] == ("t1" if self.ids.index(row["player_id"]) < 5 else "t2")
                for row in self._active()
            )
        )

    def test_incomplete_demo_does_not_replace_ten_confirmed_players(self):
        self._prepare(snapshot_only=True)
        before = self._all()
        match, data = self._demo([self.ids[0]])
        count, message = import_demo_data(self.conn, self.match_id, match, json.dumps(data), 0)
        self.assertIsNone(count, message)
        self.assertEqual(self._all(), before)

    def test_incomplete_demo_http_import_preserves_current_data(self):
        self._prepare(snapshot_only=True)
        before = self._all()
        _match, data = self._demo([self.ids[0]])
        response = self.client.post(
            f"/admin/matches/{self.match_id}/import-demo",
            data={
                "csrf_token": "pro-logic-csrf",
                "step": "import_single",
                "map_slot": "0",
                "demo_data": json.dumps(data),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._all(), before)

    def test_complete_sparse_one_vs_one_demo_remains_supported(self):
        self._prepare()
        chosen = [self.ids[0], self.ids[-1]]
        self.conn.execute("DELETE FROM match_stats WHERE player_id NOT IN (?,?)", chosen)
        self.conn.execute(
            """UPDATE matches SET roster_snapshot=NULL,team1_players=?,team2_players=?
               WHERE id=?""",
            (json.dumps([None, chosen[0]]), json.dumps([None, None, chosen[1]]), self.match_id),
        )
        self.conn.commit()
        match, data = self._demo(chosen)
        count, message = import_demo_data(self.conn, self.match_id, match, json.dumps(data), 0)
        self.assertEqual(count, 2, message)
        self.assertEqual({row["player_id"] for row in self._active()}, set(chosen))

    def test_ambiguous_demo_orientation_does_not_touch_old_rows(self):
        self._prepare(snapshot_only=True)
        before = self._all()
        match, data = self._demo()
        data["players"][0]["team_letter"] = "B"
        count, message = import_demo_data(self.conn, self.match_id, match, json.dumps(data), 0)
        self.assertIsNone(count, message)
        self.assertEqual(self._all(), before)

    def test_duplicate_demo_steam_identity_rejected(self):
        self._prepare(snapshot_only=True)
        before = self._all()
        match, data = self._demo()
        data["players"][1]["steam_id"] = data["players"][0]["steam_id"]
        count, message = import_demo_data(self.conn, self.match_id, match, json.dumps(data), 0)
        self.assertIsNone(count, message)
        self.assertEqual(self._all(), before)

    def test_identity_ignores_slot_order_and_respects_registration(self):
        from services.match_roster_service import match_side_identity

        self.assertEqual(
            match_side_identity({"team1_id": -1, "team1_players": "[1,null,2]"}, 1),
            match_side_identity({"team2_id": -2, "team2_players": "[2,1,null]"}, 2),
        )
        self.assertNotEqual(
            match_side_identity({"team1_id": -1, "team1_players": "[1,2]"}, 1),
            match_side_identity({"team1_id": -1, "team1_players": "[3,4]"}, 1),
        )
        self.assertEqual(
            match_side_identity({"team1_registration_id": 77, "team1_name": "Old"}, 1),
            match_side_identity({"team1_registration_id": 77, "team1_name": "New"}, 1),
        )


del ExistingCases, ProDatabaseCase
