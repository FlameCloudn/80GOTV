"""Read recorded match and map totals for the stats history tabs."""

import json

from src.website.domains.demos.demo_parser import normalize_map_name
from src.website.domains.matches.map_names import normalize_map_key
from src.website.domains.matches.match_utils import get_map_half_scores, get_sql_match_completed
from src.website.domains.matches.opponents import supplement_temp_teams
from src.website.domains.statistics.query_filters import _match_where, _stats_where
from src.website.domains.statistics.side_stats import side_metric_sql
from src.website.domains.statistics.stat_filters import TIME_FILTER_MAP
from src.website.domains.statistics.stats_storage import (
    stat_map_count_sql,
    stat_map_key_sql,
    stats_relation,
)

_SQL_MATCH_COMPLETED = get_sql_match_completed()


def _map_statistics(conn, filters):
    source = stats_relation(conn)
    base_extra = ["ms.map_name != ''", "ms.map_name IS NOT NULL"]
    where_sql, params = _stats_where(filters, base_extra)
    rows = [
        dict(r)
        for r in conn.execute(
            f"""
        SELECT MIN(ms.map_name) AS map_name, {stat_map_count_sql(per_player=False)} AS times_played
        FROM {source} ms
        JOIN matches m ON ms.match_id=m.id
        {where_sql}
        GROUP BY {stat_map_key_sql()}
        ORDER BY times_played DESC
    """,
            params,
        ).fetchall()
    ]
    total_maps = sum(r["times_played"] for r in rows) or 0
    for row in rows:
        row["pick_rate"] = round(row["times_played"] / total_maps * 100, 1) if total_maps else 0

    match_where, match_params = _match_where(
        filters, ["m.map_halves IS NOT NULL", "m.map_halves != ''"]
    )
    halves_matches = conn.execute(
        f"""
        SELECT m.id, m.map_halves, m.bp_state, m.map1, m.map2, m.map3, m.map4, m.map5
        FROM matches m
        {match_where}
    """,
        match_params,
    ).fetchall()
    map_halves_data = {}
    for hm in halves_matches:
        try:
            halves = json.loads(hm["map_halves"])
        except (json.JSONDecodeError, TypeError):
            continue
        for slot_key, h in halves.items():
            if not h or not isinstance(h, dict):
                continue
            try:
                map_col = (
                    str(slot_key) if str(slot_key).startswith("map") else f"map{int(slot_key) + 1}"
                )
            except (TypeError, ValueError):
                continue
            if map_col not in ("map1", "map2", "map3", "map4", "map5") or not hm[map_col]:
                continue
            mn = normalize_map_name(hm[map_col])
            if filters["map"] != "all" and normalize_map_name(filters["map"]) != mn:
                continue
            half_scores = get_map_half_scores(hm, int(map_col[3:]) - 1, halves)
            if not half_scores or half_scores["opening_ct_team"] not in {"t1", "t2"}:
                continue
            map_halves_data.setdefault(mn, {"t_rounds": 0, "ct_rounds": 0, "count": 0})
            ct_r = t_r = 0
            for half in ("h1", "h2"):
                left, right = half_scores[f"{half}_t1"], half_scores[f"{half}_t2"]
                if left is None or right is None:
                    continue
                if (half_scores["opening_ct_team"] == "t1") == (half == "h1"):
                    ct_r, t_r = ct_r + left, t_r + right
                else:
                    ct_r, t_r = ct_r + right, t_r + left
            if t_r + ct_r > 0:
                map_halves_data[mn]["t_rounds"] += t_r
                map_halves_data[mn]["ct_rounds"] += ct_r
                map_halves_data[mn]["count"] += 1

    for row in rows:
        hd = map_halves_data.get(normalize_map_name(row["map_name"]))
        if hd and hd["count"] > 0 and (hd["t_rounds"] + hd["ct_rounds"]) > 0:
            total = hd["t_rounds"] + hd["ct_rounds"]
            row["t_win_pct"] = round(hd["t_rounds"] / total * 100, 1)
            row["ct_win_pct"] = round(hd["ct_rounds"] / total * 100, 1)
        else:
            row["t_win_pct"] = None
            row["ct_win_pct"] = None

    side = filters["side"]
    metrics = ", ".join(
        f"{side_metric_sql(field, side)} AS {field}"
        for field in ("rating", "kills", "deaths", "adr", "kast", "impact", "headshot_percentage")
    )
    top_player_query = f"""
        SELECT ms.map_name, p.nickname, p.id AS player_id, {metrics}
        FROM {source} ms
        JOIN players p ON ms.player_id=p.id
        JOIN matches m ON ms.match_id=m.id
        {where_sql}
        ORDER BY rating DESC
    """
    map_top_players = {}
    display_maps = {normalize_map_key(row["map_name"]): row["map_name"] for row in rows}
    for r in conn.execute(top_player_query, params).fetchall():
        mn = display_maps[normalize_map_key(r["map_name"])]
        if mn not in map_top_players:
            map_top_players[mn] = {
                "nickname": r["nickname"],
                "player_id": r["player_id"],
                "top_rating": r["rating"],
                "kd": round(r["kills"] / r["deaths"], 2)
                if r["kills"] is not None and r["deaths"] is not None and r["deaths"] > 0
                else None,
                "adr": r["adr"],
                "kast": r["kast"],
                "impact": r["impact"],
                "hs": r["headshot_percentage"],
            }
    return rows, map_top_players


def _match_statistics(conn, filters, limit=100):
    source = stats_relation(conn)
    extra = [_SQL_MATCH_COMPLETED]
    params = []
    months = TIME_FILTER_MAP[filters["time"]]["months"]
    if months:
        extra.append("m.match_time >= datetime('now', ?)")
        params.append(f"-{months} months")
    if filters.get("event") is not None:
        extra.append("m.event_id = ?")
        params.append(filters["event"])
    if filters["map"] != "all":
        extra.append(
            f"EXISTS (SELECT 1 FROM {source} filtered_ms WHERE filtered_ms.match_id=m.id "
            "AND COALESCE(filtered_ms.data_status, 'final') <> 'superseded' "
            f"AND {stat_map_key_sql('filtered_ms.map_name')}=?)"
        )
        params.append(normalize_map_key(filters["map"]))
    where_sql = " WHERE " + " AND ".join(extra)
    rows = conn.execute(
        f"""
        SELECT m.id, m.slug, m.match_time, m.bo_format, m.stage,
               m.team1_score, m.team2_score,
               m.team1_id, m.team2_id, m.team1_players, m.team2_players,
               COALESCE(t1.short_name, t1.name) AS team1_name,
               COALESCE(t2.short_name, t2.name) AS team2_name,
               t1.logo AS team1_logo, t2.logo AS team2_logo,
               e.id AS event_id, e.slug AS event_slug, e.name AS event_name,
               (SELECT {stat_map_count_sql("counted_ms", per_player=False)}
                FROM {source} counted_ms
                WHERE counted_ms.match_id=m.id
                  AND COALESCE(counted_ms.data_status, 'final') <> 'superseded'
                  AND counted_ms.map_name IS NOT NULL
                  AND counted_ms.map_name != '') AS maps
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id
        {where_sql}
        ORDER BY COALESCE(m.match_time, '') DESC, m.id DESC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    # 与比赛列表使用同一套名称来源，不为未知队伍编造名称。
    return [supplement_temp_teams(row, conn) for row in rows]
