"""Review and correct historical Impact without changing other statistics."""

import argparse
import json
import math
import os
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.performance_service import weighted_average_sql  # noqa: E402
from utils.stats_calc import (  # noqa: E402
    HLTV2_ESTIMATE_METHOD,
    HLTV2_ESTIMATE_SOURCE,
    calculate_impact,
    estimate_hltv2_impact,
)

ROW_FIELDS = (
    "id",
    "match_id",
    "player_id",
    "team_id",
    "map_name",
    "side",
    "data_source",
    "data_status",
    "data_version",
    "kills",
    "assists",
    "rounds_played",
    "impact",
    "first_kills",
    "first_deaths",
    "multi2k",
    "multi3k",
    "multi4k",
    "multi5k",
    "clutches_won",
)
COUNT_FIELDS = (
    "kills",
    "assists",
    "rounds_played",
    "first_kills",
    "first_deaths",
    "multi2k",
    "multi3k",
    "multi4k",
    "multi5k",
    "clutches_won",
)


def _connection(database, mode):
    connection = sqlite3.connect(database.as_uri() + f"?mode={mode}", uri=True, timeout=15)
    connection.row_factory = sqlite3.Row
    return connection


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _candidate(row):
    if (row["data_status"] or "final") != "final":
        return None, "不是当前有效的最终记录"
    if (row["data_source"] or "legacy") not in {"legacy", "demo_review"}:
        return None, "来源不在本次历史修正范围内"
    if not row["player_id"] or not row["match_id"]:
        return None, "缺少选手或比赛归属"
    for field in COUNT_FIELDS:
        value = row[field]
        if not _finite(value) or value < 0 or int(value) != value:
            return None, "原始计数缺失或不合法"
    if row["rounds_played"] <= 0 or not _finite(row["impact"]):
        return None, "缺少有效回合数或原 Impact"
    impact = round(estimate_hltv2_impact(row["kills"], row["assists"], row["rounds_played"]), 2)
    if math.isclose(row["impact"], impact, abs_tol=0.005):
        return None, "已经符合当前计算方式"
    legacy = calculate_impact(
        row["first_kills"],
        row["first_deaths"],
        sum(row[field] for field in ("multi2k", "multi3k", "multi4k", "multi5k")),
        row["clutches_won"],
        row["rounds_played"],
    )
    if not math.isclose(row["impact"], legacy, abs_tol=0.005):
        return None, "与旧算法不符，保留人工值或待核对数据"
    return impact, None


def build_plan(database):
    database = Path(database).resolve(strict=True)
    plan = {
        "version": 1,
        "database": str(database),
        "method": HLTV2_ESTIMATE_METHOD,
        "source": HLTV2_ESTIMATE_SOURCE,
        "official_hltv_formula": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "rows": [],
        "skipped": [],
    }
    with closing(_connection(database, "ro")) as conn:
        rows = conn.execute(f"SELECT {','.join(ROW_FIELDS)} FROM match_stats ORDER BY id")
        for entry in rows:
            row = dict(entry)
            impact, reason = _candidate(row)
            if reason:
                plan["skipped"].append({"id": row["id"], "reason": reason})
            else:
                plan["rows"].append({"before": row, "after_impact": impact})
    return plan


def _snapshot(database, backup):
    backup.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    # A separate reader can snapshot while the writer holds a reserved lock.
    with closing(_connection(database, "ro")) as source, closing(sqlite3.connect(backup)) as target:
        source.backup(target)
        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("修改前数据库备份检查失败，未修改统计")


def apply_plan(database, plan, backup):
    database = Path(database).resolve(strict=True)
    backup = Path(backup).resolve()
    if plan.get("version") != 1 or plan.get("method") != HLTV2_ESTIMATE_METHOD:
        raise ValueError("计划版本或计算方式不符")
    if Path(plan.get("database", "")).resolve() != database or backup == database:
        raise ValueError("数据库或备份路径与计划不符")
    result = {"updated_rows": 0, "already_applied": 0, "summaries": [], "backup": None}
    with closing(_connection(database, "rw")) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            pending = []
            seen = set()
            for item in plan["rows"]:
                before = item["before"]
                if set(before) != set(ROW_FIELDS) or before["id"] in seen:
                    raise ValueError("计划包含不完整或重复的记录")
                seen.add(before["id"])
                expected, reason = _candidate(before)
                if reason or not _finite(item["after_impact"]) or expected != item["after_impact"]:
                    raise ValueError("计划中的计算结果与当前公式不符")
                entry = conn.execute(
                    f"SELECT {','.join(ROW_FIELDS)} FROM match_stats WHERE id=?",
                    (before["id"],),
                ).fetchone()
                if entry is None:
                    raise ValueError("计划中的比赛统计已变化，请重新生成对照")
                current = dict(entry)
                if any(
                    current[field] != before[field] for field in ROW_FIELDS if field != "impact"
                ):
                    raise ValueError("计划中的原始输入已变化，请重新生成对照")
                if current["impact"] == expected:
                    result["already_applied"] += 1
                elif current["impact"] == before["impact"]:
                    pending.append(item)
                else:
                    raise ValueError("计划中的 Impact 已变化，请重新生成对照")
            if not pending:
                conn.rollback()
                return result

            player_ids = sorted({item["before"]["player_id"] for item in pending})
            previous_summaries = {}
            for player_id in player_ids:
                row = conn.execute(
                    "SELECT avg_impact FROM player_performance_summary WHERE player_id=?",
                    (player_id,),
                ).fetchone()
                if row is None:
                    raise ValueError("选手缺少现有汇总记录，未修改任何统计")
                previous_summaries[player_id] = row["avg_impact"]
            _snapshot(database, backup)
            for item in pending:
                conn.execute(
                    "UPDATE match_stats SET impact=? WHERE id=?",
                    (item["after_impact"], item["before"]["id"]),
                )
            average_sql = weighted_average_sql("impact", "rounds_played")
            for player_id in player_ids:
                average = conn.execute(
                    f"SELECT COALESCE({average_sql}, 0) FROM match_stats "
                    "WHERE player_id=? AND COALESCE(data_status, 'final')<>'superseded'",
                    (player_id,),
                ).fetchone()[0]
                conn.execute(
                    "UPDATE player_performance_summary SET avg_impact=? WHERE player_id=?",
                    (average, player_id),
                )
                result["summaries"].append(
                    {
                        "player_id": player_id,
                        "before": previous_summaries[player_id],
                        "after": average,
                    }
                )
            conn.commit()
            result["updated_rows"] = len(pending)
            result["backup"] = str(backup)
            return result
        except Exception:
            conn.rollback()
            raise


def main():
    parser = argparse.ArgumentParser(
        description="先生成历史 Impact 对照，确认后只修正 Impact 和其平均数"
    )
    parser.add_argument(
        "--database", required=True, type=Path, help="明确指定 SQLite 数据库，不读取网站密码配置"
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--plan", type=Path, help="只生成对照文件，不修改数据库，不覆盖已有文件")
    action.add_argument("--apply-plan", type=Path, help="应用已经核对的对照文件，不自动加入新记录")
    parser.add_argument("--backup", type=Path, help="应用时必须提供新的修改前备份位置")
    args = parser.parse_args()
    if args.plan:
        if args.backup:
            parser.error("只生成对照时不需要备份参数")
        plan = build_plan(args.database)
        args.plan.parent.mkdir(parents=True, exist_ok=True)
        with args.plan.open("x", encoding="utf-8") as target:
            json.dump(plan, target, ensure_ascii=False, indent=2, allow_nan=False)
        print(f"已生成对照：待核对 {len(plan['rows'])} 条，跳过 {len(plan['skipped'])} 条。")
        print("计划已生成，尚未修改数据库。")
        print(f"对照文件：{args.plan.resolve()}")
    else:
        if not args.backup:
            parser.error("应用对照前必须指定新的备份位置")
        plan = json.loads(args.apply_plan.read_text(encoding="utf-8"))
        result = apply_plan(args.database, plan, args.backup)
        print(
            f"已修正 {result['updated_rows']} 条 Impact，更新 {len(result['summaries'])} 个平均数。"
        )
        print(f"已有 {result['already_applied']} 条符合对照，无需重复修改。")
        if result["backup"]:
            print(f"修改前备份：{result['backup']}")


if __name__ == "__main__":
    main()
