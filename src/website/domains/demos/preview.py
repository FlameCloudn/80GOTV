"""解析独立 Demo 文件，生成待管理员审核的快照；不接受比赛结果。"""

import json
import secrets

from src.website.domains.demos.demo_parser import get_match_info, match_map_slot, parse_player_stats
from src.website.domains.demos.demo_runner import run_analysis
from src.website.domains.demos.roster_matching import resolve_rosters
from src.website.domains.matches.match_utils import get_demo_map_names
from src.website.domains.statistics.demo_performance import build_demo_performance_payload
from src.website.runtime.database import row_get
from src.website.runtime.host import PREMATCH_ONLY, is_managed_match
from src.website.runtime.storage import site_paths


def _save_analysis_snapshot(performance_data):
    """追加保存统计所需的事件，不改动原始 Demo 或此前的解析文件。"""
    analysis_dir = site_paths().analysis
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


def analyze_demo(conn, match, demo_path):
    """分析单个 Demo，返回预览数据"""
    if is_managed_match(conn, row_get(match, "id")):
        raise ValueError(PREMATCH_ONLY)
    match_data = run_analysis(demo_path)
    players = parse_player_stats(match_data)
    info = get_match_info(match_data)
    performance_data = build_demo_performance_payload(match_data, players)

    pairing = resolve_rosters(conn, match, info, players, preview=True)
    preview_a_to_t1 = pairing.a_to_t1
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
