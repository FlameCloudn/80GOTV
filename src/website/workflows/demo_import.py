"""在调用方持有的事务中采用旧赛 Demo，同时写选手、地图结果及统计版本。"""

import json

from src.website.domains.demos.demo_parser import normalize_map_name
from src.website.domains.demos.roster_matching import resolve_rosters
from src.website.domains.directory.player_service import record_player_nickname
from src.website.domains.matches.match_utils import get_demo_map_names
from src.website.domains.statistics.demo_performance import persist_demo_performance_payload
from src.website.domains.statistics.performance_service import refresh_player_performance
from src.website.domains.statistics.stats_storage import (
    insert_match_stat,
    map_stats_rows,
    replace_map_stats_version,
)
from src.website.runtime.host import PREMATCH_ONLY, is_managed_match
from src.website.workflows.recorded_map_result import save_halftime_data, sync_match_scores
from src.website.workflows.recorded_player import resolve_recorded_player


def _read_review(match, map_slot, demo_data_str):
    try:
        map_slot = int(map_slot)
    except (TypeError, ValueError) as exc:
        raise ValueError("地图编号无效") from exc

    map_names = get_demo_map_names(match)
    if not 0 <= map_slot < len(map_names):
        raise ValueError("地图编号超出当前比赛范围")

    try:
        demo_data = json.loads(demo_data_str)
    except (TypeError, ValueError) as exc:
        raise ValueError("Demo 数据格式无效") from exc
    if not isinstance(demo_data, dict):
        raise ValueError("Demo 数据格式无效")
    players = demo_data.get("players", [])
    info = demo_data.get("info", {})
    if not isinstance(players, list) or not isinstance(info, dict):
        raise ValueError("Demo 数据格式无效")
    seen_steam_ids = set()
    for stat in players:
        if not isinstance(stat, dict):
            raise ValueError("Demo 选手数据格式无效")
        steam_id = str(stat.get("steam_id") or "").strip()
        name = str(stat.get("name") or "").strip()
        if not steam_id or steam_id == "0" or not name:
            raise ValueError("Demo 中有选手缺少身份或昵称，未导入数据")
        if steam_id in seen_steam_ids:
            raise ValueError("Demo 中有重复选手身份，未导入数据")
        if stat.get("team_letter") not in ("A", "B"):
            raise ValueError("Demo 中有选手缺少队伍归属，未导入数据")
        seen_steam_ids.add(steam_id)
        stat["steam_id"], stat["name"] = steam_id, name

    map_name = map_names[map_slot]
    source_map = normalize_map_name(info.get("map_name", ""))
    if not source_map or source_map != normalize_map_name(map_name or ""):
        raise ValueError("Demo 地图与选择的比赛地图不一致，已拒绝导入")
    return map_slot, map_name, demo_data, info, players


def import_demo_data(conn, match_id, match, demo_data_str, map_slot):
    """导入单个 Demo 数据到数据库"""
    if is_managed_match(conn, match_id):
        return None, PREMATCH_ONLY
    try:
        map_slot, map_name, demo_data, info, players = _read_review(match, map_slot, demo_data_str)
    except ValueError as exc:
        return None, str(exc)

    pairing = resolve_rosters(conn, match, info, players)
    a_to_t1 = pairing.a_to_t1
    if a_to_t1 is None:
        return None, "无法确认 Demo 队伍与网站队伍对应关系（队名和选手都不匹配），已拒绝导入"
    match_sides = {"A": (pairing.team1_id, "t1"), "B": (pairing.team2_id, "t2")}
    if not a_to_t1:
        match_sides["A"], match_sides["B"] = match_sides["B"], match_sides["A"]

    team_a_players, team_b_players = (
        sorted(
            (s for s in players if s["team_letter"] == side),
            key=lambda stat: stat["rating"] if stat.get("rating") is not None else float("-inf"),
            reverse=True,
        )
        for side in ("A", "B")
    )
    if len(team_a_players) > 5 or len(team_b_players) > 5:
        return None, "暂不支持同队超过五名选手的录像，未截取或导入部分选手"
    selected = team_a_players + team_b_players

    if not selected:
        return (
            None,
            f"未找到可导入的选手数据（A 队 {len(team_a_players)} 人，B 队 {len(team_b_players)} 人）",
        )

    matched_ids = [player["id"] for player in pairing.players.values() if player is not None]
    if len(set(matched_ids)) != len(matched_ids):
        return None, "Demo 中有重复的网站选手对应关系，未导入数据"

    # A confirmed 5v5 roster must survive whole-map replacement intact.
    # Small legacy matches without a full roster retain their existing import path.
    if (
        len(pairing.team1_roster) == len(pairing.team2_roster) == 5
        and len(pairing.team1_roster | pairing.team2_roster) == 10
    ):
        expected_a = pairing.team1_roster if a_to_t1 else pairing.team2_roster
        expected_b = pairing.team2_roster if a_to_t1 else pairing.team1_roster
        if pairing.demo_a != expected_a or pairing.demo_b != expected_b:
            return None, "Demo 参赛名单与本场完整阵容不一致，已拒绝导入，原数据未修改"

    imported, created = 0, 0
    affected_player_ids = {
        row["player_id"]
        for row in map_stats_rows(
            conn.execute(
                """SELECT player_id,map_name FROM match_stats
                   WHERE match_id=? AND COALESCE(data_status,'final')<>'superseded'""",
                (match_id,),
            ).fetchall(),
            map_name,
        )
        if row["player_id"]
    }
    version = replace_map_stats_version(conn, match_id, map_name)

    for stat in selected:
        team_id, match_team_side = match_sides[stat["team_letter"]]
        db_player = pairing.players[stat["steam_id"]]
        if not db_player:
            db_player = resolve_recorded_player(conn, stat)
            if db_player:
                created += 1
            else:
                raise ValueError("录像中有选手无法识别或创建账号，未导入本次数据")
        record_player_nickname(conn, db_player["id"], stat["name"], "demo")
        stat["_data_source"] = "demo_review"
        stat["_data_status"] = "final"
        stat["_data_version"] = version
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
        info["analysis"]["data_version"] = version
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
