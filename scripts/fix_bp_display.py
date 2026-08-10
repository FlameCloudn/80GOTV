"""One-off data fix: rewrite completed BP logs with real team names and the
team that chose each side. Creates a timestamped database copy first.

Usage: python scripts/fix_bp_display.py [db_path]
Default db_path targets the production database.
"""

import argparse
import datetime
import json
import os
import shutil
import sqlite3
import sys

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from services.match_service import supplement_temp_teams  # noqa: E402
from utils.bp_manager import format_bp_log  # noqa: E402


def _load_team_names(conn, match):
    row = conn.execute(
        """SELECT m.team1_id, m.team2_id, m.team1_players, m.team2_players,
                  t1.name AS team1_name, t2.name AS team2_name,
                  t1.short_name AS t1s, t2.short_name AS t2s
           FROM matches m
           LEFT JOIN teams t1 ON t1.id=m.team1_id
           LEFT JOIN teams t2 ON t2.id=m.team2_id
           WHERE m.id=?""",
        (match["id"],),
    ).fetchone()
    if not row:
        return "T1", "T2"
    try:
        filled = supplement_temp_teams(row, conn)
        return filled.get("team1_name") or "T1", filled.get("team2_name") or "T2"
    except Exception:
        return row["team1_name"] or "T1", row["team2_name"] or "T2"


def main():
    parser = argparse.ArgumentParser(description="重写已完成 BP 的展示文本")
    parser.add_argument("db", nargs="?", default="/srv/80gotv/data/cs_site.db")
    args = parser.parse_args()

    db = args.db
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = db + ".before-bp-display-" + ts
    shutil.copy2(db, backup)

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row

    updated = 0
    skipped = []
    for match in conn.execute(
        "SELECT id, bp_state, bp_process FROM matches WHERE bp_state IS NOT NULL"
    ):
        try:
            state = json.loads(match["bp_state"])
        except (TypeError, ValueError, json.JSONDecodeError):
            skipped.append((match["id"], "bp_state 无法解析"))
            continue
        if state.get("status") != "completed" or not state.get("picks"):
            skipped.append((match["id"], "BP 未完成"))
            continue
        team1_name, team2_name = _load_team_names(conn, match)
        text = format_bp_log(state, team1_name, team2_name)
        if text != (match["bp_process"] or ""):
            conn.execute(
                "UPDATE matches SET bp_process=? WHERE id=?",
                (text, match["id"]),
            )
            updated += 1
            print("match", match["id"], "已更新")
        else:
            print("match", match["id"], "无需更新")

    conn.commit()
    print("backup=", backup)
    print("updated=", updated)
    if skipped:
        print("skipped=", skipped)
    conn.close()


if __name__ == "__main__":
    main()
