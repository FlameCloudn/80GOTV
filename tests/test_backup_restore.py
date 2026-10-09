import configparser
import shlex
import shutil
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
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

    def test_production_retention_preserves_latest_saved_data(self):
        deploy = Path(__file__).resolve().parents[1] / "deploy"
        policies = {}
        for kind, expected in (("daily", 2), ("full", 1)):
            config = configparser.ConfigParser(interpolation=None)
            config.read(deploy / f"80gotv-backup-{kind}.service", encoding="utf-8")
            command = shlex.split(config["Service"]["ExecStart"])
            self.assertEqual(
                command[:3], ["/usr/bin/flock", "--nonblock", "/srv/80gotv/backups/.backup.lock"]
            )
            self.assertEqual("--full" in command, kind == "full")
            policies[kind] = int(command[command.index("--keep") + 1])
            self.assertEqual(policies[kind], expected)

        output = self.root / "backups"
        output.mkdir()
        unrelated = output / "my-important-archive.zip"
        unrelated.write_bytes(b"keep")
        with patch("services.backup_service.BASE_DIR", str(self.root)):
            for value, full in (
                ("daily-old", False),
                ("full-old", True),
                ("daily-middle", False),
                ("full-latest", True),
                ("daily-latest", False),
            ):
                with closing(sqlite3.connect(self.database)) as conn:
                    conn.execute("UPDATE sample SET value=?", (value,))
                    conn.commit()
                create_backup_file(
                    output, include_demos=full, keep=policies["full" if full else "daily"]
                )

        self.assertTrue(unrelated.exists())
        daily = list(output.glob("80gotv-*-日常.zip"))
        full = list(output.glob("80gotv-*-完整.zip"))
        self.assertEqual(len(daily), 2)
        self.assertEqual(len(full), 1)
        values = set()
        for index, archive in enumerate(daily + full):
            restored = restore_to_empty_directory(archive, self.root / f"policy-restore-{index}")
            with closing(sqlite3.connect(restored / "database" / "cs_site.db")) as conn:
                values.add(conn.execute("SELECT value FROM sample").fetchone()[0])
            self.assertEqual(
                (restored / "static" / "demos" / "demos.txt").exists(), archive in full
            )
        self.assertEqual(values, {"daily-middle", "daily-latest", "full-latest"})

    def test_failed_new_backup_does_not_prune_previous_verified_backup(self):
        output = self.root / "backups"
        with patch("services.backup_service.BASE_DIR", str(self.root)):
            previous = create_backup_file(output, include_demos=True, keep=1)
            with patch(
                "services.backup_service.verify_backup", side_effect=RuntimeError("备份校验失败")
            ):
                with self.assertRaisesRegex(RuntimeError, "备份校验失败"):
                    create_backup_file(output, include_demos=True, keep=1)

        self.assertEqual(list(output.glob("80gotv-*-完整.zip")), [previous])
        self.assertEqual(list(output.glob("*.partial")), [])
        self.assertTrue(verify_backup(previous))
        restored = restore_to_empty_directory(previous, self.root / "failed-backup-restore")
        with closing(sqlite3.connect(restored / "database" / "cs_site.db")) as conn:
            self.assertEqual(conn.execute("SELECT value FROM sample").fetchone()[0], "latest")

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
