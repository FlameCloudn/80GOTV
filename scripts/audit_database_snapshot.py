"""Read-only database snapshot and structural inventory for a local audit."""

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path


def snapshot(source, destination):
    source = Path(source).resolve(strict=True)
    destination = Path(destination).resolve()
    root = Path(__file__).resolve().parents[1]
    if not destination.is_relative_to(root / "backups"):
        raise ValueError("备份只能写入当前副本的 backups 目录")
    if destination.exists() or destination == source:
        raise ValueError("备份目标已经存在，拒绝覆盖")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
        with closing(sqlite3.connect(destination)) as copy:
            original.backup(copy)
    with closing(sqlite3.connect(destination.as_uri() + "?mode=ro", uri=True)) as copy:
        integrity = [row[0] for row in copy.execute("PRAGMA integrity_check")]
        if integrity != ["ok"]:
            raise RuntimeError("备份完整性检查未通过，保留文件供排查")
        tables = [
            row[0]
            for row in copy.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        inventory = {}
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            inventory[table] = {
                "rows": copy.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0],
                "columns": [
                    {"name": row[1], "type": row[2], "not_null": bool(row[3])}
                    for row in copy.execute(f"PRAGMA table_info({quoted})")
                ],
            }
        foreign_key_errors = dict(
            Counter(row[0] for row in copy.execute("PRAGMA foreign_key_check"))
        )
    with destination.open("rb") as snapshot_file:
        digest = hashlib.file_digest(snapshot_file, "sha256").hexdigest()
    result = {
        "source": str(source),
        "snapshot": str(destination),
        "integrity": integrity,
        "sha256": digest,
        "tables": inventory,
        "foreign_key_errors_by_table": foreign_key_errors,
    }
    report = destination.with_suffix(".inventory.json")
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"只读备份完成：{destination.name}；完整性通过；共 {len(tables)} 张表。")
    print(f"外键异常记录数：{sum(foreign_key_errors.values())}；未修改原数据库。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="只读备份真实数据库，不初始化、不修正任何记录")
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    snapshot(args.source, args.destination)
