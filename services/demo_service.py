"""
Demo 解析与导入服务：CSGO Demo 文件分析、选手自动创建、统计数据导入
"""

import json
import logging
import secrets
from pathlib import Path

from werkzeug.security import generate_password_hash

from config import BASE_DIR
from services.bracket_service import refresh_bracket_for_match
from services.live_service import update_unconfirmed_map_slots
from services.match_roster_service import match_player_ids
from services.match_service import score_predictions
from services.performance_service import (
    build_demo_performance_payload,
    persist_demo_performance_payload,
    refresh_player_performance,
)
from services.player_service import (
    load_unique_player_alias_ids,
    record_player_nickname,
)
from services.steam_profile_service import enrich_player_from_steam
from utils.demo_parser import (
    get_match_info,
    match_map_slot,
    normalize_map_name,
    parse_player_stats,
    run_analysis,
)
from utils.helpers import row_get
from utils.match_utils import (
    build_raw_maps,
    calculate_map_wins,
    get_demo_map_names,
    get_demo_upload_slot_count,
)
from utils.stats_calc import impact_calculation_metadata

logger = logging.getLogger("80gotv")


def _save_analysis_snapshot(performance_data):
    """追加保存统计所需的事件，不改动原始 Demo 或此前的解析文件。"""
    analysis_dir = Path(BASE_DIR) / "static" / "demos" / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    filename = secrets.token_hex(16) + ".json"
    with (analysis_dir / filename).open("x", encoding="utf-8") as output:
        json.dump(
            {"state": "preview", **performance_data},
            output,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    return {**performance_data["analysis"], "snapshot": "analysis/" + filename}


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
                """INSERT INTO users(
                       username, password_hash, steam_id64,
                       is_placeholder, approval_status
                   ) VALUES(?,?,?,1,'pending')""",
                (username, generate_password_hash(secrets.token_hex(8)), steam_id),
            )
            break
        except Exception as exc:
            # Only a taken username can be fixed by choosing another name.
            if "unique constraint" not in str(exc).lower():
                raise
            if not conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone():
                raise
            username = (
                f"{base[:15]}_{steam_id[-4:]}"
                if attempt == 0
                else f"{base[:12]}_{steam_id[-6:]}_{attempt}"
            )
    else:
        raise ValueError("无法为录像选手创建账号，未导入本次数据，请检查后重试")

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

    t1s = info.get("team_a_score") if a_to_t1 else info.get("team_b_score")
    t2s = info.get("team_b_score") if a_to_t1 else info.get("team_a_score")
    if t1s is None or t2s is None:
        return False
    try:
        t1s, t2s = int(t1s), int(t2s)
    except (TypeError, ValueError):
        return False
    if t1s < 0 or t2s < 0:
        return False

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
        "SELECT bo_format, map1, map2, map3, map4, map5, map1_t1, map1_t2, map2_t1, map2_t2, map3_t1, map3_t2, "
        "map4_t1, map4_t2, map5_t1, map5_t2, has_map3, has_map4, has_map5 FROM matches WHERE id=?",
        (match_id,),
    ).fetchone()
    if match:
        unconfirmed = update_unconfirmed_map_slots(conn, match_id, map_slot, confirmed=True)
        raw_maps = [
            (name, score1, score2, active and slot not in unconfirmed)
            for slot, (name, score1, score2, active) in enumerate(
                build_raw_maps(match, include_picked_by=False)
            )
        ]
        t1_wins, t2_wins = calculate_map_wins(match, raw_maps)
        conn.execute(
            "UPDATE matches SET team1_score = ?, team2_score = ? WHERE id = ?",
            (t1_wins, t2_wins, match_id),
        )
        refresh_bracket_for_match(conn, match_id)
        if current_match["status"] == "completed":
            score_predictions(conn, match_id)
    return True


def save_halftime_data(conn, match_id, map_slot, demo_data, a_to_t1):
    """从 demo 数据提取半场比分并保存到 match 的 map_halves JSON"""
    info = demo_data.get("info", {}) or {}
    halftime = info.get("halftime", {})
    analysis = info.get("analysis")

    if (not halftime or not any(halftime.values())) and not isinstance(analysis, dict):
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
    if not isinstance(halves, dict):
        halves = {}
    if not isinstance(halves.get(map_key), dict):
        halves[map_key] = {}

    h1_a = halftime.get("h1_a", 0)
    h1_b = halftime.get("h1_b", 0)
    h2_a = halftime.get("h2_a", 0)
    h2_b = halftime.get("h2_b", 0)

    if halftime and any(halftime.values()):
        if a_to_t1:
            halves[map_key].update({"h1_t1": h1_a, "h1_t2": h1_b, "h2_t1": h2_a, "h2_t2": h2_b})
        else:
            halves[map_key].update({"h1_t1": h1_b, "h1_t2": h1_a, "h2_t1": h2_b, "h2_t2": h2_a})
    if isinstance(analysis, dict):
        reference = str(analysis.get("snapshot") or "")
        filename = reference.removeprefix("analysis/")
        if (
            reference == "analysis/" + filename
            and len(filename) == 37
            and filename.endswith(".json")
            and all(char in "0123456789abcdef" for char in filename[:-5])
        ):
            snapshot = Path(BASE_DIR) / "static" / "demos" / "analysis" / filename
            if snapshot.is_file():
                halves[map_key]["analysis"] = {
                    key: value
                    for key, value in analysis.items()
                    if key
                    in {
                        "schema_version",
                        "parser",
                        "parser_version",
                        "demo_checksum",
                        "rating_method",
                        "impact_method",
                        "method_source",
                        "official_hltv_formula",
                        "snapshot",
                        "data_version",
                    }
                }
    opening_ct_team = str(info.get("opening_ct_team") or "").lower()
    if opening_ct_team in {"t1", "t2"}:
        halves[map_key]["opening_ct_team"] = opening_ct_team
    else:
        halves[map_key].setdefault("opening_ct_team", None)
    halves[map_key]["side_source"] = str(info.get("side_source") or "demo_review")

    conn.execute(
        "UPDATE matches SET map_halves=? WHERE id=?",
        (json.dumps(halves, ensure_ascii=False), match_id),
    )


def analyze_demo(conn, match, demo_path):
    """分析单个 Demo，返回预览数据"""
    match_data = run_analysis(demo_path)
    players = parse_player_stats(match_data)
    info = get_match_info(match_data)
    performance_data = build_demo_performance_payload(match_data, players)

    db_players = conn.execute(
        "SELECT p.*, t.name AS team_name FROM players p LEFT JOIN teams t ON p.team_id=t.id"
    ).fetchall()
    alias_player_ids = load_unique_player_alias_ids(conn)

    t1_pids_ints = match_player_ids(conn, match, 1)
    t2_pids_ints = match_player_ids(conn, match, 2)

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

    def _preview_team_key(value):
        try:
            value = int(value)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    preview_t1_key = _preview_team_key(match["team1_id"])
    preview_t2_key = _preview_team_key(match["team2_id"])
    preview_t1_pids = set(int(p) for p in t1_pids_ints)
    preview_t2_pids = set(int(p) for p in t2_pids_ints)
    preview_a_ids = set()
    preview_b_ids = set()
    for stat in players:
        db_p = _match_player_from_db(stat, db_players, alias_player_ids)
        if db_p:
            if stat.get("team_letter") == "A":
                preview_a_ids.add(db_p["id"])
            elif stat.get("team_letter") == "B":
                preview_b_ids.add(db_p["id"])
    preview_a_to_t1 = _infer_demo_team_order(
        info,
        match,
        preview_a_ids,
        preview_b_ids,
        db_players,
        preview_t1_pids,
        preview_t2_pids,
        preview_t1_key,
        preview_t2_key,
    )
    if preview_a_to_t1 is None:
        preview_team_map = "无法确认对应关系，导入会被拒绝"
    else:
        preview_team_map = (
            f"Demo A → {match['team1_name'] or 'TBD'}，B → {match['team2_name'] or 'TBD'}"
            if preview_a_to_t1
            else f"Demo A → {match['team2_name'] or 'TBD'}，B → {match['team1_name'] or 'TBD'}"
        )

    map_names = get_demo_map_names(match)
    map_slot = match_map_slot(info["map_name"], map_names)
    if map_slot < 0:
        raise ValueError("Demo 地图不在当前比赛赛程中，请先检查比赛地图设置")
    info["analysis"] = _save_analysis_snapshot(performance_data)

    return {
        "map_name": info["map_name"],
        "team_a_score": info["team_a_score"],
        "team_b_score": info["team_b_score"],
        "rounds_count": info["rounds_count"],
        "source": info["source"],
        "players": players,
        "map_slot": map_slot,
        "team_map": preview_team_map,
        "team_order_ok": preview_a_to_t1 is not None,
        "demo_data": json.dumps(
            {
                "info": info,
                "players": players,
                "performance_data": performance_data,
            },
            ensure_ascii=False,
        ),
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

    try:
        demo_data = json.loads(demo_data_str)
    except (TypeError, ValueError):
        return None, "Demo 数据格式无效"
    if not isinstance(demo_data, dict):
        return None, "Demo 数据格式无效"
    players = demo_data.get("players", [])
    info = demo_data.get("info", {})
    if not isinstance(players, list) or not isinstance(info, dict):
        return None, "Demo 数据格式无效"
    if any(not isinstance(stat, dict) for stat in players):
        return None, "Demo 选手数据格式无效"

    seen_steam_ids = set()
    for stat in players:
        steam_id = str(stat.get("steam_id") or "").strip()
        if not steam_id or steam_id == "0" or not str(stat.get("name") or "").strip():
            return None, "Demo 中有选手缺少身份或昵称，未导入数据"
        if steam_id in seen_steam_ids:
            return None, "Demo 中有重复选手身份，未导入数据"
        if stat.get("team_letter") not in ("A", "B"):
            return None, "Demo 中有选手缺少队伍归属，未导入数据"
        seen_steam_ids.add(steam_id)

    source_map = normalize_map_name(info.get("map_name", ""))
    scheduled_map = normalize_map_name(map_names[map_slot] or "")
    if not source_map or source_map != scheduled_map:
        return None, "Demo 地图与选择的比赛地图不一致，已拒绝导入"

    map_name = map_names[map_slot] or info.get("map_name", "")

    if not map_name:
        return None, "无法确定地图名称"

    db_players = conn.execute(
        "SELECT p.*, t.name AS team_name FROM players p LEFT JOIN teams t ON p.team_id=t.id"
    ).fetchall()
    alias_player_ids = load_unique_player_alias_ids(conn)

    def _stored_team_id(value):
        try:
            value = int(value)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    # Older temporary teams used -1/-2 sentinels. They are not real rows in
    # teams, so writing them into match_stats violates the foreign key.
    t1_key = _stored_team_id(match["team1_id"])
    t2_key = _stored_team_id(match["team2_id"])

    t1_pids_set = match_player_ids(conn, match, 1)
    t2_pids_set = match_player_ids(conn, match, 2)

    demo_a_db_ids = set()
    demo_b_db_ids = set()
    for stat in players:
        db_p = _match_player_from_db(stat, db_players, alias_player_ids)
        if db_p:
            if stat.get("team_letter") == "A":
                demo_a_db_ids.add(db_p["id"])
            elif stat.get("team_letter") == "B":
                demo_b_db_ids.add(db_p["id"])

    a_to_t1 = _infer_demo_team_order(
        info,
        match,
        demo_a_db_ids,
        demo_b_db_ids,
        db_players,
        t1_pids_set,
        t2_pids_set,
        t1_key,
        t2_key,
    )
    if a_to_t1 is None:
        return None, "无法确认 Demo 队伍与网站队伍对应关系（队名和选手都不匹配），已拒绝导入"
    demo_to_match_team = {
        "A": t1_key if a_to_t1 else t2_key,
        "B": t2_key if a_to_t1 else t1_key,
    }
    demo_to_match_side = {
        "A": "t1" if a_to_t1 else "t2",
        "B": "t2" if a_to_t1 else "t1",
    }

    imported, created = 0, 0
    affected_player_ids = {
        row["player_id"]
        for row in conn.execute(
            """SELECT DISTINCT player_id
               FROM match_stats
               WHERE match_id=? AND map_name=?
                 AND COALESCE(data_status, 'final') <> 'superseded'""",
            (match_id, map_name),
        ).fetchall()
        if row["player_id"]
    }
    team_a_players = sorted(
        [s for s in players if s.get("team_letter") == "A"],
        key=lambda x: x.get("rating") if x.get("rating") is not None else float("-inf"),
        reverse=True,
    )
    team_b_players = sorted(
        [s for s in players if s.get("team_letter") == "B"],
        key=lambda x: x.get("rating") if x.get("rating") is not None else float("-inf"),
        reverse=True,
    )
    if len(team_a_players) > 5 or len(team_b_players) > 5:
        return None, "暂不支持同队超过五名选手的录像，未截取或导入部分选手"
    selected = team_a_players + team_b_players

    if not selected:
        return (
            None,
            f"未找到可导入的选手数据（A 队 {len(team_a_players)} 人，B 队 {len(team_b_players)} 人）",
        )

    matched_ids = [
        player["id"]
        for stat in selected
        if (player := _match_player_from_db(stat, db_players, alias_player_ids)) is not None
    ]
    if len(set(matched_ids)) != len(matched_ids):
        return None, "Demo 中有重复的网站选手对应关系，未导入数据"

    previous_version = conn.execute(
        """SELECT COALESCE(MAX(data_version), 0) AS version
           FROM match_stats WHERE match_id=? AND map_name=?""",
        (match_id, map_name),
    ).fetchone()["version"]
    conn.execute(
        """UPDATE match_stats
           SET data_status='superseded'
           WHERE match_id=? AND map_name=?
             AND COALESCE(data_status, 'final') <> 'superseded'""",
        (match_id, map_name),
    )

    for stat in selected:
        letter = stat.get("team_letter", "")
        db_player = _match_player_from_db(stat, db_players, alias_player_ids)
        if not db_player:
            db_player = auto_create_user_from_demo(conn, stat)
            if db_player:
                created += 1
            else:
                raise ValueError("录像中有选手无法识别或创建账号，未导入本次数据")
        team_id = demo_to_match_team.get(letter, t1_key if letter == "A" else t2_key)
        match_team_side = demo_to_match_side.get(letter)
        record_player_nickname(conn, db_player["id"], stat.get("name", ""), "demo")
        stat["_data_source"] = "demo_review"
        stat["_data_status"] = "final"
        stat["_data_version"] = int(previous_version or 0) + 1
        insert_match_stat(
            conn,
            match_id,
            db_player["id"],
            team_id,
            match_team_side,
            stat,
            map_name,
        )
        affected_player_ids.add(db_player["id"])
        imported += 1

    sync_match_scores(conn, match_id, map_slot, info, a_to_t1)
    if isinstance(info.get("analysis"), dict):
        info["analysis"]["data_version"] = int(previous_version or 0) + 1
    save_halftime_data(conn, match_id, map_slot, demo_data, a_to_t1)
    affected_player_ids.update(
        persist_demo_performance_payload(
            conn,
            match_id,
            map_name,
            demo_data.get("performance_data", {}),
        )
    )
    refresh_player_performance(conn, affected_player_ids)
    return (
        imported,
        f"{info.get('map_name', '')} → {map_name}，成功 {imported} 人（新建 {created}）",
    )


# ---- 内部辅助 ----


def _match_player_from_db(stat, db_players, alias_player_ids=None):
    """从数据库选手列表中匹配 demo 选手（先按 steam_id，再按昵称）"""
    for db_p in db_players:
        if db_p["steam_id"] and str(stat["steam_id"]) == str(db_p["steam_id"]):
            return db_p
    name = str(stat.get("name") or "").strip().casefold()
    candidates = {
        db_p["id"]: db_p
        for db_p in db_players
        if name and name == str(db_p["nickname"] or "").strip().casefold()
    }
    alias_player_id = (alias_player_ids or {}).get(stat["name"].casefold())
    if alias_player_id:
        candidates.update(
            {db_p["id"]: db_p for db_p in db_players if db_p["id"] == alias_player_id}
        )
    if len(candidates) == 1:
        candidate = next(iter(candidates.values()))
        if not candidate["steam_id"] or str(candidate["steam_id"]) == str(
            stat.get("steam_id") or ""
        ):
            return candidate
    return None


def _normalise_team_name(value):
    """用稳定的字母数字串比较 Demo 和网站里的队名。"""
    return "".join(ch.casefold() for ch in str(value or "") if ch.isalnum())


def _team_name_matches(left, right):
    left_key = _normalise_team_name(left)
    right_key = _normalise_team_name(right)
    return bool(
        left_key
        and right_key
        and (left_key == right_key or left_key in right_key or right_key in left_key)
    )


def _infer_demo_team_order(
    info,
    match,
    demo_a_db_ids,
    demo_b_db_ids,
    db_players,
    t1_pids_set,
    t2_pids_set,
    t1_key,
    t2_key,
):
    """把 Demo 的 A/B 队映射到比赛的固定左右队伍，避免顺序被 Demo 反转。"""
    demo_a_name = info.get("team_a_name", "")
    demo_b_name = info.get("team_b_name", "")
    match_t1_name = row_get(match, "team1_name", "")
    match_t2_name = row_get(match, "team2_name", "")

    def orientation(direct, reverse):
        if direct and not reverse:
            return True
        if reverse and not direct:
            return False
        return None

    # 比赛当时固定的名单比选手今天所在的队伍可靠；A/B 两边都参与核对。
    direct = len(demo_a_db_ids & t1_pids_set) + len(demo_b_db_ids & t2_pids_set)
    reverse = len(demo_a_db_ids & t2_pids_set) + len(demo_b_db_ids & t1_pids_set)
    if direct or reverse:
        return orientation(direct, reverse)

    direct = _team_name_matches(demo_a_name, match_t1_name) or _team_name_matches(
        demo_b_name, match_t2_name
    )
    reverse = _team_name_matches(demo_a_name, match_t2_name) or _team_name_matches(
        demo_b_name, match_t1_name
    )
    if direct or reverse:
        return orientation(direct, reverse)

    # 已有明确比赛阵容时，不能再用今天的长期队籍猜测方向。
    if (
        t1_pids_set
        or t2_pids_set
        or row_get(match, "roster_snapshot")
        or row_get(match, "team1_registration_id")
        or row_get(match, "team2_registration_id")
        or row_get(match, "team1_players") not in (None, "")
        or row_get(match, "team2_players") not in (None, "")
    ):
        return None

    db_by_id = {row["id"]: row for row in db_players}
    current_t1 = {
        pid for pid, row in db_by_id.items() if t1_key is not None and row["team_id"] == t1_key
    }
    current_t2 = {
        pid for pid, row in db_by_id.items() if t2_key is not None and row["team_id"] == t2_key
    }
    direct = len(demo_a_db_ids & current_t1) + len(demo_b_db_ids & current_t2)
    reverse = len(demo_a_db_ids & current_t2) + len(demo_b_db_ids & current_t1)
    if direct or reverse:
        return orientation(direct, reverse)
    return None


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
    }
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
