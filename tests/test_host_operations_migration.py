"""A Slice 2 database may have version 4 only; the extension must be atomic."""

import sqlite3
from contextlib import closing
from unittest.mock import patch

import pytest

import models
from config import Config


def test_upgrade_from_standalone_four_keeps_plans_and_rolls_back_last_step(tmp_path):
    with patch.object(Config, "DATABASE", str(tmp_path / "four.db")):
        with patch.object(models, "CURRENT_SCHEMA_VERSION", 4):
            models.init_tables()
        with closing(models.get_db()) as db:
            db.execute("INSERT INTO events(id,name) VALUES(9,'旧杯')")
            db.execute("INSERT INTO matches(id,event_id,slug) VALUES(17,9,'original-17')")
            db.execute(
                "INSERT INTO scheduled_maps(scheduled_map_id,match_id,map_order,legacy_slot,is_enabled,is_decider) VALUES(32,17,1,1,1,0)"
            )
            db.commit()
            initial = set(map(tuple, db.execute("SELECT type,name FROM sqlite_master")))
            assert (
                db.execute("SELECT group_concat(version) FROM schema_migrations").fetchone()[0]
                == "4"
            )

        execute = models._execute_sql_script

        def refuse_final_step(conn, script):
            execute(conn, script)
            if "CREATE TABLE live_director_receipts" in script:
                conn.execute("SELECT * FROM deliberately_absent_fixture_table")

        with (
            patch.object(models, "_execute_sql_script", refuse_final_step),
            pytest.raises(sqlite3.OperationalError),
        ):
            models.init_tables()
        with closing(models.get_db()) as db:
            assert set(map(tuple, db.execute("SELECT type,name FROM sqlite_master"))) == initial
        models.init_tables()
        models.init_tables()
        with closing(models.get_db()) as db:
            assert [
                r[0] for r in db.execute("SELECT version FROM schema_migrations ORDER BY version")
            ] == [4, 5, 6]
            assert tuple(
                db.execute(
                    "SELECT slug,scheduled_map_id FROM matches m JOIN scheduled_maps s ON m.id=s.match_id"
                ).fetchone()
            ) == ("original-17", 32)
            assert db.execute("SELECT count(*) FROM map_runs").fetchone()[0] == 0
            assert not db.execute("PRAGMA foreign_key_check").fetchall()
