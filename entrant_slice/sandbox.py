"""Opt-in local sandbox. Importing this module does not load the website or open a DB."""

import os
import secrets
import sqlite3
import stat
import subprocess
import sys
import tempfile
from contextlib import closing
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
ROOT = PACKAGE.parent
DELIVERY = ROOT / "tests" / "acceptance" / "slice-01-event-entrant"
DEFAULT_WORKSPACE = DELIVERY / ".sandbox"
MARKER = ".entrant-sandbox"
SIGNATURE = "80GOTV isolated event entrants\n"
DB = "entrants.sqlite"
MIGRATION = "event_registration_and_initial_roster"
_configured = False
_bound: Path | None = None


def _folder(given: Path) -> Path:
    path = Path(os.path.abspath(given))
    if (
        str(path).startswith(("//", "\\\\"))
        or path.resolve() != path
        or path in (DELIVERY, ROOT)
        or not any(
            base in path.parents for base in (DELIVERY, Path(tempfile.gettempdir()).resolve())
        )
    ):
        raise ValueError("只允许切片交付目录或系统临时目录中的独立本机沙盒")
    for child in (
        path,
        path / MARKER,
        *(path / (DB + s) for s in ("", "-wal", "-shm", "-journal")),
    ):
        if child.exists() or child.is_symlink():
            info = child.lstat()
            if (
                child.is_symlink()
                or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                or (child != path and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1))
            ):
                raise ValueError("沙盒路径不接受重定向、链接或非普通文件")
    return path


def _owned(workspace: Path) -> Path:
    path = _folder(workspace)
    marker = path / MARKER
    if (
        not marker.is_file()
        or marker.stat().st_size != len(SIGNATURE)
        or marker.read_bytes() != SIGNATURE.encode()
    ):
        raise ValueError("没有本切片创建的沙盒标记，不打开数据库")
    return path


def _load_config():
    global _configured
    if not _configured:
        if any(name in sys.modules for name in ("config", "models", "web_app", "app", "wsgi")):
            raise RuntimeError("请用新的 Python 进程启动隔离切片，不借用已加载的网站配置")
        os.environ.update(
            FLASK_ENV="testing",
            PYTHON_DOTENV_DISABLED="1",
            DATABASE_PATH=":memory:",
            TURSO_URL="",
            TURSO_TOKEN="",
            GSI_TOKEN=secrets.token_urlsafe(32),
            GOTV_SECRET="",
            SECRET_KEY=secrets.token_urlsafe(32),
            STEAM_WEB_API_KEY="",
            SMTP_USERNAME="",
            SMTP_PASSWORD="",
            ADMIN_PASSWORD="",
            ADMIN_USERNAME="slice-local",
            TRUSTED_HOSTS="",
            TRUST_PROXY="false",
            PUBLIC_BASE_URL="auto",
            SESSION_COOKIE_DOMAIN="",
            SESSION_COOKIE_SECURE="false",
            SESSION_COOKIE_NAME="entrant_sandbox",
        )
        from config import Config
        Config.DATABASE = ":memory:"
        _configured = True
    from config import Config

    return Config


def connect(workspace: Path) -> sqlite3.Connection:
    path = _owned(workspace) / DB
    conn = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _base_schema(workspace: Path) -> None:
    db = _owned(workspace) / DB
    config = _load_config()
    config.DATABASE = str(db)
    from models import init_tables

    init_tables()


def initialize(workspace: Path) -> Path:
    path = _folder(workspace)
    _load_config()
    if not path.exists():
        path.mkdir(mode=0o700, parents=True)
    if not (path / MARKER).exists():
        if any(path.iterdir()):
            raise ValueError("只在空目录建立隔离环境，不接管已有文件")
        with (path / MARKER).open("xb") as file:
            file.write(SIGNATURE.encode())
    _owned(path)
    if not (path / DB).exists():
        with (path / DB).open("xb"):
            pass
    with closing(connect(path)) as db:
        has_base = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
    if not has_base:
        # init_tables() uses global site configuration; never retarget a running preview.
        subprocess.run(
            [sys.executable, "-B", "-m", "entrant_slice.sandbox", str(path)], cwd=ROOT, check=True
        )
    with closing(connect(path)) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute(
                "CREATE TABLE IF NOT EXISTS entrant_schema_migration(name TEXT PRIMARY KEY,applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            versions = {row[0] for row in db.execute("SELECT name FROM entrant_schema_migration")}
            if versions - {MIGRATION}:
                raise ValueError("沙盒结构来自其他版本，不覆盖")
            if MIGRATION not in versions:
                for filename in ("registration.sql", "formation.sql"):
                    statement = ""
                    for line in (
                        (PACKAGE / filename).read_text(encoding="utf-8").splitlines(keepends=True)
                    ):
                        statement += line
                        if sqlite3.complete_statement(statement):
                            db.execute(statement)
                            statement = ""
                    if statement.strip():
                        raise ValueError("隔离迁移 SQL 不完整")
                db.execute("INSERT INTO entrant_schema_migration(name) VALUES(?)", (MIGRATION,))
            db.commit()
        except BaseException:
            db.rollback()
            raise
    return path


def remove(workspace: Path) -> None:
    path = _owned(workspace)
    entries = list(path.iterdir())
    if _bound == path or any(
        f.name not in {MARKER, DB, DB + "-wal", DB + "-shm", DB + "-journal"} for f in entries
    ):
        raise ValueError("请先关闭预览；沙盒有未知文件时不会代为删除")
    for file in entries:
        if file.name != MARKER:
            file.unlink()
    (path / MARKER).unlink()
    path.rmdir()


def create_app(workspace: Path):
    global _bound
    path = _owned(workspace)
    config = _load_config()
    if _bound is not None:
        if _bound != path:
            raise RuntimeError("一个预览进程仅绑定一份隔离库")
        from web_app import app

        return app
    with closing(connect(path)) as db:
        if not db.execute(
            "SELECT 1 FROM entrant_schema_migration WHERE name=?", (MIGRATION,)
        ).fetchone():
            raise ValueError("请先建立隔离结构")
    config.DATABASE = str(path / DB)
    from app import app

    from .legacy import install_legacy_reads
    from .web import install_writes

    app.config.update(
        TESTING=True,
        PROPAGATE_EXCEPTIONS=False,
        SESSION_COOKIE_DOMAIN=None,
        ENTRANT_WORKSPACE=path,
        SESSION_COOKIE_SECURE=False,
        TRUSTED_HOSTS=["localhost", "127.0.0.1"],
    )
    install_legacy_reads(app, lambda: connect(path))
    install_writes(app, lambda: connect(path))
    _bound = path
    return app


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("请通过 python -m entrant_slice init 建立隔离环境")
    _base_schema(Path(sys.argv[1]))
