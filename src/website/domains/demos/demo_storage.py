"""Private originals and their explicit bindings to recorded map runs."""

import hashlib
import json
import logging
import os
import sqlite3
import stat
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import IO

from src.website.domains.demos.demo_naming import build_demo_download_name
from src.website.runtime.host import HostError, is_managed_match, write
from src.website.runtime.storage import site_paths

logger = logging.getLogger("80gotv")

MAX_DEMO_BYTES = 1024**3
_CHUNK_BYTES = 1024**2
_HEADERS = (b"PBDEMS2\0", b"HL2DEMO\0")


def private_root(instance_path, static_folder, configured=None):
    root = Path(configured or Path(instance_path) / "match-demos").resolve()
    public_media = site_paths().uploads.parent.resolve()
    if root.is_relative_to(public_media) or (
        static_folder and root.is_relative_to(Path(static_folder).resolve())
    ):
        raise HostError("Demo 原件目录不能位于公开静态目录", 503)
    return root


def require_idle_sqlite(conn):
    if not isinstance(conn, sqlite3.Connection):
        raise HostError("托管 Demo 只支持本机 SQLite 数据库", 503)
    if conn.in_transaction:
        raise HostError("接收或解析 Demo 前请先结束数据库写入事务")


def _require_target(conn, match_id, scheduled_map_id, run_id):
    if not is_managed_match(conn, match_id):
        raise HostError("这不是托管比赛，请使用旧 Demo 入口", 404)
    target = conn.execute(
        """SELECT s.map_name FROM map_runs r JOIN scheduled_maps s USING (scheduled_map_id)
           WHERE r.map_run_id=? AND s.scheduled_map_id=? AND s.match_id=? AND s.is_enabled=1""",
        (run_id, scheduled_map_id, match_id),
    ).fetchone()
    if target is None or not target["map_name"]:
        raise HostError("所选开局不属于本场已排定的赛图")


def _original_metadata(original):
    return {k: v for k, v in dict(original).items() if k != "storage_key"}


def get_original(conn, match_id, demo_id):
    row = conn.execute(
        """SELECT d.*, m.match_id, m.scheduled_map_id, m.map_name, m.legacy_slot,
                  r.status AS run_status, games.event_id, games.status AS match_status,
                  c.archived_at IS NOT NULL AS event_archived
           FROM demo_originals d
           JOIN map_runs r USING (map_run_id)
           JOIN scheduled_maps m USING (scheduled_map_id)
           JOIN matches games ON games.id=m.match_id
           JOIN event_registration_control c ON c.event_id=games.event_id
           WHERE m.match_id=? AND d.demo_id=?""",
        (match_id, demo_id),
    ).fetchone()
    if row is None:
        raise HostError("本场没有这份 Demo 原件", 404)
    return dict(row)


def original_path(root: Path, original) -> Path:
    key = original["storage_key"]
    path = root / key
    if Path(key).name != key:
        raise HostError("Demo 原件记录无效", 500)
    try:
        info = path.lstat()
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise HostError("服务器找不到完整的 Demo 原件", 404) from exc
    except OSError as exc:
        raise HostError("服务器暂时无法读取 Demo 原件", 503) from exc
    if stat.S_ISLNK(info.st_mode):
        raise HostError("Demo 原件记录无效", 500)
    if not stat.S_ISREG(info.st_mode) or info.st_size != original["byte_count"]:
        raise HostError("服务器找不到完整的 Demo 原件", 404)
    return path


def receive_original(
    conn,
    *,
    root: Path,
    match_id: int,
    scheduled_map_id: int,
    run_id: int,
    stream: IO[bytes],
    filename: str,
    actor: int,
    max_bytes: int = MAX_DEMO_BYTES,
):
    """Save the original byte stream before registering it in a short write."""
    require_idle_sqlite(conn)
    _require_target(conn, match_id, scheduled_map_id, run_id)
    if not filename.lower().endswith(".dem"):
        raise HostError("请选择 .dem 文件", 400)

    digest = hashlib.blake2b(digest_size=32)
    header = stream.read(8)
    if header not in _HEADERS:
        raise HostError("文件不是可识别的 Demo 原件", 400)
    size = len(header)
    pending = None
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="wb", dir=root, prefix=f"run-{run_id}-", suffix=".part", delete=False
        ) as output:
            pending = Path(output.name)
            digest.update(header)
            output.write(header)
            while block := stream.read(_CHUNK_BYTES):
                size += len(block)
                if size > max_bytes:
                    raise HostError("Demo 文件超过上传大小限制", 413)
                output.write(block)
                digest.update(block)
            output.flush()
            os.fsync(output.fileno())
        if size == len(header):
            raise HostError("Demo 文件没有录像内容", 400)
        fingerprint = digest.hexdigest()
        saved = pending.with_name(f"{pending.stem}-{fingerprint}.dem")
        pending.rename(saved)
        pending = None
    except OSError as exc:
        raise HostError("未能完整保存 Demo 原件，请检查存储后重试", 503) from exc
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)

    duplicate = False
    # A complete unregistered copy is identifiable by its run and fingerprint.
    # Keep it if registration fails; only a verified duplicate can be removed.
    with write(conn):
        _require_target(conn, match_id, scheduled_map_id, run_id)
        existing = conn.execute(
            "SELECT * FROM demo_originals WHERE fingerprint=?", (fingerprint,)
        ).fetchone()
        if existing:
            original_path(root, existing)
            if existing["map_run_id"] != run_id:
                saved.unlink()
                raise HostError("相同 Demo 原件已绑定另一开局，不能重复关联")
            duplicate = True
            demo_id = existing["demo_id"]
        else:
            demo_id = conn.execute(
                """INSERT INTO demo_originals(map_run_id,storage_key,fingerprint,byte_count,uploaded_by)
                   VALUES (?,?,?,?,?)""",
                (run_id, saved.name, fingerprint, size, actor),
            ).lastrowid
    if duplicate:
        saved.unlink()
    return {
        "original": _original_metadata(get_original(conn, match_id, demo_id)),
        "duplicate": duplicate,
    }


def list_originals(conn, match_id):
    if not is_managed_match(conn, match_id):
        raise HostError("这不是托管比赛，请使用旧 Demo 入口", 404)
    defaults = {item["demo_id"] for item in _default_originals(conn, match_id)}
    return [
        {**dict(row), "download_default": row["demo_id"] in defaults}
        for row in conn.execute(
            """SELECT d.demo_id,d.map_run_id,d.byte_count,d.uploaded_by,d.uploaded_at,
                      m.scheduled_map_id,m.map_order,m.map_name,r.status AS run_status
               FROM demo_originals d JOIN map_runs r USING (map_run_id)
               JOIN scheduled_maps m USING (scheduled_map_id)
               WHERE m.match_id=? ORDER BY d.demo_id""",
            (match_id,),
        )
    ]


def get_original_detail(conn, match_id, demo_id):
    original = _original_metadata(get_original(conn, match_id, demo_id))
    original["analyses"] = [
        dict(row)
        for row in conn.execute(
            """SELECT analysis_id,status,requested_by,requested_at,finished_at,error
               FROM demo_analyses WHERE demo_id=? ORDER BY analysis_id DESC""",
            (demo_id,),
        )
    ]
    return original


def _default_originals(conn, match_id: int, *, slot: int | None = None):
    # Select one default per slot before inspecting files, so missing bytes never cause fallback.
    try:
        return conn.execute(
            """WITH defaults AS (
                   SELECT s.legacy_slot,d.storage_key,d.byte_count,d.demo_id,s.map_name,
                          ROW_NUMBER() OVER (
                              PARTITION BY s.legacy_slot ORDER BY p.adoption_id DESC
                          ) AS slot_rank
                   FROM demo_adoptions p
                   JOIN demo_analyses a USING (analysis_id)
                   JOIN demo_originals d USING (demo_id)
                   JOIN map_runs r USING (map_run_id)
                   JOIN scheduled_maps s USING (scheduled_map_id)
                   JOIN official_map_results o ON o.scheduled_map_id=s.scheduled_map_id
                     AND o.map_run_id=r.map_run_id AND o.revision=p.result_revision
                   WHERE s.match_id=? AND s.legacy_slot=COALESCE(?,s.legacy_slot)
                     AND s.is_enabled=1 AND o.is_current=1
                     AND r.status='closed' AND p.download_default=1
               )
               SELECT legacy_slot,storage_key,byte_count,demo_id,map_name
               FROM defaults WHERE slot_rank=1""",
            (match_id, slot + 1 if slot is not None else None),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        # Pre-operations databases do not have managed Demo defaults.
        if str(exc) == "no such table: demo_adoptions":
            return []
        raise


def default_download(conn, root: Path, match_id: int, slot: int):
    """Return only the approved original for the currently selected official run."""
    originals = _default_originals(conn, match_id, slot=slot)
    if not originals:
        raise HostError("这张地图还没有可下载的托管 Demo", 404)
    original = originals[0]
    return original_path(root, original), original["demo_id"], original["map_name"]


def legacy_download(conn, match_id, slot):
    """Resolve an original by its recorded slot, never by a public static file name."""
    match = conn.execute(
        "SELECT demo_file, map1, map2, map3, map4, map5 FROM matches WHERE id=?", (match_id,)
    ).fetchone()
    if not match or not match["demo_file"]:
        raise HostError("这场比赛没有可下载的 Demo", 404)
    try:
        files = json.loads(match["demo_file"])
    except (ValueError, TypeError) as exc:
        raise HostError("Demo 文件记录损坏", 500) from exc
    if not isinstance(files, list):
        raise HostError("Demo 文件记录损坏", 500)
    if not 0 <= slot < len(files):
        raise HostError("找不到这张地图的 Demo", 404)
    item = files[slot]
    filename = item.get("filename") if isinstance(item, dict) else item
    if not isinstance(filename, str) or os.path.basename(filename) != filename:
        raise HostError("Demo 文件名无效", 400)
    directory = site_paths().demos
    if not (directory / filename).is_file():
        raise HostError("服务器上找不到 Demo 文件", 404)
    map_name = match[f"map{slot + 1}"] if slot < 5 else ""
    return directory, filename, build_demo_download_name(filename, slot, map_name)


def available_download_slots(conn, match_id: int, *, instance_path, static_folder, configured=None):
    """Return only zero-based slots whose selected originals can be opened."""
    candidates = _default_originals(conn, match_id)
    slots = set()
    if not candidates:
        return slots
    try:
        root = private_root(instance_path, static_folder, configured)
    except (HostError, OSError) as exc:
        detail = exc.message if isinstance(exc, HostError) else type(exc).__name__
        logger.warning("托管 Demo 下载目录不可用：比赛 %s（%s）", match_id, detail)
        return slots

    for original in candidates:
        slot = original["legacy_slot"] - 1
        try:
            with original_path(root, original).open("rb"):
                slots.add(slot)
        except (FileNotFoundError, NotADirectoryError):
            continue
        except HostError as exc:
            if exc.status != 404:
                logger.warning(
                    "托管 Demo 可读性检查失败：比赛 %s，槽 %s（%s）", match_id, slot, exc.message
                )
        except OSError as exc:
            logger.warning(
                "托管 Demo 可读性检查失败：比赛 %s，槽 %s（%s）", match_id, slot, type(exc).__name__
            )
    return slots
