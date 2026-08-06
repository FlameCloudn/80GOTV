import json
import sqlite3
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from utils.bp_manager import (
    ALL_MAPS,
    TURN_TIME_LIMIT_SECONDS,
    ban_map,
    bp_open_at_timestamp,
    bp_window_is_open,
    choose_side,
    get_team_for_step,
    init_bp_state,
    normalize_bp_state,
    pick_map,
    process_roll,
    save_bp_to_match,
    set_first_choice,
)


class BPWindowTests(unittest.TestCase):
    def test_bp_opens_exactly_twenty_minutes_before_match(self):
        zone = ZoneInfo("Asia/Shanghai")
        match_time = datetime(2026, 8, 6, 20, 0, tzinfo=zone)
        self.assertFalse(
            bp_window_is_open(
                match_time.isoformat(),
                "upcoming",
                datetime(2026, 8, 6, 19, 39, tzinfo=zone),
            )
        )
        self.assertTrue(
            bp_window_is_open(
                match_time.isoformat(),
                "upcoming",
                datetime(2026, 8, 6, 19, 40, tzinfo=zone),
            )
        )
        self.assertEqual(
            bp_open_at_timestamp(match_time.isoformat()),
            int(datetime(2026, 8, 6, 19, 40, tzinfo=zone).timestamp()),
        )

    def test_completed_match_never_opens_bp_window(self):
        self.assertFalse(
            bp_window_is_open(
                "2026-08-06T19:00",
                "completed",
                datetime(2026, 8, 6, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            )
        )


def ready_state(bo_format):
    state = init_bp_state(bo_format)
    ok, winner = process_roll(state, "t1", 80)
    assert ok and winner is None
    ok, winner = process_roll(state, "t2", 20)
    assert ok and winner == "t1"
    ok, _ = set_first_choice(state, "t1", "first")
    assert ok
    return state


def complete_bp(bo_format):
    state = ready_state(bo_format)
    while state["status"] == "bp":
        step_index = state["current_step"]
        step = state["steps"][step_index]
        team = get_team_for_step(state, step_index)
        map_name = state["pool"][0]
        operation = ban_map if step["action"] == "ban" else pick_map
        ok, message = operation(state, team, map_name)
        assert ok, message

    if state["status"] == "side_select":
        for pick in state["picks"]:
            if pick["picked_by"] == "remaining" and state["bo"] != "BO1":
                continue
            if pick.get("side_team"):
                team = pick["side_team"]
            else:
                team = "t2" if pick["picked_by"] == "t1" else "t1"
            ok, message = choose_side(state, team, pick["map"], "CT")
            assert ok, message

    return state


class BPFlowTests(unittest.TestCase):
    def test_bo1_finishes_with_one_map(self):
        state = complete_bp("BO1")
        self.assertEqual(state["status"], "completed")
        self.assertEqual(len(state["bans"]), 6)
        self.assertEqual(len(state["picks"]), 1)
        self.assertEqual(len(state["map_order"]), 1)

    def test_bo3_finishes_with_three_maps(self):
        state = complete_bp("BO3")
        self.assertEqual(state["status"], "completed")
        self.assertEqual(len(state["bans"]), 4)
        self.assertEqual(len(state["picks"]), 3)
        self.assertEqual(len(state["map_order"]), 3)

    def test_bo5_finishes_with_five_maps(self):
        state = complete_bp("BO5")
        self.assertEqual(state["status"], "completed")
        self.assertEqual(len(state["bans"]), 2)
        self.assertEqual(len(state["picks"]), 5)
        self.assertEqual(len(state["map_order"]), 5)

    def test_bo1_step_counts_are_really_applied(self):
        state = ready_state("BO1")
        first_team = get_team_for_step(state, 0)

        for expected_progress in (1,):
            ok, _ = ban_map(state, first_team, state["pool"][0])
            self.assertTrue(ok)
            self.assertEqual(state["current_step"], 0)
            self.assertEqual(state["current_step_progress"], expected_progress)

        ok, _ = ban_map(state, first_team, state["pool"][0])
        self.assertTrue(ok)
        self.assertEqual(state["current_step"], 1)
        self.assertEqual(state["current_step_progress"], 0)

        second_team = get_team_for_step(state, 1)
        for expected_progress in (1, 2, 3):
            ok, _ = ban_map(state, second_team, state["pool"][0])
            self.assertTrue(ok)
            if expected_progress < 3:
                self.assertEqual(state["current_step"], 1)
                self.assertEqual(state["current_step_progress"], expected_progress)

        self.assertEqual(state["current_step"], 2)
        self.assertEqual(state["current_step_progress"], 0)

    def test_bo1_requires_final_map_side_selection(self):
        state = ready_state("BO1")
        while state["status"] == "bp":
            step = state["steps"][state["current_step"]]
            team = get_team_for_step(state, state["current_step"])
            ok, message = ban_map(state, team, state["pool"][0])
            self.assertTrue(ok, message)

        self.assertEqual(state["status"], "side_select")
        remaining = state["picks"][0]
        self.assertEqual(remaining["picked_by"], "remaining")
        self.assertEqual(remaining["side_team"], "t2")

        ok, message = choose_side(state, "t1", remaining["map"], "CT")
        self.assertFalse(ok)
        self.assertEqual(message, "该图由对方选边")

        ok, message = choose_side(state, "t2", remaining["map"], "CT")
        self.assertTrue(ok, message)
        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["sides"][remaining["map"]], "CT")

    def test_tied_roll_can_restart_and_roll_cannot_be_overwritten(self):
        state = init_bp_state("BO3")
        self.assertEqual(process_roll(state, "t1", 50), (True, None))
        ok, message = process_roll(state, "t1", 99)
        self.assertFalse(ok)
        self.assertIn("已经", str(message))
        self.assertEqual(process_roll(state, "t2", 50), (True, "tie"))
        self.assertEqual(state["rolls"], {"t1": None, "t2": None})
        self.assertEqual(state["status"], "rolling")

    def test_side_cannot_be_selected_before_bp_finishes(self):
        state = ready_state("BO3")
        self.assertTrue(ban_map(state, "t1", state["pool"][0])[0])
        self.assertTrue(ban_map(state, "t2", state["pool"][0])[0])
        picked_map = state["pool"][0]
        self.assertTrue(pick_map(state, "t1", picked_map)[0])

        ok, message = choose_side(state, "t2", picked_map, "CT")
        self.assertFalse(ok)
        self.assertEqual(message, "当前不能选边")
        self.assertEqual(state["status"], "bp")

    def test_old_broken_bo1_state_is_resumed_instead_of_finishing_early(self):
        state = ready_state("BO1")
        state.pop("state_version")
        state.pop("current_step_progress")
        for team in ("t1", "t2", "t1"):
            map_name = state["pool"].pop(0)
            state["bans"].append(map_name)
            state["action_log"].append({"team": team, "action": "ban", "map": map_name})
        state["current_step"] = 3
        state["picks"] = [
            {"map": name, "picked_by": "remaining", "side": None} for name in state["pool"]
        ]
        state["status"] = "side_select"

        self.assertTrue(normalize_bp_state(state))
        self.assertEqual(state["status"], "bp")
        self.assertEqual(state["current_step"], 1)
        self.assertEqual(state["current_step_progress"], 1)
        self.assertEqual(state["picks"], [])
        self.assertEqual(len(state["pool"]), 4)


class BPTimerTests(unittest.TestCase):
    def test_new_bp_starts_with_three_minutes(self):
        with patch("utils.bp_manager.time.time", return_value=1000):
            state = init_bp_state("BO3")

        self.assertEqual(state["turn_started_at"], 1000)
        self.assertEqual(state["turn_deadline"], 1000 + TURN_TIME_LIMIT_SECONDS)

    def test_each_successful_action_restarts_the_timer(self):
        with patch("utils.bp_manager.time.time", return_value=1000):
            state = init_bp_state("BO3")

        with patch("utils.bp_manager.time.time", return_value=2000):
            self.assertEqual(process_roll(state, "t1", 80), (True, None))
        self.assertEqual(state["turn_deadline"], 2000 + TURN_TIME_LIMIT_SECONDS)

        with patch("utils.bp_manager.time.time", return_value=3000):
            self.assertEqual(process_roll(state, "t2", 20), (True, "t1"))
        self.assertEqual(state["turn_deadline"], 3000 + TURN_TIME_LIMIT_SECONDS)

        with patch("utils.bp_manager.time.time", return_value=4000):
            self.assertTrue(set_first_choice(state, "t1", "first")[0])
        self.assertEqual(state["turn_deadline"], 4000 + TURN_TIME_LIMIT_SECONDS)

        with patch("utils.bp_manager.time.time", return_value=5000):
            self.assertTrue(ban_map(state, "t1", state["pool"][0])[0])
        self.assertEqual(state["turn_deadline"], 5000 + TURN_TIME_LIMIT_SECONDS)

    def test_invalid_action_does_not_restart_the_timer(self):
        with patch("utils.bp_manager.time.time", return_value=1000):
            state = init_bp_state("BO3")
        original_deadline = state["turn_deadline"]

        with patch("utils.bp_manager.time.time", return_value=5000):
            ok, _ = process_roll(state, "invalid-team", 80)

        self.assertFalse(ok)
        self.assertEqual(state["turn_deadline"], original_deadline)

    def test_pick_and_side_selection_restart_the_timer(self):
        state = ready_state("BO3")
        self.assertTrue(ban_map(state, "t1", state["pool"][0])[0])
        self.assertTrue(ban_map(state, "t2", state["pool"][0])[0])

        with patch("utils.bp_manager.time.time", return_value=7000):
            self.assertTrue(pick_map(state, "t1", state["pool"][0])[0])
        self.assertEqual(state["turn_deadline"], 7000 + TURN_TIME_LIMIT_SECONDS)

        self.assertTrue(pick_map(state, "t2", state["pool"][0])[0])
        self.assertTrue(ban_map(state, "t1", state["pool"][0])[0])
        self.assertTrue(ban_map(state, "t2", state["pool"][0])[0])
        self.assertEqual(state["status"], "side_select")

        first_pick = state["picks"][0]
        side_team = "t2" if first_pick["picked_by"] == "t1" else "t1"
        with patch("utils.bp_manager.time.time", return_value=8000):
            self.assertTrue(choose_side(state, side_team, first_pick["map"], "CT")[0])
        self.assertEqual(state["turn_deadline"], 8000 + TURN_TIME_LIMIT_SECONDS)

    def test_expired_turn_can_continue_and_gets_a_new_three_minutes(self):
        with patch("utils.bp_manager.time.time", return_value=1000):
            state = init_bp_state("BO3")

        with patch("utils.bp_manager.time.time", return_value=2000):
            ok, _ = process_roll(state, "t1", 80)

        self.assertTrue(ok)
        self.assertEqual(state["turn_deadline"], 2000 + TURN_TIME_LIMIT_SECONDS)

    def test_completed_bp_stops_the_timer(self):
        state = complete_bp("BO1")
        self.assertIsNone(state["turn_started_at"])
        self.assertIsNone(state["turn_deadline"])

    def test_old_active_state_gets_a_timer_when_loaded(self):
        state = init_bp_state("BO3")
        state["state_version"] = 2
        state.pop("turn_started_at")
        state.pop("turn_deadline")

        with patch("utils.bp_manager.time.time", return_value=6000):
            self.assertTrue(normalize_bp_state(state))

        self.assertEqual(state["turn_deadline"], 6000 + TURN_TIME_LIMIT_SECONDS)


class BPSaveTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        map_columns = ", ".join(f"map{i} TEXT, map{i}_picked_by TEXT" for i in range(1, 6))
        self.conn.execute(
            f"""CREATE TABLE matches (
                id INTEGER PRIMARY KEY,
                bp_process TEXT,
                bp_state TEXT,
                map_pool TEXT,
                {map_columns},
                has_map3 INTEGER,
                has_map4 INTEGER,
                has_map5 INTEGER
            )"""
        )
        self.conn.execute(
            """INSERT INTO matches (
                id, map1, map2, map3, map4, map5,
                map1_picked_by, map2_picked_by, map3_picked_by,
                map4_picked_by, map5_picked_by,
                has_map3, has_map4, has_map5
            ) VALUES (1, 'Old1', 'Old2', 'Old3', 'Old4', 'Old5',
                      't1', 't2', 't1', 't2', 'decider', 1, 1, 1)"""
        )

    def tearDown(self):
        self.conn.close()

    def test_bo1_save_clears_old_extra_maps(self):
        state = complete_bp("BO1")
        self.assertTrue(save_bp_to_match(self.conn, 1, state))
        row = self.conn.execute("SELECT * FROM matches WHERE id=1").fetchone()

        self.assertEqual(row[3], json.dumps(ALL_MAPS, ensure_ascii=False))
        self.assertEqual(row[4], "de_" + state["map_order"][0].lower())
        self.assertIsNone(row[6])
        self.assertIsNone(row[8])
        self.assertIsNone(row[10])
        self.assertIsNone(row[12])
        self.assertEqual(row[5], "decider")
        self.assertEqual(row[14:17], (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
