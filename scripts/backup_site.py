"""安全备份网站资料，不修改源文件。"""

import argparse
import json
import os
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import BASE_DIR, Config


def _add_tree(archive, folder, archive_root):
    folder = Path(folder)
    if not folder.is_dir():
        return 0
    count = 0
    for source in folder.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(folder)
        archive.write(source, str(Path(archive_root) / relative), zipfile.ZIP_STORED)
        count += 1
    return count


def _snapshot_database(target):
    source_path = Path(Config.DATABASE)
    if not source_path.is_file():
        raise FileNotFoundError(f"找不到数据库：{source_path}")
    source = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()


def create_backup(output_dir, include_demos=False):
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    kind = "完整" if include_demos else "日常"
    output = output_dir / f"80gotv-{stamp}-{kind}.zip"

    with tempfile.TemporaryDirectory(prefix="80gotv-backup-") as temp_dir:
        snapshot = Path(temp_dir) / "cs_site.db"
        _snapshot_database(snapshot)
        counts = {}
        with zipfile.ZipFile(output, "w", allowZip64=True) as archive:
            archive.write(snapshot, "database/cs_site.db", zipfile.ZIP_DEFLATED)
            counts["avatars"] = _add_tree(
                archive, Path(BASE_DIR) / "static" / "avatars", "static/avatars"
            )
            counts["uploads"] = _add_tree(
                archive, Path(BASE_DIR) / "static" / "uploads", "static/uploads"
            )
            if include_demos:
                counts["demos"] = _add_tree(
                    archive, Path(BASE_DIR) / "static" / "demos", "static/demos"
                )
            manifest = {
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "type": kind,
                "database": os.path.abspath(Config.DATABASE),
                "file_counts": counts,
                "note": "环境变量文件 .env 含有密钥，不会放入备份包。",
            }
            archive.writestr(
                "BACKUP_INFO.json",
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )
    return output


def main():
    parser = argparse.ArgumentParser(description="备份 80GOTV 网站资料")
    parser.add_argument(
        "--output-dir",
        default=os.environ.get("BACKUP_DIR", os.path.join(BASE_DIR, ".backups")),
        help="备份保存目录",
    )
    parser.add_argument("--full", action="store_true", help="同时备份大型 Demo 文件")
    args = parser.parse_args()
    output = create_backup(args.output_dir, include_demos=args.full)
    print(f"备份完成：{output}")


if __name__ == "__main__":
    main()
