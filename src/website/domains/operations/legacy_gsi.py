"""Route an authenticated GSI frame to managed or historical live state."""

import json
from datetime import datetime, timezone

from src.website.domains.demos.demo_parser import normalize_map_name
from src.website.domains.directory.player_service import record_observed_player_nickname
from src.website.domains.matches.maps import project_legacy_map_fields
from src.website.domains.matches.match_roster_service import (
    freeze_match_roster,
    resolve_match_roster,
)
from src.website.domains.matches.match_utils import get_sql_match_live
from src.website.domains.operations.legacy_live_state import _active_map_slots, _sanitize_live_state
from src.website.domains.operations.live_log import (
    persist_live_match_events,
    record_ingest_status,
)
from src.website.domains.operations.live_rosters import gsi_team_mapping as _gsi_team_mapping
from src.website.domains.operations.live_rosters import (
    roster_side_by_steamid as _roster_side_by_steamid,
)
from src.website.domains.operations.live_service import (
    _is_recent_iso_timestamp,
    _record_gsi_bomb_events,
    _record_gsi_deaths,
    _round_win_reason,
    _round_win_reason_code,
)
from src.website.domains.operations.live_service import read_ingest_number as _bounded_number
from src.website.domains.operations.live_sources import receive_gsi
from src.website.domains.operations.projection import live_schema_ready
from src.website.runtime.host import HostError, has_event_schema, is_managed_match


def _match_team_for_gsi_side(data, side, side_mapping=None):
    identity = (data.get("_80gotv") or {}) if isinstance(data, dict) else {}
    mapped = (side_mapping or {}).get(side)
    if mapped not in {"team1", "team2"}:
        mapped = identity.get("team_ct" if side == "CT" else "team_t")
    if mapped == "team2":
        return "t2"
    if mapped == "team1":
        return "t1"
    return None


def _merge_app_live_events(merged, data, side_mapping=None, previous_side_mapping=None):
    """Merge canonical events prepared by the desktop app and deduplicate by round/id."""
    identity = (data.get("_80gotv") or {}) if isinstance(data, dict) else {}
    round_events = identity.get("round_events") if "round_events" in identity else None
    death_markers = identity.get("death_markers") if "death_markers" in identity else None

    if isinstance(round_events, list):
        by_key = {}
        for event in (
            (merged.get("round_history", []) or [])
            + (merged.get("overtime_history", []) or [])
            + round_events
        ):
            if not isinstance(event, dict):
                continue
            try:
                round_number = int(event.get("round_number", event.get("round", 0)) or 0)
            except (TypeError, ValueError):
                continue
            if not 1 <= round_number <= 48:
                continue
            normalized = dict(event)
            normalized["round"] = round_number
            normalized["round_number"] = round_number
            normalized.setdefault("id", f"round-{round_number}-{normalized.get('side', '')}")
            winner_side = str(normalized.get("winner_side") or normalized.get("side") or "").upper()
            if normalized.get("winner") not in ("t1", "t2") and winner_side in ("CT", "T"):
                stored = by_key.get(str(normalized["id"])) or next(
                    (
                        item
                        for item in by_key.values()
                        if item.get("round") == round_number and item.get("winner") in ("t1", "t2")
                    ),
                    {},
                )
                mapping = side_mapping
                if round_number == max(1, (data.get("map") or {}).get("round", 0)):
                    mapping = previous_side_mapping or side_mapping
                normalized["winner"] = stored.get("winner") or _match_team_for_gsi_side(
                    data, winner_side, mapping
                )
            by_key[str(normalized["id"])] = normalized
        ordered = sorted(
            by_key.values(), key=lambda item: (int(item.get("round", 0)), str(item.get("id", "")))
        )
        # A round has one winner; an app resend must replace the earlier partial event.
        by_round = {int(item["round"]): item for item in ordered}
        regulation = [by_round[number] for number in sorted(by_round) if number <= 24]
        overtime = [by_round[number] for number in sorted(by_round) if number > 24]
        merged["round_history"] = regulation[-24:]
        merged["overtime_history"] = overtime[-24:]

    if isinstance(death_markers, list):
        by_id = {}
        for marker in (
            merged.get("death_markers", merged.get("kill_markers", [])) or []
        ) + death_markers:
            if not isinstance(marker, dict):
                continue
            marker = dict(marker)
            try:
                round_number = int(marker.get("round_number", marker.get("round", 0)) or 0)
            except (TypeError, ValueError):
                continue
            if not 1 <= round_number <= 48:
                continue
            marker["round"] = round_number
            marker["round_number"] = round_number
            marker.setdefault(
                "id",
                f"death-{round_number}-{marker.get('steamid', '')}-{marker.get('captured_at_epoch', '')}",
            )
            by_id[str(marker["id"])] = marker
        merged["death_markers"] = list(by_id.values())[-10:]
        merged["kill_markers"] = merged["death_markers"]
    return isinstance(round_events, list), isinstance(death_markers, list)


def store_gsi_frame(conn, data, map_name, forced_match_id=None):
    if forced_match_id is None:
        live_filter = get_sql_match_live()
        archive_filter = (
            """AND NOT EXISTS(SELECT 1 FROM event_registration_control c
            WHERE c.event_id=m.event_id AND c.archived_at IS NOT NULL)"""
            if has_event_schema(conn)
            else ""
        )
        if live_schema_ready(conn):
            live_filter = f"""({live_filter} AND NOT EXISTS(
                    SELECT 1 FROM event_registration_control c WHERE c.event_id=m.event_id
                )) OR (m.status IN ('upcoming','live') AND EXISTS(
                    SELECT 1 FROM match_start_authorizations a WHERE a.match_id=m.id
                ))"""
        matches = conn.execute(
            f"""
            SELECT m.* FROM matches m
            WHERE ({live_filter}) {archive_filter}
        """,
        ).fetchall()
        matches = [
            project_legacy_map_fields(conn, dict(m)) if is_managed_match(conn, m["id"]) else m
            for m in matches
        ]
        matches = [
            match
            for match in matches
            if any(
                normalize_map_name(match[f"map{slot + 1}"] or "") == normalize_map_name(map_name)
                for slot in _active_map_slots(match)
            )
        ]
    else:
        if is_managed_match(conn, forced_match_id):
            conn.execute("BEGIN IMMEDIATE")
            return receive_gsi(conn, forced_match_id, map_name, data)
        matches = conn.execute(
            "SELECT * FROM matches WHERE id=?",
            (forced_match_id,),
        ).fetchall()
        if matches and matches[0]["status"] in {"completed", "cancelled"}:
            raise HostError("比赛已结束或取消，拒绝覆盖直播数据", 409)
        configured_maps = (
            [matches[0][f"map{slot + 1}"] for slot in _active_map_slots(matches[0])]
            if matches
            else []
        )
        configured_maps = [name for name in configured_maps if name]
        if matches and not any(
            normalize_map_name(name) == normalize_map_name(map_name) for name in configured_maps
        ):
            raise HostError("推送地图不在该比赛赛程中", 409)

    if not matches:
        raise HostError("未找到匹配的比赛", 404)
    if len(matches) > 1:
        raise HostError("存在多场同地图直播比赛，请管理员检查赛程", 409)
    match_id = matches[0]["id"]
    if is_managed_match(conn, match_id):
        conn.execute("BEGIN IMMEDIATE")
        return receive_gsi(conn, match_id, map_name, data)
    conn.execute("UPDATE matches SET status=status WHERE id=?", (match_id,))
    match = conn.execute(
        """
        SELECT m.*, t1.name AS scheduled_team1_name, t2.name AS scheduled_team2_name,
               t1.short_name AS scheduled_team1_short, t2.short_name AS scheduled_team2_short
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        WHERE m.id=?
        """,
        (match_id,),
    ).fetchone()
    if not match or match["status"] in ("completed", "cancelled"):
        raise HostError("比赛已结束或取消，拒绝覆盖直播数据", 409)
    roster_side_by_steamid = _roster_side_by_steamid(conn, match) if match else {}
    side_mapping = _gsi_team_mapping(data, match, roster_side_by_steamid) if match else None

    # 合并已有 live_state（避免覆盖 GOTV 等其他数据）
    existing = conn.execute(
        "SELECT live_state FROM live_match_data WHERE match_id=?", (match_id,)
    ).fetchone()
    merged = {}
    if existing and existing["live_state"]:
        try:
            merged = json.loads(existing["live_state"])
        except (ValueError, TypeError):
            pass
    merged = _sanitize_live_state(merged)
    identity = (data.get("_80gotv") or {}) if isinstance(data, dict) else {}
    incoming_session = str(identity.get("session_id") or "").strip()
    incoming_seq = identity.get("frame_seq")
    if incoming_seq is not None:
        incoming_seq = _bounded_number(identity, "frame_seq", 0, 2**53 - 1, integer=True)
    previous_session = str(merged.get("gsi_session_id") or "").strip()
    previous_seq = merged.get("gsi_frame_seq")
    try:
        previous_seq = int(previous_seq) if previous_seq is not None else None
    except (TypeError, ValueError):
        previous_seq = None
    if incoming_session and previous_session and incoming_session != previous_session:
        if _is_recent_iso_timestamp(merged.get("gsi_received_at")):
            raise HostError("实时数据会话仍在使用，拒绝覆盖当前比赛，请稍后重试", 409)
        # 旧导播已断开超过有效期，新会话可以恢复；帧编号不能跨会话比较。
        previous_seq = None
    if previous_session and not incoming_session:
        raise HostError("导播实时会话正在负责本场比赛，备用 GSI 不得覆盖", 409)
    if incoming_session and incoming_seq is not None and previous_seq is not None:
        if incoming_seq < previous_seq:
            raise HostError("较旧实时帧被拒绝", 409)
        if incoming_seq == previous_seq:
            return {
                "ok": True,
                "duplicate": True,
                "match_id": match_id,
                "session_id": incoming_session,
                "frame_seq": incoming_seq,
            }
    for steamid, player in (data.get("allplayers", {}) or {}).items():
        record_observed_player_nickname(conn, steamid, player.get("name", ""), "gsi")
    previous_gsi = merged.get("gsi", {}) or {}
    previous_map_name = normalize_map_name((previous_gsi.get("map", {}) or {}).get("name", ""))
    if previous_gsi and not _is_recent_iso_timestamp(merged.get("gsi_received_at")):
        merged["gsi"] = {}
        previous_gsi = {}
    current_map_name = normalize_map_name(map_name)
    if previous_map_name and current_map_name and previous_map_name != current_map_name:
        for key in (
            "round_history",
            "overtime_history",
            "death_markers",
            "kill_markers",
            "kill_events",
            "bomb_events",
        ):
            merged[key] = []
        # 换图后的首帧不能与上一张图比较，否则会制造阵亡或漏掉下包事件。
        merged["gsi"] = {}
        previous_gsi = {}
    # APP 已经在本地按正式比赛缓存阵亡点；兼容旧 GSI 客户端时才使用
    # 服务端的帧差兜底，避免两套判断互相覆盖。
    if "death_markers" not in identity:
        _record_gsi_deaths(merged, data)
    _record_gsi_bomb_events(merged, data)
    previous_side_mapping = (
        _gsi_team_mapping(previous_gsi, match, roster_side_by_steamid) if previous_gsi else None
    )
    app_round_events, app_death_markers = _merge_app_live_events(
        merged,
        data,
        side_mapping,
        previous_side_mapping,
    )

    # 计算回合历史（每回合结束时记录胜负方）
    round_num = (data.get("map") or {}).get("round", 0)
    # In transition frames CS2 reports the newly-entered zero-based round while
    # `previously.round` describes the round that just finished. Some servers
    # briefly keep round 0 on the first result, so clamp that one to round 1.
    completed_round = max(1, round_num)
    if "round_history" not in merged:
        merged["round_history"] = []
    rh = merged["round_history"]
    # 检测新回合结束
    prev_round = (data.get("previously") or {}).get("round", {}) or {}
    prev_winner = prev_round.get("win_team", "")
    # 常规时间固定保留 24 个格子；加时单独保存，不能挤进常规栏。
    if "overtime_history" not in merged:
        merged["overtime_history"] = []
    overtime = merged["overtime_history"]
    if not isinstance(overtime, list):
        overtime = []
    if (
        (not app_round_events)
        and 1 <= completed_round <= 48
        and prev_winner
        and (
            (completed_round <= 24 and (not rh or rh[-1].get("round") != completed_round))
            or (
                completed_round > 24
                and (not overtime or overtime[-1].get("round") != completed_round)
            )
        )
    ):
        current_map = data.get("map", {}) or {}
        captured_at = datetime.now(timezone.utc)
        reason_code = _round_win_reason_code(data, previous_gsi, prev_winner)
        round_result = {
            "id": f"round-{completed_round}-{prev_winner.lower()}",
            "round": completed_round,
            "round_number": completed_round,
            "winner": _match_team_for_gsi_side(
                data, prev_winner, previous_side_mapping or side_mapping
            ),
            "side": prev_winner.lower(),
            "score_ct": (current_map.get("team_ct", {}) or {}).get("score", 0),
            "score_t": (current_map.get("team_t", {}) or {}).get("score", 0),
            "reason": _round_win_reason(data, previous_gsi, prev_winner),
            "reason_code": reason_code,
            "captured_at": captured_at.isoformat(),
            "captured_at_epoch": captured_at.timestamp(),
        }
        if completed_round <= 24:
            rh.append(round_result)
            if len(rh) > 24:
                rh = rh[-24:]
            merged["round_history"] = rh
        else:
            overtime.append(round_result)
            merged["overtime_history"] = overtime[-24:]

    # The app is authoritative for formal-match events. It may send an empty
    # event list while a frame is being skipped, so do not manufacture kills
    # or round results from that transient frame.
    if app_death_markers:
        merged["death_markers"] = merged.get("death_markers", [])[-10:]
        merged["kill_markers"] = merged["death_markers"]
    # Do not clear a previously persisted kill timeline just because this GSI
    # frame did not carry a new event.
    if not isinstance(merged.get("kill_events"), list):
        merged["kill_events"] = []

    merged["gsi"] = data
    if incoming_session:
        merged["gsi_session_id"] = incoming_session
    if incoming_seq is not None:
        merged["gsi_frame_seq"] = incoming_seq
    merged["gsi_received_at"] = datetime.now(timezone.utc).isoformat()
    if resolve_match_roster(conn, match)["locked"]:
        freeze_match_roster(conn, match, confirmed=True)
    persist_live_match_events(conn, match_id, merged)
    record_ingest_status(conn, "gsi", "ok", "观战账号数据正常", match_id, map_name)

    conn.execute(
        """
        INSERT INTO live_match_data(match_id, live_state)
        VALUES(?, ?)
        ON CONFLICT(match_id) DO UPDATE SET live_state=excluded.live_state, updated_at=CURRENT_TIMESTAMP
    """,
        (match_id, json.dumps(merged, ensure_ascii=False)),
    )

    return {
        "ok": True,
        "match_id": match_id,
        "session_id": incoming_session or None,
        "frame_seq": incoming_seq,
    }
