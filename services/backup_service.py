"""Create and verify disk-backed website backups."""

import json
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from config import BASE_DIR, Config


def _add_tree(archive, folder, archive_root):
    folder = Path(folder).resolve()
    if not folder.is_dir():
        return 0
    count = 0
    for source in folder.rglob("*"):
        if not source.is_file():
            continue
        resolved = source.resolve()
        if not resolved.is_relative_to(folder):
            continue
        archive_name = (Path(archive_root) / source.relative_to(folder)).as_posix()
        archive.write(resolved, archive_name, zipfile.ZIP_STORED)
        count += 1
    return count


def _snapshot_database(target):
    if os.environ.get("TURSO_URL", "").strip() and os.environ.get("TURSO_TOKEN", "").strip():
        raise RuntimeError(
            "当前使用 Turso 云数据库，本地备份脚本不能生成可信快照；请先配置云端备份。"
        )
    source_path = Path(Config.DATABASE).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"找不到数据库：{source_path}")
    source = sqlite3.connect(f"{source_path.as_uri()}?mode=ro", uri=True)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()


def verify_backup(path):
    """Check ZIP contents and the copied SQLite database."""
    path = Path(path).resolve()
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise RuntimeError("备份中包含重复路径")
        bad_member = archive.testzip()
        if bad_member:
            raise RuntimeError(f"备份文件损坏：{bad_member}")
        if "database/cs_site.db" not in names:
            raise RuntimeError("备份中缺少数据库")
        if "BACKUP_INFO.json" not in names:
            raise RuntimeError("备份中缺少说明文件")
        try:
            manifest = json.loads(archive.read("BACKUP_INFO.json"))
        except (UnicodeDecodeError, ValueError, TypeError) as exc:
            raise RuntimeError("备份说明文件无效") from exc
        if not isinstance(manifest, dict) or manifest.get("type") not in {"日常", "完整"}:
            raise RuntimeError("备份说明文件内容无效")
        with tempfile.TemporaryDirectory(prefix="80gotv-verify-") as temp_dir:
            database_path = Path(temp_dir) / "cs_site.db"
            with archive.open("database/cs_site.db") as source, database_path.open("wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
            conn = sqlite3.connect(database_path)
            try:
                result = conn.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                conn.close()
            if result != "ok":
                raise RuntimeError(f"备份数据库检查失败：{result}")
    return True


def _prune_old_backups(output_dir, kind, keep):
    if keep is None:
        return
    if keep < 1:
        raise ValueError("备份保留数量必须至少为 1")
    pattern = re.compile(rf"^80gotv-\d{{8}}-\d{{6}}(?:-\d{{6}})?-{re.escape(kind)}\.zip$")
    backups = sorted(
        (path for path in output_dir.iterdir() if path.is_file() and pattern.fullmatch(path.name)),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )
    for old_backup in backups[keep:]:
        old_backup.unlink()


def create_backup_file(output_dir, include_demos=False, keep=None):
    """Write a verified ZIP to disk and return its absolute path."""
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    kind = "完整" if include_demos else "日常"
    output = output_dir / f"80gotv-{stamp}-{kind}.zip"
    partial = output.with_suffix(".zip.partial")

    try:
        with tempfile.TemporaryDirectory(prefix="80gotv-backup-") as temp_dir:
            snapshot = Path(temp_dir) / "cs_site.db"
            _snapshot_database(snapshot)
            counts = {}
            with zipfile.ZipFile(partial, "w", allowZip64=True) as archive:
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
                    "note": ".env 含有密钥，不会放入备份包。",
                }
                archive.writestr(
                    "BACKUP_INFO.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2),
                )
        verify_backup(partial)
        os.replace(partial, output)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    _prune_old_backups(output_dir, kind, keep)
    return output
