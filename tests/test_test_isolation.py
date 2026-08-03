import tempfile
import unittest
from pathlib import Path

from config import Config
from models import TURSO_TOKEN, TURSO_URL


class TestIsolationTests(unittest.TestCase):
    def test_suite_uses_a_temporary_local_database(self):
        database = Path(Config.DATABASE).resolve()
        temporary_root = Path(tempfile.gettempdir()).resolve()

        self.assertTrue(database.is_relative_to(temporary_root))
        self.assertFalse(TURSO_URL)
        self.assertFalse(TURSO_TOKEN)


if __name__ == "__main__":
    unittest.main()
