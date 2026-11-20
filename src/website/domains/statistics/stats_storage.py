"""地图统计的共同身份与版本替换，兼容旧地图别名。"""

import json

from src.website.domains.matches.map_names import normalize_map_key
from src.website.domains.statistics.stats_calc import impact_calculation_metadata
from src.website.runtime.database import row_get


def match_stat_belongs_to_side(row, expected_side, expected_team_id):
    """Use the recorded match side; only fall back to real team IDs for old rows."""
    stored_side = str(row_get(row, "match_team_side", "") or "").strip().lower()
    if stored_side in {"t1", "t2"}:
        return stored_side == expected_side
    return expected_team_id is not None and row_get(row, "team_id") == expected_team_id


def stats_relation(conn):
    """Use the current official/legacy read view when the host migration is installed."""
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='view' AND name='site_player_map_stats'"
    ).fetchone():
        return "site_player_map_stats"
    return "(SELECT *, NULL AS scheduled_map_id, NULL AS legacy_slot FROM match_stats)"


def stat_map_count_sql(alias="ms", *, per_player=True):
    legacy_key = (
        f"{alias}.id"
        if per_player
        else f"{alias}.match_id || ':' || COALESCE({alias}.map_name, '')"
    )
    return (
        f"(COUNT(DISTINCT {alias}.scheduled_map_id) + "
        f"COUNT(DISTINCT CASE WHEN {alias}.scheduled_map_id IS NULL THEN {legacy_key} END))"
    )


def stat_map_key_sql(column="ms.map_name"):
    return f"REPLACE(REPLACE(LOWER({column}), 'de_', ''), ' ', '')"


def stats_for_slot(rows, slot, map_name):
    """Modern samples use the map slot; only old samples need name matching."""
    key = normalize_map_key(map_name)
    return [
        row
        for row in rows
        if (
            row["legacy_slot"] == slot
            if row["scheduled_map_id"] is not None
            else key and normalize_map_key(row["map_name"]) == key
        )
    ]


def map_stats_rows(rows, map_name):
    key = normalize_map_key(map_name)
    return [row for row in rows if key and normalize_map_key(row["map_name"]) == key]


def replace_map_stats_version(conn, match_id: int, map_name: str) -> int:
    """在调用者事务内作废该地图所有别名的旧版本，返回下一版本号。"""
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    existing = map_stats_rows(
        conn.execute(
            "SELECT id,map_name,data_version,data_status FROM match_stats WHERE match_id=?",
            (match_id,),
        ).fetchall(),
        map_name,
    )
    version = max((row["data_version"] or 0 for row in existing), default=0) + 1
    conn.executemany(
        "UPDATE match_stats SET data_status='superseded' WHERE id=?",
        [(row["id"],) for row in existing if row["data_status"] != "superseded"],
    )
    return version


def insert_match_stat(conn, match_id, player_id, team_id, match_team_side, stat, map_name):
    """插入一条 match_stat 记录"""
    columns = (
        "match_id",
        "player_id",
        "team_id",
        "match_team_side",
        "kills",
        "deaths",
        "assists",
        "adr",
        "kpr",
        "dpr",
        "rating",
        "impact",
        "impact_method",
        "rating_impact",
        "kast",
        "headshot_percentage",
        "clutches_won",
        "t_rating",
        "ct_rating",
        "t_kills",
        "ct_kills",
        "t_deaths",
        "ct_deaths",
        "t_adr",
        "ct_adr",
        "side_stats_json",
        "multi1k",
        "multi2k",
        "multi3k",
        "multi4k",
        "multi5k",
        "first_kills",
        "first_deaths",
        "mvp_count",
        "utility_damage",
        "enemies_flashed",
        "flash_count",
        "flash_count_recorded",
        "he_count",
        "smoke_count",
        "molotov_count",
        "trade_kills",
        "trade_deaths",
        "bomb_plants",
        "bomb_defuses",
        "utility_damage_per_round",
        "rounds_played",
        "damage_delta_per_round",
        "rws_basic",
        "clutch_1v1",
        "clutch_1v2",
        "clutch_1v3",
        "clutch_1v4",
        "clutch_1v5",
        "flash_blinded_seconds",
        "flash_enemy_seconds",
        "flash_assists",
        "map_name",
        "data_source",
        "data_status",
        "data_version",
    )
    impact_method, rating_impact = impact_calculation_metadata(stat)
    stat_values = {
        **stat,
        "impact_method": impact_method,
        "rating_impact": rating_impact,
        "first_kills": stat.get("first_kill_count"),
        "first_deaths": stat.get("first_death_count"),
        "flash_count_recorded": int(stat.get("flash_count") is not None),
        "side_stats_json": json.dumps(stat["side_stats"], separators=(",", ":"))
        if stat.get("side_stats")
        else None,
    }
    if stat.get("side_stats"):
        for side in ("t", "ct"):
            for key in ("kills", "deaths", "adr", "rating"):
                stat_values[f"{side}_{key}"] = stat["side_stats"].get(side, {}).get(key)
        stat_values["flash_assists"] = sum(
            values["flash_assists"] for values in stat["side_stats"].values()
        )
    values = (
        match_id,
        player_id,
        team_id,
        match_team_side,
        *(stat_values.get(column) for column in columns[4:-4]),
        map_name,
        stat.get("_data_source", "demo"),
        stat.get("_data_status", "final"),
        int(stat.get("_data_version", 1) or 1),
    )
    placeholders = ",".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO match_stats({','.join(columns)}) VALUES({placeholders})",
        values,
    )
