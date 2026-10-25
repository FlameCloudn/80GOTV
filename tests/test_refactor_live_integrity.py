import json
import threading
import unittest
from copy import deepcopy
from unittest.mock import patch

from config import Config
from models import get_db
from routes.live import _format_live_timer, _gsi_team_mapping
from services.live_service import _parse_gsi_coordinates
from tests import test_broadcast_map_result as broadcast_tests
from tests import test_live_data_stream as stream_tests


class RefactorLiveResultTests(broadcast_tests.BroadcastMapResultTests):
    def _snapshot(self):
        conn = get_db()
        try:
            return {
                table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
                for table in ("matches", "match_stats", "live_match_data", "players", "users")
            }
        finally:
            conn.close()

    def _update(self, **values):
        conn = get_db()
        conn.execute(
            "UPDATE matches SET " + ",".join(f"{key}=?" for key in values) + " WHERE id=?",
            (*values.values(), self.match_id),
        )
        conn.commit()
        conn.close()

    def test_nonfinite_fractional_negative_and_text_scores_are_rejected_without_writes(self):
        for value in (float("nan"), float("inf"), -1, 13.5, "invalid", True):
            with self.subTest(value=str(value)):
                payload = self._payload()
                payload["team1_score"] = value
                before = self._snapshot()
                response = self._post(payload)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(self._snapshot(), before)

    def test_invalid_player_numbers_are_not_clamped_into_real_stats(self):
        for value in (float("nan"), float("inf"), -1, 1.5, "invalid", True):
            with self.subTest(value=str(value)):
                payload = self._payload()
                payload["players"][0]["kills"] = value
                before = self._snapshot()
                response = self._post(payload)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(self._snapshot(), before)

    def test_missing_assists_stays_unknown_instead_of_fabricating_impact_or_rating(self):
        payload = self._payload()
        payload["players"][0].pop("assists")
        response = self._post(payload)
        self.assertEqual(response.status_code, 200)
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT * FROM match_stats WHERE player_id=?", (self.player1_id,)
            ).fetchone()
            self.assertIsNone(row["assists"])
            self.assertIsNone(row["impact"])
            self.assertIsNone(row["rating"])
            self.assertEqual(row["kpr"], 1)
            self.assertIsNone(row["t_rating"])
        finally:
            conn.close()

    def test_new_live_rating_uses_the_same_documented_formula_as_new_demos(self):
        response = self._post()
        self.assertEqual(response.status_code, 200)
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT impact,rating FROM match_stats WHERE player_id=?", (self.player1_id,)
            ).fetchone()
            self.assertAlmostEqual(row["impact"], 1.846)
            self.assertEqual(row["rating"], 1.51)
        finally:
            conn.close()

    def test_duplicate_steam_identity_is_rejected_even_without_ten_player_lock(self):
        payload = self._payload()
        payload["players"][1]["steam_id"] = payload["players"][0]["steam_id"]
        before = self._snapshot()
        self.assertEqual(self._post(payload).status_code, 409)
        self.assertEqual(self._snapshot(), before)

    def test_one_invalid_player_does_not_silently_replace_a_full_map_with_partial_stats(self):
        payload = self._payload()
        payload["players"][1]["name"] = ""
        before = self._snapshot()
        self.assertEqual(self._post(payload).status_code, 400)
        self.assertEqual(self._snapshot(), before)

    def test_map_slots_outside_bo_limit_are_rejected(self):
        self._update(bo_format="BO1")
        payload = self._payload()
        payload["map_name"] = "de_mirage"
        before = self._snapshot()
        self.assertEqual(self._post(payload).status_code, 409)
        self.assertEqual(self._snapshot(), before)

    def test_ambiguous_repeated_map_requires_an_explicit_slot(self):
        self._update(map2="de_nuke")
        before = self._snapshot()
        self.assertEqual(self._post().status_code, 409)
        self.assertEqual(self._snapshot(), before)

    def test_same_result_id_with_different_content_is_a_conflict_not_a_duplicate(self):
        payload = self._payload()
        payload["result_id"] = "same-result"
        self.assertEqual(self._post(payload).status_code, 200)
        before = self._snapshot()
        payload["team2_score"] = 8
        response = self._post(payload)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self._snapshot(), before)

    def test_series_complete_claim_cannot_end_an_incomplete_bo3(self):
        payload = self._payload()
        payload["series_complete"] = True
        before = self._snapshot()
        self.assertEqual(self._post(payload).status_code, 409)
        self.assertEqual(self._snapshot(), before)

    def test_actual_series_completion_is_derived_without_auto_finishing_the_match(self):
        self._update(map1_t1=13, map1_t2=7, team1_score=1, team2_score=0)
        payload = self._payload()
        payload["map_name"] = "de_mirage"
        response = self._post(payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["series_complete"])
        conn = get_db()
        try:
            match = conn.execute(
                "SELECT status,team1_score,team2_score FROM matches WHERE id=?", (self.match_id,)
            ).fetchone()
            self.assertEqual(tuple(match), ("live", 2, 0))
            state = json.loads(
                conn.execute(
                    "SELECT live_state FROM live_match_data WHERE match_id=?", (self.match_id,)
                ).fetchone()[0]
            )
            self.assertTrue(state["latest_map_result"]["series_complete"])
        finally:
            conn.close()

    def test_an_extra_map_cannot_be_added_after_the_series_is_decided(self):
        self._update(map1_t1=13, map1_t2=7, map2_t1=13, map2_t2=8, team1_score=2, team2_score=0)
        payload = self._payload()
        payload["map_name"] = "de_dust2"
        before = self._snapshot()
        self.assertEqual(self._post(payload).status_code, 409)
        self.assertEqual(self._snapshot(), before)

    def test_tied_final_map_is_rejected(self):
        payload = self._payload()
        payload["team2_score"] = 13
        self.assertEqual(self._post(payload).status_code, 400)

    def test_a_late_failure_rolls_back_scores_stats_and_live_state_together(self):
        payload = self._payload()
        self.assertEqual(self._post(payload).status_code, 200)
        before = self._snapshot()
        payload["result_id"] = "replacement-failure"
        with (
            self.assertLogs("80gotv", level="ERROR"),
            patch(
                "routes.live_ingest.refresh_player_performance",
                side_effect=RuntimeError("测试保存故障"),
            ),
        ):
            self.assertEqual(self._post(payload).status_code, 500)
        self.assertEqual(self._snapshot(), before)

    def test_concurrent_retries_create_one_stat_version_only(self):
        first_ready, second_ready = threading.Event(), threading.Event()
        release_first, first_done = threading.Event(), threading.Event()
        responses, errors = {}, []

        class ControlledConnection:
            def __init__(self, connection):
                self.connection = connection

            def __getattr__(self, name):
                return getattr(self.connection, name)

            def execute(self, sql, *args):
                if sql.lstrip().startswith("UPDATE match_stats SET data_status"):
                    if (
                        threading.current_thread().name == "result-first"
                        and not first_ready.is_set()
                    ):
                        first_ready.set()
                        if not release_first.wait(5):
                            raise AssertionError("等待首次结算恢复超时")
                    elif (
                        threading.current_thread().name == "result-second"
                        and not second_ready.is_set()
                    ):
                        second_ready.set()
                        if not first_done.wait(5):
                            raise AssertionError("等待首次结算提交超时")
                return self.connection.execute(sql, *args)

        def send(name):
            try:
                client = self.client.application.test_client()
                responses[name] = client.post(
                    f"/api/broadcast/matches/{self.match_id}/map-result",
                    json=self._payload(),
                    headers={"X-80GOTV-Token": Config.GSI_TOKEN},
                )
            except Exception as exc:
                errors.append(exc)
            finally:
                if name == "first":
                    first_done.set()

        first = threading.Thread(name="result-first", target=send, args=("first",))
        second = threading.Thread(name="result-second", target=send, args=("second",))
        with (
            patch("routes.live_ingest.get_db", side_effect=lambda: ControlledConnection(get_db())),
            patch("routes.live_ingest.rate_limit", return_value=True),
            patch("services.demo_service.enrich_player_from_steam"),
        ):
            first.start()
            try:
                self.assertTrue(first_ready.wait(5))
                second.start()
                second_ready.wait(0.15)
            finally:
                release_first.set()
                first.join(10)
                if second.ident is not None:
                    second.join(10)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(responses["first"].status_code, 200)
        self.assertEqual(responses["second"].status_code, 200)
        self.assertTrue(responses["second"].get_json().get("duplicate"))
        conn = get_db()
        try:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM match_stats WHERE match_id=?", (self.match_id,)
                ).fetchone()[0],
                2,
            )
        finally:
            conn.close()


class RefactorGSIValidationTests(stream_tests.LiveDataStreamTests):
    def test_halftime_transition_uses_the_previous_sides_for_the_finished_round(self):
        before = self._payload()
        before["map"]["round"] = 11
        before["bomb"] = {}
        self.assertEqual(self._post(before).status_code, 200)
        switched = self._payload()
        switched["bomb"] = {}
        switched["map"]["round"] = 12
        switched["map"]["team_ct"]["name"] = "Golden Eight"
        switched["map"]["team_t"]["name"] = "Ultimate Eight"
        switched["allplayers"]["111"]["team"] = "CT"
        switched["allplayers"]["222"]["team"] = "T"
        switched["_80gotv"].update({"team_ct": "team1", "team_t": "team2"})
        switched["previously"]["round"] = {"win_team": "CT"}
        self.assertEqual(self._post(switched).status_code, 200)
        conn = get_db()
        try:
            state = json.loads(
                conn.execute(
                    "SELECT live_state FROM live_match_data WHERE match_id=?", (self.match_id,)
                ).fetchone()[0]
            )
            self.assertEqual(state["round_history"][-1]["winner"], "t2")
        finally:
            conn.close()
        live = self.client.get(f"/api/live/{self.match_id}").get_json()
        self.assertEqual(live["side_mapping"], {"CT": "team1", "T": "team2"})

    def test_old_app_round_events_do_not_flip_winner_when_resent_after_halftime(self):
        before = self._payload()
        before["map"]["round"] = 1
        before["_80gotv"]["round_events"] = [
            {"id": "round-1-t", "round_number": 1, "winner_side": "T"}
        ]
        self.assertEqual(self._post(before).status_code, 200)
        switched = deepcopy(before)
        switched["map"]["round"] = 13
        switched["map"]["team_ct"]["name"] = "Golden Eight"
        switched["map"]["team_t"]["name"] = "Ultimate Eight"
        switched["allplayers"]["111"]["team"] = "CT"
        switched["allplayers"]["222"]["team"] = "T"
        switched["_80gotv"].update({"team_ct": "team1", "team_t": "team2"})
        self.assertEqual(self._post(switched).status_code, 200)
        live = self.client.get(f"/api/live/{self.match_id}").get_json()
        self.assertEqual(live["round_history"][0]["winner"], "t1")

    def test_malformed_numeric_and_nested_shapes_are_rejected_before_database_work(self):
        values = []
        payload = self._payload()
        payload["map"]["round"] = "invalid"
        values.append(payload)
        payload = self._payload()
        payload["_80gotv"] = ["invalid"]
        values.append(payload)
        payload = self._payload()
        payload["_80gotv"]["team_ct"] = []
        values.append(payload)
        payload = self._payload()
        payload["allplayers"]["111"]["state"]["health"] = float("nan")
        values.append(payload)
        payload = self._payload()
        payload["allplayers"]["111"]["weapons"]["weapon_0"] = []
        values.append(payload)
        values.append(["invalid"])
        for payload in values:
            with self.subTest(payload_type=type(payload).__name__):
                with patch("routes.live_ingest.get_db") as opened:
                    response = self._post(payload)
                    self.assertEqual(response.status_code, 400)
                    opened.assert_not_called()

    def test_disabled_bo_map_cannot_receive_live_frames(self):
        conn = get_db()
        conn.execute("UPDATE matches SET bo_format='BO1' WHERE id=?", (self.match_id,))
        conn.commit()
        conn.close()
        payload = self._payload()
        payload["map"]["name"] = "de_mirage"
        self.assertEqual(self._post(payload).status_code, 409)


class RefactorGotvTests(broadcast_tests.BroadcastMapResultTests):
    def setUp(self):
        super().setUp()
        self.original_gotv_secret = Config.GOTV_SECRET
        Config.GOTV_SECRET = "gotv-integrity-test"

    def tearDown(self):
        Config.GOTV_SECRET = self.original_gotv_secret
        super().tearDown()

    def _gotv_payload(self):
        return {
            "match_id": self.match_id,
            "map_name": "de_nuke",
            "team_a_name": "Golden Eight",
            "team_b_name": "Ultimate Eight",
            "team_a_score": 6,
            "team_b_score": 5,
            "rounds_count": 11,
            "players": [
                {
                    "steam_id": "111",
                    "name": "False Emperor",
                    "team_letter": "A",
                    "kills": 20,
                    "deaths": 12,
                    "assists": 6,
                    "adr": 90,
                    "kast": 80,
                },
                {
                    "steam_id": "222",
                    "name": "Aurora",
                    "team_letter": "B",
                    "kills": 15,
                    "deaths": 16,
                    "assists": 2,
                    "adr": 71,
                    "kast": 70,
                },
            ],
        }

    def _post_gotv(self, payload):
        with (
            patch("routes.live_ingest.rate_limit", return_value=True),
            patch("services.demo_service.enrich_player_from_steam"),
        ):
            return self.client.post(
                "/api/gotv/stats",
                json=payload,
                headers={"X-GOTV-Secret": Config.GOTV_SECRET},
            )

    def test_mid_map_six_five_does_not_award_a_series_map_win(self):
        response = self._post_gotv(self._gotv_payload())
        self.assertEqual(response.status_code, 200)
        conn = get_db()
        try:
            match = conn.execute(
                "SELECT map1_t1,map1_t2,team1_score,team2_score,status FROM matches WHERE id=?",
                (self.match_id,),
            ).fetchone()
            self.assertEqual(tuple(match), (6, 5, 0, 0, "live"))
            state = json.loads(
                conn.execute(
                    "SELECT live_state FROM live_match_data WHERE match_id=?", (self.match_id,)
                ).fetchone()[0]
            )
            self.assertEqual(state["unconfirmed_map_slots"], [0])
        finally:
            conn.close()

    def test_both_team_names_must_agree_before_replacing_gotv_stats(self):
        payload = self._gotv_payload()
        payload["team_b_name"] = "Unrelated Team"
        self.assertEqual(self._post_gotv(payload).status_code, 409)

    def test_mid_map_relay_cannot_replace_already_confirmed_demo_stats(self):
        conn = get_db()
        conn.execute(
            """INSERT INTO match_stats(match_id,player_id,team_id,map_name,kills,data_status,data_source)
               VALUES(?,?,?,'Nuke',42,'final','demo')""",
            (self.match_id, self.player1_id, self.team1_id),
        )
        conn.commit()
        conn.close()
        self.assertEqual(self._post_gotv(self._gotv_payload()).status_code, 409)
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT kills,data_status,data_source FROM match_stats WHERE match_id=?",
                (self.match_id,),
            ).fetchall()
            self.assertEqual([tuple(row) for row in rows], [(42, "final", "demo")])
        finally:
            conn.close()

    def test_missing_identity_or_unknown_team_letter_cannot_be_silently_assigned(self):
        for key, value in (("steam_id", ""), ("team_letter", "unknown")):
            with self.subTest(field=key):
                payload = self._gotv_payload()
                payload["players"][0][key] = value
                self.assertEqual(self._post_gotv(payload).status_code, 400)

    def test_secondary_relay_metrics_are_validated_too(self):
        for key, value in (("t_rating", "NaN"), ("utility_damage", -1), ("flash_count", 1.5)):
            with self.subTest(field=key):
                payload = self._gotv_payload()
                payload["players"][0][key] = value
                self.assertEqual(self._post_gotv(payload).status_code, 400)

    def test_new_gotv_stats_use_server_formula_instead_of_client_supplied_rating(self):
        payload = self._gotv_payload()
        payload["rounds_count"] = 20
        payload["players"][0].update({"impact": 99, "rating": 99})
        self.assertEqual(self._post_gotv(payload).status_code, 200)
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT impact,rating FROM match_stats WHERE player_id=?", (self.player1_id,)
            ).fetchone()
            self.assertAlmostEqual(row["impact"], 1.846)
            self.assertEqual(row["rating"], 1.51)
        finally:
            conn.close()

    def test_only_explicitly_confirmed_maps_count_after_multiple_relay_frames(self):
        self.assertEqual(self._post_gotv(self._gotv_payload()).status_code, 200)
        second = self._gotv_payload()
        second.update({"map_name": "de_mirage", "team_a_score": 9, "team_b_score": 8})
        self.assertEqual(self._post_gotv(second).status_code, 200)
        first_final = self._payload()
        self.assertEqual(self._post(first_final).status_code, 200)
        conn = get_db()
        try:
            match = conn.execute(
                "SELECT team1_score,team2_score FROM matches WHERE id=?", (self.match_id,)
            ).fetchone()
            self.assertEqual(tuple(match), (1, 0))
            state = json.loads(
                conn.execute(
                    "SELECT live_state FROM live_match_data WHERE match_id=?", (self.match_id,)
                ).fetchone()[0]
            )
            self.assertEqual(state["unconfirmed_map_slots"], [1])
            self.assertFalse(state["latest_map_result"]["series_complete"])
        finally:
            conn.close()


class RefactorLiveHelperTests(unittest.TestCase):
    def test_nonfinite_radar_coordinates_are_not_returned(self):
        for value in ("NaN, 20, 0", "10, inf, 0", [10, 20, float("inf")]):
            self.assertIsNone(_parse_gsi_coordinates(value))

    def test_nonfinite_timer_is_unknown_instead_of_crashing(self):
        for value in (float("inf"), float("nan"), "Infinity"):
            self.assertEqual(_format_live_timer(value), "-")

    def test_full_roster_side_switch_overrides_a_stale_director_side_label(self):
        roster = {str(index): "team1" if index < 5 else "team2" for index in range(10)}
        gsi = {
            "allplayers": {str(index): {"team": "T" if index < 5 else "CT"} for index in range(10)},
            "_80gotv": {"team_ct": "team1", "team_t": "team2"},
        }
        self.assertEqual(_gsi_team_mapping(gsi, {}, roster), {"CT": "team2", "T": "team1"})
