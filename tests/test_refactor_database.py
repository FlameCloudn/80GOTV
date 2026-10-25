import runpy
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from config import Config
from models import get_db, init_tables
from services.performance_service import refresh_player_performance


class DatabaseRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        original = Config.DATABASE
        self.addCleanup(setattr, Config, "DATABASE", original)
        Config.DATABASE = str(Path(self.temp.name) / "data.db")
        init_tables()

    def test_startup_does_not_supersede_current_row_because_history_has_larger_id(self):
        with closing(get_db()) as conn:
            player = conn.execute("INSERT INTO players(nickname) VALUES('Player')").lastrowid
            match = conn.execute("INSERT INTO matches(bo_format) VALUES('BO1')").lastrowid
            current = conn.execute(
                """INSERT INTO match_stats(player_id,match_id,map_name,kills,data_status,data_version)
                   VALUES(?,?,'de_mirage',20,'final',2)""",
                (player, match),
            ).lastrowid
            historical = conn.execute(
                """INSERT INTO match_stats(player_id,match_id,map_name,kills,data_status,data_version)
                   VALUES(?,?,'de_mirage',10,'superseded',1)""",
                (player, match),
            ).lastrowid
            conn.commit()
        init_tables()
        init_tables()
        with closing(get_db()) as conn:
            rows = conn.execute(
                "SELECT id,data_status,kills,data_version FROM match_stats ORDER BY id"
            ).fetchall()
        self.assertEqual(
            [tuple(row) for row in rows],
            [
                (current, "final", 20, 2),
                (historical, "superseded", 10, 1),
            ],
        )

    def test_config_only_loads_env_from_its_own_directory(self):
        config_path = Path(__file__).resolve().parents[1] / "config.py"
        with patch("dotenv.load_dotenv") as load:
            runpy.run_path(str(config_path))
        load.assert_called_once_with(str(config_path.parent / ".env"))

    def test_deduplication_refreshes_affected_cached_player_totals(self):
        with closing(get_db()) as conn:
            conn.execute("DROP INDEX idx_match_stats_match_map_player_current")
            player = conn.execute("INSERT INTO players(nickname) VALUES('Legacy')").lastrowid
            match = conn.execute("INSERT INTO matches(bo_format) VALUES('BO1')").lastrowid
            for kills in (10, 20):
                conn.execute(
                    "INSERT INTO match_stats(player_id,match_id,map_name,kills) VALUES(?,?,'de_mirage',?)",
                    (player, match, kills),
                )
            refresh_player_performance(conn)
            conn.commit()
        init_tables()
        with closing(get_db()) as conn:
            summary = conn.execute(
                "SELECT maps,total_kills FROM player_performance_summary WHERE player_id=?",
                (player,),
            ).fetchone()
            history = conn.execute(
                "SELECT COUNT(*) FROM match_stats WHERE player_id=?", (player,)
            ).fetchone()[0]
        self.assertEqual(tuple(summary), (1, 20))
        self.assertEqual(history, 2)


if __name__ == "__main__":
    unittest.main()
