"""Safely reparse stored Demo files and replace per-map statistics."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models import get_db  # noqa: E402
from services.demo_service import analyze_demo, import_demo_data  # noqa: E402


def _stored_demo_files(raw_value):
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value)
    except (TypeError, json.JSONDecodeError):
        parsed = raw_value
    if isinstance(parsed, list):
        return [str(item).strip() if item else "" for item in parsed]
    return [str(parsed).strip()]


def _load_matches(conn, match_ids):
    where = ""
    params = []
    if match_ids:
        placeholders = ",".join("?" for _ in match_ids)
        where = f"WHERE m.id IN ({placeholders})"
        params.extend(match_ids)
    else:
        where = "WHERE COALESCE(m.demo_file, '') NOT IN ('', '[]')"
    return conn.execute(
        f"""
        SELECT m.*, e.short_name AS event_short_name
        FROM matches m
        LEFT JOIN events e ON e.id=m.event_id
        {where}
        ORDER BY m.id
        """,
        params,
    ).fetchall()


def _backup_sqlite(conn, backup_dir):
    if not isinstance(conn, sqlite3.Connection):
        raise RuntimeError("自动备份只支持本地 SQLite；当前数据库不能安全执行写入")
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"reparse-before-{stamp}.db"
    target = sqlite3.connect(backup_path)
    try:
        conn.backup(target)
    finally:
        target.close()
    return backup_path


def _summary(preview):
    players = preview.get("players", [])
    return {
        "players": len(players),
        "clutches": sum(int(player.get("clutches_won", 0) or 0) for player in players),
        "multi2plus": sum(
            sum(int(player.get(f"multi{count}k", 0) or 0) for count in range(2, 6))
            for player in players
        ),
    }


def main():
    parser = argparse.ArgumentParser(
        description="重新解析已保存的 Demo。默认只预览，不修改数据库。"
    )
    parser.add_argument(
        "--match-id",
        type=int,
        action="append",
        dest="match_ids",
        help="只处理指定比赛；可重复使用。省略时处理所有有 Demo 的比赛。",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只解析并显示结果（默认）")
    mode.add_argument("--apply", action="store_true", help="备份数据库后写入真实统计")
    parser.add_argument(
        "--demo-dir",
        type=Path,
        default=ROOT / "static" / "demos",
        help="Demo 文件目录",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=ROOT / "backups",
        help="写入前的数据库备份目录",
    )
    args = parser.parse_args()

    conn = get_db()
    try:
        matches = _load_matches(conn, args.match_ids)
        if not matches:
            print("没有找到包含 Demo 的比赛。")
            return 0

        parsed_items = []
        for match in matches:
            for slot, filename in enumerate(_stored_demo_files(match["demo_file"])):
                if not filename:
                    continue
                demo_path = args.demo_dir / Path(filename).name
                if not demo_path.is_file():
                    raise FileNotFoundError(f"Demo 不存在：{demo_path}")
                print(f"解析比赛 {match['id']}，地图 {slot + 1}：{demo_path.name}")
                preview = analyze_demo(conn, match, str(demo_path))
                parsed_items.append((match, slot, preview))
                summary = _summary(preview)
                print(
                    "  "
                    f"{preview.get('map_name') or '未知地图'}，"
                    f"{summary['players']} 名选手，"
                    f"{summary['clutches']} 次残局获胜，"
                    f"{summary['multi2plus']} 个多杀回合"
                )

        if not args.apply:
            print("预览完成：数据库没有被修改。使用 --apply 才会写入。")
            return 0

        backup_path = _backup_sqlite(conn, args.backup_dir)
        print(f"数据库备份：{backup_path}")
        conn.execute("BEGIN")
        try:
            for match, slot, preview in parsed_items:
                result, message = import_demo_data(
                    conn,
                    match["id"],
                    match,
                    preview["demo_data"],
                    slot,
                )
                if result is None:
                    raise RuntimeError(message)
                print(f"写入比赛 {match['id']}，地图 {slot + 1}：{message}")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        print(f"完成：已写入 {len(parsed_items)} 份 Demo。")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
