"""Keep the automated test suite away from real local or cloud data."""

import atexit
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

# Test databases and credentials must not inherit a developer's .env file.
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["ADMIN_USERNAME"] = "suite-test-admin"
os.environ["ADMIN_PASSWORD"] = "suite-only-not-a-real-password"

_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="80gotv-tests-"))

os.environ["FLASK_ENV"] = "testing"
os.environ["DATABASE_PATH"] = str(_TEST_DATA_DIR / "suite.db")
os.environ["TURSO_URL"] = ""
os.environ["TURSO_TOKEN"] = ""
os.environ["SECRET_KEY"] = "automated-test-secret-not-for-production"
os.environ["SESSION_COOKIE_SECURE"] = "false"

# 测试选手编号也可能是真实 Steam 账号。不得用它们刷新本机缓存和头像。
_steam_profiles = patch("services.steam_profile_service.fetch_steam_public_profile", return_value={})
_steam_profiles.start()
atexit.register(_steam_profiles.stop)
atexit.register(shutil.rmtree, _TEST_DATA_DIR, True)
