"""Public statistics, predictions and team list pages."""

import json
from collections import Counter
from functools import partial
from pathlib import Path

from flask import abort, render_template, request

from models import get_db
from services.arg_event_service import ordinary_event_condition
from services.champion_service import championship_teams_relation, list_championship_teams
from services.home_service import load_home_feed
from services.match_service import (
    get_prediction_upcoming_matches,
    supplement_temp_teams,
)
from services.performance_service import stat_average_sql, summary_metric_sql, weighted_rate_sql
from services.public_stat_evidence import pistol_rankings, weapon_counts
from site_core.predictions import get_prediction_leaderboard
from utils.demo_parser import normalize_map_name
from utils.helpers import normalize_map_key
from utils.match_utils import get_map_half_scores, get_sql_effective_status, get_sql_match_completed
from utils.side_stats import side_metric_sql
from utils.stat_filters import SIDE_OPTIONS, TIME_FILTER_MAP, TIME_FILTERS, stat_filters
from utils.stats_display import format_stat
from utils.stats_storage import stat_map_count_sql, stat_map_key_sql, stats_relation
from web_app import app

RANKING_OPTIONS = [
    {"value": "rating", "label": "RATING"},
    {"value": "kd", "label": "K/D"},
    {"value": "adr", "label": "ADR"},
    {"value": "maps", "label": "地图数"},
]
RANKING_VALUES = {item["value"] for item in RANKING_OPTIONS}
STATS_TABS = ("overview", "players", "matches", "events", "maps", "compare")
_SQL_MATCH_COMPLETED = get_sql_match_completed()
OVERVIEW_DETAIL_SECTIONS = {
    "best-players": {"title": "最佳选手", "kind": "players", "order": "rating"},
    "top-events": {"title": "冠军赛事", "kind": "events", "order": "matches"},
    "kd": {"title": "K/D", "kind": "players", "order": "kd"},
    "pistol-rounds": {"title": "手枪局", "kind": "pistol", "order": "pistol"},
    "flashes": {"title": "闪光弹", "kind": "flashes", "order": "success"},
}


def _current_filters():
    event_id = request.args.get("event", type=int)
    ranking = (request.args.get("ranking") or "rating").strip().lower()
    if ranking not in RANKING_VALUES:
        ranking = "rating"
    return {
        **stat_filters(request.args),
        "event": event_id,
        "ranking": ranking,
    }


def _is_unfiltered(filters):
    return (
        filters["time"] == "all"
        and filters["map"] == "all"
        and filters["side"] == "both"
        and filters.get("event") is None
    )


def _stats_where(filters, extra=None):
    clauses = ["COALESCE(ms.data_status, 'final') <> 'superseded'"]
    clauses.extend(extra or [])
    params = []
    months = TIME_FILTER_MAP[filters["time"]]["months"]
    if months:
        clauses.append("m.match_time >= datetime('now', ?)")
        params.append(f"-{months} months")
    if filters["map"] != "all":
        clauses.append(f"{stat_map_key_sql()} = ?")
        params.append(normalize_map_key(filters["map"]))
    if filters.get("event") is not None:
        clauses.append("m.event_id = ?")
        params.append(filters["event"])
    if not clauses:
        return "", params
    return " WHERE " + " AND ".join(clauses), params


def _match_where(filters, extra=None):
    clauses = list(extra or [])
    params = []
    months = TIME_FILTER_MAP[filters["time"]]["months"]
    if months:
        clauses.append("m.match_time >= datetime('now', ?)")
        params.append(f"-{months} months")
    if filters.get("event") is not None:
        clauses.append("m.event_id = ?")
        params.append(filters["event"])
    if not clauses:
        return "", params
    return " WHERE " + " AND ".join(clauses), params


def _side_expr(side):
    return {
        **{key: f"SUM({side_metric_sql(key, side)})" for key in (
            "kills", "deaths", "rounds_played", "clutches_won", "first_kills", "first_deaths"
        )},
        **{key: stat_average_sql(key, side) for key in ("rating", "adr", "kast", "impact")},
        "hs": stat_average_sql("headshot_percentage", side, weight="kills"),
        "kpr": weighted_rate_sql(side_metric_sql("kills", side), side_metric_sql("rounds_played", side)),
    }




def _available_maps(conn):
    rows = conn.execute(f"""
        SELECT DISTINCT map_name
        FROM {stats_relation(conn)}
        WHERE map_name IS NOT NULL AND map_name != ''
          AND COALESCE(data_status, 'final') <> 'superseded'
        ORDER BY map_name
    """).fetchall()
    seen = set()
    maps = []
    for row in rows:
        name = row["map_name"]
        key = normalize_map_key(name)
        if not key or key in seen:
            continue
        seen.add(key)
        maps.append({"value": name, "label": name})
    return maps


def _available_events(conn):
    return conn.execute(
        f"""
        SELECT DISTINCT e.id, e.name, e.start_date
        FROM events e
        JOIN matches m ON m.event_id=e.id
        JOIN {stats_relation(conn)} ms ON ms.match_id=m.id
        WHERE COALESCE(ms.data_status, 'final') <> 'superseded'
          AND {ordinary_event_condition("e")}
        ORDER BY COALESCE(e.start_date, '') DESC, e.name ASC
        """
    ).fetchall()


def _player_rankings(conn, filters, order="rating", limit=50):
    source = stats_relation(conn)
    if _is_unfiltered(filters):
        metric = partial(summary_metric_sql, stats_source=source)
        kills = metric("total_kills", "kills")
        deaths = metric("total_deaths", "deaths")
        first_kills = metric("first_kills", "first_kills")
        first_deaths = metric("first_deaths", "first_deaths")
        order_sql = {
            "rating": "rating IS NULL, rating DESC, s.maps DESC, p.nickname ASC",
            "kd": "kd IS NULL, kd DESC, rating DESC, p.nickname ASC",
            "adr": "adr IS NULL, adr DESC, rating DESC, p.nickname ASC",
            "maps": "s.maps DESC, rating DESC, p.nickname ASC",
            "pistol": "first_kills IS NULL, first_kills DESC, opening_success DESC, rating DESC",
        }.get(order, "rating IS NULL, rating DESC, s.maps DESC")
        return conn.execute(
            f"""
            SELECT p.nickname, p.id, p.avatar, t.short_name AS team,
                   {metric("avg_rating", "rating")} AS rating,
                   {kills} AS kills,
                   {deaths} AS deaths,
                   {metric("rounds_played", "rounds_played")} AS rounds,
                   ({kills}) - ({deaths}) AS kd_diff,
                   (({kills}) * 1.0 / NULLIF(({deaths}), 0)) AS kd,
                   {metric("avg_adr", "adr")} AS adr,
                   {metric("avg_kast", "kast")} AS kast,
                   {metric("avg_impact", "impact")} AS impact,
                   {metric("avg_hs", "headshot_percentage")} AS hs,
                   {metric("clutches_won", "clutches_won")} AS clutch,
                   {first_kills} AS first_kills,
                   {first_deaths} AS first_deaths,
                   (({first_kills}) * 1.0 /
                    NULLIF(({first_kills}) + ({first_deaths}), 0)) AS opening_success,
                   s.maps
            FROM player_performance_summary s
            JOIN players p ON s.player_id=p.id
            LEFT JOIN teams t ON p.team_id=t.id
            WHERE s.maps > 0
            ORDER BY {order_sql}
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    expr = _side_expr(filters["side"])
    where_sql, params = _stats_where(filters)
    order_sql = {
        "rating": "rating IS NULL, rating DESC, maps DESC, p.nickname ASC",
        "kd": "kd IS NULL, kd DESC, rating DESC, p.nickname ASC",
        "adr": "adr IS NULL, adr DESC, rating DESC, p.nickname ASC",
        "maps": "maps DESC, rating DESC, p.nickname ASC",
        "pistol": "first_kills DESC, opening_success DESC, rating DESC",
    }.get(order, "rating IS NULL, rating DESC")
    return conn.execute(
        f"""
        SELECT p.nickname, p.id, p.avatar, t.short_name AS team,
               {expr["rating"]} AS rating,
               {expr["kills"]} AS kills,
               {expr["deaths"]} AS deaths,
               {expr["rounds_played"]} AS rounds,
               {expr["kills"]} - {expr["deaths"]} AS kd_diff,
               ({expr["kills"]} * 1.0 / NULLIF({expr["deaths"]}, 0)) AS kd,
               {expr["adr"]} AS adr,
               {expr["kast"]} AS kast,
               {expr["impact"]} AS impact,
               {expr["hs"]} AS hs,
               {expr["clutches_won"]} AS clutch,
               {expr["first_kills"]} AS first_kills,
               {expr["first_deaths"]} AS first_deaths,
               ({expr["first_kills"]} * 1.0 /
                NULLIF({expr["first_kills"]} + {expr["first_deaths"]}, 0)) AS opening_success,
               {stat_map_count_sql()} AS maps
        FROM {source} ms
        JOIN players p ON ms.player_id=p.id
        LEFT JOIN teams t ON p.team_id=t.id
        JOIN matches m ON ms.match_id=m.id
        {where_sql}
        GROUP BY p.id
        ORDER BY {order_sql}
        LIMIT ?
    """,
        (*params, limit),
    ).fetchall()


# 新导入明确记录每名选手的零值；旧数据只有正数能证明曾记录过投掷次数。
_FLASH_RECORDED_SQL = "(ms.flash_count_recorded = 1 OR ms.flash_count > 0)"


def _flash_rankings(conn, filters, limit=50):
    """闪光弹榜：投掷和成功率只按有投掷记录的地图计算，全部缺失时返回 None（页面显示“暂无数据”）。"""
    where_sql, params = _stats_where(filters)
    side = filters["side"]
    thrown, blinded, opponent, assists, rounds = (
        side_metric_sql(field, side) for field in (
            "flash_count", "flash_blinded_seconds", "flash_enemy_seconds", "flash_assists", "rounds_played"
        )
    )
    recorded = _FLASH_RECORDED_SQL if side == "both" else f"{thrown} IS NOT NULL"
    return conn.execute(
        f"""
        SELECT p.nickname, p.id, p.avatar,
               {stat_map_count_sql()} AS maps,
               SUM({rounds}) AS rounds,
               AVG(CASE WHEN {recorded} THEN {thrown} END) AS thrown,
               AVG({blinded}) AS blinded,
               AVG({opponent}) AS opp_flashed,
               AVG(({opponent}) - ({blinded})) AS diff,
               AVG({assists}) AS fa,
               (SUM(CASE WHEN {recorded} AND {thrown} > 0
                         AND {opponent} > 0 THEN 1 ELSE 0 END) * 1.0 /
                NULLIF(SUM(CASE WHEN {recorded} AND {thrown} > 0
                                THEN 1 ELSE 0 END), 0)) AS success
        FROM {stats_relation(conn)} ms
        JOIN players p ON ms.player_id=p.id
        JOIN matches m ON ms.match_id=m.id
        {where_sql}
        GROUP BY p.id
        HAVING maps > 0
        ORDER BY success IS NULL, success DESC, diff DESC, maps DESC
        LIMIT ?
    """,
        (*params, limit),
    ).fetchall()


def _top_teams(conn, filters, limit=8):
    expr = _side_expr(filters["side"])
    # Temporary match-side teams use negative IDs and are not real team records.
    where_sql, params = _stats_where(filters, ["ms.team_id > 0"])
    return conn.execute(
        f"""
        SELECT
               MIN(CASE WHEN ms.team_id > 0 THEN t.id END) AS id,
               CASE
                 WHEN ms.team_id = -1 THEN COALESCE(t1.name, t1.short_name, 'TBD')
                 WHEN ms.team_id = -2 THEN COALESCE(t2.name, t2.short_name, 'TBD')
                 ELSE COALESCE(t.name, 'Team')
               END AS name,
               CASE
                 WHEN ms.team_id = -1 THEN COALESCE(t1.short_name, t1.name, 'T1')
                 WHEN ms.team_id = -2 THEN COALESCE(t2.short_name, t2.name, 'T2')
                 ELSE COALESCE(t.short_name, t.name, 'Team')
               END AS short_name,
               MIN(t.logo) AS logo,
               CASE WHEN ms.team_id > 0 THEN 0 ELSE 1 END AS is_temp,
               {expr["rating"]} AS rating,
               {stat_map_count_sql(per_player=False)} AS maps
        FROM {stats_relation(conn)} ms
        JOIN matches m ON ms.match_id=m.id
        LEFT JOIN teams t ON ms.team_id=t.id
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        {where_sql}
        GROUP BY CASE
                   WHEN ms.team_id > 0 THEN 'team:' || ms.team_id
                   ELSE 'match:' || ms.match_id || ':side:' || ms.team_id
                 END
        ORDER BY rating IS NULL, rating DESC, maps DESC, t.name ASC
        LIMIT ?
    """,
        (*params, limit),
    ).fetchall()


def _top_events(conn, filters, limit=20):
    """冠军赛事排名：按赛事维度展示冠军队伍/选手和比赛数。"""
    where_sql, params = _stats_where(filters)
    return conn.execute(
        f"""
        SELECT e.id, e.name, e.slug, e.status, e.start_date, e.end_date,
               COUNT(DISTINCT m.id) AS matches,
               {stat_map_count_sql(per_player=False)} AS maps,
               GROUP_CONCAT(DISTINCT COALESCE(c.team_short, c.team_name)) AS champion_teams,
               GROUP_CONCAT(DISTINCT c.team_id) AS champion_team_ids
        FROM events e
        JOIN matches m ON m.event_id=e.id
        JOIN {stats_relation(conn)} ms ON ms.match_id=m.id
        LEFT JOIN {championship_teams_relation(conn)} c ON c.event_id=e.id
        {where_sql}
        GROUP BY e.id
        ORDER BY matches DESC, e.start_date DESC, e.name ASC
        LIMIT ?
    """,
        (*params, limit),
    ).fetchall()


def _format_top_weapons(weapon_counter):
    weapon_names = {
        "ak47": "ak47",
        "m4a1_silencer": "m4a1_silencer",
        "m4a1": "m4a1",
        "awp": "awp",
        "usp_silencer": "usp_silencer",
        "hkp2000": "p2000",
        "glock": "glock",
        "galilar": "galilar",
        "famas": "famas",
        "deagle": "deagle",
        "mac10": "mac10",
        "mp9": "mp9",
        "mp7": "mp7",
        "ssg08": "ssg08",
        "aug": "aug",
        "sg556": "sg556",
    }
    weapon_colors = [
        "#2f76b7",
        "#338f98",
        "#2e9b73",
        "#9baa3f",
        "#b7a22f",
        "#c88324",
        "#d46a1f",
        "#bf4a2c",
        "#6f7d8c",
        "#9a7bc2",
    ]
    top_weapon_pairs = weapon_counter.most_common(9)
    other_weapon_count = sum(weapon_counter.values()) - sum(v for _, v in top_weapon_pairs)
    if other_weapon_count > 0:
        top_weapon_pairs.append(("other", other_weapon_count))
    total_weapon_kills = sum(v for _, v in top_weapon_pairs)
    cursor = 0
    weapons = []
    for idx, (weapon, count) in enumerate(top_weapon_pairs):
        pct = (count / total_weapon_kills * 100) if total_weapon_kills else 0
        start = cursor
        cursor += pct
        weapons.append(
            {
                "name": weapon_names.get(weapon, weapon),
                "count": count,
                "pct": pct,
                "start": start,
                "end": cursor,
                "color": weapon_colors[idx % len(weapon_colors)],
            }
        )
    return weapons


def _top_weapons(conn, filters):
    weapon_counter = Counter()
    rows = weapon_counts(conn, filters, TIME_FILTER_MAP[filters["time"]]["months"])
    for row in rows:
        weapon = str(row["weapon"] or "").strip().lower().removeprefix("weapon_")
        weapon = weapon.replace("-", "").replace(" ", "_")
        weapon = {
            "usps": "usp_silencer",
            "m4a1s": "m4a1_silencer",
        }.get(weapon, weapon)
        if weapon and weapon not in {"world", "worldent"}:
            weapon_counter[weapon] += int(row["kills"] or 0)
    return _format_top_weapons(weapon_counter)


def _overview_context(conn, filters):
    source = stats_relation(conn)
    totals = conn.execute(f"""
        SELECT COUNT(*) AS total_stats, {stat_average_sql("rating")} AS avg_rating,
               {stat_average_sql("adr")} AS avg_adr
        FROM {source} ms WHERE COALESCE(ms.data_status, 'final') <> 'superseded'
    """).fetchone()
    overview = {
        **dict(totals),
        "total_players": conn.execute("SELECT COUNT(*) AS cnt FROM players").fetchone()["cnt"],
        "total_teams": conn.execute("SELECT COUNT(*) AS cnt FROM teams").fetchone()["cnt"],
        "total_events": conn.execute(
            f"SELECT COUNT(*) AS cnt FROM events WHERE {ordinary_event_condition()}"
        ).fetchone()["cnt"],
        "total_matches": conn.execute(
            "SELECT COUNT(*) AS cnt FROM matches WHERE team1_score IS NOT NULL"
        ).fetchone()["cnt"],
    }
    overview["top_player"] = conn.execute(f"""
        SELECT p.nickname, p.id,
               {summary_metric_sql("avg_rating", "rating", stats_source=source)} AS r, s.maps AS m
        FROM player_performance_summary s
        JOIN players p ON s.player_id=p.id
        WHERE s.maps >= 5
        ORDER BY r IS NULL, r DESC, s.maps DESC
        LIMIT 1
    """).fetchone()
    overview["top_team"] = conn.execute("""
        SELECT t.name, t.short_name, t.id, COUNT(m.id) AS cnt,
               SUM(CASE WHEN (m.team1_id=t.id AND m.team1_score>m.team2_score)
                         OR (m.team2_id=t.id AND m.team2_score>m.team1_score) THEN 1 ELSE 0 END) AS wins
        FROM teams t
        JOIN matches m ON (m.team1_id=t.id OR m.team2_id=t.id)
        WHERE m.team1_score IS NOT NULL
        GROUP BY t.id HAVING cnt >= 3 ORDER BY (wins*1.0/cnt) DESC LIMIT 1
    """).fetchone()
    overview["recent_matches"] = conn.execute("""
        SELECT m.*, t1.short_name AS t1s, t2.short_name AS t2s,
               COALESCE(t1.name,'TBD') AS t1n, COALESCE(t2.name,'TBD') AS t2n,
               e.name AS event_name
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id
        WHERE m.team1_score IS NOT NULL
        ORDER BY m.match_time DESC LIMIT 8
    """).fetchall()
    overview["top_players"] = _player_rankings(conn, filters, "rating", 8)
    overview["top_teams"] = _top_teams(conn, filters, 8)
    overview["top_events"] = _top_events(conn, filters, 5)
    overview["top_weapons"] = _top_weapons(conn, filters)
    return overview


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
        f"{side_metric_sql(field, side)} AS {field}" for field in (
            "rating", "kills", "deaths", "adr", "kast", "impact", "headshot_percentage"
        )
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


def _comparison_players(conn):
    return conn.execute(
        """
        SELECT p.id, p.nickname, p.avatar, t.short_name AS team
        FROM player_performance_summary s
        JOIN players p ON s.player_id=p.id
        LEFT JOIN teams t ON p.team_id=t.id
        WHERE s.maps > 0
        ORDER BY p.nickname COLLATE NOCASE
        """
    ).fetchall()


def _comparison_profile(conn, player_id, filters):
    expr = _side_expr(filters["side"])
    where_sql, filter_params = _stats_where(filters, ["ms.player_id = ?"])
    row = conn.execute(
        f"""
        SELECT p.id, p.nickname, p.avatar, t.short_name AS team,
               COUNT(DISTINCT ms.match_id) AS matches,
               {stat_map_count_sql()} AS maps,
               {expr["rounds_played"]} AS rounds,
               {expr["kills"]} AS kills,
               {expr["deaths"]} AS deaths,
               ({expr["kills"]} * 1.0 / NULLIF({expr["deaths"]}, 0)) AS kd,
               {expr["kpr"]} AS kpr,
               {expr["rating"]} AS rating,
               {expr["adr"]} AS adr,
               {expr["kast"]} AS kast,
               {expr["impact"]} AS impact,
               {expr["hs"]} AS hs
        FROM {stats_relation(conn)} ms
        JOIN matches m ON ms.match_id=m.id
        JOIN players p ON ms.player_id=p.id
        LEFT JOIN teams t ON p.team_id=t.id
        {where_sql}
        GROUP BY p.id
        HAVING maps > 0
        """,
        (player_id, *filter_params),
    ).fetchone()
    return dict(row) if row else None


def _comparison_context(conn, filters):
    players = _comparison_players(conn)
    id1 = request.args.get("id1", type=int)
    id2 = request.args.get("id2", type=int)
    left = _comparison_profile(conn, id1, filters) if id1 else None
    right = _comparison_profile(conn, id2, filters) if id2 else None
    metrics = []
    if left and right:
        metric_specs = (
            ("RATING 2.0", "rating", 2, ""),
            ("K/D", "kd", 2, ""),
            ("ADR", "adr", 1, ""),
            ("KAST", "kast", 1, "%"),
            ("Impact", "impact", 2, ""),
            ("爆头率", "hs", 1, "%"),
            ("每回合击杀", "kpr", 2, ""),
            ("比赛数", "matches", 0, ""),
            ("地图数", "maps", 0, ""),
        )
        for label, key, digits, suffix in metric_specs:
            left_value = left.get(key)
            right_value = right.get(key)
            if left_value is None or right_value is None:
                continue
            metrics.append(
                {
                    "label": label,
                    "left": left_value,
                    "right": right_value,
                    "left_display": f"{left_value:.{digits}f}{suffix}",
                    "right_display": f"{right_value:.{digits}f}{suffix}",
                }
            )
    return {
        "players": players,
        "left": left,
        "right": right,
        "id1": id1,
        "id2": id2,
        "metrics": metrics,
    }


def _award_groups(conn):
    medals = [
        dict(r)
        for r in conn.execute("""
        SELECT pm.id, pm.type, pm.evp_rank, pm.reason, pm.player_id, pm.event_id, pm.match_id,
               p.nickname, p.avatar,
               e.name AS event_name, e.slug AS event_slug, e.start_date AS event_date,
               t.short_name AS team_short, t.name AS team_name
        FROM player_medals pm
        JOIN players p ON pm.player_id = p.id
        LEFT JOIN events e ON pm.event_id = e.id
        LEFT JOIN teams t ON p.team_id = t.id
        ORDER BY e.start_date DESC, CASE pm.type WHEN 'MVP' THEN 0 ELSE 1 END, pm.evp_rank ASC
    """).fetchall()
    ]
    champions = [dict(row) for row in list_championship_teams(conn)]
    event_groups = {}
    for medal in medals:
        key = (
            medal["event_id"],
            medal["event_slug"],
            medal["event_name"],
            medal["event_date"],
        )
        event_groups.setdefault(key, {"medals": [], "champions": []})["medals"].append(medal)
    for champion in champions:
        key = (
            champion["event_id"],
            champion["event_slug"],
            champion["event_name"],
            champion["event_date"],
        )
        event_groups.setdefault(key, {"medals": [], "champions": []})["champions"].append(champion)
    return sorted(event_groups.items(), key=lambda x: x[0][3] or "", reverse=True), champions


@app.route("/stats")
def stats_page():
    """HLTV-style statistics hub backed only by recorded site data."""
    tab = request.args.get("tab", "overview")
    if tab == "awards":
        tab = "events"
    if tab not in STATS_TABS:
        tab = "overview"
    filters = _current_filters()

    conn = get_db()
    try:
        map_options = _available_maps(conn)
        event_options = _available_events(conn)
        sidebar_feed = load_home_feed(conn)

        # Only query the active view. This keeps the six real-data pages quick.
        overview = None
        rankings = None
        matches = None
        events = None
        map_stats = None
        map_top_players = None
        comparison = None

        if tab == "overview":
            overview = _overview_context(conn, filters)
        elif tab == "players":
            rankings = _player_rankings(conn, filters, filters["ranking"], 100)
        elif tab == "matches":
            matches = _match_statistics(conn, filters, 100)
        elif tab == "events":
            events = _top_events(conn, filters, 100)
        elif tab == "maps":
            map_stats, map_top_players = _map_statistics(conn, filters)
        elif tab == "compare":
            comparison = _comparison_context(conn, filters)
    finally:
        conn.close()

    return render_template(
        "stats.html",
        format_stat=format_stat,
        rankings=rankings,
        matches=matches,
        events=events,
        comparison=comparison,
        tab=tab,
        filters=filters,
        time_options=TIME_FILTERS,
        ranking_options=RANKING_OPTIONS,
        map_options=map_options,
        event_options=event_options,
        side_options=SIDE_OPTIONS,
        map_stats=map_stats,
        map_top_players=map_top_players,
        overview=overview,
        sidebar_feed=sidebar_feed,
    )


@app.route("/stats/overview/<section>")
def stats_overview_detail(section):
    """Stats Overview 五个独立详情页。"""
    if section not in OVERVIEW_DETAIL_SECTIONS:
        abort(404)
    filters = _current_filters()
    config = OVERVIEW_DETAIL_SECTIONS[section]
    conn = get_db()
    try:
        if config["kind"] == "events":
            rows = _top_events(conn, filters, 100)
        elif config["kind"] == "flashes":
            rows = _flash_rankings(conn, filters, 100)
        elif config["kind"] == "pistol":
            rows = pistol_rankings(
                conn, filters, TIME_FILTER_MAP[filters["time"]]["months"],
                Path(app.instance_path) / "csda_cache", Path(app.static_folder) / "demos" / "analysis",
            )
        else:
            rows = _player_rankings(conn, filters, config["order"], 100)
        map_options = _available_maps(conn)
        event_options = _available_events(conn)
        sidebar_feed = load_home_feed(conn)
    finally:
        conn.close()
    return render_template(
        "stats_detail.html",
        format_stat=format_stat,
        section=section,
        config=config,
        rows=rows,
        filters=filters,
        time_options=TIME_FILTERS,
        map_options=map_options,
        event_options=event_options,
        side_options=SIDE_OPTIONS,
        sidebar_feed=sidebar_feed,
    )


@app.route("/predictions")
def predictions_page():
    """预测排行榜"""
    conn = get_db()

    points_rows = get_prediction_leaderboard(conn)

    upcoming_matches = get_prediction_upcoming_matches(conn)

    conn.close()

    return render_template(
        "predictions.html", predictions=points_rows, upcoming_matches=upcoming_matches
    )


@app.route("/awards")
def awards_page():
    """独立荣誉堂页面。"""
    conn = get_db()
    event_groups, champions = _award_groups(conn)
    conn.close()
    return render_template("awards.html", event_groups=event_groups, championship_teams=champions)


@app.route("/teams")
def teams_list():
    """队伍列表（公开）：每支队伍带上当前阵容，列表里显示队员小头像。"""
    conn = get_db()
    teams = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
    roster_rows = conn.execute(
        """SELECT id, nickname, avatar, team_id FROM players
           WHERE team_id IS NOT NULL ORDER BY nickname, id"""
    ).fetchall()
    conn.close()
    rosters = {}
    for row in roster_rows:
        rosters.setdefault(row["team_id"], []).append(row)
    return render_template("teams_public.html", teams=teams, rosters=rosters)


def _team_record(matches, team_id):
    """按本队视角统计已结束比赛的胜 / 负 / 平（0:0 或没填比分的不算）。"""
    record = {"wins": 0, "losses": 0, "draws": 0, "finished": 0}
    for match in matches:
        first, second = match["team1_score"], match["team2_score"]
        if (
            match["effective_status"] != "completed"
            or first is None
            or second is None
            or first == second == 0
        ):
            continue
        record["finished"] += 1
        if first == second:
            record["draws"] += 1
        elif (first > second) == (match["team1_id"] == team_id):
            record["wins"] += 1
        else:
            record["losses"] += 1
    return record


@app.route("/teams/<int:team_id>")
def team_detail(team_id):
    """展示指定队伍、当前阵容（带生涯 Rating）和实际以该队伍身份参加的比赛。"""
    conn = get_db()
    try:
        team = conn.execute("SELECT * FROM teams WHERE id=?", (team_id,)).fetchone()
        if team is None:
            abort(404)
        players = conn.execute(
            f"""SELECT p.id, p.nickname, p.avatar, s.maps,
                      {summary_metric_sql("avg_rating", "rating", stats_source=stats_relation(conn))} AS avg_rating
               FROM players p
               LEFT JOIN player_performance_summary s ON s.player_id=p.id
               WHERE p.team_id=? ORDER BY p.nickname, p.id""",
            (team_id,),
        ).fetchall()
        rows = conn.execute(
            f"""SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
                       t1.short_name AS t1s, t2.short_name AS t2s,
                       t1.logo AS t1_logo, t2.logo AS t2_logo,
                       e.name AS event_name, {get_sql_effective_status()}
                FROM matches m
                LEFT JOIN teams t1 ON t1.id=m.team1_id
                LEFT JOIN teams t2 ON t2.id=m.team2_id
                LEFT JOIN events e ON e.id=m.event_id
                WHERE m.team1_id=? OR m.team2_id=?
                ORDER BY m.match_time DESC, m.id DESC""",
            (team_id, team_id),
        ).fetchall()
        matches = [supplement_temp_teams(row, conn) for row in rows]
    finally:
        conn.close()
    return render_template(
        "team_detail.html",
        team=team,
        players=players,
        matches=matches,
        record=_team_record(matches, team_id),
    )
