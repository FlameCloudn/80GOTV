"""地图统计的共同身份与版本替换，兼容旧地图别名。"""

from utils.helpers import normalize_map_key


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
