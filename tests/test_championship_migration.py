import sqlite3
from contextlib import closing
from unittest.mock import patch

import pytest

import models
from config import Config
from scripts.migrate_database import current_version


def test_v5_champion_upgrade_is_additive_and_rolls_back_ddl(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    monkeypatch.setattr(Config, "DATABASE", str(path))
    assert current_version() == 0
    assert not path.exists()
    with patch.object(models, "CURRENT_SCHEMA_VERSION", 5):
        models.init_tables()
    with closing(models.get_db()) as conn:
        conn.execute("INSERT INTO events(id,name) VALUES(10,'老赛事')")
        conn.execute("INSERT INTO teams(id,name) VALUES(20,'历史冠军')")
        conn.execute("INSERT INTO players(id,nickname) VALUES(30,'已获奖选手')")
        conn.execute(
            """INSERT INTO event_champions(id,event_id,team_id,players_snapshot_at)
               VALUES(40,10,20,'2020-01-01')"""
        )
        conn.execute("INSERT INTO event_champion_players(champion_id,player_id) VALUES(40,30)")
        conn.execute("""CREATE TRIGGER refuse_v6 BEFORE INSERT ON schema_migrations
                        WHEN NEW.version=6 BEGIN SELECT RAISE(ABORT,'fixture'); END""")
        conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="fixture"):
        models.init_tables()
    with closing(models.get_db()) as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='managed_event_champions'").fetchone()
        assert conn.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == 5
        conn.execute("DROP TRIGGER refuse_v6")
        conn.commit()
    models.init_tables()
    models.init_tables()
    assert current_version() == 6
    with closing(models.get_db()) as conn:
        assert list(map(tuple, conn.execute("SELECT version FROM schema_migrations ORDER BY version"))) == [(5,), (6,)]
        assert not conn.execute("SELECT 1 FROM managed_event_champions").fetchone()
        assert not conn.execute("SELECT 1 FROM managed_event_champion_players").fetchone()
        assert tuple(conn.execute(
            """SELECT c.event_id,c.team_id,c.players_snapshot_at,p.player_id FROM event_champions c
               JOIN event_champion_players p ON c.id=p.champion_id"""
        ).fetchone()) == (10, 20, "2020-01-01", 30)
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
