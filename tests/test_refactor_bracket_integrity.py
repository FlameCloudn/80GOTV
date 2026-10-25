import json
import os
import tempfile
import threading
import unittest
from unittest.mock import patch

from app import app
from config import Config
from models import get_db, init_tables
from services.bracket_service import (
    FORMAT_SPECS,
    _find_reusable_stage_match,
    build_event_bracket,
    refresh_event_bracket,
)


def nodes(data):
    return {
        match["id"]: match
        for section in data["tournament"]["sections"]
        for round_data in section["rounds"]
        for match in round_data["matches"]
    }


class BracketIntegrityTests(unittest.TestCase):
    def setUp(self):
        handle, self.database_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.original_database = Config.DATABASE
        self.original_testing = app.config.get("TESTING")
        self.original_secure_cookie = app.config.get("SESSION_COOKIE_SECURE")
        Config.DATABASE = self.database_path
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        init_tables()
        self.conn = get_db()
        self.event_id = self.conn.execute(
            "INSERT INTO events(name) VALUES('Bracket Audit')"
        ).lastrowid
        self.team_ids = [
            self.conn.execute("INSERT INTO teams(name) VALUES(?)", (f"Team {index}",)).lastrowid
            for index in range(1, 5)
        ]
        self.data = build_event_bracket(self.conn, self.event_id, self._payload())
        self.match_nodes = nodes(self.data)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        Config.DATABASE = self.original_database
        app.config.update(
            TESTING=self.original_testing, SESSION_COOKIE_SECURE=self.original_secure_cookie
        )
        os.remove(self.database_path)

    def _payload(self):
        return {
            "tournament": {
                "format_key": "4se",
                "bo_format": "BO3",
                "teams": [
                    {"id": f"t{index}", "db_id": team_id, "name": f"Team {index}"}
                    for index, team_id in enumerate(self.team_ids, 1)
                ],
                "sections": [
                    {
                        "rounds": [
                            {
                                "matches": [
                                    {"id": "SF_M1", "team1": "t1", "team2": "t4"},
                                    {"id": "SF_M2", "team1": "t2", "team2": "t3"},
                                ]
                            }
                        ]
                    }
                ],
            }
        }

    def _result(self, node_id, score1=2, score2=0):
        self.conn.execute(
            "UPDATE matches SET status='completed',team1_score=?,team2_score=? WHERE id=?",
            (score1, score2, self.match_nodes[node_id]["match_id"]),
        )

    def _row(self, node_id):
        return self.conn.execute(
            "SELECT * FROM matches WHERE id=?", (self.match_nodes[node_id]["match_id"],)
        ).fetchone()

    def test_incomplete_completed_series_never_advances(self):
        self._result("SF_M1", 1, 0)
        refresh_event_bracket(self.conn, self.event_id)
        self.assertIsNone(self._row("F_M1")["team1_id"])

    def test_changed_seed_is_applied_to_unstarted_matches(self):
        submitted = json.loads(json.dumps(self.data))
        submitted_nodes = nodes(submitted)
        submitted_nodes["SF_M1"]["team1"] = "t2"
        submitted_nodes["SF_M2"]["team1"] = "t1"
        build_event_bracket(self.conn, self.event_id, submitted)
        self.assertEqual(self._row("SF_M1")["team1_id"], self.team_ids[1])
        self.assertEqual(self._row("SF_M2")["team1_id"], self.team_ids[0])

    def test_reopen_revokes_upcoming_winner_assignment(self):
        self._result("SF_M1")
        refresh_event_bracket(self.conn, self.event_id)
        self.assertEqual(self._row("F_M1")["team1_id"], self.team_ids[0])
        self.conn.execute(
            "UPDATE matches SET status='live' WHERE id=?", (self.match_nodes["SF_M1"]["match_id"],)
        )
        refresh_event_bracket(self.conn, self.event_id)
        self.assertIsNone(self._row("F_M1")["team1_id"])

    def test_changed_result_is_rejected_if_next_match_already_started(self):
        self._result("SF_M1")
        self._result("SF_M2")
        refresh_event_bracket(self.conn, self.event_id)
        self.conn.execute(
            "UPDATE matches SET status='live' WHERE id=?", (self.match_nodes["F_M1"]["match_id"],)
        )
        self.conn.commit()
        before = self.conn.execute(
            "SELECT bracket_data FROM events WHERE id=?", (self.event_id,)
        ).fetchone()[0]
        self._result("SF_M1", 0, 2)
        with self.assertRaisesRegex(ValueError, "后续比赛"):
            refresh_event_bracket(self.conn, self.event_id)
        self.conn.rollback()
        self.assertEqual(self._row("SF_M1")["team1_score"], 2)
        self.assertEqual(self._row("F_M1")["team1_id"], self.team_ids[0])
        self.assertEqual(
            self.conn.execute(
                "SELECT bracket_data FROM events WHERE id=?", (self.event_id,)
            ).fetchone()[0],
            before,
        )

    def test_reopening_is_atomic_when_downstream_already_has_bp(self):
        self._result("SF_M1")
        refresh_event_bracket(self.conn, self.event_id)
        self.conn.execute(
            "UPDATE matches SET bp_state=? WHERE id=?",
            ('{"status":"rolling"}', self.match_nodes["F_M1"]["match_id"]),
        )
        self.conn.commit()
        client = app.test_client()
        with client.session_transaction() as saved:
            saved["admin_id"] = 1
            saved["csrf_token"] = "bracket-audit"
        response = client.post(
            f"/admin/matches/{self.match_nodes['SF_M1']['match_id']}/reopen",
            data={"csrf_token": "bracket-audit"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._row("SF_M1")["status"], "completed")
        self.assertEqual(self._row("F_M1")["team1_id"], self.team_ids[0])

    def test_historical_result_cannot_replace_a_side_with_a_locked_roster(self):
        self._result("SF_M1")
        refresh_event_bracket(self.conn, self.event_id)
        player_id = self.conn.execute(
            "INSERT INTO players(nickname,team_id) VALUES('Locked Final Player',?)",
            (self.team_ids[0],),
        ).lastrowid
        self.conn.execute(
            "UPDATE matches SET team1_players=? WHERE id=?",
            (json.dumps([player_id]), self.match_nodes["F_M1"]["match_id"]),
        )
        self.conn.commit()
        self._result("SF_M1", 0, 2)
        with self.assertRaisesRegex(ValueError, "后续比赛|名单"):
            refresh_event_bracket(self.conn, self.event_id)
        self.conn.rollback()
        self.assertEqual(self._row("F_M1")["team1_id"], self.team_ids[0])

    def test_roster_of_an_unchanged_side_does_not_block_the_other_winner_advancing(self):
        self._result("SF_M1")
        refresh_event_bracket(self.conn, self.event_id)
        self.conn.execute(
            "UPDATE matches SET team1_players='[100]' WHERE id=?",
            (self.match_nodes["F_M1"]["match_id"],),
        )
        self._result("SF_M2")
        refresh_event_bracket(self.conn, self.event_id)
        self.assertEqual(self._row("F_M1")["team2_id"], self.team_ids[1])

    def test_foreign_event_match_binding_is_never_updated(self):
        other_event = self.conn.execute("INSERT INTO events(name) VALUES('Other Cup')").lastrowid
        foreign_match = self.conn.execute(
            "INSERT INTO matches(event_id,status) VALUES(?,'upcoming')", (other_event,)
        ).lastrowid
        poisoned = json.loads(json.dumps(self.data))
        nodes(poisoned)["F_M1"]["match_id"] = foreign_match
        self._result("SF_M1")
        with self.assertRaisesRegex(ValueError, "其他赛事|不属于"):
            refresh_event_bracket(self.conn, self.event_id, data=poisoned)
        row = self.conn.execute(
            "SELECT team1_id FROM matches WHERE id=?", (foreign_match,)
        ).fetchone()
        self.assertIsNone(row[0])

    def test_late_invalid_schedule_rolls_back_earlier_bracket_edits(self):
        payload = json.loads(json.dumps(self.data))
        changed = nodes(payload)
        changed["SF_M1"]["bo_format"] = "BO1"
        changed["F_M1"]["match_time"] = "not-a-time"
        before = [tuple(row) for row in self.conn.execute("SELECT * FROM matches ORDER BY id")]
        client = app.test_client()
        with client.session_transaction() as saved:
            saved["admin_id"] = 1
            saved["csrf_token"] = "bracket-audit"
        response = client.post(
            f"/admin/events/{self.event_id}/bracket/api/save",
            json=payload,
            headers={"X-CSRF-Token": "bracket-audit"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            [tuple(row) for row in self.conn.execute("SELECT * FROM matches ORDER BY id")], before
        )

    def test_raw_bracket_form_cannot_store_cross_event_bindings(self):
        other_event = self.conn.execute("INSERT INTO events(name) VALUES('Other Cup')").lastrowid
        foreign_match = self.conn.execute(
            "INSERT INTO matches(event_id,status) VALUES(?,'upcoming')", (other_event,)
        ).lastrowid
        self.conn.commit()
        before = self.conn.execute(
            "SELECT bracket_data FROM events WHERE id=?", (self.event_id,)
        ).fetchone()[0]
        payload = json.loads(json.dumps(self.data))
        nodes(payload)["F_M1"]["match_id"] = foreign_match
        client = app.test_client()
        with client.session_transaction() as saved:
            saved["admin_id"] = 1
            saved["csrf_token"] = "bracket-audit"
        response = client.post(
            f"/admin/events/{self.event_id}/bracket",
            data={"csrf_token": "bracket-audit", "bracket_data": json.dumps(payload)},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            self.conn.execute(
                "SELECT bracket_data FROM events WHERE id=?", (self.event_id,)
            ).fetchone()[0],
            before,
        )

    def test_deleting_a_result_clears_unstarted_downstream_assignment(self):
        self._result("SF_M1")
        refresh_event_bracket(self.conn, self.event_id)
        self.conn.commit()
        client = app.test_client()
        with client.session_transaction() as saved:
            saved["admin_id"] = 1
            saved["csrf_token"] = "bracket-audit"
        response = client.post(
            f"/admin/matches/delete/{self.match_nodes['SF_M1']['match_id']}",
            data={"csrf_token": "bracket-audit"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(self._row("F_M1")["team1_id"])
        stored = json.loads(
            self.conn.execute(
                "SELECT bracket_data FROM events WHERE id=?", (self.event_id,)
            ).fetchone()[0]
        )
        self.assertIsNone(nodes(stored)["SF_M1"]["match_id"])
        self.assertIsNone(nodes(stored)["SF_M1"]["score1"])

    def test_legacy_rounds_and_sections_keep_identical_live_scores(self):
        self._result("SF_M1")
        data = refresh_event_bracket(self.conn, self.event_id)
        self.assertEqual(data["tournament"]["rounds"][0]["matches"][0]["score1"], 2)
        self.assertEqual(
            data["tournament"]["rounds"][0], data["tournament"]["sections"][0]["rounds"][0]
        )

    def test_two_concurrent_builds_do_not_create_duplicate_matches(self):
        event_id = self.conn.execute("INSERT INTO events(name) VALUES('Concurrent Cup')").lastrowid
        self.conn.commit()
        first_read = threading.Event()
        second_read = threading.Event()
        release_first = threading.Event()
        first_finished = threading.Event()
        results, errors = {}, []

        def controlled_find(conn, *args):
            found = _find_reusable_stage_match(conn, *args)
            if threading.current_thread().name == "bracket-first" and not first_read.is_set():
                first_read.set()
                if not release_first.wait(5):
                    raise AssertionError("等待首次生成对阵恢复超时")
            elif threading.current_thread().name == "bracket-second" and not second_read.is_set():
                second_read.set()
                if not first_finished.wait(5):
                    raise AssertionError("等待首次生成对阵完成超时")
            return found

        def build(name):
            conn = get_db()
            try:
                results[name] = build_event_bracket(conn, event_id, self._payload())
                conn.commit()
            except Exception as exc:
                conn.rollback()
                errors.append(exc)
            finally:
                conn.close()
                if name == "first":
                    first_finished.set()

        first = threading.Thread(name="bracket-first", target=build, args=("first",))
        second = threading.Thread(name="bracket-second", target=build, args=("second",))
        with patch(
            "services.bracket_service._find_reusable_stage_match", side_effect=controlled_find
        ):
            first.start()
            try:
                self.assertTrue(first_read.wait(5))
                second.start()
                second_read.wait(0.15)
            finally:
                release_first.set()
                first.join(10)
                if second.ident is not None:
                    second.join(10)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM matches WHERE event_id=?", (event_id,)
            ).fetchone()[0],
            3,
        )
        self.assertEqual(
            {key: item["match_id"] for key, item in nodes(results["first"]).items()},
            {key: item["match_id"] for key, item in nodes(results["second"]).items()},
        )

    def test_all_supported_formats_route_every_real_winner_and_loser(self):
        for format_key, spec in FORMAT_SPECS.items():
            with self.subTest(format=format_key):
                event_id = self.conn.execute(
                    "INSERT INTO events(name) VALUES(?)", (format_key,)
                ).lastrowid
                team_ids = [
                    self.conn.execute(
                        "INSERT INTO teams(name) VALUES(?)", (f"{format_key}-{index}",)
                    ).lastrowid
                    for index in range(1, spec["total_teams"] + 1)
                ]
                team_data = [
                    {"id": f"s{index}", "db_id": team_id, "name": str(team_id)}
                    for index, team_id in enumerate(team_ids, 1)
                ]
                seed_matches = []
                all_specs = []
                for _, rounds in spec["sections"]:
                    for _, matches in rounds:
                        for node_id, _, source1, source2 in matches:
                            all_specs.append((node_id, source1, source2))
                            if source1[0] == "seed":
                                seed_matches.append(
                                    {
                                        "id": node_id,
                                        "team1": f"s{source1[1]}",
                                        "team2": f"s{source2[1]}",
                                    }
                                )
                payload = {
                    "tournament": {
                        "format_key": format_key,
                        "bo_format": "BO3",
                        "teams": team_data,
                        "sections": [{"rounds": [{"matches": seed_matches}]}],
                    }
                }
                data = build_event_bracket(self.conn, event_id, payload)
                by_node = nodes(data)
                expected_results = {}
                for index, (node_id, source1, source2) in enumerate(all_specs):
                    row = self.conn.execute(
                        "SELECT * FROM matches WHERE id=?", (by_node[node_id]["match_id"],)
                    ).fetchone()
                    expected = [
                        team_ids[source[1] - 1]
                        if source[0] == "seed"
                        else expected_results[source[1]][source[0]]
                        for source in (source1, source2)
                    ]
                    self.assertEqual([row["team1_id"], row["team2_id"]], expected)
                    self.assertNotEqual(*expected)
                    winner_index = index % 2
                    scores = (2, 0) if winner_index == 0 else (0, 2)
                    self.conn.execute(
                        "UPDATE matches SET status='completed',team1_score=?,team2_score=? WHERE id=?",
                        (*scores, row["id"]),
                    )
                    expected_results[node_id] = {
                        "winner": expected[winner_index],
                        "loser": expected[1 - winner_index],
                    }
                    data = refresh_event_bracket(self.conn, event_id)
                count_before = self.conn.execute(
                    "SELECT COUNT(*) FROM matches WHERE event_id=?", (event_id,)
                ).fetchone()[0]
                refresh_event_bracket(self.conn, event_id)
                self.assertEqual(count_before, len(all_specs))
                self.assertEqual(
                    self.conn.execute(
                        "SELECT COUNT(*) FROM matches WHERE event_id=?", (event_id,)
                    ).fetchone()[0],
                    count_before,
                )
