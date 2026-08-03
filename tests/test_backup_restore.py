import shutil
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from config import Config
from scripts.restore_site import restore_database_in_place, restore_to_empty_directory
from services.backup_service import create_backup_file, verify_backup


class BackupRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.database = self.root / "cs_site.db"
        conn = sqlite3.connect(self.database)
        conn.execute("CREATE TABLE sample(value TEXT)")
        conn.execute("INSERT INTO sample(value) VALUES('latest')")
        conn.commit()
        conn.close()
        for name in ("avatars", "uploads", "demos"):
            folder = self.root / "static" / name
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{name}.txt").write_text(name, encoding="utf-8")
        self.original_database = Config.DATABASE
        Config.DATABASE = str(self.database)

    def tearDown(self):
        Config.DATABASE = self.original_database
        self.temp_dir.cleanup()

    def test_daily_and_full_backups_are_verified_and_restore_to_new_directory(self):
        output = self.root / "backups"
        with patch("services.backup_service.BASE_DIR", str(self.root)):
            daily = create_backup_file(output, include_demos=False)
            full = create_backup_file(output, include_demos=True)

        self.assertTrue(verify_backup(daily))
        with zipfile.ZipFile(daily) as archive:
            self.assertNotIn("static/demos/demos.txt", archive.namelist())
        with zipfile.ZipFile(full) as archive:
            self.assertIn("static/demos/demos.txt", archive.namelist())

        restored = restore_to_empty_directory(full, self.root / "restored")
        conn = sqlite3.connect(restored / "database" / "cs_site.db")
        value = conn.execute("SELECT value FROM sample").fetchone()[0]
        conn.close()
        self.assertEqual(value, "latest")

    def test_restore_refuses_non_empty_target(self):
        with patch("services.backup_service.BASE_DIR", str(self.root)):
            backup = create_backup_file(self.root / "backups")
        target = self.root / "not-empty"
        target.mkdir()
        (target / "keep.txt").write_text("keep", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            restore_to_empty_directory(backup, target)
        self.assertTrue((target / "keep.txt").exists())

    def test_database_only_restore_replaces_live_database(self):
        with patch("services.backup_service.BASE_DIR", str(self.root)):
            backup = create_backup_file(self.root / "backups")
        conn = sqlite3.connect(self.database)
        conn.execute("UPDATE sample SET value='broken'")
        conn.commit()
        conn.close()

        restored = restore_database_in_place(backup, self.database)

        self.assertEqual(restored, self.database.resolve())
        conn = sqlite3.connect(self.database)
        value = conn.execute("SELECT value FROM sample").fetchone()[0]
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        conn.close()
        self.assertEqual(value, "latest")
        self.assertEqual(integrity, "ok")

    def test_retention_only_removes_older_site_backups_of_same_type(self):
        output = self.root / "backups"
        output.mkdir()
        unrelated = output / "my-important-archive.zip"
        unrelated.write_bytes(b"keep")
        with patch("services.backup_service.BASE_DIR", str(self.root)):
            create_backup_file(output, keep=2)
            create_backup_file(output, keep=2)
            create_backup_file(output, keep=2)

        daily = list(output.glob("80gotv-*-日常.zip"))
        self.assertEqual(len(daily), 2)
        self.assertTrue(unrelated.exists())

    def test_restore_rejects_unsafe_member_without_touching_target(self):
        with patch("services.backup_service.BASE_DIR", str(self.root)):
            backup = create_backup_file(self.root / "backups")
        unsafe = self.root / "unsafe.zip"
        shutil.copy2(backup, unsafe)
        with zipfile.ZipFile(unsafe, "a") as archive:
            archive.writestr("../escape.txt", "bad")

        target = self.root / "unsafe-restore"
        with self.assertRaisesRegex(RuntimeError, "不安全路径"):
            restore_to_empty_directory(unsafe, target)
        self.assertFalse(target.exists())
        self.assertFalse((self.root / "escape.txt").exists())


if __name__ == "__main__":
    unittest.main()
