import copy
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from scripts.recalculate_legacy_impact import apply_plan, build_plan


class ImpactRecalculationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.database = self.root / "statistics.db"
        self.backup = self.root / "before-impact.db"
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.executescript(
                """
                CREATE TABLE match_stats (
                    id INTEGER PRIMARY KEY, match_id INTEGER, player_id INTEGER,
                    team_id INTEGER, map_name TEXT, side TEXT,
                    data_source TEXT, data_status TEXT, data_version INTEGER,
                    kills INTEGER, assists INTEGER, rounds_played INTEGER,
                    impact REAL, first_kills INTEGER, first_deaths INTEGER,
                    multi2k INTEGER, multi3k INTEGER, multi4k INTEGER,
                    multi5k INTEGER, clutches_won INTEGER,
                    rating REAL, adr REAL, created_at TEXT
                );
                CREATE TABLE player_performance_summary (
                    player_id INTEGER PRIMARY KEY, avg_impact REAL,
                    avg_rating REAL, rounds_played INTEGER, updated_at TEXT
                );
                CREATE TABLE matches (id INTEGER PRIMARY KEY, score1 INTEGER, score2 INTEGER);
                INSERT INTO matches VALUES (5, 13, 9);
                INSERT INTO player_performance_summary VALUES (7, .25, 1.4, 50, 'keep-this-date');
                """
            )
        self.insert_stat(1)

    def insert_stat(self, stat_id, **changes):
        values = dict(
            id=stat_id,
            match_id=5,
            player_id=7,
            team_id=3,
            map_name=f"map-{stat_id}",
            side=None,
            data_source="legacy",
            data_status="final",
            data_version=1,
            kills=26,
            assists=2,
            rounds_played=22,
            impact=0.54,
            first_kills=7,
            first_deaths=3,
            multi2k=3,
            multi3k=0,
            multi4k=0,
            multi5k=0,
            clutches_won=1,
            rating=1.9,
            adr=110.5,
            created_at="keep-this-date",
        )
        values.update(changes)
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute(
                f"INSERT INTO match_stats ({','.join(values)}) VALUES ({','.join('?' for _ in values)})",
                tuple(values.values()),
            )

    def contents(self, database=None):
        with closing(sqlite3.connect(database or self.database)) as conn:
            return {
                table: conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                for table in ("match_stats", "player_performance_summary", "matches")
            }

    def test_preview_is_read_only_and_uses_independent_expected_value(self):
        before = self.contents()
        plan = build_plan(self.database)
        self.assertEqual(self.contents(), before)
        self.assertEqual(len(plan["rows"]), 1)
        self.assertEqual(plan["rows"][0]["before"]["impact"], 0.54)
        self.assertEqual(plan["rows"][0]["after_impact"], 2.15)
        self.assertFalse(self.backup.exists())

    def test_apply_changes_only_impact_and_weighted_impact_summary(self):
        self.insert_stat(
            2,
            data_source="demo_review",
            kills=10,
            assists=3,
            rounds_played=10,
            impact=1.19,
        )
        self.insert_stat(3, impact=None, rounds_played=90)
        before = self.contents()
        result = apply_plan(self.database, build_plan(self.database), self.backup)
        after = self.contents()
        self.assertEqual(result["updated_rows"], 2)
        self.assertEqual(self.contents(self.backup), before)
        self.assertEqual(after["matches"], before["matches"])
        for old, new in zip(before["match_stats"], after["match_stats"]):
            self.assertEqual(old[:12], new[:12])
            self.assertEqual(old[13:], new[13:])
        self.assertEqual(after["match_stats"][0][12], 2.15)
        self.assertEqual(after["match_stats"][1][12], 1.85)
        self.assertIsNone(after["match_stats"][2][12])
        self.assertAlmostEqual(
            after["player_performance_summary"][0][1], (2.15 * 22 + 1.85 * 10) / 32
        )
        self.assertEqual(
            after["player_performance_summary"][0][2:], before["player_performance_summary"][0][2:]
        )

    def test_unknown_counts_and_unconfirmed_values_are_not_rewritten(self):
        cases = [
            {"assists": None},
            {"kills": None},
            {"rounds_played": 0},
            {"rounds_played": None},
            {"first_kills": None},
            {"assists": -1},
            {"kills": 2.5},
            {"impact": None},
            {"impact": 0.8},
            {"impact": 2.15},
            {"data_source": "manual"},
            {"data_status": "superseded"},
            {"data_status": "provisional"},
        ]
        for stat_id, changes in enumerate(cases, start=2):
            self.insert_stat(stat_id, **changes)
        plan = build_plan(self.database)
        self.assertEqual([item["before"]["id"] for item in plan["rows"]], [1])
        self.assertEqual(len(plan["skipped"]), len(cases))

    def test_zero_kills_and_assists_never_write_a_negative_impact(self):
        # 回归公式在 0 杀 0 助攻时是 -0.41；保存的 Impact 最低记 0，原来已是 0 的记录不用改
        self.insert_stat(
            2,
            kills=0,
            assists=0,
            impact=0,
            first_kills=0,
            first_deaths=0,
            multi2k=0,
            clutches_won=0,
        )
        plan = build_plan(self.database)
        self.assertNotIn(2, [item["before"]["id"] for item in plan["rows"]])
        result = apply_plan(self.database, plan, self.backup)
        self.assertEqual(result["updated_rows"], 1)
        self.assertEqual(self.contents()["match_stats"][1][12], 0)

    def test_changed_input_invalidates_the_reviewed_plan(self):
        plan = build_plan(self.database)
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute("UPDATE match_stats SET assists=4 WHERE id=1")
        before = self.contents()
        with self.assertRaisesRegex(ValueError, "已变化"):
            apply_plan(self.database, plan, self.backup)
        self.assertEqual(self.contents(), before)
        self.assertFalse(self.backup.exists())

    def test_modified_plan_cannot_supply_an_arbitrary_value(self):
        plan = copy.deepcopy(build_plan(self.database))
        plan["rows"][0]["after_impact"] = 9.99
        before = self.contents()
        with self.assertRaisesRegex(ValueError, "计算结果"):
            apply_plan(self.database, plan, self.backup)
        self.assertEqual(self.contents(), before)
        self.assertFalse(self.backup.exists())

    def test_existing_backup_is_never_overwritten(self):
        self.backup.write_bytes(b"keep-original")
        before = self.contents()
        with self.assertRaises(FileExistsError):
            apply_plan(self.database, build_plan(self.database), self.backup)
        self.assertEqual(self.backup.read_bytes(), b"keep-original")
        self.assertEqual(self.contents(), before)

    def test_missing_summary_aborts_before_any_change(self):
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute("DELETE FROM player_performance_summary WHERE player_id=7")
        before = self.contents()
        with self.assertRaisesRegex(ValueError, "汇总"):
            apply_plan(self.database, build_plan(self.database), self.backup)
        self.assertEqual(self.contents(), before)
        self.assertFalse(self.backup.exists())

    def test_failure_rolls_back_every_row_and_keeps_backup(self):
        self.insert_stat(2)
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute("""CREATE TRIGGER fail_second_impact BEFORE UPDATE OF impact ON match_stats
                            WHEN OLD.id=2 BEGIN SELECT RAISE(ABORT,'fixture failure'); END""")
        before = self.contents()
        with self.assertRaises(sqlite3.IntegrityError):
            apply_plan(self.database, build_plan(self.database), self.backup)
        self.assertEqual(self.contents(), before)
        self.assertEqual(self.contents(self.backup), before)

    def test_reapplying_a_plan_is_a_no_op(self):
        plan = build_plan(self.database)
        apply_plan(self.database, plan, self.backup)
        before = self.contents()
        unused_backup = self.root / "not-needed.db"
        result = apply_plan(self.database, plan, unused_backup)
        self.assertEqual(result["updated_rows"], 0)
        self.assertEqual(result["already_applied"], 1)
        self.assertEqual(self.contents(), before)
        self.assertFalse(unused_backup.exists())

    def test_plan_is_bound_to_the_explicit_database(self):
        plan = build_plan(self.database)
        plan["database"] = str(self.root / "another.db")
        with self.assertRaisesRegex(ValueError, "数据库"):
            apply_plan(self.database, plan, self.backup)
        self.assertFalse(self.backup.exists())

    def test_cli_plan_does_not_modify_database_or_overwrite_report(self):
        script = Path(__file__).resolve().parents[1] / "scripts/recalculate_legacy_impact.py"
        report = self.root / "plan.json"
        command = [
            sys.executable,
            str(script),
            "--database",
            str(self.database),
            "--plan",
            str(report),
        ]
        before = self.contents()
        first = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(first.returncode, 0, first.stderr)
        original_report = report.read_bytes()
        second = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual(report.read_bytes(), original_report)
        self.assertEqual(self.contents(), before)


if __name__ == "__main__":
    unittest.main()
