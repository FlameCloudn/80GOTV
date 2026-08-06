import json
import sqlite3
import unittest

from utils.bp_manager import (
    ALL_MAPS,
    ban_map,
    choose_side,
    ensure_bp_started,
    get_team_for_step,
    init_bp_state,
    normalize_bp_state,
    pick_map,
    process_roll,
    save_bp_to_match,
    set_first_choice,
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


def complete_bp_with_pool(bo_format, map_pool):
    state = init_bp_state(bo_format, map_pool)
    process_roll(state, "t1", 80)
    process_roll(state, "t2", 20)
    set_first_choice(state, "t1", "first")
    while state["status"] == "bp":
        step_index = state["current_step"]
        step = state["steps"][step_index]
        team = get_team_for_step(state, step_index)
        operation = ban_map if step["action"] == "ban" else pick_map
        ok, message = operation(state, team, state["pool"][0])
        assert ok, message
    if state["status"] == "side_select":
        for pick in state["picks"]:
            if pick["picked_by"] == "remaining" and state["bo"] != "BO1":
                continue
            team = pick.get("side_team") or ("t2" if pick["picked_by"] == "t1" else "t1")
            ok, message = choose_side(state, team, pick["map"], "CT")
            assert ok, message
    return state


class BPFlowTests(unittest.TestCase):
    def test_custom_map_pool_drives_steps_without_default_replacement(self):
        custom_pool = ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]
        state = complete_bp_with_pool("BO3", custom_pool)
        self.assertEqual(state["initial_pool"], custom_pool)
        self.assertEqual(len(state["map_order"]), 3)
        self.assertEqual(len(state["bans"]), 2)

        state = complete_bp_with_pool("BO5", custom_pool)
        self.assertEqual(state["initial_pool"], custom_pool)
        self.assertEqual(len(state["map_order"]), 5)
        self.assertEqual(len(state["bans"]), 0)

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


class BPNoTimerTests(unittest.TestCase):
    def test_new_bp_has_no_turn_timer(self):
        state = init_bp_state("BO3")
        self.assertNotIn("turn_started_at", state)
        self.assertNotIn("turn_deadline", state)

    def test_actions_progress_without_creating_timer_fields(self):
        state = ready_state("BO3")
        self.assertTrue(ban_map(state, "t1", state["pool"][0])[0])
        self.assertNotIn("turn_started_at", state)
        self.assertNotIn("turn_deadline", state)

    def test_old_timer_and_auto_start_fields_are_removed(self):
        state = init_bp_state("BO3")
        state["state_version"] = 5
        state["turn_started_at"] = 1000
        state["turn_deadline"] = 1180
        state["auto_started"] = True
        state["auto_started_at"] = 900

        self.assertTrue(normalize_bp_state(state))
        self.assertNotIn("turn_started_at", state)
        self.assertNotIn("turn_deadline", state)
        self.assertNotIn("auto_started", state)
        self.assertNotIn("auto_started_at", state)

    def test_reading_an_unstarted_match_does_not_auto_create_bp(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE matches(id INTEGER PRIMARY KEY, bp_state TEXT)")
        conn.execute("INSERT INTO matches(id, bp_state) VALUES(1, NULL)")
        match = conn.execute("SELECT * FROM matches WHERE id=1").fetchone()

        state, changed = ensure_bp_started(conn, match)

        self.assertIsNone(state)
        self.assertFalse(changed)
        self.assertIsNone(conn.execute("SELECT bp_state FROM matches WHERE id=1").fetchone()[0])
        conn.close()


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
