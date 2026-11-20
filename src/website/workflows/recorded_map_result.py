"""旧赛制的一图赛果：更新上下半场、系列比分、晋级及已结束比赛的竞猜。"""

import json

from src.website.domains.matches.bracket_service import refresh_bracket_for_match
from src.website.domains.matches.match_utils import (
    build_raw_maps,
    calculate_map_wins,
    get_demo_upload_slot_count,
)
from src.website.domains.operations.live_service import update_unconfirmed_map_slots
from src.website.domains.predictions.scoring import score_predictions
from src.website.runtime.host import PREMATCH_ONLY, is_managed_match
from src.website.runtime.storage import site_paths


def sync_match_scores(conn, match_id, map_slot, info, a_to_t1):
    """从 demo 信息更新比赛的每图比分和总比分（按地图胜场数计）"""
    if is_managed_match(conn, match_id):
        raise ValueError(PREMATCH_ONLY)
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

    number = map_slot + 1  # 已按 BO1/3/5 可见槽位校验，不接受外部列名。
    conn.execute(
        f"UPDATE matches SET map{number}_t1=?, map{number}_t2=? WHERE id=?",
        (t1s, t2s, match_id),
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
    if is_managed_match(conn, match_id):
        raise ValueError(PREMATCH_ONLY)
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
            snapshot = site_paths().analysis / filename
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
                halves[map_key]["analysis"]["demo_a_to_t1"] = a_to_t1
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
