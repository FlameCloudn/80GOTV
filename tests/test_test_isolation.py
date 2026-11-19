import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from config import Config
from models import TURSO_TOKEN, TURSO_URL
from services.steam_profile_service import enrich_player_from_steam


class TestIsolationTests(unittest.TestCase):
    def test_suite_uses_a_temporary_local_database(self):
        database = Path(Config.DATABASE).resolve()
        temporary_root = Path(tempfile.gettempdir()).resolve()

        self.assertTrue(database.is_relative_to(temporary_root))
        self.assertFalse(TURSO_URL)
        self.assertFalse(TURSO_TOKEN)

    def test_test_profiles_do_not_download_or_cache_avatars(self):
        with (
            tempfile.TemporaryDirectory() as root,
            closing(sqlite3.connect(":memory:")) as db,
            patch("services.steam_profile_service.urlopen") as request,
        ):
            player = {"steam_id": "76561198000000002", "avatar": "", "real_name": ""}
            self.assertFalse(enrich_player_from_steam(db, player, root))
            request.assert_not_called()
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_disabled_dotenv_does_not_import_local_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = Path(__file__).resolve().parents[1] / "config.py"
            (root / "config.py").write_bytes(config.read_bytes())
            (root / ".env").write_text("WORKSPACE_TEST_MARKER=local-only\n", encoding="utf-8")
            env = {**os.environ, "PYTHON_DOTENV_DISABLED": "1"}
            env.pop("WORKSPACE_TEST_MARKER", None)
            result = subprocess.run(
                [sys.executable, "-c", "import config, os; print(os.getenv('WORKSPACE_TEST_MARKER', 'absent'))"],
                cwd=root, env=env, text=True, capture_output=True, check=True,
            )
            self.assertEqual(result.stdout.strip(), "absent")


if __name__ == "__main__":
    unittest.main()
