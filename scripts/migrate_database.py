"""Run or check 80GOTV database upgrades."""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from models import CURRENT_SCHEMA_VERSION, get_db, init_tables


def current_version():
    conn = get_db()
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        return int(row[0] or 0)
    except Exception:
        return 0
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="升级或检查 80GOTV 数据库")
    parser.add_argument("--check", action="store_true", help="只检查是否已升级")
    args = parser.parse_args()
    before = current_version()
    if args.check:
        if before != CURRENT_SCHEMA_VERSION:
            raise SystemExit(f"数据库版本不正确：当前 {before}，代码需要 {CURRENT_SCHEMA_VERSION}")
        print(f"数据库版本正常：{before}")
        return
    init_tables()
    after = current_version()
    print(f"数据库升级完成：{before} -> {after}")


if __name__ == "__main__":
    main()
