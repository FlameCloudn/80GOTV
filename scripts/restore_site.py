"""Verify and extract a backup into a new, empty directory."""

import argparse
import os
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.backup_service import verify_backup

ALLOWED_FILES = {"database/cs_site.db", "BACKUP_INFO.json"}
ALLOWED_PREFIXES = ("static/avatars/", "static/uploads/", "static/demos/")


def _validated_member_path(filename):
    normalized = filename.replace("\\", "/")
    member_path = PurePosixPath(normalized)
    if member_path.is_absolute() or ".." in member_path.parts:
        raise RuntimeError(f"备份包含不安全路径：{filename}")
    member_name = member_path.as_posix().rstrip("/")
    allowed_directory = member_name in {"database", "static"} or any(
        member_name == prefix.rstrip("/") or prefix.rstrip("/").startswith(f"{member_name}/")
        for prefix in ALLOWED_PREFIXES
    )
    if (
        member_name not in ALLOWED_FILES
        and not any(member_name.startswith(prefix) for prefix in ALLOWED_PREFIXES)
        and not allowed_directory
    ):
        raise RuntimeError(f"备份包含未知内容：{filename}")
    return member_path


def restore_to_empty_directory(backup, target):
    backup = Path(backup).resolve()
    target = Path(target).resolve()
    if target.exists():
        raise RuntimeError("恢复目录已经存在，已停止以免覆盖文件")
    verify_backup(backup)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}-restore-", dir=target.parent))
    try:
        with zipfile.ZipFile(backup) as archive:
            for member in archive.infolist():
                _validated_member_path(member.filename)
            archive.extractall(staging)

        restored_database = staging / "database" / "cs_site.db"
        conn = sqlite3.connect(restored_database)
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            conn.close()
        if result != "ok":
            raise RuntimeError(f"恢复后的数据库检查失败：{result}")
        staging.rename(target)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return target


def restore_database_in_place(backup, target):
    """Restore only the verified database snapshot, replacing the live file atomically."""
    backup = Path(backup).resolve()
    target = Path(target).resolve()
    if not target.parent.is_dir():
        raise RuntimeError("数据库所在目录不存在")
    verify_backup(backup)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}-restore-", suffix=".db", dir=target.parent
    )
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(backup) as archive:
            with archive.open("database/cs_site.db") as source, temporary.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
        conn = sqlite3.connect(temporary)
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            conn.close()
        if result != "ok":
            raise RuntimeError(f"恢复后的数据库检查失败：{result}")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def main():
    parser = argparse.ArgumentParser(description="安全检查并恢复到新的空目录")
    parser.add_argument("backup")
    parser.add_argument("target", nargs="?")
    parser.add_argument("--database-only", metavar="DATABASE")
    args = parser.parse_args()
    if args.database_only:
        if args.target:
            parser.error("使用 --database-only 时不要再填写恢复目录")
        target = restore_database_in_place(args.backup, args.database_only)
        print(f"数据库已恢复：{target}")
        return
    if not args.target:
        parser.error("请填写新的空恢复目录")
    target = restore_to_empty_directory(args.backup, args.target)
    print(f"已恢复到新目录：{target}")


if __name__ == "__main__":
    main()
