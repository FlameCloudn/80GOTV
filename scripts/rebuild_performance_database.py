"""Build persistent player-performance data from existing database/cache rows."""

import argparse
import gc
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from models import get_db, init_tables  # noqa: E402
from services.performance_service import (  # noqa: E402
    backfill_demo_performance,
    refresh_player_performance,
)


def _map_name_for_slot(match, slot, data):
    if 0 <= slot < 5:
        configured = match[f"map{slot + 1}"]
        if configured:
            return configured
    return str(data.get("mapName") or data.get("map_name") or "").strip()


def rebuild(cache_dir):
    init_tables()
    conn = get_db()
    processed = 0
    failed = 0
    files = sorted(Path(cache_dir).glob("match_*_slot_*.json"))
    for cache_file in files:
        match_info = re.fullmatch(r"match_(\d+)_slot_(\d+)\.json", cache_file.name)
        if not match_info:
            continue
        match_id = int(match_info.group(1))
        slot = int(match_info.group(2))
        match = conn.execute(
            """SELECT id, map1, map2, map3, map4, map5
               FROM matches WHERE id=?""",
            (match_id,),
        ).fetchone()
        if not match:
            print(f"跳过 {cache_file.name}：数据库中没有这场比赛")
            continue
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            map_name = _map_name_for_slot(match, slot, data)
            if not map_name:
                raise ValueError("缺少地图名")
            player_count = backfill_demo_performance(conn, match_id, map_name, data)
            conn.commit()
            processed += 1
            print(f"已写入 {cache_file.name}：{map_name}，{player_count} 名选手")
        except Exception as exc:
            conn.rollback()
            failed += 1
            print(f"处理失败 {cache_file.name}：{exc}")
        finally:
            gc.collect()

    refresh_player_performance(conn)
    conn.commit()
    summary_count = conn.execute("SELECT COUNT(*) FROM player_performance_summary").fetchone()[0]
    kill_count = conn.execute("SELECT COUNT(*) FROM match_kill_events").fetchone()[0]
    conn.close()
    print(
        f"完成：缓存 {processed} 个，失败 {failed} 个，"
        f"选手汇总 {summary_count} 条，击杀事件 {kill_count} 条"
    )
    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(description="重建选手表现数据库")
    parser.add_argument(
        "--cache-dir",
        default=str(PROJECT_ROOT / "instance" / "csda_cache"),
        help="CSDA 缓存目录",
    )
    args = parser.parse_args()
    raise SystemExit(rebuild(args.cache_dir))


if __name__ == "__main__":
    main()
