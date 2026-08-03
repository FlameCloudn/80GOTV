"""Persistent player-performance rollups and compact Demo event storage."""

from collections import defaultdict

SUMMARY_COLUMNS = (
    "player_id",
    "matches",
    "maps",
    "total_kills",
    "total_deaths",
    "total_assists",
    "avg_kills",
    "avg_deaths",
    "avg_assists",
    "avg_rating",
    "avg_adr",
    "avg_kast",
    "avg_hs",
    "avg_kpr",
    "avg_dpr",
    "avg_impact",
    "avg_t_rating",
    "avg_ct_rating",
    "avg_t_adr",
    "avg_ct_adr",
    "rounds_played",
    "multi1k",
    "multi2k",
    "multi3k",
    "multi4k",
    "multi5k",
    "first_kills",
    "first_deaths",
    "mvp_count",
    "clutches_won",
    "clutch_1v1",
    "clutch_1v2",
    "clutch_1v3",
    "clutch_1v4",
    "clutch_1v5",
    "utility_damage",
    "enemies_flashed",
    "flash_count",
    "he_count",
    "smoke_count",
    "molotov_count",
    "flash_blinded_seconds",
    "flash_enemy_seconds",
    "flash_assists",
    "flash_maps",
    "opponent_flash_maps",
    "trade_kills",
    "trade_deaths",
    "bomb_plants",
    "bomb_defuses",
    "avg_utility_damage_per_round",
    "avg_damage_delta_per_round",
    "avg_rws_basic",
    "updated_at",
)


def weighted_average_sql(value_sql, weight_sql):
    """Return a SQL expression for a value weighted by recorded rounds.

    Rating-like fields are emitted per map.  Averaging those map averages
    gives a short map the same influence as a full map, which makes career and
    filtered views disagree.  Keeping the expression here makes every reader
    use the same rule.
    """
    valid = f"COALESCE({weight_sql}, 0) > 0 AND {value_sql} IS NOT NULL"
    return (
        "COALESCE("
        f"SUM(CASE WHEN {valid} THEN {value_sql} * {weight_sql} END) * 1.0 / "
        f"NULLIF(SUM(CASE WHEN {valid} THEN {weight_sql} END), 0), "
        f"AVG({value_sql}))"
    )


def weighted_rate_sql(numerator_sql, denominator_sql):
    """Return a SQL expression for totals divided by recorded rounds."""
    valid = f"COALESCE({denominator_sql}, 0) > 0"
    return (
        "COALESCE("
        f"SUM(CASE WHEN {valid} THEN COALESCE({numerator_sql}, 0) ELSE 0 END) * 1.0 / "
        f"NULLIF(SUM(CASE WHEN {valid} THEN {denominator_sql} END), 0), 0)"
    )


def refresh_player_performance(conn, player_ids=None):
    """Refresh compact career rows from persisted per-map match_stats."""
    ids = sorted({int(player_id) for player_id in (player_ids or []) if player_id})
    if player_ids is not None and not ids:
        return
    params = ()
    where_sql = ""
    if ids:
        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            f"DELETE FROM player_performance_summary WHERE player_id IN ({placeholders})",
            tuple(ids),
        )
        where_sql = f"WHERE player_id IN ({placeholders})"
        params = tuple(ids)
    else:
        conn.execute(
            """DELETE FROM player_performance_summary
               WHERE player_id NOT IN (
                   SELECT DISTINCT player_id
                   FROM match_stats
                   WHERE player_id IS NOT NULL
               )"""
        )
    filter_sql = (
        f"{where_sql} AND player_id IS NOT NULL" if where_sql else "WHERE player_id IS NOT NULL"
    )

    columns_sql = ",".join(SUMMARY_COLUMNS)
    avg_rating = weighted_average_sql("rating", "rounds_played")
    avg_adr = weighted_average_sql("adr", "rounds_played")
    avg_kast = weighted_average_sql("kast", "rounds_played")
    avg_hs = weighted_average_sql("headshot_percentage", "kills")
    avg_kpr = weighted_rate_sql("kills", "rounds_played")
    avg_dpr = weighted_rate_sql("deaths", "rounds_played")
    avg_impact = weighted_average_sql("impact", "rounds_played")
    avg_utility_damage_per_round = weighted_rate_sql("utility_damage", "rounds_played")
    avg_damage_delta_per_round = weighted_average_sql("damage_delta_per_round", "rounds_played")
    avg_rws_basic = weighted_average_sql("rws_basic", "rounds_played")
    conn.execute(
        f"""
        INSERT OR REPLACE INTO player_performance_summary({columns_sql})
        SELECT
            player_id,
            COUNT(DISTINCT match_id),
            COUNT(id),
            COALESCE(SUM(kills), 0),
            COALESCE(SUM(deaths), 0),
            COALESCE(SUM(assists), 0),
            COALESCE(AVG(kills), 0),
            COALESCE(AVG(deaths), 0),
            COALESCE(AVG(assists), 0),
            COALESCE({avg_rating}, 0),
            COALESCE({avg_adr}, 0),
            COALESCE({avg_kast}, 0),
            COALESCE({avg_hs}, 0),
            {avg_kpr},
            {avg_dpr},
            COALESCE({avg_impact}, 0),
            COALESCE(AVG(NULLIF(t_rating, 0)), 0),
            COALESCE(AVG(NULLIF(ct_rating, 0)), 0),
            COALESCE(AVG(NULLIF(t_adr, 0)), 0),
            COALESCE(AVG(NULLIF(ct_adr, 0)), 0),
            COALESCE(SUM(rounds_played), 0),
            COALESCE(SUM(multi1k), 0),
            COALESCE(SUM(multi2k), 0),
            COALESCE(SUM(multi3k), 0),
            COALESCE(SUM(multi4k), 0),
            COALESCE(SUM(multi5k), 0),
            COALESCE(SUM(first_kills), 0),
            COALESCE(SUM(first_deaths), 0),
            COALESCE(SUM(mvp_count), 0),
            COALESCE(SUM(clutches_won), 0),
            COALESCE(SUM(clutch_1v1), 0),
            COALESCE(SUM(clutch_1v2), 0),
            COALESCE(SUM(clutch_1v3), 0),
            COALESCE(SUM(clutch_1v4), 0),
            COALESCE(SUM(clutch_1v5), 0),
            COALESCE(SUM(utility_damage), 0),
            COALESCE(SUM(enemies_flashed), 0),
            COALESCE(SUM(flash_count), 0),
            COALESCE(SUM(he_count), 0),
            COALESCE(SUM(smoke_count), 0),
            COALESCE(SUM(molotov_count), 0),
            COALESCE(SUM(flash_blinded_seconds), 0),
            COALESCE(SUM(flash_enemy_seconds), 0),
            COALESCE(SUM(flash_assists), 0),
            COALESCE(SUM(CASE WHEN flash_count > 0 THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN flash_enemy_seconds > 0 THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(trade_kills), 0),
            COALESCE(SUM(trade_deaths), 0),
            COALESCE(SUM(bomb_plants), 0),
            COALESCE(SUM(bomb_defuses), 0),
            COALESCE({avg_utility_damage_per_round}, 0),
            COALESCE({avg_damage_delta_per_round}, 0),
            COALESCE({avg_rws_basic}, 0),
            CURRENT_TIMESTAMP
        FROM match_stats
        {filter_sql}
        GROUP BY player_id
        """,
        params,
    )


def _steam_id(value):
    value = str(value or "").strip()
    return "" if value == "0" else value


def _side(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = str(value or "").strip().upper()
    if value in (2, "T", "TERRORIST"):
        return "T"
    if value in (3, "CT", "COUNTERTERRORIST", "COUNTER_TERRORIST"):
        return "CT"
    return ""


def build_demo_performance_payload(match_data):
    """Reduce a multi-megabyte parser result to the fields pages actually need."""
    kill_events = []
    flash_metrics = defaultdict(
        lambda: {
            "steam_id": "",
            "name": "",
            "blinded_seconds": 0.0,
            "enemy_seconds": 0.0,
            "flash_assists": 0,
        }
    )

    for event in match_data.get("kills", []) or []:
        if not isinstance(event, dict):
            continue
        killer_steam_id = _steam_id(event.get("killerSteamId", event.get("killerSteamId64")))
        victim_steam_id = _steam_id(event.get("victimSteamId", event.get("victimSteamId64")))
        assister_steam_id = _steam_id(event.get("assisterSteamId", event.get("assisterSteamId64")))
        killer_name = str(event.get("killerName") or "").strip()
        victim_name = str(event.get("victimName") or "").strip()
        if not (killer_steam_id or killer_name) or not (victim_steam_id or victim_name):
            continue
        kill_events.append(
            {
                "round_number": int(event.get("roundNumber", 0) or 0),
                "tick": int(event.get("tick", 0) or 0),
                "killer_steam_id": killer_steam_id,
                "victim_steam_id": victim_steam_id,
                "assister_steam_id": assister_steam_id,
                "killer_name": killer_name,
                "victim_name": victim_name,
                "assister_name": str(event.get("assisterName") or "").strip(),
                "killer_side": _side(event.get("killerSide")),
                "victim_side": _side(event.get("victimSide")),
                "assister_side": _side(event.get("assisterSide")),
                "weapon": str(event.get("weaponName") or event.get("weapon") or "").strip(),
                "headshot": int(bool(event.get("isHeadshot"))),
                "assisted_flash": int(bool(event.get("isAssistedFlash"))),
            }
        )
        if event.get("isAssistedFlash") and assister_steam_id:
            item = flash_metrics[assister_steam_id]
            item["steam_id"] = assister_steam_id
            item["name"] = str(event.get("assisterName") or "").strip()
            item["flash_assists"] += 1

    for event in match_data.get("playersFlashed", []) or []:
        if not isinstance(event, dict):
            continue
        duration = max(0.0, float(event.get("duration", 0) or 0))
        flasher_steam_id = _steam_id(event.get("flasherSteamId"))
        flashed_steam_id = _steam_id(event.get("flashedSteamId"))
        flasher_side = _side(event.get("flasherSide"))
        flashed_side = _side(event.get("flashedSide"))
        if flasher_steam_id:
            item = flash_metrics[flasher_steam_id]
            item["steam_id"] = flasher_steam_id
            item["name"] = str(event.get("flasherName") or "").strip()
            if flasher_side and flashed_side and flasher_side != flashed_side:
                item["enemy_seconds"] += duration
        if flashed_steam_id:
            item = flash_metrics[flashed_steam_id]
            item["steam_id"] = flashed_steam_id
            item["name"] = str(event.get("flashedName") or "").strip()
            item["blinded_seconds"] += duration

    return {
        "kill_events": kill_events,
        "flash_metrics": [
            {
                **item,
                "blinded_seconds": round(item["blinded_seconds"], 3),
                "enemy_seconds": round(item["enemy_seconds"], 3),
            }
            for item in flash_metrics.values()
        ],
    }


def _player_identity_maps(conn):
    players = conn.execute("SELECT id, nickname, steam_id FROM players").fetchall()
    by_steam = {}
    names = defaultdict(set)
    for player in players:
        steam_id = _steam_id(player["steam_id"])
        if steam_id:
            by_steam[steam_id] = player["id"]
        nickname = str(player["nickname"] or "").strip().casefold()
        if nickname:
            names[nickname].add(player["id"])
    for alias in conn.execute("SELECT player_id, nickname FROM player_nickname_history").fetchall():
        nickname = str(alias["nickname"] or "").strip().casefold()
        if nickname:
            names[nickname].add(alias["player_id"])
    by_name = {
        nickname: next(iter(player_ids))
        for nickname, player_ids in names.items()
        if len(player_ids) == 1
    }
    return by_steam, by_name


def _player_id(by_steam, by_name, steam_id, name):
    steam_id = _steam_id(steam_id)
    if steam_id and steam_id in by_steam:
        return by_steam[steam_id]
    return by_name.get(str(name or "").strip().casefold())


def _match_player_id(conn, by_steam, by_name, match_id, map_name, steam_id, name):
    """Resolve imported identities against the player row used by this map.

    Historical data can be transferred to another website player while the
    Demo still contains the original Steam ID. Prefer the normal identity when
    it owns a stats row for this map. Otherwise, use a unique nickname-history
    owner that does own the row. This keeps old aliases useful without globally
    merging two active player accounts.
    """
    primary_id = _player_id(by_steam, by_name, steam_id, name)
    if primary_id:
        row = conn.execute(
            """
            SELECT 1 FROM match_stats
            WHERE match_id=? AND map_name=? COLLATE NOCASE AND player_id=?
            LIMIT 1
            """,
            (match_id, str(map_name or "").strip(), primary_id),
        ).fetchone()
        if row:
            return primary_id

    nickname = str(name or "").strip()
    if nickname:
        rows = conn.execute(
            """
            SELECT DISTINCT ms.player_id
            FROM match_stats ms
            JOIN players p ON p.id = ms.player_id
            LEFT JOIN player_nickname_history history
              ON history.player_id = ms.player_id
            WHERE ms.match_id=?
              AND ms.map_name=? COLLATE NOCASE
              AND (
                TRIM(p.nickname)=? COLLATE NOCASE
                OR TRIM(history.nickname)=? COLLATE NOCASE
              )
            """,
            (match_id, str(map_name or "").strip(), nickname, nickname),
        ).fetchall()
        candidates = {row["player_id"] for row in rows}
        if len(candidates) == 1:
            return next(iter(candidates))

    return primary_id


def persist_demo_performance_payload(conn, match_id, map_name, payload):
    """Persist compact kill and flash data for one imported map."""
    map_name = str(map_name or "").strip()
    by_steam, by_name = _player_identity_maps(conn)
    affected_player_ids = set()

    conn.execute(
        "DELETE FROM match_kill_events WHERE match_id=? AND map_name=?",
        (match_id, map_name),
    )
    for event in (payload or {}).get("kill_events", []) or []:
        killer_player_id = _match_player_id(
            conn,
            by_steam,
            by_name,
            match_id,
            map_name,
            event.get("killer_steam_id"),
            event.get("killer_name"),
        )
        victim_player_id = _match_player_id(
            conn,
            by_steam,
            by_name,
            match_id,
            map_name,
            event.get("victim_steam_id"),
            event.get("victim_name"),
        )
        assister_player_id = _match_player_id(
            conn,
            by_steam,
            by_name,
            match_id,
            map_name,
            event.get("assister_steam_id"),
            event.get("assister_name"),
        )
        affected_player_ids.update(
            player_id
            for player_id in (killer_player_id, victim_player_id, assister_player_id)
            if player_id
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO match_kill_events(
                match_id, map_name, round_number, tick,
                killer_player_id, victim_player_id, assister_player_id,
                killer_steam_id, victim_steam_id, assister_steam_id,
                killer_name, victim_name, assister_name,
                killer_side, victim_side, assister_side,
                weapon, headshot, assisted_flash
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                match_id,
                map_name,
                int(event.get("round_number", 0) or 0),
                int(event.get("tick", 0) or 0),
                killer_player_id,
                victim_player_id,
                assister_player_id,
                _steam_id(event.get("killer_steam_id")),
                _steam_id(event.get("victim_steam_id")),
                _steam_id(event.get("assister_steam_id")),
                str(event.get("killer_name") or "").strip(),
                str(event.get("victim_name") or "").strip(),
                str(event.get("assister_name") or "").strip(),
                _side(event.get("killer_side")),
                _side(event.get("victim_side")),
                _side(event.get("assister_side")),
                str(event.get("weapon") or "").strip(),
                int(bool(event.get("headshot"))),
                int(bool(event.get("assisted_flash"))),
            ),
        )

    for metric in (payload or {}).get("flash_metrics", []) or []:
        player_id = _match_player_id(
            conn,
            by_steam,
            by_name,
            match_id,
            map_name,
            metric.get("steam_id"),
            metric.get("name"),
        )
        if not player_id:
            continue
        affected_player_ids.add(player_id)
        conn.execute(
            """
            UPDATE match_stats
            SET flash_blinded_seconds=?,
                flash_enemy_seconds=?,
                flash_assists=?
            WHERE match_id=? AND map_name=? AND player_id=?
            """,
            (
                float(metric.get("blinded_seconds", 0) or 0),
                float(metric.get("enemy_seconds", 0) or 0),
                int(metric.get("flash_assists", 0) or 0),
                match_id,
                map_name,
                player_id,
            ),
        )
    return affected_player_ids


def backfill_demo_performance(conn, match_id, map_name, match_data):
    """Offline migration helper for existing CSDA cache files."""
    from utils.demo_parser import parse_player_stats

    by_steam, by_name = _player_identity_maps(conn)
    affected_player_ids = set()
    conn.execute(
        """
        UPDATE match_stats
        SET clutch_1v1=0, clutch_1v2=0, clutch_1v3=0,
            clutch_1v4=0, clutch_1v5=0, clutches_won=0,
            rws_basic=0
        WHERE match_id=? AND map_name=? COLLATE NOCASE
        """,
        (match_id, str(map_name or "").strip()),
    )
    for stat in parse_player_stats(match_data):
        player_id = _match_player_id(
            conn,
            by_steam,
            by_name,
            match_id,
            map_name,
            stat.get("steam_id"),
            stat.get("name"),
        )
        if not player_id:
            continue
        affected_player_ids.add(player_id)
        conn.execute(
            """
            UPDATE match_stats
            SET clutch_1v1=?, clutch_1v2=?, clutch_1v3=?,
                clutch_1v4=?, clutch_1v5=?, clutches_won=?,
                rws_basic=?
            WHERE match_id=? AND map_name=? AND player_id=?
            """,
            (
                int(stat.get("clutch_1v1", 0) or 0),
                int(stat.get("clutch_1v2", 0) or 0),
                int(stat.get("clutch_1v3", 0) or 0),
                int(stat.get("clutch_1v4", 0) or 0),
                int(stat.get("clutch_1v5", 0) or 0),
                int(stat.get("clutches_won", 0) or 0),
                float(stat.get("rws_basic", 0) or 0),
                match_id,
                map_name,
                player_id,
            ),
        )
    affected_player_ids.update(
        persist_demo_performance_payload(
            conn,
            match_id,
            map_name,
            build_demo_performance_payload(match_data),
        )
    )
    refresh_player_performance(conn, affected_player_ids)
    return len(affected_player_ids)
