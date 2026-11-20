"""Run or check 80GOTV database upgrades."""

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path

from src.website.runtime.config import Config
from src.website.runtime.database import get_db, using_turso
from src.website.runtime.schema import init_tables, supported_schema_version


def current_version():
    if using_turso():
        connection = get_db()
    else:
        path = Path(Config.DATABASE).resolve()
        if not path.exists():
            return 0
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    with closing(connection) as conn:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone():
            return 0
        row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        return int(row[0] or 0)


def main():
    parser = argparse.ArgumentParser(description="升级或检查 80GOTV 数据库")
    parser.add_argument("--check", action="store_true", help="只检查是否已升级")
    args = parser.parse_args()
    before = current_version()
    if args.check:
        expected = supported_schema_version(remote=using_turso())
        if before != expected:
            raise SystemExit(f"数据库版本不正确：当前 {before}，代码需要 {expected}")
        print(f"数据库版本正常：{before}")
        return
    init_tables()
    after = current_version()
    print(f"数据库升级完成：{before} -> {after}")


if __name__ == "__main__":
    main()
