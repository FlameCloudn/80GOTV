"""手动修改地图统计：先完整校验，保留旧记录中未编辑的字段。"""

import math

from services.match_roster_service import match_player_slots, match_registration
from utils.stats_calc import (
    HLTV2_ESTIMATE_METHOD,
    calculate_rating,
    estimate_hltv2_impact,
    impact_calculation_metadata,
    non_negative_impact,
)

FORM_FIELDS = {
    "kills": ("kills", True, None),
    "deaths": ("deaths", True, None),
    "assists": ("assists", True, None),
    "adr": ("adr", False, None),
    "kast": ("kast", False, 100),
    "hs": ("headshot_percentage", False, 100),
    "impact": ("impact", False, None),
}


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


def _number(form, field, player_id, *, integer, maximum):
    name = f"{field}_{player_id}"
    if name not in form:
        raise ValueError("提交的选手数据不完整，请刷新页面后重试")
    text = str(form[name]).strip()
    if not text:
        return None
    try:
        value = int(text) if integer else float(text)
        finite = math.isfinite(value)
    except (TypeError, ValueError, OverflowError):
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
    elif method == HLTV2_ESTIMATE_METHOD and any(
        row[key] != previous.get(key) for key in ("kills", "assists", "rounds_played")
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


def prepare_manual_map_rows(match, map_name, rounds, sides, existing, form):
    """先校验完整提交并组装新记录，此步骤不写库；保留小人数旧阵容兼容。"""
    if rounds <= 0:
        raise ValueError("该地图比分尚未确认，不能按旧的 30 回合默认值保存")
    ids = [player["id"] for players in sides.values() for player in players]
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("本场名单为空或存在重复身份，未保存任何数据")
    old = {row["player_id"]: dict(row) for row in existing}
    if len(old) != len(existing) or not set(old).issubset(ids):
        raise ValueError("现有统计与本场名单不一致，请先核对阵容，原数据未修改")
    submitted = {name[6:] for name in form if name.startswith("kills_")}
    if submitted != {str(player_id) for player_id in ids}:
        raise ValueError("提交的选手名单不完整或与本场名单不一致，原数据未修改")
    rows = []
    changed = False
    for side, players in sides.items():
        for player in players:
            row, row_changed = _prepare_player_row(
                match, map_name, rounds, side, player["id"], old.get(player["id"]), form
            )
            rows.append(row)
            changed = changed or row_changed
    return rows, changed


def write_manual_map_revision(conn, match_id, map_name, rows):
    """在调用者的写事务内，保存已经完整校验的新版本。"""
    if not conn.in_transaction:
        raise RuntimeError("手动统计保存必须在写事务中执行")
    if not rows:
        raise ValueError("不能保存空统计")
    version = conn.execute(
        "SELECT COALESCE(MAX(data_version),0)+1 FROM match_stats WHERE match_id=? AND map_name=?",
        (match_id, map_name),
    ).fetchone()[0]
    conn.execute(
        """UPDATE match_stats SET data_status='superseded'
           WHERE match_id=? AND map_name=? AND COALESCE(data_status,'final')<>'superseded'""",
        (match_id, map_name),
    )
    allowed = {row[1] for row in conn.execute("PRAGMA table_info(match_stats)")} - {"id"}
    for prepared in rows:
        row = {key: value for key, value in prepared.items() if key in allowed}
        row["data_version"] = version
        columns = list(row)
        conn.execute(
            f"INSERT INTO match_stats({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
            [row[column] for column in columns],
        )
