"""Plan and apply Demo side details without replacing formal match results."""

import json
from collections import defaultdict
from pathlib import Path

from src.website.domains.demos.demo_parser import normalize_map_name, parse_player_stats
from src.website.domains.demos.demo_runner import run_analysis

SIDE_UPDATE_COLUMNS = (
    "side_stats_json",
    "t_kills",
    "ct_kills",
    "t_deaths",
    "ct_deaths",
    "t_adr",
    "ct_adr",
    "t_rating",
    "ct_rating",
    "flash_assists",
)
GUARD_COLUMNS = (
    "match_id",
    "player_id",
    "map_name",
    "data_status",
    "data_version",
    "kills",
    "deaths",
    "assists",
    "rating",
    *SIDE_UPDATE_COLUMNS,
)


def _historical_steam_ids(conn, match_id, map_key):
    result = defaultdict(set)
    for event in conn.execute("SELECT * FROM match_kill_events WHERE match_id=?", (match_id,)):
        if normalize_map_name(event["map_name"]) != map_key:
            continue
        for role in ("killer", "victim", "assister"):
            player_id, steam_id = event[f"{role}_player_id"], event[f"{role}_steam_id"]
            if player_id and steam_id:
                result[player_id].add(str(steam_id))
    return result


def prepare_side_backfill(conn, demo_dir, analysis_dir):
    updates, maps, unavailable = [], [], []
    for match in conn.execute("SELECT id,demo_file FROM matches ORDER BY id").fetchall():
        try:
            files = json.loads(match["demo_file"] or "[]")
        except (TypeError, ValueError):
            files = [match["demo_file"]] if match["demo_file"] else []
        if isinstance(files, str):
            files = [files]
        if not files or not any(files):
            unavailable.append(match["id"])
            continue
        for filename in files:
            if not filename:
                continue
            path = Path(demo_dir) / Path(filename).name
            if not path.is_file():
                raise ValueError(f"比赛{match['id']}保存的Demo文件不存在，停止写入")
            raw = run_analysis(str(path), str(analysis_dir))
            map_key = normalize_map_name(raw.get("mapName", ""))
            rows = [
                dict(row)
                for row in conn.execute(
                    "SELECT ms.*,p.steam_id FROM match_stats ms JOIN players p ON p.id=ms.player_id "
                    "WHERE ms.match_id=? AND COALESCE(ms.data_status,'final')<>'superseded'",
                    (match["id"],),
                ).fetchall()
                if normalize_map_name(row["map_name"]) == map_key
            ]
            if not map_key or not rows:
                raise ValueError(f"比赛{match['id']}的Demo地图与现有统计不匹配，停止写入")
            parsed = {str(player["steam_id"]): player for player in parse_player_stats(raw)}
            historical = _historical_steam_ids(conn, match["id"], map_key)
            for row in rows:
                identities = historical[row["player_id"]] & parsed.keys()
                if len(identities) > 1:
                    raise ValueError("比赛当时的选手身份不唯一，保留原记录")
                identity = next(iter(identities)) if identities else str(row["steam_id"])
                player = parsed.get(identity)
                if not player or not player.get("side_stats"):
                    raise ValueError(f"比赛{match['id']}选手{row['player_id']}缺少可核实的分边记录")
                for key in ("kills", "deaths", "assists"):
                    if row[key] is not None and player[key] != row[key]:
                        raise ValueError(
                            f"比赛{match['id']}选手{row['player_id']}的{key}与Demo不一致，保留原记录"
                        )
                    combined = sum(side[key] for side in player["side_stats"].values())
                    if combined != player[key]:
                        raise ValueError(
                            f"比赛{match['id']}选手{row['player_id']}的分边{key}不完整"
                        )
                sides = player["side_stats"]
                values = {
                    "side_stats_json": json.dumps(sides, separators=(",", ":")),
                    "flash_assists": sum(side["flash_assists"] for side in sides.values()),
                }
                for side in ("t", "ct"):
                    for key in ("kills", "deaths", "adr", "rating"):
                        values[f"{side}_{key}"] = sides.get(side, {}).get(key)
                updates.append(
                    {
                        "id": row["id"],
                        "before": {key: row.get(key) for key in GUARD_COLUMNS},
                        "values": values,
                    }
                )
            maps.append(
                {"match_id": match["id"], "map": map_key, "players": len(rows), "demo": path.name}
            )
    return {"version": 1, "maps": maps, "unavailable_matches": unavailable, "updates": updates}


def apply_side_backfill(conn, plan):
    if plan.get("version") != 1 or not isinstance(plan.get("updates"), list):
        raise ValueError("分边补齐计划格式不正确")
    conn.execute("SAVEPOINT demo_side_backfill")
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(match_stats)")}
        if "side_stats_json" not in columns:
            conn.execute("ALTER TABLE match_stats ADD COLUMN side_stats_json TEXT")
        for update in plan["updates"]:
            values = update["values"]
            if set(values) != set(SIDE_UPDATE_COLUMNS):
                raise ValueError("分边补齐计划试图修改范围外的字段")
            row = conn.execute("SELECT * FROM match_stats WHERE id=?", (update["id"],)).fetchone()
            current = dict(row) if row else {}
            if not current or current.get("data_status") == "superseded":
                raise ValueError("统计记录已改变，未覆盖历史版本")
            if all(current.get(key) == value for key, value in values.items()):
                continue
            if any(current.get(key) != value for key, value in update["before"].items()):
                raise ValueError("预览后统计记录已被修改，停止覆盖")
            assignments = ",".join(f"{key}=?" for key in SIDE_UPDATE_COLUMNS)
            conn.execute(
                f"UPDATE match_stats SET {assignments} WHERE id=?",
                (*[values[key] for key in SIDE_UPDATE_COLUMNS], update["id"]),
            )
        if plan["updates"]:
            from src.website.domains.statistics.performance_service import (
                refresh_player_performance,
            )

            refresh_player_performance(
                conn, {update["before"]["player_id"] for update in plan["updates"]}
            )
        conn.execute("RELEASE SAVEPOINT demo_side_backfill")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT demo_side_backfill")
        conn.execute("RELEASE SAVEPOINT demo_side_backfill")
        raise
    return len(plan["updates"])
