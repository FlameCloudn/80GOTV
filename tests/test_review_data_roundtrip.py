"""跨入口回归：整图保存、历史阵容、Demo 队伍方向及赛事身份一致性。"""

import json
from contextlib import contextmanager
from unittest.mock import patch

from flask import template_rendered

from app import app
from routes.events import (
    _event_matches_with_teams,
    _event_player_teams,
    _event_team_count,
    _event_team_rankings,
)
from services.demo_service import analyze_demo, import_demo_data
from services.match_roster_service import freeze_match_roster, match_side_identity
from tests.test_match_roster_linkage import RegisteredMatchCase
from tests.test_pro_logic_regressions import ProDatabaseCase
from utils.stats_calc import calculate_rating, estimate_hltv2_impact


@contextmanager
def rendered_contexts():
    captured = []

    def record(sender, template, context, **extra):
        captured.append((template.name, context))

    template_rendered.connect(record, app)
    try:
        yield captured
    finally:
        template_rendered.disconnect(record, app)


class ReviewDataRoundtripTests(ProDatabaseCase):
    def _prepare(self, *, snapshot_only=False):
        self.ids = [self.player_id]
        for index in range(2, 11):
            self.ids.append(
                self.conn.execute(
                    "INSERT INTO players(nickname,steam_id,team_id) VALUES(?,?,?)",
                    (f"Review Player {index}", str(76561198090000000 + index), self.team_ids[2]),
                ).lastrowid
            )
        self.conn.execute(
            "UPDATE players SET team_id=? WHERE id=?", (self.team_ids[2], self.player_id)
        )
        self.conn.execute(
            """UPDATE matches SET status='live',bo_format='BO3',
               team1_score=1,team2_score=0,map1='de_nuke',map1_t1=13,map1_t2=7,
               team1_players=?,team2_players=? WHERE id=?""",
            (json.dumps(self.ids[:5]), json.dumps(self.ids[5:]), self.match_id),
        )
        match = dict(
            self.conn.execute("SELECT * FROM matches WHERE id=?", (self.match_id,)).fetchone()
        )
        freeze_match_roster(self.conn, match, confirmed=True)
        # Snapshot-only rows are a supported preserved/legacy representation.
        # Fixture construction is deliberate; this test does not claim to exercise
        # the registration UI that produced such historical rows.
        if snapshot_only:
            self.conn.execute(
                "UPDATE matches SET team1_players=NULL,team2_players=NULL WHERE id=?",
                (self.match_id,),
            )
        raw = estimate_hltv2_impact(10, 4, 20)
        rating, kpr, dpr = calculate_rating(10, 10, 20, adr=50, kast=50, impact=raw)
        for index, player_id in enumerate(self.ids):
            self.conn.execute(
                """INSERT INTO match_stats(
                  match_id,player_id,team_id,match_team_side,map_name,
                  kills,deaths,assists,adr,kast,impact,rating,kpr,dpr,
                  headshot_percentage,rounds_played,data_source,data_status,data_version,
                  clutches_won,first_kills,multi2k,trade_kills,flash_assists,t_kills,ct_kills)
                  VALUES(?,?,?,?,?,10,10,4,50,50,?,?,?,?,40,20,'demo_review','final',1,
                         2,4,3,2,3,6,4)""",
                (
                    self.match_id,
                    player_id,
                    self.team_ids[0 if index < 5 else 1],
                    "t1" if index < 5 else "t2",
                    "de_nuke",
                    round(raw, 2),
                    rating,
                    kpr,
                    dpr,
                ),
            )
        self.conn.commit()

    def _active(self):
        return [
            dict(row)
            for row in self.conn.execute(
                """SELECT * FROM match_stats WHERE match_id=?
               AND COALESCE(data_status,'final')<>'superseded' ORDER BY player_id""",
                (self.match_id,),
            )
        ]

    def _all(self):
        return [
            dict(row)
            for row in self.conn.execute(
                "SELECT * FROM match_stats WHERE match_id=? ORDER BY id", (self.match_id,)
            )
        ]

    def _form(self):
        form = {"csrf_token": "pro-logic-csrf", "map_name": "de_nuke"}
        fields = [
            ("kills", "kills"),
            ("deaths", "deaths"),
            ("assists", "assists"),
            ("adr", "adr"),
            ("impact", "impact"),
            ("kast", "kast"),
            ("hs", "headshot_percentage"),
            ("team_id", "team_id"),
        ]
        for row in self._active():
            for field, column in fields:
                form[f"{field}_{row['player_id']}"] = (
                    "" if row[column] is None else str(row[column])
                )
        return form

    def _post(self, form=None):
        return self.client.post(
            f"/admin/matches/{self.match_id}/stats", data=self._form() if form is None else form
        )

    def test_stats_editor_reads_snapshot_players(self):
        self._prepare(snapshot_only=True)
        with rendered_contexts() as captured:
            response = self.client.get(f"/admin/matches/{self.match_id}/stats")
        self.assertEqual(response.status_code, 200)
        context = next(context for name, context in captured if name == "admin/match_stats.html")
        self.assertEqual({row["id"] for row in context["team1_players"]}, set(self.ids[:5]))
        self.assertEqual({row["id"] for row in context["team2_players"]}, set(self.ids[5:]))

    def test_empty_submission_never_erases_existing_map_stats(self):
        self._prepare(snapshot_only=True)
        before = self._active()
        self._post({"csrf_token": "pro-logic-csrf", "map_name": "de_nuke"})
        after = self._active()
        columns = [
            "player_id",
            "team_id",
            "match_team_side",
            "kills",
            "deaths",
            "assists",
            "adr",
            "kast",
            "impact",
            "rating",
            "clutches_won",
            "first_kills",
        ]
        self.assertEqual(
            [{key: r[key] for key in columns} for r in after],
            [{key: r[key] for key in columns} for r in before],
        )

    def test_unchanged_save_preserves_uneditable_statistics(self):
        self._prepare()
        columns = [
            "clutches_won",
            "first_kills",
            "multi2k",
            "trade_kills",
            "flash_assists",
            "t_kills",
            "ct_kills",
        ]
        before = [{key: r[key] for key in columns} for r in self._active()]
        response = self._post()
        self.assertIn(response.status_code, (200, 302, 303))
        self.assertEqual([{key: r[key] for key in columns} for r in self._active()], before)

    def test_unchanged_low_impact_save_preserves_rating(self):
        self._prepare()
        self.conn.execute(
            """UPDATE match_stats SET kills=0,assists=0,impact=0,rating=0.32,
                kpr=0,clutches_won=0,first_kills=0,multi2k=0,t_kills=0,ct_kills=0,
                trade_kills=0,flash_assists=0,headshot_percentage=0 WHERE match_id=? AND player_id=?""",
            (self.match_id, self.player_id),
        )
        self.conn.commit()
        response = self._post()
        self.assertIn(response.status_code, (200, 302, 303))
        row = next(row for row in self._active() if row["player_id"] == self.player_id)
        self.assertAlmostEqual(row["rating"], 0.32)
        self.assertEqual(row["impact"], 0)

    def test_completed_match_still_blocks_manual_changes(self):
        self._prepare()
        self.conn.execute("UPDATE matches SET status='completed' WHERE id=?", (self.match_id,))
        self.conn.commit()
        before = self._all()
        form = self._form()
        form[f"kills_{self.player_id}"] = "99"
        self._post(form)
        self.assertEqual(self._all(), before)

    def test_invalid_rounds_do_not_supersede_old_stats(self):
        self._prepare()
        self.conn.execute("UPDATE matches SET map1_t1=0,map1_t2=0 WHERE id=?", (self.match_id,))
        self.conn.commit()
        before = self._all()
        response = self._post()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._all(), before)

    def test_demo_orientation_respects_snapshot_over_current_clubs(self):
        self._prepare(snapshot_only=True)
        for index, player_id in enumerate(self.ids):
            self.conn.execute(
                "UPDATE players SET team_id=? WHERE id=?",
                (self.team_ids[1 if index < 5 else 0], player_id),
            )
        self.conn.commit()
        match = dict(
            self.conn.execute("SELECT * FROM matches WHERE id=?", (self.match_id,)).fetchone()
        )
        match.update(team1_name="Orion", team2_name="Lyra")
        profiles = {row["id"]: dict(row) for row in self.conn.execute("SELECT * FROM players")}
        saved = {row["player_id"]: row for row in self._active()}
        players = [
            dict(
                saved[player_id],
                steam_id=profiles[player_id]["steam_id"],
                name=profiles[player_id]["nickname"],
                team_letter="A" if index < 5 else "B",
            )
            for index, player_id in enumerate(self.ids)
        ]
        payload = {
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
        count, message = import_demo_data(self.conn, self.match_id, match, json.dumps(payload), 0)
        self.assertEqual(count, 10, message)
        actual = {row["player_id"]: row["match_team_side"] for row in self._active()}
        self.assertEqual(
            actual,
            {player_id: "t1" if index < 5 else "t2" for index, player_id in enumerate(self.ids)},
        )

    def test_legacy_side_sentinels_are_not_team_identities(self):
        self._prepare()
        extra = [
            self.conn.execute(
                "INSERT INTO players(nickname,steam_id) VALUES(?,?)",
                (f"Other Player {n}", str(76561198100000000 + n)),
            ).lastrowid
            for n in range(10)
        ]
        self.conn.commit()
        self.conn.execute("PRAGMA foreign_keys=OFF")
        self.conn.execute("UPDATE matches SET team1_id=-1,team2_id=-2 WHERE id=?", (self.match_id,))
        self.conn.execute(
            """INSERT INTO matches(event_id,team1_id,team2_id,team1_players,team2_players,status)
               VALUES(?,-1,-2,?,?,'completed')""",
            (self.event_id, json.dumps(extra[:5]), json.dumps(extra[5:])),
        )
        self.conn.commit()
        self.assertEqual(_event_team_count(self.conn, self.event_id), 4)

    def _renamed_matches(self):
        return {
            number: {
                "id": number,
                "effective_status": "completed",
                "team1_id": None,
                "team2_id": self.team_ids[1],
                "team1_registration_id": 77,
                "team2_registration_id": 88,
                "team1_name": name,
                "team2_name": "Opponent",
                "t1s": "",
                "t2s": "",
                "team1_score": 1,
                "team2_score": 0,
                "roster_snapshot": json.dumps(
                    {
                        "version": 1,
                        "teams": {
                            "1": {
                                "team_id": None,
                                "registration_id": 77,
                                "name": name,
                                "players": [],
                            },
                            "2": {
                                "team_id": self.team_ids[1],
                                "registration_id": 88,
                                "name": "Opponent",
                                "players": [],
                            },
                        },
                    }
                ),
            }
            for number, name in ((1, "Old Name"), (2, "New Name"))
        }

    def test_registration_rename_keeps_one_team_ranking(self):
        rows = _event_team_rankings(self._renamed_matches())
        self.assertEqual(len(rows), 2)
        winner = next(row for row in rows if row["wins"])
        self.assertEqual((winner["match_count"], winner["wins"]), (2, 2))

    def test_registration_rename_is_not_a_player_transfer(self):
        self._prepare()
        second = self.conn.execute(
            "INSERT INTO matches(event_id,status) VALUES(?,'completed')", (self.event_id,)
        ).lastrowid
        self.conn.execute(
            """INSERT INTO match_stats(match_id,player_id,match_team_side,map_name,data_status)
               VALUES(?,?,'t1','de_nuke','final')""",
            (second, self.player_id),
        )
        self.conn.commit()
        original = self._renamed_matches()
        matches = {
            self.match_id: dict(original[1], id=self.match_id),
            second: dict(original[2], id=second),
        }
        result = _event_player_teams(self.conn, self.event_id, matches)
        self.assertIn(result[self.player_id], ("Old Name", "New Name"))

    def test_unchanged_form_is_a_noop_for_every_stored_column(self):
        self._prepare()
        before = self._all()
        self.assertEqual(self._post().status_code, 302)
        self.assertEqual(self._all(), before)

    def test_editing_one_field_preserves_extended_and_unknown_metrics(self):
        self._prepare()
        self.conn.execute(
            "UPDATE match_stats SET enemies_flashed=NULL WHERE match_id=?", (self.match_id,)
        )
        self.conn.commit()
        before = self._active()
        form = self._form()
        form[f"deaths_{self.player_id}"] = "11"
        self.assertEqual(self._post(form).status_code, 302)
        columns = (
            "first_kills",
            "clutches_won",
            "multi2k",
            "trade_kills",
            "flash_assists",
            "t_kills",
            "ct_kills",
            "enemies_flashed",
        )
        self.assertEqual(
            [[row[key] for key in columns] for row in self._active()],
            [[row[key] for key in columns] for row in before],
        )
        self.assertTrue(all(row["data_version"] == 2 for row in self._active()))

    def test_partial_or_nonfinite_submission_preserves_all_versions(self):
        self._prepare()
        before = self._all()
        forms = []
        missing = self._form()
        del missing[f"adr_{self.ids[-1]}"]
        forms.append(missing)
        for value in ("nan", "inf", "-1"):
            form = self._form()
            form[f"adr_{self.player_id}"] = value
            forms.append(form)
        for form in forms:
            with self.subTest(value=form.get(f"adr_{self.player_id}")):
                self.assertEqual(self._post(form).status_code, 400)
                self.assertEqual(self._all(), before)

    def _low_impact(self):
        self._prepare()
        self.conn.execute(
            """UPDATE match_stats SET kills=0,assists=0,impact=0,rating=0.32,kpr=0
               WHERE match_id=? AND player_id=?""",
            (self.match_id, self.player_id),
        )
        self.conn.commit()

    def test_raw_impact_survives_successive_manual_revisions(self):
        self._low_impact()
        for deaths in (11, 12):
            form = self._form()
            form[f"deaths_{self.player_id}"] = str(deaths)
            self.assertEqual(self._post(form).status_code, 302)
            row = next(row for row in self._active() if row["player_id"] == self.player_id)
            expected, _, _ = calculate_rating(0, deaths, 20, adr=50, kast=50, impact=-0.41)
            self.assertEqual(row["rating"], expected)
            self.assertAlmostEqual(row["rating_impact"], -0.41)
            self.assertEqual(row["impact"], 0)
            self.assertEqual(row["impact_method"], "csda_hltv2_regression_v1")

    def test_explicit_custom_impact_stays_custom_after_later_edits(self):
        self._prepare()
        form = self._form()
        form[f"impact_{self.player_id}"] = "1.9"
        self.assertEqual(self._post(form).status_code, 302)
        form = self._form()
        form[f"kills_{self.player_id}"] = "12"
        self.assertEqual(self._post(form).status_code, 302)
        row = next(row for row in self._active() if row["player_id"] == self.player_id)
        expected, _, _ = calculate_rating(12, 10, 20, adr=50, kast=50, impact=1.9)
        self.assertEqual(row["rating"], expected)
        self.assertEqual(row["impact_method"], "manual")
        self.assertEqual((row["impact"], row["rating_impact"]), (1.9, 1.9))

    def test_headshot_only_edit_preserves_rating_and_rounded_impact(self):
        self._prepare()
        # External parser ratings must not be recalculated for an unrelated edit.
        self.conn.execute("UPDATE match_stats SET rating=1.37 WHERE match_id=?", (self.match_id,))
        self.conn.commit()
        before = {row["player_id"]: (row["rating"], row["impact"]) for row in self._active()}
        form = self._form()
        form[f"hs_{self.player_id}"] = "41"
        self.assertEqual(self._post(form).status_code, 302)
        self.assertEqual(
            {row["player_id"]: (row["rating"], row["impact"]) for row in self._active()}, before
        )

    def test_actual_html_form_keeps_nulls_unknown(self):
        from tests.test_dot_stats_recovery import StatsForms

        self._prepare()
        self.conn.execute(
            "UPDATE match_stats SET adr=NULL,kast=NULL,rating=NULL WHERE match_id=?",
            (self.match_id,),
        )
        self.conn.commit()
        page = self.client.get(f"/admin/matches/{self.match_id}/stats")
        form = StatsForms(page.get_data(as_text=True)).for_map("de_nuke")["fields"]
        self.assertEqual(form[f"adr_{self.player_id}"], "")
        self.assertEqual(self._post(form).status_code, 302)
        self.assertTrue(
            all(
                row["adr"] is None and row["kast"] is None and row["rating"] is None
                for row in self._active()
            )
        )

    def test_hidden_team_id_cannot_reassign_statistics(self):
        self._prepare()
        form = self._form()
        form[f"team_id_{self.player_id}"] = str(self.team_ids[3])
        form[f"deaths_{self.player_id}"] = "11"
        self.assertEqual(self._post(form).status_code, 302)
        row = next(row for row in self._active() if row["player_id"] == self.player_id)
        self.assertEqual((row["team_id"], row["match_team_side"]), (self.team_ids[0], "t1"))

    def test_duplicate_snapshot_identity_rejects_the_whole_write(self):
        self._prepare()
        snapshot = json.loads(
            self.conn.execute(
                "SELECT roster_snapshot FROM matches WHERE id=?", (self.match_id,)
            ).fetchone()[0]
        )
        snapshot["teams"]["2"]["players"][0] = snapshot["teams"]["1"]["players"][0]
        self.conn.execute(
            "UPDATE matches SET roster_snapshot=? WHERE id=?", (json.dumps(snapshot), self.match_id)
        )
        self.conn.commit()
        before = self._all()
        self.assertEqual(self._post().status_code, 400)
        self.assertEqual(self._all(), before)

    def test_temporary_identity_ignores_slot_order_and_padding(self):
        first = {"team1_id": -1, "team1_players": json.dumps([None, 3, 1, 2])}
        second = {"team2_id": -2, "team2_players": json.dumps([2, 1, 3, None, None])}
        self.assertEqual(match_side_identity(first, 1), match_side_identity(second, 2))

    def test_same_name_different_registrations_remain_distinct(self):
        matches = self._renamed_matches()
        matches[2]["team1_registration_id"] = 99
        snapshot = json.loads(matches[2]["roster_snapshot"])
        snapshot["teams"]["1"]["registration_id"] = 99
        matches[2]["roster_snapshot"] = json.dumps(snapshot)
        matches[2]["team1_name"] = matches[1]["team1_name"]
        self.assertEqual(len(_event_team_rankings(matches)), 3)

    def test_demo_preview_uses_the_same_snapshot_orientation_as_import(self):
        self._prepare(snapshot_only=True)
        for index, player_id in enumerate(self.ids):
            self.conn.execute(
                "UPDATE players SET team_id=? WHERE id=?",
                (self.team_ids[1 if index < 5 else 0], player_id),
            )
        self.conn.commit()
        match = dict(
            self.conn.execute("SELECT * FROM matches WHERE id=?", (self.match_id,)).fetchone()
        )
        match.update(team1_name="Orion", team2_name="Lyra")
        profiles = {row["id"]: dict(row) for row in self.conn.execute("SELECT * FROM players")}
        players = [
            {
                "name": profiles[pid]["nickname"],
                "steam_id": profiles[pid]["steam_id"],
                "team_letter": "A" if index < 5 else "B",
            }
            for index, pid in enumerate(self.ids)
        ]
        info = {
            "team_a_name": "Counter-Terrorists",
            "team_b_name": "Terrorists",
            "team_a_score": 13,
            "team_b_score": 7,
            "rounds_count": 20,
            "map_name": "de_nuke",
            "source": "test",
        }
        with (
            patch("services.demo_service.run_analysis", return_value={}),
            patch("services.demo_service.parse_player_stats", return_value=players),
            patch("services.demo_service.get_match_info", return_value=info),
            patch("services.demo_service.build_demo_performance_payload", return_value={}),
            patch("services.demo_service._save_analysis_snapshot", return_value={}),
        ):
            preview = analyze_demo(self.conn, match, "unused.dem")
        self.assertTrue(preview["team_order_ok"])
        self.assertIn("Demo A → Orion", preview["team_map"])

    def test_metadata_migration_is_idempotent_and_does_not_rewrite_ratings(self):
        from models import _ensure_match_stats_data_version_columns

        self._low_impact()
        before = self._all()
        _ensure_match_stats_data_version_columns(self.conn.cursor())
        _ensure_match_stats_data_version_columns(self.conn.cursor())
        self.assertEqual(self._all(), before)


class RegisteredManualRoundtripTests(RegisteredMatchCase):
    def test_registration_only_lineup_is_used_by_editor_and_save(self):
        from tests.test_dot_stats_recovery import StatsForms

        self.conn.execute(
            "UPDATE matches SET status='live',map1_t1=13,map1_t2=7 WHERE id=?", (self.match_id,)
        )
        self.conn.commit()
        with rendered_contexts() as captured:
            response = self.client.get(f"/admin/matches/{self.match_id}/stats")
        self.assertEqual(response.status_code, 200)
        context = next(context for name, context in captured if name == "admin/match_stats.html")
        for side in (1, 2):
            self.assertEqual(
                {p["id"] for p in context[f"team{side}_players"]},
                {p["id"] for p in self.rosters[side]},
            )
        form = StatsForms(response.get_data(as_text=True)).for_map("de_nuke")["fields"]
        self.assertEqual(
            self.client.post(f"/admin/matches/{self.match_id}/stats", data=form).status_code, 302
        )
        saved = {
            row["player_id"]: row["match_team_side"]
            for row in self.conn.execute(
                "SELECT * FROM match_stats WHERE match_id=? AND data_status='final'",
                (self.match_id,),
            )
        }
        self.assertEqual(
            saved, {p["id"]: f"t{side}" for side in (1, 2) for p in self.rosters[side]}
        )

    def test_rename_endpoint_keeps_cards_count_and_rankings_consistent(self):
        self.conn.execute(
            "UPDATE matches SET status='completed',team1_score=2,team2_score=0 WHERE id=?",
            (self.match_id,),
        )
        self.conn.commit()
        response = self.client.post(
            f"/events/{self.event_id}/registrations/{self.registrations[1]}/rename",
            data={"csrf_token": "pro-logic-csrf", "team_name": "Renamed Registration"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(response.status_code, 200)
        new_id = self.conn.execute(
            """INSERT INTO matches(event_id,team1_id,team2_id,team1_registration_id,team2_registration_id,
               status,bo_format,team1_score,team2_score) VALUES(?,?,?,?,?,'completed','BO3',2,0)""",
            (
                self.event_id,
                self.team_ids[0],
                self.team_ids[1],
                self.registrations[1],
                self.registrations[2],
            ),
        ).lastrowid
        match = self.conn.execute("SELECT * FROM matches WHERE id=?", (new_id,)).fetchone()
        freeze_match_roster(self.conn, match, confirmed=True)
        self.conn.commit()
        self.assertEqual(_event_team_count(self.conn, self.event_id), 2)
        rankings = _event_team_rankings(_event_matches_with_teams(self.conn, self.event_id))
        self.assertEqual(
            sorted((row["match_count"], row["wins"]) for row in rankings), [(2, 0), (2, 2)]
        )
        with rendered_contexts() as captured:
            self.assertEqual(self.client.get(f"/events/{self.event_id}").status_code, 200)
        context = next(context for name, context in captured if name == "event_detail.html")
        self.assertEqual(len(context["teams"]), 2)


del ProDatabaseCase, RegisteredMatchCase
