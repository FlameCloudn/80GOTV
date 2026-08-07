"""Public statistics, predictions and team list pages."""

import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

from flask import abort, render_template, request

from models import get_db
from services.home_service import load_home_feed
from services.match_service import score_predictions
from services.performance_service import weighted_average_sql
from utils.demo_parser import normalize_map_name
from utils.match_utils import get_sql_match_completed
from web_app import app, logger

TIME_FILTERS = [
    {"value": "all", "label": "全部", "months": None},
    {"value": "3m", "label": "最近 3 个月", "months": 3},
    {"value": "6m", "label": "最近 6 个月", "months": 6},
    {"value": "12m", "label": "最近 12 个月", "months": 12},
]
TIME_FILTER_MAP = {item["value"]: item for item in TIME_FILTERS}
SIDE_OPTIONS = [
    {"value": "both", "label": "双方"},
    {"value": "ct", "label": "CT 方"},
    {"value": "t", "label": "T 方"},
]
SIDE_VALUES = {item["value"] for item in SIDE_OPTIONS}
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
    time_key = request.args.get("time") or request.args.get("period") or "all"
    if time_key not in TIME_FILTER_MAP:
        time_key = "all"
    map_key = (request.args.get("map") or "all").strip()
    if not map_key:
        map_key = "all"
    side_key = (request.args.get("side") or "both").strip().lower()
    if side_key not in SIDE_VALUES:
        side_key = "both"
    event_id = request.args.get("event", type=int)
    ranking = (request.args.get("ranking") or "rating").strip().lower()
    if ranking not in RANKING_VALUES:
        ranking = "rating"
    return {
        "time": time_key,
        "map": map_key,
        "side": side_key,
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
        clauses.append("ms.map_name = ?")
        params.append(filters["map"])
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
    if side == "t":
        return {
            "kills": "SUM(COALESCE(ms.t_kills, 0))",
            "deaths": "SUM(COALESCE(ms.t_deaths, 0))",
            "rating": "AVG(NULLIF(ms.t_rating, 0))",
            "adr": "AVG(NULLIF(ms.t_adr, 0))",
        }
    if side == "ct":
        return {
            "kills": "SUM(COALESCE(ms.ct_kills, 0))",
            "deaths": "SUM(COALESCE(ms.ct_deaths, 0))",
            "rating": "AVG(NULLIF(ms.ct_rating, 0))",
            "adr": "AVG(NULLIF(ms.ct_adr, 0))",
        }
    return {
        "kills": "SUM(COALESCE(ms.kills, 0))",
        "deaths": "SUM(COALESCE(ms.deaths, 0))",
        "rating": weighted_average_sql("ms.rating", "ms.rounds_played"),
        "adr": weighted_average_sql("ms.adr", "ms.rounds_played"),
    }


# ---- CSDA Cache Helpers ----
def _csda_cache_dir():
    return os.path.join(app.instance_path, "csda_cache")


def _load_csda_cache(match_id, slot):
    """加载 csda JSON 缓存；若不存在则尝试从 demo 文件生成并缓存。"""
    cache_dir = _csda_cache_dir()
    cache_path = os.path.join(cache_dir, f"match_{match_id}_slot_{slot}.json")
    if os.path.isfile(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass

    # 尝试从数据库找到 demo 文件并运行 csda
    conn = get_db()
    try:
        match = conn.execute("SELECT demo_file FROM matches WHERE id=?", (match_id,)).fetchone()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if not match:
        return None
    try:
        demo_list = json.loads(match["demo_file"] or "[]")
    except (json.JSONDecodeError, TypeError):
        return None
    if slot < 0 or slot >= len(demo_list):
        return None
    demo_filename = demo_list[slot]
    if not isinstance(demo_filename, str) or os.path.basename(demo_filename) != demo_filename:
        return None

    from web_app import DEMOS_DIR

    demo_path = os.path.join(DEMOS_DIR, demo_filename)
    if not os.path.isfile(demo_path):
        return None

    try:
        from utils.demo_parser import run_analysis

        data = run_analysis(demo_path, output_dir=cache_dir)
        # 重命名输出文件为 match_{id}_slot_{slot}.json
        base = os.path.splitext(demo_filename)[0]
        default_path = os.path.join(cache_dir, f"{base}.json")
        if os.path.isfile(default_path) and default_path != cache_path:
            try:
                os.replace(default_path, cache_path)
            except OSError:
                pass
        return data
    except Exception:
        logger.exception("CSDA 缓存生成失败 match=%s slot=%s", match_id, slot)
        return None


def _csda_flash_stats(filters, limit=100):
    """从 CSDA 缓存 JSON 提取闪光弹统计（含玩家被闪时长和闪光助攻）。

    返回 list[dict]，字段: nickname, id, avatar, maps, rounds, thrown, blinded,
    opp_flashed, diff, fa, success
    """
    cache_dir = _csda_cache_dir()
    if not os.path.isdir(cache_dir):
        return []

    # 收集候选 match_id
    conn = get_db()
    try:
        where_sql, params = _stats_where(filters)
        match_rows = conn.execute(
            f"""
            SELECT DISTINCT ms.match_id
            FROM match_stats ms
            JOIN matches m ON ms.match_id=m.id
            {where_sql}
        """,
            params,
        ).fetchall()
        valid_match_ids = {int(r["match_id"]) for r in match_rows}
        db_players = {
            p["id"]: p
            for p in conn.execute("""
            SELECT p.id, p.nickname, p.avatar, p.steam_id
            FROM players p
        """).fetchall()
        }
    finally:
        try:
            conn.close()
        except Exception:
            pass

    target_map = normalize_map_name(filters["map"]) if filters.get("map", "all") != "all" else ""

    player_stats = defaultdict(
        lambda: {
            "maps": set(),
            "rounds": 0,
            "thrown_sum": 0.0,
            "blinded_sum": 0.0,
            "opp_flashed_sum": 0.0,
            "fa_sum": 0.0,
            "map_count": 0,
            "flash_maps": 0,  # maps where player threw at least one flash
            "opp_flash_maps": 0,  # maps where player flashed at least one enemy
        }
    )

    for cache_file in Path(cache_dir).glob("match_*_slot_*.json"):
        m = re.match(r"match_(\d+)_slot_(\d+)\.json$", cache_file.name)
        if not m:
            continue
        match_id = int(m.group(1))
        if valid_match_ids and match_id not in valid_match_ids:
            continue
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        match_map = normalize_map_name(data.get("mapName", ""))
        if target_map and match_map and match_map != target_map:
            continue

        players = data.get("players", {}) or {}
        players_flashed = data.get("playersFlashed", []) or []
        kills = data.get("kills", []) or []
        rounds_data = data.get("rounds", []) or []
        rounds_count = max(len(rounds_data), 1)

        # 按 steam_id 映射到 steam_id -> 玩家数据
        steam_to_player = {}
        for steam_id, pd in players.items():
            if not isinstance(pd, dict):
                continue
            steam_to_player[str(steam_id)] = {
                "name": pd.get("name", ""),
                "steam_id": str(steam_id),
            }

        # 按 steam_id 映射到数据库 player id
        steam_to_db_id = {}
        for db_p in db_players.values():
            raw_sid = db_p["steam_id"] if db_p["steam_id"] else ""
            sid = str(raw_sid).strip()
            if sid:
                steam_to_db_id[sid] = db_p["id"]
        # 也按昵称匹配
        for steam_id, pinfo in steam_to_player.items():
            if steam_id in steam_to_db_id:
                continue
            name = pinfo["name"].casefold()
            for db_p in db_players.values():
                if db_p["nickname"].casefold() == name:
                    steam_to_db_id[steam_id] = db_p["id"]
                    break

        # 计算闪光被闪时长 (blinded)
        flash_events_by_player = defaultdict(list)
        for fe in players_flashed:
            if not isinstance(fe, dict):
                continue
            flasher_sid = str(fe.get("flasherSteamId", ""))
            flashed_sid = str(fe.get("flashedSteamId", ""))
            duration = float(fe.get("duration", 0))
            if flasher_sid:
                flash_events_by_player[flasher_sid].append(
                    {"type": "flasher", "sid": flashed_sid, "duration": duration}
                )
            if flashed_sid:
                flash_events_by_player[flashed_sid].append(
                    {"type": "flashed", "sid": flasher_sid, "duration": duration}
                )

        # 闪光助攻 (FA): kills 中的 isAssistedFlash
        fa_by_player = defaultdict(float)
        for kill in kills:
            if not isinstance(kill, dict):
                continue
            if kill.get("isAssistedFlash"):
                assister_sid = str(kill.get("assisterSteamId", ""))
                if assister_sid:
                    fa_by_player[assister_sid] += 1.0

        # 统计每位选手
        for steam_id, pinfo in steam_to_player.items():
            db_id = steam_to_db_id.get(steam_id)
            if db_id is None:
                continue
            db_p = db_players.get(db_id)
            if not db_p:
                continue
            key = db_id

            fe_list = flash_events_by_player.get(steam_id, [])
            blinded_dur = sum(e["duration"] for e in fe_list if e["type"] == "flashed")
            opp_flashed_dur = sum(e["duration"] for e in fe_list if e["type"] == "flasher")
            fa_val = fa_by_player.get(steam_id, 0.0)
            thrown = sum(1 for e in fe_list if e["type"] == "flasher")

            st = player_stats[key]
            if thrown > 0:
                st["flash_maps"] += 1
            if opp_flashed_dur > 0:
                st["opp_flash_maps"] += 1
            st["maps"].add(match_id)
            st["rounds"] += rounds_count
            st["thrown_sum"] += thrown
            st["blinded_sum"] += blinded_dur
            st["opp_flashed_sum"] += opp_flashed_dur
            st["fa_sum"] += fa_val
            st["map_count"] += 1

    # 组装结果
    rows = []
    for db_id, st in player_stats.items():
        db_p = db_players.get(db_id)
        if not db_p:
            continue
        nmaps = len(st["maps"])
        if nmaps == 0:
            continue
        mc = st["map_count"]
        thrown_avg = st["thrown_sum"] / mc if mc > 0 else 0
        blinded_avg = st["blinded_sum"] / mc if mc > 0 else 0
        opp_flashed_avg = st["opp_flashed_sum"] / mc if mc > 0 else 0
        diff_val = opp_flashed_avg - blinded_avg
        fa_avg = st["fa_sum"] / mc if mc > 0 else 0
        success_val = (st["opp_flash_maps"] / st["flash_maps"]) if st["flash_maps"] > 0 else 0

        rows.append(
            {
                "nickname": db_p["nickname"],
                "id": db_id,
                "avatar": db_p["avatar"] if db_p["avatar"] else "",
                "maps": nmaps,
                "rounds": st["rounds"],
                "thrown": round(thrown_avg, 2),
                "blinded": round(blinded_avg, 2),
                "opp_flashed": round(opp_flashed_avg, 2),
                "diff": round(diff_val, 2),
                "fa": round(fa_avg, 2),
                "success": round(success_val, 2),
            }
        )

    rows.sort(key=lambda r: (-r["success"], -r["diff"], -r["maps"]))
    return rows[:limit]


def _pistol_rounds(filters, limit=100):
    """从 CSDA 缓存 JSON 提取手枪局数据（按队伍统计）。

    返回 list[dict]，字段: team_name, logo, maps, won, lost, pistol_win_pct,
    round2_conv, round2_break
    """
    cache_dir = _csda_cache_dir()
    if not os.path.isdir(cache_dir):
        return []

    conn = get_db()
    try:
        where_sql, params = _stats_where(filters)
        match_rows = conn.execute(
            f"""
            SELECT DISTINCT ms.match_id
            FROM match_stats ms
            JOIN matches m ON ms.match_id=m.id
            {where_sql}
        """,
            params,
        ).fetchall()
        valid_match_ids = {int(r["match_id"]) for r in match_rows}

        # 获取队伍信息
        teams_by_id = {}
        for t in conn.execute("SELECT id, name, short_name, logo FROM teams").fetchall():
            teams_by_id[t["id"]] = dict(t)
        # 获取 match 的 team1/team2 映射
        match_teams = {}
        for mrow in conn.execute("""
            SELECT m.id, m.team1_id, m.team2_id,
                   COALESCE(t1.name, t1.short_name, 'TBD') AS t1_name,
                   COALESCE(t2.name, t2.short_name, 'TBD') AS t2_name,
                   t1.logo AS t1_logo, t2.logo AS t2_logo
            FROM matches m
            LEFT JOIN teams t1 ON m.team1_id=t1.id
            LEFT JOIN teams t2 ON m.team2_id=t2.id
        """).fetchall():
            match_teams[mrow["id"]] = dict(mrow)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    target_map = normalize_map_name(filters["map"]) if filters.get("map", "all") != "all" else ""
    side_filter = filters.get("side", "both")

    # team_key -> stats
    team_stats = defaultdict(
        lambda: {
            "maps": 0,
            "pistol_wins": 0,
            "pistol_total": 0,
            "round2_conv": 0,
            "round2_break": 0,
            "round2_total": 0,
            "logo": "",
            "team_name": "",
            "team_id": None,
        }
    )

    for cache_file in Path(cache_dir).glob("match_*_slot_*.json"):
        m = re.match(r"match_(\d+)_slot_(\d+)\.json$", cache_file.name)
        if not m:
            continue
        match_id = int(m.group(1))
        if valid_match_ids and match_id not in valid_match_ids:
            continue
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        match_map = normalize_map_name(data.get("mapName", ""))
        if target_map and match_map and match_map != target_map:
            continue

        rounds_data = data.get("rounds", []) or []
        team_a = data.get("teamA", {}) or {}

        mt = match_teams.get(match_id)
        if mt is None:
            continue

        # 建立 teamA/teamB 到 match teams 的映射
        a_name_lower = (team_a.get("name", "")).strip().casefold()
        t1_name_lower = (mt.get("t1_name", "")).strip().casefold()
        t2_name_lower = (mt.get("t2_name", "")).strip().casefold()

        # 尝试匹配
        a_map_to_t1 = (
            a_name_lower == t1_name_lower
            or t1_name_lower in a_name_lower
            or a_name_lower in t1_name_lower
        )
        a_map_to_t2 = (
            a_name_lower == t2_name_lower
            or t2_name_lower in a_name_lower
            or a_name_lower in t2_name_lower
        )

        if a_map_to_t1 and not a_map_to_t2:
            a_is_t1 = True
        elif a_map_to_t2 and not a_map_to_t1:
            a_is_t1 = False
        else:
            # 无法按名称匹配，默认 teamA = team1（csda 导出顺序）
            a_is_t1 = True

        t1_id = mt.get("team1_id", -1)
        t2_id = mt.get("team2_id", -2)
        t1_name = mt.get("t1_name", "TBD")
        t1_logo = mt.get("t1_logo", "")
        t2_name = mt.get("t2_name", "TBD")
        t2_logo = mt.get("t2_logo", "")

        def _team_key(is_t1):
            if is_t1:
                if t1_id and t1_id > 0:
                    return f"team:{t1_id}"
                return f"temp:t1:{match_id}"
            else:
                if t2_id and t2_id > 0:
                    return f"team:{t2_id}"
                return f"temp:t2:{match_id}"

        def _team_display(is_t1):
            if is_t1:
                return (
                    t1_name,
                    t1_logo,
                    t1_id if t1_id and t1_id > 0 else None,
                )
            else:
                return (
                    t2_name,
                    t2_logo,
                    t2_id if t2_id and t2_id > 0 else None,
                )

        # 找到手枪局（economyType == 'pistol'）
        pistol_rounds = []
        for rnd in rounds_data:
            if not isinstance(rnd, dict):
                continue
            if rnd.get("teamAEconomyType") == "pistol":
                pistol_rounds.append(rnd)

        for pr in pistol_rounds:
            rn = pr.get("number", 0)
            winner_side = pr.get("winnerSide", 0)  # 2=T, 3=CT
            a_side = pr.get("teamASide", 0)

            # 判断 winner 是 t1 还是 t2
            # teamA 的 side 是 a_side (2=T, 3=CT)
            # 如果 winnerSide == a_side -> teamA won
            a_won = winner_side == a_side
            # 如果 teamA 赢了且 a_is_t1 -> t1 won
            t1_won = (a_won and a_is_t1) or (not a_won and not a_is_t1)
            t2_won = not t1_won

            t1_key = _team_key(True)
            t2_key = _team_key(False)

            team_stats[t1_key]["pistol_total"] += 1
            team_stats[t2_key]["pistol_total"] += 1
            if t1_won:
                team_stats[t1_key]["pistol_wins"] += 1
            else:
                team_stats[t2_key]["pistol_wins"] += 1

            # 查找 round 2 (rn+1)
            r2 = next(
                (r for r in rounds_data if isinstance(r, dict) and r.get("number") == rn + 1), None
            )
            if r2:
                r2_winner_side = r2.get("winnerSide", 0)
                r2_a_won = r2_winner_side == r2.get("teamASide", 0)
                r2_t1_won = (r2_a_won and a_is_t1) or (not r2_a_won and not a_is_t1)

                team_stats[t1_key]["round2_total"] += 1
                team_stats[t2_key]["round2_total"] += 1
                if t1_won and r2_t1_won:
                    team_stats[t1_key]["round2_conv"] += 1
                elif t2_won and not r2_t1_won:
                    team_stats[t2_key]["round2_conv"] += 1
                elif t1_won and not r2_t1_won:
                    team_stats[t2_key]["round2_break"] += 1
                elif t2_won and r2_t1_won:
                    team_stats[t1_key]["round2_break"] += 1

        # 统计 maps
        for is_t1 in (True, False):
            key = _team_key(is_t1)
            name, logo, tid = _team_display(is_t1)
            # 区分重复的 temp 队伍
            if key not in team_stats:
                continue
            st = team_stats[key]
            st["maps"] = st["maps"] + 1
            st["team_name"] = name
            st["logo"] = logo
            st["team_id"] = tid

    # 侧筛选
    def _side_filter_match(side, team_key):
        if side == "both":
            return True
        # 根据 team_id 在 match_stats 中的 side 筛选
        # 简化：所有队伍都通过（在 csda 层面不做侧筛选）
        return True

    rows = []
    for key, st in team_stats.items():
        if not _side_filter_match(side_filter, key):
            continue
        if st["maps"] == 0:
            continue
        pistol_win_pct = (
            round(st["pistol_wins"] / st["pistol_total"] * 100, 1) if st["pistol_total"] > 0 else 0
        )
        round2_conv_pct = (
            round(st["round2_conv"] / st["round2_total"] * 100, 1) if st["round2_total"] > 0 else 0
        )
        round2_break_pct = (
            round(st["round2_break"] / st["round2_total"] * 100, 1) if st["round2_total"] > 0 else 0
        )

        rows.append(
            {
                "team_name": st["team_name"],
                "team_id": st["team_id"],
                "logo": st["logo"],
                "maps": st["maps"],
                "won": st["pistol_wins"],
                "lost": st["pistol_total"] - st["pistol_wins"],
                "pistol_win_pct": pistol_win_pct,
                "round2_conv": round2_conv_pct,
                "round2_break": round2_break_pct,
            }
        )

    rows.sort(key=lambda r: (-r["pistol_win_pct"], -r["maps"]))
    return rows[:limit]


def _available_maps(conn):
    rows = conn.execute("""
        SELECT DISTINCT map_name
        FROM match_stats
        WHERE map_name IS NOT NULL AND map_name != ''
          AND COALESCE(data_status, 'final') <> 'superseded'
        ORDER BY map_name
    """).fetchall()
    seen = set()
    maps = []
    for row in rows:
        name = row["map_name"]
        key = normalize_map_name(name)
        if not key or key in seen:
            continue
        seen.add(key)
        maps.append({"value": name, "label": name})
    return maps


def _available_events(conn):
    return conn.execute(
        """
        SELECT DISTINCT e.id, e.name, e.start_date
        FROM events e
        JOIN matches m ON m.event_id=e.id
        JOIN match_stats ms ON ms.match_id=m.id
        WHERE COALESCE(ms.data_status, 'final') <> 'superseded'
        ORDER BY COALESCE(e.start_date, '') DESC, e.name ASC
        """
    ).fetchall()


def _player_rankings(conn, filters, order="rating", limit=50):
    if _is_unfiltered(filters):
        order_sql = {
            "rating": "s.avg_rating DESC, s.maps DESC, p.nickname ASC",
            "kd": "kd DESC, s.avg_rating DESC, p.nickname ASC",
            "adr": "s.avg_adr DESC, s.avg_rating DESC, p.nickname ASC",
            "maps": "s.maps DESC, s.avg_rating DESC, p.nickname ASC",
            "pistol": "s.first_kills DESC, opening_success DESC, s.avg_rating DESC",
        }.get(order, "s.avg_rating DESC, s.maps DESC")
        return conn.execute(
            f"""
            SELECT p.nickname, p.id, p.avatar, t.short_name AS team,
                   s.avg_rating AS rating,
                   s.total_kills AS kills,
                   s.total_deaths AS deaths,
                   s.rounds_played AS rounds,
                   s.total_kills - s.total_deaths AS kd_diff,
                   (s.total_kills * 1.0 / NULLIF(s.total_deaths, 0)) AS kd,
                   s.avg_adr AS adr,
                   s.avg_kast AS kast,
                   s.avg_impact AS impact,
                   s.avg_hs AS hs,
                   s.clutches_won AS clutch,
                   s.first_kills,
                   s.first_deaths,
                   (s.first_kills * 1.0 /
                    NULLIF(s.first_kills + s.first_deaths, 0)) AS opening_success,
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
               SUM(COALESCE(ms.rounds_played, 0)) AS rounds,
               {expr["kills"]} - {expr["deaths"]} AS kd_diff,
               ({expr["kills"]} * 1.0 / NULLIF({expr["deaths"]}, 0)) AS kd,
               {expr["adr"]} AS adr,
               AVG(ms.kast) AS kast,
               AVG(ms.impact) AS impact,
               AVG(ms.headshot_percentage) AS hs,
               SUM(COALESCE(ms.clutches_won, 0)) AS clutch,
               SUM(COALESCE(ms.first_kills, 0)) AS first_kills,
               SUM(COALESCE(ms.first_deaths, 0)) AS first_deaths,
               (SUM(COALESCE(ms.first_kills, 0)) * 1.0 /
                NULLIF(SUM(COALESCE(ms.first_kills, 0)) + SUM(COALESCE(ms.first_deaths, 0)), 0)) AS opening_success,
               COUNT(ms.id) AS maps
        FROM match_stats ms
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


def _flash_rankings(conn, filters, limit=50):
    """Read persisted flash metrics without opening multi-megabyte cache files."""
    if _is_unfiltered(filters):
        return conn.execute(
            """
            SELECT p.nickname, p.id, p.avatar,
                   s.maps, s.rounds_played AS rounds,
                   (s.flash_count * 1.0 / NULLIF(s.maps, 0)) AS thrown,
                   (s.flash_blinded_seconds / NULLIF(s.maps, 0)) AS blinded,
                   (s.flash_enemy_seconds / NULLIF(s.maps, 0)) AS opp_flashed,
                   ((s.flash_enemy_seconds - s.flash_blinded_seconds) /
                    NULLIF(s.maps, 0)) AS diff,
                   (s.flash_assists * 1.0 / NULLIF(s.maps, 0)) AS fa,
                   (s.opponent_flash_maps * 1.0 /
                    NULLIF(s.flash_maps, 0)) AS success
            FROM player_performance_summary s
            JOIN players p ON s.player_id=p.id
            WHERE s.maps > 0
            ORDER BY success DESC, diff DESC, s.maps DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    where_sql, params = _stats_where(filters)
    return conn.execute(
        f"""
        SELECT p.nickname, p.id, p.avatar,
               COUNT(ms.id) AS maps,
               SUM(COALESCE(ms.rounds_played, 0)) AS rounds,
               AVG(ms.flash_count) AS thrown,
               AVG(ms.flash_blinded_seconds) AS blinded,
               AVG(ms.flash_enemy_seconds) AS opp_flashed,
               AVG(ms.flash_enemy_seconds - ms.flash_blinded_seconds) AS diff,
               AVG(ms.flash_assists) AS fa,
               (SUM(CASE WHEN ms.flash_enemy_seconds > 0 THEN 1 ELSE 0 END) * 1.0 /
                NULLIF(SUM(CASE WHEN ms.flash_count > 0 THEN 1 ELSE 0 END), 0)) AS success
        FROM match_stats ms
        JOIN players p ON ms.player_id=p.id
        JOIN matches m ON ms.match_id=m.id
        {where_sql}
        GROUP BY p.id
        HAVING maps > 0
        ORDER BY success DESC, diff DESC, maps DESC
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
               COUNT(DISTINCT CAST(ms.match_id AS TEXT) || ':' || COALESCE(ms.map_name, '')) AS maps
        FROM match_stats ms
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
               COUNT(DISTINCT CAST(m.id AS TEXT) || ':' ||
                     COALESCE(ms.map_name, '')) AS maps,
               GROUP_CONCAT(DISTINCT COALESCE(t.short_name, t.name)) AS champion_teams,
               GROUP_CONCAT(DISTINCT t.id) AS champion_team_ids
        FROM events e
        JOIN matches m ON m.event_id=e.id
        JOIN match_stats ms ON ms.match_id=m.id
        LEFT JOIN event_champions ec ON ec.event_id=e.id
        LEFT JOIN teams t ON ec.team_id=t.id
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
    clauses = ["ke.weapon IS NOT NULL", "TRIM(ke.weapon) != ''"]
    params = []
    months = TIME_FILTER_MAP[filters["time"]]["months"]
    if months:
        clauses.append("m.match_time >= datetime('now', ?)")
        params.append(f"-{months} months")
    if filters["map"] != "all":
        clauses.append("ke.map_name=?")
        params.append(filters["map"])
    where_sql = " WHERE " + " AND ".join(clauses)
    weapon_counter = Counter()
    rows = conn.execute(
        f"""
        SELECT ke.weapon, COUNT(*) AS kills
        FROM match_kill_events ke
        JOIN matches m ON m.id=ke.match_id
        {where_sql}
        GROUP BY ke.weapon
        """,
        tuple(params),
    ).fetchall()
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
    overview = {
        "total_players": conn.execute("SELECT COUNT(*) AS cnt FROM players").fetchone()["cnt"],
        "total_teams": conn.execute("SELECT COUNT(*) AS cnt FROM teams").fetchone()["cnt"],
        "total_events": conn.execute("SELECT COUNT(*) AS cnt FROM events").fetchone()["cnt"],
        "total_matches": conn.execute(
            "SELECT COUNT(*) AS cnt FROM matches WHERE team1_score IS NOT NULL"
        ).fetchone()["cnt"],
        "total_stats": conn.execute(
            "SELECT COUNT(*) AS cnt FROM match_stats WHERE COALESCE(data_status, 'final') <> 'superseded'"
        ).fetchone()["cnt"],
        "avg_rating": conn.execute(
            "SELECT AVG(rating) AS v FROM match_stats WHERE COALESCE(data_status, 'final') <> 'superseded'"
        ).fetchone()["v"],
        "avg_adr": conn.execute(
            "SELECT AVG(adr) AS v FROM match_stats WHERE COALESCE(data_status, 'final') <> 'superseded'"
        ).fetchone()["v"],
    }
    overview["top_player"] = conn.execute("""
        SELECT p.nickname, p.id, s.avg_rating AS r, s.maps AS m
        FROM player_performance_summary s
        JOIN players p ON s.player_id=p.id
        WHERE s.maps >= 5
        ORDER BY s.avg_rating DESC, s.maps DESC
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
    base_extra = ["ms.map_name != ''", "ms.map_name IS NOT NULL"]
    where_sql, params = _stats_where(filters, base_extra)
    rows = [
        dict(r)
        for r in conn.execute(
            f"""
        SELECT ms.map_name, COUNT(DISTINCT ms.match_id) AS times_played
        FROM match_stats ms
        JOIN matches m ON ms.match_id=m.id
        {where_sql}
        GROUP BY ms.map_name
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
        SELECT m.id, m.map_halves, m.map1, m.map2, m.map3, m.map4, m.map5
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
            map_halves_data.setdefault(mn, {"t_rounds": 0, "ct_rounds": 0, "count": 0})
            if "t1_h1" in h or "t2_h1" in h:
                t_r = (h.get("t1_h1", 0) or 0) + (h.get("t2_h2", 0) or 0)
                ct_r = (h.get("t2_h1", 0) or 0) + (h.get("t1_h2", 0) or 0)
            else:
                t_r = (h.get("h1_t1", 0) or 0) + (h.get("h2_t2", 0) or 0)
                ct_r = (h.get("h1_t2", 0) or 0) + (h.get("h2_t1", 0) or 0)
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

    top_player_query = f"""
        SELECT ms.map_name, p.nickname, p.id AS player_id,
               ms.rating, ms.kills, ms.deaths, ms.adr, ms.kast, ms.impact, ms.headshot_percentage
        FROM match_stats ms
        JOIN players p ON ms.player_id=p.id
        JOIN matches m ON ms.match_id=m.id
        {where_sql}
        ORDER BY ms.rating DESC
    """
    map_top_players = {}
    for r in conn.execute(top_player_query, params).fetchall():
        mn = r["map_name"]
        if mn not in map_top_players:
            map_top_players[mn] = {
                "nickname": r["nickname"],
                "player_id": r["player_id"],
                "top_rating": r["rating"],
                "kd": round(r["kills"] / r["deaths"], 2) if r["deaths"] else None,
                "adr": r["adr"],
                "kast": r["kast"],
                "impact": r["impact"],
                "hs": r["headshot_percentage"],
            }
    return rows, map_top_players


def _match_statistics(conn, filters, limit=100):
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
            "EXISTS (SELECT 1 FROM match_stats filtered_ms "
            "WHERE filtered_ms.match_id=m.id AND filtered_ms.map_name=?)"
        )
        params.append(filters["map"])
    where_sql = " WHERE " + " AND ".join(extra)
    return conn.execute(
        f"""
        SELECT m.id, m.slug, m.match_time, m.bo_format, m.stage,
               m.team1_score, m.team2_score,
               COALESCE(t1.short_name, t1.name, 'TBD') AS team1_name,
               COALESCE(t2.short_name, t2.name, 'TBD') AS team2_name,
               t1.logo AS team1_logo, t2.logo AS team2_logo,
               e.id AS event_id, e.slug AS event_slug, e.name AS event_name,
               (SELECT COUNT(DISTINCT counted_ms.map_name)
                FROM match_stats counted_ms
                WHERE counted_ms.match_id=m.id
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
               COUNT(ms.id) AS maps,
               SUM(COALESCE(ms.rounds_played, 0)) AS rounds,
               {expr["kills"]} AS kills,
               {expr["deaths"]} AS deaths,
               ({expr["kills"]} * 1.0 / NULLIF({expr["deaths"]}, 0)) AS kd,
               ({expr["kills"]} * 1.0 /
                NULLIF(SUM(COALESCE(ms.rounds_played, 0)), 0)) AS kpr,
               {expr["rating"]} AS rating,
               {expr["adr"]} AS adr,
               AVG(ms.kast) AS kast,
               AVG(ms.impact) AS impact,
               AVG(ms.headshot_percentage) AS hs
        FROM match_stats ms
        JOIN matches m ON ms.match_id=m.id
        JOIN players p ON ms.player_id=p.id
        LEFT JOIN teams t ON p.team_id=t.id
        {where_sql}
        GROUP BY p.id
        HAVING COUNT(ms.id) > 0
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
            ("影响力", "impact", 2, ""),
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
    champions = [
        dict(r)
        for r in conn.execute("""
        SELECT ec.id, ec.event_id, ec.team_id,
               e.name AS event_name, e.slug AS event_slug, e.start_date AS event_date,
               t.name AS team_name, t.short_name AS team_short, t.logo
        FROM event_champions ec
        JOIN events e ON ec.event_id = e.id
        JOIN teams t ON ec.team_id = t.id
        ORDER BY e.start_date DESC
    """).fetchall()
    ]
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
    return sorted(event_groups.items(), key=lambda x: x[0][3] or "", reverse=True)


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
            rows = _pistol_rounds(filters, 100)
        else:
            rows = _player_rankings(conn, filters, config["order"], 100)
        map_options = _available_maps(conn)
        event_options = _available_events(conn)
        sidebar_feed = load_home_feed(conn)
    finally:
        conn.close()
    return render_template(
        "stats_detail.html",
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

    # 自动计分
    score_predictions(conn)
    conn.commit()

    # 积分排行榜（Total Points）
    points_rows = conn.execute("""
        SELECT u.username, u.id AS user_id, u.avatar, u.is_cheater,
               COUNT(v.id) AS total_votes,
               SUM(CASE WHEN v.points_earned > 0 THEN 1 ELSE 0 END) AS correct_votes,
               SUM(v.points_earned) AS total_points,
               MAX(CASE WHEN v.points_earned >= 8 THEN 1 ELSE 0 END) AS has_perfect
        FROM match_votes v
        JOIN users u ON v.user_id = u.id
        WHERE v.scored = 1
        GROUP BY v.user_id
        HAVING total_votes >= 1
        ORDER BY total_points DESC, correct_votes DESC
        LIMIT 10
    """).fetchall()

    # 即将进行的比赛。没有人投票的比赛也要显示，否则用户看不到入口。
    upcoming_matches = conn.execute("""
        SELECT m.id, m.slug, m.match_time, m.bo_format,
               COALESCE(t1.name, 'TBD') AS team1_name,
               COALESCE(t2.name, 'TBD') AS team2_name,
               e.name AS event_name,
               COUNT(v.id) AS vote_count,
               SUM(CASE WHEN v.voted_for = 't1' THEN 1 ELSE 0 END) AS t1_votes,
               SUM(CASE WHEN v.voted_for = 't2' THEN 1 ELSE 0 END) AS t2_votes
        FROM matches m
        LEFT JOIN match_votes v ON m.id = v.match_id
        LEFT JOIN teams t1 ON m.team1_id = t1.id
        LEFT JOIN teams t2 ON m.team2_id = t2.id
        LEFT JOIN events e ON m.event_id = e.id
        WHERE COALESCE(m.status, '') = 'upcoming'
          AND (m.match_time IS NULL OR datetime(m.match_time) > datetime('now', 'localtime'))
        GROUP BY m.id
        ORDER BY vote_count DESC, m.match_time ASC
        LIMIT 10
    """).fetchall()

    conn.close()

    return render_template(
        "predictions.html", predictions=points_rows, upcoming_matches=upcoming_matches
    )


@app.route("/awards")
def awards_page():
    """独立荣誉堂页面。"""
    conn = get_db()
    event_groups = _award_groups(conn)
    conn.close()
    return render_template("awards.html", event_groups=event_groups)


@app.route("/teams")
def teams_list():
    """队伍列表（公开）"""
    conn = get_db()
    teams = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
    conn.close()
    return render_template("teams_public.html", teams=teams)
