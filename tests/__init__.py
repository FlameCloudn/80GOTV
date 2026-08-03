"""Keep the automated test suite away from real local or cloud data."""

import atexit
import os
import shutil
import tempfile
from pathlib import Path

_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="80gotv-tests-"))

os.environ["FLASK_ENV"] = "testing"
os.environ["DATABASE_PATH"] = str(_TEST_DATA_DIR / "suite.db")
os.environ["TURSO_URL"] = ""
os.environ["TURSO_TOKEN"] = ""
os.environ["SECRET_KEY"] = "automated-test-secret-not-for-production"
os.environ["SESSION_COOKIE_SECURE"] = "false"

atexit.register(shutil.rmtree, _TEST_DATA_DIR, True)
