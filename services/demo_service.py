"""
Demo 解析与导入服务：CSGO Demo 文件分析、选手自动创建、统计数据导入
"""

import json
import logging
import secrets

from werkzeug.security import generate_password_hash

from services.player_service import (
    load_unique_player_alias_ids,
    record_player_nickname,
)
from services.steam_profile_service import enrich_player_from_steam
from utils.demo_parser import get_match_info, match_map_slot, parse_player_stats, run_analysis
from utils.helpers import row_get
from utils.match_utils import get_demo_map_names, get_demo_upload_slot_count

logger = logging.getLogger("80gotv")


def auto_create_user_from_demo(conn, stat):
    """从 demo 数据自动创建用户和选手记录，返回 dict 或 None"""
    name = stat["name"].strip()
    steam_id = str(stat["steam_id"])

    if not name or not steam_id:
        return None

    existing = conn.execute(
        "SELECT id, nickname FROM players WHERE steam_id=?", (steam_id,)
    ).fetchone()
    if existing:
        record_player_nickname(conn, existing["id"], existing["nickname"], "website")
        record_player_nickname(conn, existing["id"], name, "demo")
        enrich_player_from_steam(conn, existing["id"])
        return {
            "id": existing["id"],
            "nickname": existing["nickname"],
            "team_name": None,
            "team_id": None,
            "_new": False,
        }

    username = name[:20]
    base = username
    for attempt in range(10):
        try:
            conn.execute(
                "INSERT INTO users(username, password_hash, steam_id64, is_placeholder) VALUES(?,?,?,1)",
                (username, generate_password_hash(secrets.token_hex(8)), steam_id),
            )
            break
        except Exception as _e:
            from sqlite3 import IntegrityError

            if not issubclass(type(_e), IntegrityError):
                err_str = str(_e)
                if "UNIQUE" not in err_str.upper() and "unique" not in err_str.lower():
                    return None
            username = (
                f"{base[:15]}_{steam_id[-4:]}"
                if attempt == 0
                else f"{base[:12]}_{steam_id[-6:]}_{attempt}"
            )
    else:
        return None

    conn.execute("INSERT INTO players(nickname, steam_id) VALUES(?,?)", (name, steam_id))
    player_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    record_player_nickname(conn, player_id, name, "demo")
    enrich_player_from_steam(conn, player_id)
    return {"id": player_id, "nickname": name, "team_name": None, "team_id": None, "_new": True}


def sync_match_scores(conn, match_id, map_slot, info, a_to_t1):
    """从 demo 信息更新比赛的每图比分和总比分（按地图胜场数计）"""
    try:
        map_slot = int(map_slot)
    except (TypeError, ValueError):
        return False

    current_match = conn.execute(
        "SELECT bo_format, status, team1_score, team2_score FROM matches WHERE id=?", (match_id,)
    ).fetchone()
    if not current_match or not 0 <= map_slot < get_demo_upload_slot_count(current_match):
        return False

    t1s = info.get("team_a_score", 0) if a_to_t1 else info.get("team_b_score", 0)
    t2s = info.get("team_b_score", 0) if a_to_t1 else info.get("team_a_score", 0)

    # 更新该地图槽位的比分
    map_cols = [
        "map1_t1",
        "map1_t2",
        "map2_t1",
        "map2_t2",
        "map3_t1",
        "map3_t2",
        "map4_t1",
        "map4_t2",
        "map5_t1",
        "map5_t2",
    ]
    if map_slot * 2 + 1 < len(map_cols):
        conn.execute(
            f"UPDATE matches SET {map_cols[map_slot * 2]} = ?, {map_cols[map_slot * 2 + 1]} = ? WHERE id = ?",
            (int(t1s or 0), int(t2s or 0), match_id),
        )

    # 重新统计总比分（按地图胜场数）
    match = conn.execute(
        "SELECT map1_t1, map1_t2, map2_t1, map2_t2, map3_t1, map3_t2, "
        "map4_t1, map4_t2, map5_t1, map5_t2, has_map3, has_map4, has_map5 FROM matches WHERE id=?",
        (match_id,),
    ).fetchone()
    if match:
        t1_wins = 0
        t2_wins = 0
        raw = [
            (match["map1_t1"], match["map1_t2"], True),
            (match["map2_t1"], match["map2_t2"], True),
            (match["map3_t1"], match["map3_t2"], bool(match["has_map3"])),
            (match["map4_t1"], match["map4_t2"], bool(row_get(match, "has_map4", 1))),
            (match["map5_t1"], match["map5_t2"], bool(row_get(match, "has_map5", 1))),
        ]
        for m1, m2, active in raw:
            if active and (m1 or m2):
                s1 = int(m1 or 0)
                s2 = int(m2 or 0)
                if s1 > s2:
                    t1_wins += 1
                elif s2 > s1:
                    t2_wins += 1
        conn.execute(
            "UPDATE matches SET team1_score = ?, team2_score = ? WHERE id = ?",
            (t1_wins, t2_wins, match_id),
        )
    return True


def save_halftime_data(conn, match_id, map_slot, demo_data, a_to_t1):
    """从 demo 数据提取半场比分并保存到 match 的 map_halves JSON"""
    info = demo_data.get("info", {}) or {}
    halftime = info.get("halftime", {})

    if not halftime or not any(halftime.values()):
        return

    # Load existing map_halves
    match = conn.execute("SELECT map_halves FROM matches WHERE id=?", (match_id,)).fetchone()
    halves = {}
    if match and match["map_halves"]:
        try:
            halves = json.loads(match["map_halves"])
        except (json.JSONDecodeError, TypeError):
            halves = {}

    map_key = str(map_slot)

    h1_a = halftime.get("h1_a", 0)
    h1_b = halftime.get("h1_b", 0)
    h2_a = halftime.get("h2_a", 0)
    h2_b = halftime.get("h2_b", 0)

    if a_to_t1:
        halves[map_key] = {"h1_t1": h1_a, "h1_t2": h1_b, "h2_t1": h2_a, "h2_t2": h2_b}
    else:
        halves[map_key] = {"h1_t1": h1_b, "h1_t2": h1_a, "h2_t1": h2_b, "h2_t2": h2_a}

    conn.execute(
        "UPDATE matches SET map_halves=? WHERE id=?",
        (json.dumps(halves, ensure_ascii=False), match_id),
    )


def analyze_demo(conn, match, demo_path):
    """分析单个 Demo，返回预览数据"""
    match_data = run_analysis(demo_path)
    players = parse_player_stats(match_data)
    info = get_match_info(match_data)

    db_players = conn.execute(
        "SELECT p.*, t.name AS team_name FROM players p LEFT JOIN teams t ON p.team_id=t.id"
    ).fetchall()
    alias_player_ids = load_unique_player_alias_ids(conn)

    t1_pids = json.loads(match["team1_players"]) if match["team1_players"] else []
    t2_pids = json.loads(match["team2_players"]) if match["team2_players"] else []
    t1_pids_ints = [int(p) for p in t1_pids]
    t2_pids_ints = [int(p) for p in t2_pids]

    for stat in players:
        matched = None
        for db_p in db_players:
            if db_p["steam_id"] and str(stat["steam_id"]) == str(db_p["steam_id"]):
                if (
                    db_p["team_id"] in (match["team1_id"], match["team2_id"])
                    or db_p["id"] in t1_pids_ints
                    or db_p["id"] in t2_pids_ints
                ):
                    matched = {
                        "nickname": db_p["nickname"],
                        "team_name": db_p["team_name"],
                        "id": db_p["id"],
                        "team_id": db_p["team_id"],
                    }
                    stat["db_player"] = matched
                    break
                else:
                    matched = {
                        "nickname": db_p["nickname"],
                        "team_name": db_p["team_name"],
                        "id": db_p["id"],
                        "team_id": db_p["team_id"],
                    }
                    stat["db_player_by_name"] = matched
        if not matched:
            for db_p in db_players:
                if (
                    stat["name"].casefold() == db_p["nickname"].casefold()
                    or alias_player_ids.get(stat["name"].casefold()) == db_p["id"]
                ):
                    if (
                        db_p["team_id"] in (match["team1_id"], match["team2_id"])
                        or db_p["id"] in t1_pids_ints
                        or db_p["id"] in t2_pids_ints
                    ):
                        stat["db_player_by_name"] = {
                            "nickname": db_p["nickname"],
                            "team_name": db_p["team_name"],
                            "id": db_p["id"],
                            "team_id": db_p["team_id"],
                        }
                        break

    map_names = get_demo_map_names(match)
    map_slot = match_map_slot(info["map_name"], map_names)

    return {
        "map_name": info["map_name"],
        "team_a_score": info["team_a_score"],
        "team_b_score": info["team_b_score"],
        "rounds_count": info["rounds_count"],
        "source": info["source"],
        "players": players,
        "map_slot": map_slot,
        "demo_data": json.dumps({"info": info, "players": players}, ensure_ascii=False),
    }


def import_demo_data(conn, match_id, match, demo_data_str, map_slot):
    """导入单个 Demo 数据到数据库"""
    try:
        map_slot = int(map_slot)
    except (TypeError, ValueError):
        return None, "地图编号无效"

    map_names = get_demo_map_names(match)
    if not 0 <= map_slot < len(map_names):
        return None, "地图编号超出当前比赛范围"

    demo_data = json.loads(demo_data_str)
    players = demo_data.get("players", [])
    info = demo_data.get("info", {})

    map_name = map_names[map_slot] or info.get("map_name", "")

    if not map_name:
        return None, "无法确定地图名称"

    db_players = conn.execute(
        "SELECT p.*, t.name AS team_name FROM players p LEFT JOIN teams t ON p.team_id=t.id"
    ).fetchall()
    alias_player_ids = load_unique_player_alias_ids(conn)

    t1_key = match["team1_id"] if match["team1_id"] else -1
    t2_key = match["team2_id"] if match["team2_id"] else -2

    t1_pids_set = set(
        int(p) for p in (json.loads(match["team1_players"]) if match["team1_players"] else [])
    )
    t2_pids_set = set(
        int(p) for p in (json.loads(match["team2_players"]) if match["team2_players"] else [])
    )

    demo_a_db_ids = set()
    demo_b_db_ids = set()
    for stat in players:
        db_p = _match_player_from_db(stat, db_players, alias_player_ids)
        if db_p:
            if stat.get("team_letter") == "A":
                demo_a_db_ids.add(db_p["id"])
            elif stat.get("team_letter") == "B":
                demo_b_db_ids.add(db_p["id"])

    a_to_t1 = True
    if demo_a_db_ids and (t1_pids_set or t2_pids_set):
        a_in_t1 = len(demo_a_db_ids & t1_pids_set)
        a_in_t2 = len(demo_a_db_ids & t2_pids_set)
        if a_in_t2 > a_in_t1:
            a_to_t1 = False
    demo_to_match_team = {
        "A": t1_key if a_to_t1 else t2_key,
        "B": t2_key if a_to_t1 else t1_key,
    }

    imported, skipped, created = 0, 0, 0
    team_a_players = sorted(
        [s for s in players if s.get("team_letter") == "A"], key=lambda x: x["rating"], reverse=True
    )[:5]
    team_b_players = sorted(
        [s for s in players if s.get("team_letter") == "B"], key=lambda x: x["rating"], reverse=True
    )[:5]
    selected = team_a_players + team_b_players

    if not selected:
        return (
            None,
            f"未找到可导入的选手数据（A 队 {len(team_a_players)} 人，B 队 {len(team_b_players)} 人）",
        )

    conn.execute("DELETE FROM match_stats WHERE match_id=? AND map_name=?", (match_id, map_name))

    for stat in selected:
        letter = stat.get("team_letter", "")
        db_player = _match_player_from_db(stat, db_players, alias_player_ids)
        if not db_player:
            db_player = auto_create_user_from_demo(conn, stat)
            if db_player:
                created += 1
            else:
                skipped += 1
                continue
        team_id = demo_to_match_team.get(letter, t1_key if letter == "A" else t2_key)
        record_player_nickname(conn, db_player["id"], stat.get("name", ""), "demo")
        _insert_match_stat(conn, match_id, db_player["id"], team_id, stat, map_name)
        imported += 1

    sync_match_scores(conn, match_id, map_slot, info, a_to_t1)
    save_halftime_data(conn, match_id, map_slot, demo_data, a_to_t1)
    return (
        imported,
        f"{info.get('map_name', '')} → {map_name}，成功 {imported} 人（新建 {created}，跳过 {skipped}）",
    )


# ---- 内部辅助 ----


def _match_player_from_db(stat, db_players, alias_player_ids=None):
    """从数据库选手列表中匹配 demo 选手（先按 steam_id，再按昵称）"""
    for db_p in db_players:
        if db_p["steam_id"] and str(stat["steam_id"]) == str(db_p["steam_id"]):
            return db_p
    for db_p in db_players:
        if stat["name"].casefold() == db_p["nickname"].casefold():
            return db_p
    alias_player_id = (alias_player_ids or {}).get(stat["name"].casefold())
    if alias_player_id:
        return next((db_p for db_p in db_players if db_p["id"] == alias_player_id), None)
    return None


def _insert_match_stat(conn, match_id, player_id, team_id, stat, map_name):
    """插入一条 match_stat 记录"""
    columns = (
        "match_id",
        "player_id",
        "team_id",
        "kills",
        "deaths",
        "assists",
        "adr",
        "kpr",
        "dpr",
        "rating",
        "impact",
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
        "map_name",
    )
    values = (
        match_id,
        player_id,
        team_id,
        stat["kills"],
        stat["deaths"],
        stat["assists"],
        stat["adr"],
        stat["kpr"],
        stat["dpr"],
        stat["rating"],
        stat["impact"],
        stat["kast"],
        stat["headshot_percentage"],
        stat.get("clutches_won", 0),
        stat.get("t_rating", 0),
        stat.get("ct_rating", 0),
        stat.get("t_kills", 0),
        stat.get("ct_kills", 0),
        stat.get("t_deaths", 0),
        stat.get("ct_deaths", 0),
        stat.get("t_adr", 0),
        stat.get("ct_adr", 0),
        stat.get("multi1k", 0),
        stat.get("multi2k", 0),
        stat.get("multi3k", 0),
        stat.get("multi4k", 0),
        stat.get("multi5k", 0),
        stat.get("first_kill_count", 0),
        stat.get("first_death_count", 0),
        stat.get("mvp_count", 0),
        stat.get("utility_damage", 0),
        stat.get("enemies_flashed", 0),
        stat.get("flash_count", 0),
        stat.get("he_count", 0),
        stat.get("smoke_count", 0),
        stat.get("molotov_count", 0),
        stat.get("trade_kills", 0),
        stat.get("trade_deaths", 0),
        stat.get("bomb_plants", 0),
        stat.get("bomb_defuses", 0),
        stat.get("utility_damage_per_round", 0),
        stat.get("rounds_played", 0),
        stat.get("damage_delta_per_round", 0),
        stat.get("rws_basic", 0),
        map_name,
    )
    placeholders = ",".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO match_stats({','.join(columns)}) VALUES({placeholders})",
        values,
    )
