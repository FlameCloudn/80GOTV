"""Create and verify disk-backed website backups."""

import json
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path, PurePosixPath

from flask import current_app, has_app_context

from src.website.domains.demos.demo_storage import original_path, private_root
from src.website.runtime.config import Config
from src.website.runtime.database import database_path
from src.website.runtime.storage import SOURCE_ROOT, site_paths


def _originals_in_snapshot(conn):
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='demo_originals'"
    ).fetchone():
        return []
    conn.row_factory = sqlite3.Row
    return conn.execute("SELECT storage_key,byte_count FROM demo_originals").fetchall()


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
    source_path = Path(database_path()).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"找不到数据库：{source_path}")
    source = sqlite3.connect(f"{source_path.as_uri()}?mode=ro", uri=True)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()


_DATABASE_MEMBER = "database/cs_site.db"
_ALLOWED_PREFIXES = (
    "static/avatars/",
    "static/uploads/",
    "static/demos/",
    "instance/match-demos/",
    "instance/team_logo_originals/",
    "instance/csda_cache/",
)


def _check_member_path(filename):
    path = PurePosixPath(filename.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeError(f"备份包含不安全路径：{filename}")
    name = path.as_posix().rstrip("/")
    if name in {_DATABASE_MEMBER, "BACKUP_INFO.json", "database", "static"}:
        return
    if not any(
        name.startswith(prefix) or prefix.startswith(name + "/") for prefix in _ALLOWED_PREFIXES
    ):
        raise RuntimeError(f"备份包含未知内容：{filename}")


def read_backup_manifest(archive, *, database_only=False):
    """验证同一份已打开的包。单库恢复不提取其他成员，仍兼容旧包的附加文件。"""
    names = archive.namelist()
    if len(names) != len(set(names)):
        raise RuntimeError("备份中包含重复路径")
    if not database_only:
        for name in names:
            _check_member_path(name)
    bad_member = archive.testzip()
    if bad_member:
        raise RuntimeError(f"备份文件损坏：{bad_member}")
    if _DATABASE_MEMBER not in names:
        raise RuntimeError("备份中缺少数据库")
    if "BACKUP_INFO.json" not in names:
        raise RuntimeError("备份中缺少说明文件")
    try:
        manifest = json.loads(archive.read("BACKUP_INFO.json"))
    except (UnicodeDecodeError, ValueError, TypeError) as exc:
        raise RuntimeError("备份说明文件无效") from exc
    if not isinstance(manifest, dict) or manifest.get("type") not in {"日常", "完整"}:
        raise RuntimeError("备份说明文件内容无效")
    return manifest


def verify_snapshot(archive, database_path, manifest):
    """核对实际提取的数据库，以及完整备份承诺登记的 Demo 原件。"""
    with closing(sqlite3.connect(database_path)) as conn:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"备份数据库检查失败：{result}")
        if manifest["type"] == "完整":
            for original in _originals_in_snapshot(conn):
                name = f"instance/match-demos/{original['storage_key']}"
                if (
                    name not in archive.NameToInfo
                    or archive.getinfo(name).file_size != original["byte_count"]
                ):
                    raise RuntimeError("完整备份缺少数据库登记的 Demo 原件，或文件大小不符")


def extract_verified_database(archive, destination, *, database_only=False):
    manifest = read_backup_manifest(archive, database_only=database_only)
    with archive.open(_DATABASE_MEMBER) as source, destination.open("wb") as target:
        shutil.copyfileobj(source, target, length=1024 * 1024)
    verify_snapshot(archive, destination, manifest)


def verify_backup(path):
    """核对整站归档的成员、校验码、数据库和完整备份的原件。"""
    with zipfile.ZipFile(Path(path).resolve()) as archive:
        with tempfile.TemporaryDirectory(prefix="80gotv-verify-") as temp_dir:
            extract_verified_database(archive, Path(temp_dir) / "cs_site.db")
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
            paths = site_paths()
            counts = {}
            with zipfile.ZipFile(partial, "w", allowZip64=True) as archive:
                archive.write(snapshot, "database/cs_site.db", zipfile.ZIP_DEFLATED)
                counts["avatars"] = _add_tree(archive, paths.avatars, "static/avatars")
                counts["uploads"] = _add_tree(archive, paths.uploads, "static/uploads")
                counts["team_logo_originals"] = _add_tree(
                    archive, paths.logo_originals, "instance/team_logo_originals"
                )
                if include_demos:
                    counts["demos"] = _add_tree(archive, paths.demos, "static/demos")
                    if paths.analysis.is_dir():
                        counts["demos"] += _add_tree(
                            archive, paths.analysis, "static/demos/analysis"
                        )
                    # 旧赛手枪局排行仍读取这份解析结果，不能当成浏览器缓存丢弃。
                    counts["csda_cache"] = _add_tree(
                        archive, paths.csda_records, "instance/csda_cache"
                    )
                    # 只带走与这份数据库快照对应的永久原件，不复制正在上传或解析的临时文件。
                    with closing(sqlite3.connect(snapshot)) as copied_db:
                        originals = _originals_in_snapshot(copied_db)
                    configured = (
                        current_app.config.get("HOST_DEMO_ROOT")
                        if has_app_context()
                        else Config.HOST_DEMO_ROOT
                    )
                    root = private_root(
                        paths.root, SOURCE_ROOT / "static", configured or paths.managed_demos
                    )
                    for original in originals:
                        archive.write(
                            original_path(root, original),
                            f"instance/match-demos/{original['storage_key']}",
                            zipfile.ZIP_STORED,
                        )
                    counts["managed_demos"] = len(originals)
                manifest = {
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    "type": kind,
                    "database": os.path.abspath(database_path()),
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
