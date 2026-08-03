import json
import os
import tempfile
import unittest

from config import Config
from models import get_db, init_tables
from services.bracket_service import build_event_bracket, refresh_event_bracket


def _match_map(data):
    result = {}
    for section in data["tournament"]["sections"]:
        for round_data in section["rounds"]:
            for match in round_data["matches"]:
                result[match["id"]] = match
    return result


class BracketGenerationTests(unittest.TestCase):
    def setUp(self):
        handle, self.database_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.original_database = Config.DATABASE
        Config.DATABASE = self.database_path
        init_tables()

        conn = get_db()
        conn.execute(
            "INSERT INTO events(name,slug,status) VALUES('Test Major','test-major','upcoming')"
        )
        self.event_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.team_ids = []
        for index in range(1, 5):
            conn.execute(
                "INSERT INTO teams(name,short_name) VALUES(?,?)",
                (f"Team {index}", f"T{index}"),
            )
            self.team_ids.append(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        conn.commit()
        conn.close()

    def tearDown(self):
        Config.DATABASE = self.original_database
        try:
            os.remove(self.database_path)
        except OSError:
            pass

    def _payload(self):
        teams = [
            {
                "id": f"t{index}",
                "db_id": team_id,
                "name": f"Team {index}",
                "short_name": f"T{index}",
            }
            for index, team_id in enumerate(self.team_ids, 1)
        ]
        return {
            "tournament": {
                "format_key": "4de",
                "bo_format": "BO3",
                "teams": teams,
                "sections": [
                    {
                        "label": "胜者组",
                        "rounds": [
                            {
                                "name": "UB 第一轮",
                                "matches": [
                                    {"id": "UB_R1_M1", "team1": "t1", "team2": "t4"},
                                    {"id": "UB_R1_M2", "team1": "t2", "team2": "t3"},
                                ],
                            }
                        ],
                    }
                ],
            }
        }

    def test_builds_every_match_once_and_keeps_future_slots_tbd(self):
        conn = get_db()
        saved = build_event_bracket(conn, self.event_id, self._payload())
        conn.commit()

        matches = _match_map(saved)
        self.assertEqual(
            set(matches),
            {
                "UB_R1_M1",
                "UB_R1_M2",
                "UB_R2_M1",
                "LB_R1_M1",
                "LB_R2_M1",
                "GF_R1_M1",
            },
        )
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM matches WHERE event_id=?", (self.event_id,)
            ).fetchone()[0],
            6,
        )
        future_id = matches["UB_R2_M1"]["match_id"]
        future = conn.execute(
            "SELECT team1_id,team2_id,match_time FROM matches WHERE id=?", (future_id,)
        ).fetchone()
        self.assertIsNone(future["team1_id"])
        self.assertIsNone(future["team2_id"])
        self.assertIsNone(future["match_time"])

        saved_again = build_event_bracket(conn, self.event_id, saved)
        conn.commit()
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM matches WHERE event_id=?", (self.event_id,)
            ).fetchone()[0],
            6,
        )
        self.assertEqual(
            _match_map(saved_again)["GF_R1_M1"]["match_id"],
            matches["GF_R1_M1"]["match_id"],
        )
        conn.close()

    def test_reuses_existing_seed_matches_and_preserves_their_schedule(self):
        conn = get_db()
        conn.execute(
            """INSERT INTO matches(
                   event_id,team1_id,team2_id,match_time,bo_format,stage,status,
                   team1_score,team2_score
               ) VALUES(?,?,?,?,?,'第一轮','upcoming',0,0)""",
            (self.event_id, self.team_ids[0], self.team_ids[3], "2026-08-06T13:00", "BO1"),
        )
        first_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO matches(
                   event_id,team1_id,team2_id,match_time,bo_format,stage,status,
                   team1_score,team2_score
               ) VALUES(?,?,?,?,?,'第一轮','upcoming',0,0)""",
            (self.event_id, self.team_ids[1], self.team_ids[2], "2026-08-06T14:30", "BO1"),
        )
        second_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        saved = build_event_bracket(conn, self.event_id, self._payload())
        conn.commit()
        matches = _match_map(saved)

        self.assertEqual(matches["UB_R1_M1"]["match_id"], first_id)
        self.assertEqual(matches["UB_R1_M2"]["match_id"], second_id)
        self.assertEqual(matches["UB_R1_M1"]["match_time"], "2026-08-06T13:00")
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM matches WHERE event_id=?", (self.event_id,)
            ).fetchone()[0],
            6,
        )
        conn.close()

    def test_reuses_existing_future_match_by_unique_stage(self):
        conn = get_db()
        conn.execute(
            """INSERT INTO matches(
                   event_id,team1_id,team2_id,match_time,bo_format,stage,status,
                   team1_score,team2_score
               ) VALUES(?,NULL,NULL,?,'BO5','总决赛','upcoming',0,0)""",
            (self.event_id, "2026-08-10T18:00"),
        )
        final_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        saved = build_event_bracket(conn, self.event_id, self._payload())
        conn.commit()
        final = _match_map(saved)["GF_R1_M1"]

        self.assertEqual(final["match_id"], final_id)
        self.assertEqual(final["match_time"], "2026-08-10T18:00")
        self.assertEqual(final["bo_format"], "BO5")
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM matches WHERE event_id=?", (self.event_id,)
            ).fetchone()[0],
            6,
        )
        conn.close()

    def test_manual_binding_uses_the_selected_existing_match(self):
        conn = get_db()
        conn.execute(
            """INSERT INTO matches(
                   event_id,team1_id,team2_id,match_time,bo_format,stage,status,
                   team1_score,team2_score
               ) VALUES(?,?,?,?,?,'管理员先创建的比赛','upcoming',0,0)""",
            (
                self.event_id,
                self.team_ids[0],
                self.team_ids[3],
                "2026-08-06T13:00",
                "BO1",
            ),
        )
        existing_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        payload = self._payload()
        payload["tournament"]["sections"][0]["rounds"][0]["matches"][0]["match_id"] = existing_id

        saved = build_event_bracket(conn, self.event_id, payload)
        conn.commit()

        self.assertEqual(_match_map(saved)["UB_R1_M1"]["match_id"], existing_id)
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM matches WHERE event_id=?", (self.event_id,)
            ).fetchone()[0],
            6,
        )
        conn.close()

    def test_rejects_binding_one_match_to_multiple_slots(self):
        conn = get_db()
        saved = build_event_bracket(conn, self.event_id, self._payload())
        nodes = _match_map(saved)
        nodes["UB_R1_M2"]["match_id"] = nodes["UB_R1_M1"]["match_id"]

        with self.assertRaisesRegex(ValueError, "不能绑定到多个"):
            build_event_bracket(conn, self.event_id, saved)
        conn.rollback()
        conn.close()

    def test_saves_match_time_from_bracket_editor_payload(self):
        conn = get_db()
        saved = build_event_bracket(conn, self.event_id, self._payload())
        nodes = _match_map(saved)
        nodes["UB_R2_M1"]["match_time"] = "2026-08-08T16:45"
        nodes["UB_R2_M1"]["bo_format"] = "BO5"

        saved = build_event_bracket(conn, self.event_id, saved)
        conn.commit()
        future = _match_map(saved)["UB_R2_M1"]
        row = conn.execute(
            "SELECT match_time,bo_format FROM matches WHERE id=?", (future["match_id"],)
        ).fetchone()

        self.assertEqual(row["match_time"], "2026-08-08T16:45")
        self.assertEqual(row["bo_format"], "BO5")
        self.assertEqual(future["match_time"], "2026-08-08T16:45")
        self.assertEqual(future["bo_format"], "BO5")
        conn.close()

    def test_completed_results_advance_winners_and_losers(self):
        conn = get_db()
        data = build_event_bracket(conn, self.event_id, self._payload())
        nodes = _match_map(data)

        conn.execute(
            "UPDATE matches SET team1_score=2,team2_score=0,status='completed' WHERE id=?",
            (nodes["UB_R1_M1"]["match_id"],),
        )
        conn.execute(
            "UPDATE matches SET team1_score=0,team2_score=2,status='completed' WHERE id=?",
            (nodes["UB_R1_M2"]["match_id"],),
        )
        data = refresh_event_bracket(conn, self.event_id)
        nodes = _match_map(data)
        upper_final = conn.execute(
            "SELECT team1_id,team2_id FROM matches WHERE id=?",
            (nodes["UB_R2_M1"]["match_id"],),
        ).fetchone()
        lower_round = conn.execute(
            "SELECT team1_id,team2_id FROM matches WHERE id=?",
            (nodes["LB_R1_M1"]["match_id"],),
        ).fetchone()
        self.assertEqual(tuple(upper_final), (self.team_ids[0], self.team_ids[2]))
        self.assertEqual(tuple(lower_round), (self.team_ids[3], self.team_ids[1]))
        self.assertEqual(nodes["UB_R1_M1"]["score1"], 2)

        conn.execute(
            "UPDATE matches SET team1_score=2,team2_score=1,status='completed' WHERE id=?",
            (nodes["UB_R2_M1"]["match_id"],),
        )
        conn.execute(
            "UPDATE matches SET team1_score=0,team2_score=2,status='completed' WHERE id=?",
            (nodes["LB_R1_M1"]["match_id"],),
        )
        data = refresh_event_bracket(conn, self.event_id)
        nodes = _match_map(data)
        lower_final = conn.execute(
            "SELECT team1_id,team2_id FROM matches WHERE id=?",
            (nodes["LB_R2_M1"]["match_id"],),
        ).fetchone()
        self.assertEqual(tuple(lower_final), (self.team_ids[1], self.team_ids[2]))

        conn.execute(
            "UPDATE matches SET team1_score=1,team2_score=2,status='completed' WHERE id=?",
            (nodes["LB_R2_M1"]["match_id"],),
        )
        data = refresh_event_bracket(conn, self.event_id)
        nodes = _match_map(data)
        grand_final = conn.execute(
            "SELECT team1_id,team2_id FROM matches WHERE id=?",
            (nodes["GF_R1_M1"]["match_id"],),
        ).fetchone()
        self.assertEqual(tuple(grand_final), (self.team_ids[0], self.team_ids[2]))

        stored = conn.execute(
            "SELECT bracket_data FROM events WHERE id=?", (self.event_id,)
        ).fetchone()[0]
        self.assertIn(
            "GF_R1_M1",
            json.loads(stored)["tournament"]["sections"][-1]["rounds"][0]["matches"][0]["id"],
        )
        conn.close()


if __name__ == "__main__":
    unittest.main()
