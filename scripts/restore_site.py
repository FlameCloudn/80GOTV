"""Verify and extract a backup into a new, empty directory."""

import argparse
import os
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 必须先完成上面的 sys.path 处理，项目模块才可导入，故此处豁免 E402。
from services.backup_service import (  # noqa: E402
    extract_verified_database,
    read_backup_manifest,
    verify_snapshot,
)


def restore_to_empty_directory(backup, target):
    backup = Path(backup).resolve()
    target = Path(target).resolve()
    if target.exists():
        raise RuntimeError("恢复目录已经存在，已停止以免覆盖文件")
    with zipfile.ZipFile(backup) as archive:
        manifest = read_backup_manifest(archive)
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{target.name}-restore-", dir=target.parent))
        try:
            archive.extractall(staging)
            verify_snapshot(archive, staging / "database" / "cs_site.db", manifest)
            # Only retry Windows rename denials; never replace a newly created target.
            for attempt in range(4):
                try:
                    staging.rename(target)
                    break
                except PermissionError as error:
                    if (
                        getattr(error, "winerror", None) not in (5, 32)
                        or target.exists()
                        or attempt == 3
                    ):
                        raise
                    time.sleep(0.05 * (attempt + 1))
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
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}-restore-", suffix=".db", dir=target.parent
    )
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(backup) as archive:
            extract_verified_database(archive, temporary, database_only=True)
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
