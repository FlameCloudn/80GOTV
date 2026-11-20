"""手动修改地图统计：先完整校验，保留旧记录中未编辑的字段。"""

import hashlib
import json
import math
from collections.abc import Mapping

from src.website.domains.matches.map_names import MAP_NAME_MAPPING, normalize_map_key
from src.website.domains.matches.match_roster_service import match_player_slots, match_registration
from src.website.domains.statistics.stats_calc import (
    HLTV2_ESTIMATE_METHOD,
    calculate_rating,
    estimate_hltv2_impact,
    impact_calculation_metadata,
    non_negative_impact,
)
from src.website.domains.statistics.stats_storage import replace_map_stats_version

FORM_FIELDS = {
    "kills": ("kills", True, None),
    "deaths": ("deaths", True, None),
    "assists": ("assists", True, None),
    "adr": ("adr", False, None),
    "kast": ("kast", False, 100),
    "hs": ("headshot_percentage", False, 100),
    "impact": ("impact", False, None),
}


class StatsRevisionConflict(ValueError):
    """表单基于旧统计，不能覆盖当前数据。"""


def manual_map_revision(match, map_name, sides, existing):
    """逐地图比较整份统计和比分、阵容，捕获导入或其他管理员的修改。"""
    key = normalize_map_key(map_name)
    snapshot = {
        "match_id": match["id"],
        "map": key,
        "status": match.get("status"),
        "bo_format": match.get("bo_format"),
        "teams": [match.get(f"team{side}_id") for side in (1, 2)],
        "roster": [[player["id"] for player in sides[side]] for side in (1, 2)],
        "scores": [
            [slot, match.get(f"map{slot}_t1"), match.get(f"map{slot}_t2")]
            for slot in range(1, 6)
            if normalize_map_key(match.get(f"map{slot}")) == key
        ],
        "stats": sorted((dict(row) for row in existing), key=lambda row: row["id"]),
    }
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def stats_editor_players(conn, match, side):
    """优先本场阵容；完全没有比赛证据的旧记录才兼容长期队籍。"""
    slots = match_player_slots(conn, match, side)
    if slots:
        return [player for player in slots if player.get("id")]
    if (
        match.get("roster_snapshot")
        or match.get(f"team{side}_players") not in (None, "")
        or match.get(f"team{side}_registration_id")
        or match_registration(conn, match, side)
    ):
        return []
    # 旧统计可能只有当时的队伍 ID：按真实参赛者补齐，不套用今天的队籍。
    rows = conn.execute(
        """SELECT DISTINCT p.* FROM match_stats ms JOIN players p ON p.id=ms.player_id
           WHERE ms.match_id=? AND COALESCE(ms.data_status,'final')='final'
             AND ms.team_id=? AND COALESCE(ms.match_team_side,'') NOT IN ('t1','t2')
           ORDER BY p.id""",
        (match["id"], match.get(f"team{side}_id")),
    ).fetchall()
    if rows:
        return [dict(row) for row in rows]
    if conn.execute(
        "SELECT 1 FROM match_stats WHERE match_id=? LIMIT 1", (match["id"],)
    ).fetchone():
        return []
    team_id = match.get(f"team{side}_id")
    if not isinstance(team_id, int) or team_id <= 0:
        return []
    return [
        dict(row)
        for row in conn.execute("SELECT * FROM players WHERE team_id=? ORDER BY id", (team_id,))
    ]


def _number(form: Mapping[str, str], field, player_id, *, integer, maximum) -> int | float | None:
    name = f"{field}_{player_id}"
    if name not in form:
        raise ValueError("提交的选手数据不完整，请刷新页面后重试")
    text = form[name].strip()
    if not text:
        return None
    try:
        value = int(text) if integer else float(text)
        finite = math.isfinite(value)
    except (ValueError, OverflowError):
        raise ValueError(f"选手 {player_id} 的 {field} 不是有效数字") from None
    if not finite or value < 0 or (maximum is not None and value > maximum):
        raise ValueError(f"选手 {player_id} 的 {field} 超出有效范围")
    return value


def _apply_rating_edit(row, previous):
    """区分计算用 Impact 与显示值；管理员明确修改的值保持手工口径。"""
    impact_edited = previous is None or row["impact"] != previous.get("impact")
    method, raw = impact_calculation_metadata(previous or row)
    if impact_edited:
        method, raw = "manual", row["impact"]
    elif (
        previous is not None
        and method == HLTV2_ESTIMATE_METHOD
        and any(row[key] != previous.get(key) for key in ("kills", "assists", "rounds_played"))
    ):
        raw = estimate_hltv2_impact(row["kills"], row["assists"], row["rounds_played"])
        displayed = non_negative_impact(raw)
        row["impact"] = round(displayed, 2) if displayed is not None else None
    row["impact_method"], row["rating_impact"] = method, raw
    inputs = ("kills", "deaths", "assists", "adr", "kast", "impact", "rounds_played")
    if previous is None or any(row[key] != previous.get(key) for key in inputs):
        row["rating"], row["kpr"], row["dpr"] = calculate_rating(
            row["kills"],
            row["deaths"],
            row["rounds_played"],
            adr=row["adr"],
            kast=row["kast"],
            impact=raw,
        )


def _prepare_player_row(match, map_name, rounds, side, player_id, previous, form):
    """继承旧记录，仅覆盖表单允许编辑的字段；队伍归属由服务端确定。"""
    row = dict(previous or {})
    row.pop("id", None)
    for field, (column, integer, maximum) in FORM_FIELDS.items():
        row[column] = _number(form, field, player_id, integer=integer, maximum=maximum)
    team_id = match.get(f"team{side}_id")
    team_id = team_id if isinstance(team_id, int) and team_id > 0 else None
    row.update(
        match_id=match["id"],
        player_id=player_id,
        team_id=team_id,
        match_team_side=f"t{side}",
        map_name=map_name,
        rounds_played=rounds,
    )
    comparison = [spec[0] for spec in FORM_FIELDS.values()] + [
        "rounds_played",
        "team_id",
        "match_team_side",
    ]
    changed = previous is None or any(row[key] != previous.get(key) for key in comparison)
    needs_final = previous is None or (previous.get("data_status") or "final") != "final"
    if changed or needs_final:
        # Preserve the original calculation method before changing provenance.
        _apply_rating_edit(row, previous)
        row["data_source"] = "manual_review"
    row["data_status"] = "final"
    return row, changed or needs_final


def save_manual_map_stats(
    conn, match, map_name: str, rounds: int, sides, existing, form: Mapping[str, str]
) -> list[int]:
    """在调用方事务中校验整张表，再替换旧版本；返回需要更新汇总的选手。"""
    from src.website.runtime.host import HostError, is_managed_match

    if is_managed_match(conn, match["id"]):
        raise ValueError("托管赛事请在比赛运营中按实际开局和出场选手修订统计")
    if rounds <= 0:
        raise HostError(
            "该地图比分尚未确认，不能按旧的 30 回合默认值保存", 400, code="map_score_unconfirmed"
        )
    ids = [player["id"] for players in sides.values() for player in players]
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("本场名单为空或存在重复身份，未保存任何数据")
    old = {row["player_id"]: dict(row) for row in existing}
    if len(old) != len(existing) or not set(old).issubset(ids):
        raise ValueError("现有统计与本场名单不一致，请先核对阵容，原数据未修改")
    submitted = {name[6:] for name in form if name.startswith("kills_")}
    if submitted != {str(player_id) for player_id in ids}:
        raise ValueError("提交的选手名单不完整或与本场名单不一致，原数据未修改")
    key = normalize_map_key(map_name)
    stored_name = f"de_{key}" if key in MAP_NAME_MAPPING else map_name.strip()
    rows = []
    changed = False
    for side, players in sides.items():
        for player in players:
            row, row_changed = _prepare_player_row(
                match, stored_name, rounds, side, player["id"], old.get(player["id"]), form
            )
            rows.append(row)
            changed = changed or row_changed
    if changed:
        version = replace_map_stats_version(conn, match["id"], stored_name)
        for row in rows:
            row["data_version"] = version
            # 列名来自原统计行和后台字段表，表单只提供绑定的值。
            conn.execute(
                f"INSERT INTO match_stats({','.join(row)}) VALUES({','.join('?' for _ in row)})",
                tuple(row.values()),
            )
    return ids
