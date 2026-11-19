"""Preview stored Demos, then apply only verified side details."""

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.demo_side_backfill import apply_side_backfill, prepare_side_backfill  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="从Demo补齐分边数据，不修改整场评分、比分或名单")
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--demo-dir", type=Path, default=ROOT / "static/demos")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--apply-plan", type=Path)
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.apply_plan:
        if not args.backup_dir:
            parser.error("写入前必须指定--backup-dir保存原数据")
        args.backup_dir.mkdir(parents=True, exist_ok=True)
        plan = json.loads(args.apply_plan.read_text(encoding="utf-8"))
        conn = sqlite3.connect(args.database)
        conn.row_factory = sqlite3.Row
        backup = args.backup_dir / (
            "side-before-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".db"
        )
        with sqlite3.connect(backup) as target:
            conn.backup(target)
        try:
            count = apply_side_backfill(conn, plan)
            conn.commit()
            print(f"已补齐{count}条选手单图分边记录，整场评分、比分和名单均保留。")
            print(f"原数据备份：{backup}")
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            plan = prepare_side_backfill(conn, args.demo_dir, args.output / "analysis")
        finally:
            conn.close()
        (args.output / "plan.json").write_text(
            json.dumps(plan, ensure_ascii=True, indent=2), encoding="utf-8"
        )
        print(
            f"已从{len(plan['maps'])}份Demo解析出{len(plan['updates'])}条分边记录；目前仅预览，没有修改数据库。"
        )
        print("未保存Demo的比赛：" + ",".join(str(item) for item in plan["unavailable_matches"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
