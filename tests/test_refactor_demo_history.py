import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services.demo_service import (
    _infer_demo_team_order,
    _match_player_from_db,
    _save_analysis_snapshot,
    import_demo_data,
    insert_match_stat,
    save_halftime_data,
    sync_match_scores,
)
from services.performance_service import backfill_demo_performance, build_demo_performance_payload
from services.player_service import merge_player_records
from tests.test_refactor_stats_consistency import StatsDatabaseCase, add_stat
from utils.demo_parser import get_match_info, parse_player_stats, run_analysis


class DemoCalculationTests(unittest.TestCase):
    def test_demo_impact_matches_csda_rating_inputs(self):
        data = {
            "players": {
                "111": {
                    "name": "Audit",
                    "team": {"letter": "A"},
                    "killCount": 20,
                    "deathCount": 10,
                    "assistCount": 5,
                    "hltvRating2": 1.22,
                }
            },
            "rounds": [
                {"number": number, "teamASide": 2, "teamBSide": 3} for number in range(1, 21)
            ],
        }
        player = parse_player_stats(data)[0]
        self.assertAlmostEqual(player["impact"], round(2.13 + 0.42 * 0.25 - 0.41, 2))
        self.assertEqual(player["impact_method"], "csda_hltv2_regression_v1")

    def test_missing_demo_metrics_remain_unknown_and_no_round_is_invented(self):
        player = parse_player_stats(
            {"players": {"111": {"name": "Audit", "team": {"letter": "A"}}}}
        )[0]
        for field in ("impact", "rating", "adr", "kast", "headshot_percentage", "he_count"):
            self.assertIsNone(player[field], field)
        self.assertEqual(player["rounds_played"], 0)
        self.assertIsNone(player["t_rating"])

    def test_explicit_zero_demo_metrics_are_not_missing(self):
        player = parse_player_stats(
            {
                "players": {
                    "111": {
                        "name": "Audit",
                        "team": {"letter": "A"},
                        "killCount": 0,
                        "assistCount": 0,
                        "hltvRating2": 0,
                        "kast": 0,
                        "headshotPercent": 0,
                    }
                },
                "rounds": [{"number": 1, "teamASide": 2, "teamBSide": 3}],
            }
        )[0]
        self.assertEqual(player["rating"], 0)
        self.assertEqual(player["kast"], 0)
        # 回归公式算出 -0.41，保存的 Impact 最低记 0（真实的 0 仍是 0，不会变成“没有数据”）
        self.assertEqual(player["impact"], 0)

    def test_match_roster_beats_players_current_team_after_transfer(self):
        result = _infer_demo_team_order(
            {},
            {"team1_name": "Alpha", "team2_name": "Bravo"},
            {1},
            {2},
            [{"id": 1, "team_id": 20}, {"id": 2, "team_id": 10}],
            {1},
            {2},
            10,
            20,
        )
        self.assertIs(result, True)

    def test_b_team_roster_can_resolve_order_when_a_is_unknown(self):
        self.assertIs(
            _infer_demo_team_order(
                {}, {}, set(), {2}, [{"id": 2, "team_id": None}], {1}, {2}, None, None
            ),
            True,
        )

    def test_contradictory_team_names_do_not_silently_pick_first_match(self):
        self.assertIsNone(
            _infer_demo_team_order(
                {"team_a_name": "Alpha", "team_b_name": "Alpha"},
                {"team1_name": "Alpha", "team2_name": "Bravo"},
                set(),
                set(),
                [],
                set(),
                set(),
                10,
                20,
            )
        )

    def test_duplicate_nickname_does_not_attach_unknown_steam_to_first_player(self):
        players = [
            {"id": 1, "steam_id": "111", "nickname": "Same"},
            {"id": 2, "steam_id": "222", "nickname": "Same"},
        ]
        self.assertIsNone(_match_player_from_db({"name": "Same", "steam_id": "333"}, players, {}))


class DemoHistoryTests(StatsDatabaseCase):
    def test_completed_demo_score_correction_reconciles_prediction_in_same_transaction(self):
        self.conn.execute(
            "UPDATE matches SET bo_format='BO1', team1_score=1, team2_score=0, map1_t1=13, map1_t2=7 WHERE id=?",
            (self.match_id,),
        )
        user_id = self.conn.execute(
            "INSERT INTO users(username,password_hash) VALUES('prediction-fixture','unused')"
        ).lastrowid
        self.conn.execute(
            """INSERT INTO match_votes(match_id,user_id,voted_for,score1_guess,score2_guess,scored,points_earned)
               VALUES(?,?,'t1',1,0,1,8)""",
            (self.match_id, user_id),
        )
        sync_match_scores(
            self.conn, self.match_id, 0, {"team_a_score": 7, "team_b_score": 13}, True
        )
        vote = self.conn.execute("SELECT points_earned,scored FROM match_votes").fetchone()
        self.assertEqual(tuple(vote), (0, 1))

    def test_prediction_reconciliation_failure_rolls_back_demo_scores_and_points(self):
        from models import db
        from services.match_service import score_predictions

        self.conn.execute(
            "UPDATE matches SET bo_format='BO1', team1_score=1, team2_score=0, map1_t1=13, map1_t2=7 WHERE id=?",
            (self.match_id,),
        )
        user_id = self.conn.execute(
            "INSERT INTO users(username,password_hash) VALUES('rollback-fixture','unused')"
        ).lastrowid
        self.conn.execute(
            """INSERT INTO match_votes(match_id,user_id,voted_for,scored,points_earned)
               VALUES(?,?,'t1',1,8)""",
            (self.match_id, user_id),
        )
        self.conn.commit()

        def failing_reconcile(conn, match_id):
            score_predictions(conn, match_id)
            raise RuntimeError("积分故障注入")

        with patch(
            "services.demo_service.score_predictions", side_effect=failing_reconcile, create=True
        ):
            with self.assertRaisesRegex(RuntimeError, "积分故障"):
                with db() as conn:
                    sync_match_scores(
                        conn, self.match_id, 0, {"team_a_score": 7, "team_b_score": 13}, True
                    )
        score = self.conn.execute(
            "SELECT team1_score,team2_score,map1_t1,map1_t2 FROM matches"
        ).fetchone()
        vote = self.conn.execute("SELECT points_earned FROM match_votes").fetchone()
        self.assertEqual(tuple(score), (1, 0, 13, 7))
        self.assertEqual(vote[0], 8)

    def test_final_demo_confirms_only_its_own_map_not_other_live_scores(self):
        self.conn.execute(
            "UPDATE matches SET map1_t1=6, map1_t2=5, map2_t1=11, map2_t2=10 WHERE id=?",
            (self.match_id,),
        )
        self.conn.execute(
            "INSERT INTO live_match_data(match_id, live_state) VALUES(?, ?)",
            (
                self.match_id,
                json.dumps({"unconfirmed_map_slots": [0, 1], "marker": {"keep": True}}),
            ),
        )
        self.assertTrue(
            sync_match_scores(
                self.conn, self.match_id, 0, {"team_a_score": 13, "team_b_score": 7}, True
            )
        )
        scores = self.conn.execute(
            "SELECT team1_score, team2_score FROM matches WHERE id=?", (self.match_id,)
        ).fetchone()
        self.assertEqual(tuple(scores), (1, 0))
        state = json.loads(
            self.conn.execute(
                "SELECT live_state FROM live_match_data WHERE match_id=?", (self.match_id,)
            ).fetchone()[0]
        )
        self.assertEqual(state["unconfirmed_map_slots"], [1])
        self.assertEqual(state["marker"], {"keep": True})

    def test_merged_current_result_survives_database_reinitialization(self):
        from models import init_tables

        target_id = self.conn.execute("INSERT INTO players(nickname) VALUES('Retained')").lastrowid
        add_stat(
            self.conn,
            self.match_id,
            target_id,
            self.team1,
            "Mirage",
            kills=10,
            data_status="final",
            data_version=3,
        )
        add_stat(
            self.conn,
            self.match_id,
            self.player_id,
            self.team1,
            "Mirage",
            kills=40,
            data_status="superseded",
            data_version=1,
        )
        merge_player_records(self.conn, self.player_id, target_id)
        self.conn.commit()
        init_tables()
        current = self.conn.execute(
            "SELECT kills, data_version FROM match_stats WHERE data_status='final'"
        ).fetchall()
        self.assertEqual([tuple(row) for row in current], [(10, 3)])

    def test_player_merge_transfers_published_yearly_award(self):
        target_id = self.conn.execute("INSERT INTO players(nickname) VALUES('Retained')").lastrowid
        self.conn.execute(
            "INSERT INTO yearly_top_players(year, rank, player_id) VALUES(2026, 1, ?)",
            (self.player_id,),
        )
        merge_player_records(self.conn, self.player_id, target_id)
        rows = self.conn.execute("SELECT player_id, year, rank FROM yearly_top_players").fetchall()
        self.assertEqual([tuple(row) for row in rows], [(target_id, 2026, 1)])

    def test_conflicting_published_awards_stop_merge_before_any_change(self):
        target_id = self.conn.execute("INSERT INTO players(nickname) VALUES('Retained')").lastrowid
        self.conn.execute(
            "INSERT INTO yearly_top_players(year, rank, player_id) VALUES(2026, 1, ?)",
            (self.player_id,),
        )
        self.conn.execute(
            "INSERT INTO yearly_top_players(year, rank, player_id) VALUES(2026, 2, ?)", (target_id,)
        )
        with self.assertRaisesRegex(ValueError, "年度排名"):
            merge_player_records(self.conn, self.player_id, target_id)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM players").fetchone()[0], 2)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM player_nickname_history").fetchone()[0], 0
        )

    def test_missing_demo_scores_do_not_clear_recorded_result(self):
        self.conn.execute("UPDATE matches SET map1_t1=13, map1_t2=7 WHERE id=?", (self.match_id,))
        self.assertFalse(sync_match_scores(self.conn, self.match_id, 0, {}, True))
        row = self.conn.execute(
            "SELECT map1_t1, map1_t2 FROM matches WHERE id=?", (self.match_id,)
        ).fetchone()
        self.assertEqual(tuple(row), (13, 7))

    def test_analysis_snapshots_are_append_only_and_metadata_has_import_version(self):
        payload = build_demo_performance_payload({"rounds": [], "kills": []})
        with patch("services.demo_service.BASE_DIR", self.temp_dir.name):
            first = _save_analysis_snapshot(payload)
            first_path = Path(self.temp_dir.name) / "static" / "demos" / first["snapshot"]
            first_content = first_path.read_bytes()
            second = _save_analysis_snapshot(payload)
            self.assertNotEqual(first["snapshot"], second["snapshot"])
            self.assertEqual(first_path.read_bytes(), first_content)
            second["data_version"] = 4
            save_halftime_data(self.conn, self.match_id, 0, {"info": {"analysis": second}}, True)
        saved = json.loads(
            self.conn.execute(
                "SELECT map_halves FROM matches WHERE id=?", (self.match_id,)
            ).fetchone()[0]
        )
        self.assertEqual(saved["0"]["analysis"]["data_version"], 4)
        self.assertFalse(saved["0"]["analysis"]["official_hltv_formula"])
        self.assertEqual(json.loads(first_content)["state"], "preview")

    def test_missing_import_metric_is_null_not_a_zero_score(self):
        insert_match_stat(
            self.conn, self.match_id, self.player_id, self.team1, "t1", {"kills": 0}, "Mirage"
        )
        stat = self.conn.execute("SELECT * FROM match_stats").fetchone()
        self.assertEqual(stat["kills"], 0)
        for field in ("impact", "rating", "assists", "rws_basic", "flash_count"):
            self.assertIsNone(stat[field], field)

    def test_player_merge_keeps_newer_current_result_and_old_versions(self):
        conn, _, match_id, player_id, team1, _ = self.stats_database
        target_id = conn.execute("INSERT INTO players(nickname) VALUES('Retained')").lastrowid
        add_stat(
            conn,
            match_id,
            player_id,
            team1,
            "Mirage",
            kills=40,
            data_status="superseded",
            data_version=1,
        )
        add_stat(
            conn,
            match_id,
            player_id,
            team1,
            "Mirage",
            kills=10,
            data_status="final",
            data_version=3,
        )
        add_stat(
            conn,
            match_id,
            target_id,
            team1,
            "Mirage",
            kills=20,
            data_status="final",
            data_version=2,
        )
        merge_player_records(conn, player_id, target_id)
        current = conn.execute(
            "SELECT * FROM match_stats WHERE data_status <> 'superseded'"
        ).fetchall()
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["kills"], 10)
        self.assertEqual(current[0]["data_version"], 3)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM match_stats").fetchone()[0], 3)

    def test_duplicate_demo_identity_rejected_before_current_rows_are_superseded(self):
        conn, _, match_id, player_id, team1, team2 = self.stats_database
        add_stat(conn, match_id, player_id, team1, "Mirage", kills=4)
        match = conn.execute(
            """SELECT m.*, 'Alpha' AS team1_name, 'Bravo' AS team2_name
                            FROM matches m WHERE id=?""",
            (match_id,),
        ).fetchone()
        data = {
            "info": {"map_name": "Mirage", "team_a_name": "Alpha", "team_b_name": "Bravo"},
            "players": [
                {"name": "Audit Player", "steam_id": "111", "team_letter": side, "rating": 1.0}
                for side in ("A", "B")
            ],
        }
        imported, message = import_demo_data(conn, match_id, match, json.dumps(data), 0)
        self.assertIsNone(imported)
        self.assertIn("重复", message)
        self.assertEqual(conn.execute("SELECT data_status FROM match_stats").fetchone()[0], "final")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM match_stats").fetchone()[0], 1)

    def test_backfill_keeps_superseded_history_unchanged(self):
        conn, _, match_id, player_id, team1, _ = self.stats_database
        add_stat(
            conn,
            match_id,
            player_id,
            team1,
            "Mirage",
            kills=4,
            clutch_1v5=7,
            clutches_won=7,
            rws_basic=8,
            data_status="superseded",
            data_version=1,
        )
        add_stat(conn, match_id, player_id, team1, "Mirage", kills=5, data_version=2)
        parsed = [
            {
                "steam_id": "111",
                "name": "Audit Player",
                "clutch_1v2": 1,
                "clutches_won": 1,
                "rws_basic": 3.5,
            }
        ]
        with patch("utils.demo_parser.parse_player_stats", return_value=parsed):
            backfill_demo_performance(conn, match_id, "Mirage", {})
        old = conn.execute("SELECT * FROM match_stats WHERE data_status='superseded'").fetchone()
        self.assertEqual(old["clutch_1v5"], 7)
        self.assertEqual(old["clutches_won"], 7)
        self.assertEqual(old["rws_basic"], 8)


class DemoRawDataTests(unittest.TestCase):
    def test_null_flash_events_are_unknown_not_a_recorded_zero(self):
        payload = build_demo_performance_payload(
            {"players": {"111": {"name": "Audit"}}, "flashbangsExplode": None}
        )
        for metric in payload["flash_metrics"]:
            self.assertIsNone(metric["flash_count"])

    def test_flash_only_payload_does_not_invent_blinding_or_assist_metrics(self):
        payload = build_demo_performance_payload(
            {"players": {"111": {"name": "Audit"}}, "flashbangsExplode": []}
        )
        metric = payload["flash_metrics"][0]
        self.assertEqual(metric["flash_count"], 0)
        self.assertIsNone(metric["blinded_seconds"])
        self.assertIsNone(metric["enemy_seconds"])
        self.assertIsNone(metric["flash_assists"])

    def test_regulation_halves_exclude_overtime_and_unknown_winners(self):
        info = get_match_info(
            {
                "rounds": [
                    {"teamASide": 3, "winnerSide": 3, "overtimeNumber": 0},
                    {"teamASide": 2, "winnerSide": 2, "overtimeNumber": 0},
                    {"teamASide": 3, "winnerSide": 3, "overtimeNumber": 1},
                    {},
                ]
            }
        )
        self.assertEqual(info["halftime"], {"h1_a": 1, "h1_b": 0, "h2_a": 1, "h2_b": 0})
        self.assertIsNone(info["team_a_score"])

    def test_parser_cannot_mistake_old_json_for_successful_new_output(self):
        with tempfile.TemporaryDirectory(prefix="refactor-parser-") as directory:
            path = Path(directory)
            demo = path / "sample.dem"
            demo.write_bytes(b"PBDEMS2")
            (path / "unrelated.json").write_text('{"mapName":"old"}', encoding="utf-8")
            with (
                patch("utils.demo_parser.find_csda", return_value="csda"),
                patch(
                    "utils.demo_parser.subprocess.run",
                    return_value=SimpleNamespace(returncode=0, stderr=""),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "JSON"):
                    run_analysis(str(demo), str(path))

    def test_grenade_event_counts_distinguish_zero_from_missing(self):
        data = {
            "players": {"111": {"name": "Audit", "team": {"letter": "A"}}},
            "heGrenadesExplode": [{"throwerSteamId": "111"}, {"throwerSteamId": "111"}],
            "smokesStart": [],
        }
        player = parse_player_stats(data)[0]
        self.assertEqual(player["he_count"], 2)
        self.assertEqual(player["smoke_count"], 0)
        self.assertIsNone(player["molotov_count"])

    def test_rich_payload_preserves_available_events_and_marks_missing(self):
        data = {
            "checksum": "sample-checksum",
            "rounds": [{"number": 1, "winnerSide": 3}],
            "damages": [{"roundNumber": 1, "healthDamage": 34}],
            "playerEconomies": [],
            "bombsPlanted": [{"roundNumber": 1}],
            "kills": [],
        }
        payload = build_demo_performance_payload(data)
        self.assertEqual(payload["analysis"]["schema_version"], 2)
        self.assertEqual(payload["analysis"]["impact_method"], "csda_hltv2_regression_v1")
        self.assertFalse(payload["analysis"]["official_hltv_formula"])
        self.assertEqual(payload["raw_events"]["damages"], data["damages"])
        self.assertEqual(payload["raw_events"]["playerEconomies"], [])
        self.assertIsNone(payload["raw_events"]["playersBuy"])
        self.assertNotIn("playersBuy", data)

    def test_side_without_rounds_has_no_rating_and_missing_damage_is_not_zero(self):
        data = {
            "players": {
                "111": {
                    "name": "Audit",
                    "team": {"letter": "A"},
                    "killCount": 0,
                    "deathCount": 0,
                    "assistCount": 0,
                    "kast": 100,
                }
            },
            "rounds": [{"number": 1, "teamASide": 2, "teamBSide": 3}],
            "kills": [],
        }
        player = parse_player_stats(data)[0]
        self.assertIsNone(player["ct_rating"])
        self.assertIsNone(player["t_adr"])
        self.assertIsNone(player["t_rating"])

    def test_missing_damage_events_do_not_create_zero_rws(self):
        player = parse_player_stats(
            {
                "players": {"111": {"name": "Audit", "team": {"letter": "A"}}},
                "rounds": [{"number": 1}],
            }
        )[0]
        self.assertIsNone(player["damage_delta_per_round"])
        self.assertIsNone(player["rws_basic"])
