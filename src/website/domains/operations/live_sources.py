"""Adopt provable GSI and GOTV observations, never official results."""

import json
from datetime import datetime, timezone

from src.website.domains.operations import run_control as operations
from src.website.domains.operations.live_log import record_ingest_status
from src.website.domains.operations.live_service import (
    _is_recent_iso_timestamp,
    _record_gsi_bomb_events,
    _record_gsi_deaths,
    _round_win_reason_code,
    read_ingest_number,
)
from src.website.domains.operations.projection import (
    load_snapshot,
    parse_session_id,
    register_director_session,
    require_start_authorization,
    resolve_run,
    resolve_schedule,
    run_lineup,
    save_snapshot,
    snapshot_for_run,
)
from src.website.runtime.host import HostError

_SIDES = {"home": "team1", "away": "team2"}
_MAX_ROUNDS = 200


def _ordered_scores(mapping, first, score1, score2):
    return [score1, score2] if mapping[first] == "home" else [score2, score1]


def _feed_lineup(conn, match_id, scheduled_map_id, run_id):
    if run_id is not None:
        return run_lineup(conn, run_id)
    return {
        member["steam_id"]: member
        for member in operations.effective_roster(conn, match_id, scheduled_map_id)
    }


def _check_score_progress(state, scores):
    previous = state.get("observed_score")
    if previous and any(new < old for new, old in zip(scores, previous)):
        raise HostError("上报比分早于本局已接收的比分，请核对开局与报文顺序")


def _record_event(conn, run_id, kind, key, event):
    return (
        conn.execute(
            """INSERT INTO live_run_events(map_run_id,event_type,event_key,round_number,payload)
           VALUES(?,?,?,?,?) ON CONFLICT(map_run_id,event_type,event_key) DO NOTHING""",
            (
                run_id,
                kind,
                key,
                event["round_number"],
                json.dumps(event, ensure_ascii=False, separators=(",", ":")),
            ),
        ).rowcount
        == 1
    )


def _event_round(event, last_round):
    number = event.get("round_number", event.get("round"))
    return number if type(number) is int and 1 <= number <= last_round else None


def _gsi_rounds(conn, run_id, data, state, side_map, scores, active_round):
    completed = sum(scores)
    previous_scores = state.get("observed_score", [0, 0])
    previous = state.get("gsi", {})
    identity = data["_80gotv"]
    round_events = identity.get("round_events") or []
    from_app = {}
    for event in round_events:
        if not isinstance(event, dict):
            continue
        number = _event_round(event, completed)
        if number is not None:
            from_app[number] = event
    gmap = data["map"]
    round_data = data.get("round") or {}
    round_phase = round_data.get("phase")
    raw_round = int(gmap["round"])
    finish_frame = round_phase == "over" and raw_round == completed - 1
    next_round_frame = (
        gmap["phase"] == "live" and round_phase in ("live", "freezetime") and raw_round == completed
    )
    previous_identity = previous.get("_80gotv", {})
    # Outside the first round, require a verified frame from that very round
    # with the same sides. The current CT/T scoreboard may be after a switch.
    same_round_sides = (
        (previous.get("map") or {}).get("round") == completed - 1
        and (previous.get("round") or {}).get("phase") in ("live", "freezetime")
        and all(previous_identity.get(key) == identity[key] for key in ("team_ct", "team_t"))
    )
    round_mapping_known = (finish_frame or next_round_frame) and (
        completed == 1 or same_round_sides
    )
    win_ct_t = str(round_data.get("win_team") or "").upper() if finish_frame else ""
    if win_ct_t not in side_map:
        win_ct_t = ""
    # The fixed winner follows the real point increase even on a side switch.
    winner = None
    if completed == sum(previous_scores) + 1:
        winner = "home" if scores[0] > previous_scores[0] else "away"
    elif round_mapping_known and win_ct_t:
        winner = side_map[win_ct_t]
    proven_side = next((side for side in side_map if side_map[side] == winner), "")
    if not round_mapping_known or (win_ct_t and win_ct_t != proven_side):
        proven_side = ""

    for number in range(sum(previous_scores) + 1, completed + 1):
        operations.record_round(
            conn, run_id, number, source="gsi", winner_side=winner if number == completed else None
        )
    if active_round is not None:
        operations.record_round(conn, run_id, active_round, source="gsi")

    if completed and (win_ct_t or winner):
        from_app.setdefault(completed, {})
    history = {
        item["round_number"]: item
        for key in ("round_history", "overtime_history")
        for item in state.get(key, [])
    }
    for number, event in sorted(from_app.items()):
        saved = history.get(number)
        if saved and not event:
            continue
        side = str(event.get("winner_side") or event.get("side") or "").upper()
        if side not in side_map:
            side = ""
        if number == completed and not side:
            side = win_ct_t or proven_side
        fixed = winner if number == completed else None
        if fixed:
            operations.record_round(conn, run_id, number, source="gsi", winner_side=fixed)
        entry = {
            "id": f"round-{run_id}-{number}",
            "round": number,
            "round_number": number,
            "map_run_id": run_id,
            "map_name": data["map"]["name"],
            "side": side.lower(),
            "winner": {"home": "t1", "away": "t2"}[fixed] if fixed else None,
            "reason_code": event.get("reason_code"),
        }
        for key in ("captured_at", "captured_at_epoch"):
            if key in event:
                entry[key] = event[key]
        reported_scores = {
            key: event[key]
            for key in ("score_ct", "score_t")
            if type(event.get(key)) is int and 0 <= event[key] <= number
        }
        # The old director can send a pre-point scoreboard (including 0:0).
        if len(reported_scores) < 2 or sum(reported_scores.values()) == number:
            entry.update(reported_scores)
        if number == completed:
            if not entry["reason_code"]:
                entry["reason_code"] = (
                    _round_win_reason_code(data, previous, side)
                    if finish_frame and proven_side == side and side
                    else "completed"
                )
            if proven_side and side == proven_side:
                entry.update(
                    score_ct=int(gmap["team_ct"]["score"]), score_t=int(gmap["team_t"]["score"])
                )
        if saved:
            # Later packets repeat roundEnd details. Fill gaps without rewriting a known side or score.
            if saved.get("side") and side and saved["side"] != side.lower():
                continue
            additions = {
                key: value
                for key, value in entry.items()
                if value not in (None, "")
                and (
                    saved.get(key) in (None, "")
                    or (key == "reason_code" and saved[key] == "completed" and value != "completed")
                )
            }
            if not additions:
                continue
            conn.execute(
                "UPDATE live_run_events SET payload=json_patch(payload, ?) "
                "WHERE map_run_id=? AND event_type='round' AND event_key=?",
                (json.dumps(additions, ensure_ascii=False), run_id, str(number)),
            )
            entry = {**saved, **additions}
        else:
            _record_event(conn, run_id, "round", str(number), entry)
        history[number] = entry
    state["round_history"] = [history[number] for number in sorted(history) if number <= 24]
    state["overtime_history"] = [history[number] for number in sorted(history) if number > 24][-24:]


def _gsi_player_events(conn, run_id, data, state, lineup, side_map, active_round, last_round):
    identity = data["_80gotv"]
    if "death_markers" not in identity:
        _record_gsi_deaths(state, data)
    markers = state.get("death_markers", []) + identity.get("death_markers", [])
    by_id = {}
    for marker in markers:
        if not isinstance(marker, dict):
            continue
        number = _event_round(marker, last_round)
        steam_id = marker.get("steamid")
        side = str(marker.get("side") or "").upper()
        event_id = marker.get("id")
        if (
            number is None
            or not isinstance(steam_id, str)
            or steam_id not in lineup
            or side not in side_map
            or not isinstance(event_id, str)
            or not event_id
        ):
            continue
        member = lineup[steam_id]
        if number == active_round and member["side_key"] != side_map[side]:
            continue
        entry = {
            key: marker[key]
            for key in ("name", "x", "y", "z", "observer_slot", "captured_at", "captured_at_epoch")
            if key in marker
        }
        entry.update(
            id=event_id,
            steamid=steam_id,
            side=side,
            round=number,
            round_number=number,
            map_run_id=run_id,
            map_name=data["map"]["name"],
        )
        by_id[event_id] = entry
        if _record_event(conn, run_id, "death", event_id, entry):
            operations.record_participation(
                conn,
                run_id,
                member["player_id"],
                member["match_participant_id"],
                source="gsi",
                round_number=number,
                side=side,
            )
    state["death_markers"] = state["kill_markers"] = list(by_id.values())[-10:]

    if active_round is None:
        return
    for steam_id, player in (data.get("allplayers") or {}).items():
        member = lineup.get(steam_id)
        side = str(player.get("team") or "").upper()
        if (
            member
            and side_map.get(side) == member["side_key"]
            and (player.get("state") or {}).get("health", 0) > 0
        ):
            operations.record_participation(
                conn,
                run_id,
                member["player_id"],
                member["match_participant_id"],
                source="gsi",
                round_number=active_round,
                side=side,
            )
    _record_gsi_bomb_events(state, data)
    if state.get("bomb_events"):
        event = state["bomb_events"][-1]
        if event["round_number"] == active_round:
            event.update(map_run_id=run_id, map_name=data["map"]["name"])
            _record_event(conn, run_id, "plant", str(active_round), event)


def receive_gsi(conn, match_id, map_name, data):
    require_start_authorization(conn, match_id)
    identity = data.get("_80gotv") or {}
    slot = read_ingest_number(identity, "map_slot", 1, 5, integer=True)
    expected = read_ingest_number(identity, "map_run_id", 1, 2**53 - 1, integer=True)
    session = parse_session_id(identity.get("session_id"), match_id)
    seq = read_ingest_number(identity, "frame_seq", 0, 2**53 - 1, integer=True)
    ack = {"ok": True, "match_id": match_id, "session_id": session or None, "frame_seq": seq}
    plan = resolve_schedule(conn, match_id, map_name, slot)
    gmap = data["map"]
    phase = gmap.get("phase")
    countdown = (data.get("phase_countdowns") or {}).get("phase")
    if phase not in ("live", "gameover") or countdown in ("warmup", "knife"):
        return dict(ack, applied=False, reason="not_in_play")
    scheduled_id = plan["scheduled_map_id"]
    run = resolve_run(conn, scheduled_id, expected, session_id=session)
    run_id = run["map_run_id"] if run else None
    if run and run["status"] != "active":
        return dict(ack, map_run_id=run_id, applied=False, reason="map_finished")

    ct_score = (gmap.get("team_ct") or {}).get("score")
    t_score = (gmap.get("team_t") or {}).get("score")
    raw_round = gmap.get("round")
    if ct_score is None or t_score is None or raw_round is None:
        return dict(ack, applied=False, reason="awaiting_play_evidence")
    ct_score, t_score, raw_round = int(ct_score), int(t_score), int(raw_round)
    completed = ct_score + t_score
    if completed > _MAX_ROUNDS or abs(completed - raw_round) > 1:
        raise HostError("GSI 回合进度与比分不一致，请核对现场数据")
    # A knife round / 0:0 freeze can look live. Do not create a run until the
    # first scored round has ended and the server has entered the next round.
    round_phase = (data.get("round") or {}).get("phase")
    if run_id is None and (
        phase != "live"
        or not 1 <= raw_round == completed
        or round_phase not in ("live", "freezetime")
    ):
        return dict(ack, applied=False, reason="awaiting_play_evidence")

    previous = load_snapshot(conn, match_id)
    old_session = previous.get("gsi_session_id")
    if old_session and old_session != session:
        if not session or _is_recent_iso_timestamp(previous.get("gsi_received_at")):
            raise HostError("导播实时会话仍在负责本场比赛，其他来源不得覆盖")
    if session and session == old_session and seq is not None:
        old_seq = previous.get("gsi_frame_seq")
        if old_seq is not None and (
            seq < old_seq or (seq == old_seq and previous.get("map_run_id") != run_id)
        ):
            raise HostError("较旧实时帧被拒绝")
        if old_seq == seq:
            return dict(ack, map_run_id=run_id, applied=False, duplicate=True)

    lineup = _feed_lineup(conn, match_id, scheduled_id, run_id)
    teams = {"CT": set(), "T": set()}
    for steam_id, player in (data.get("allplayers") or {}).items():
        side = str(player.get("team") or "").upper()
        if steam_id in lineup and side in teams:
            teams[side].add(lineup[steam_id]["side_key"])
    if any(len(team) != 1 for team in teams.values()) or teams["CT"] == teams["T"]:
        raise HostError("无法用本局名单核对 GSI 的 CT/T 归属")
    side_map = {side: next(iter(team)) for side, team in teams.items()}
    scores = _ordered_scores(side_map, "CT", ct_score, t_score)
    if run_id is None:
        run_id = operations.observe_start(
            conn,
            match_id,
            scheduled_id,
            source="gsi",
            evidence=f"GSI live, round={raw_round}, score={scores[0]}:{scores[1]}, verified teams",
        )
    state = snapshot_for_run(previous, plan, run_id)
    _check_score_progress(state, scores)
    if session:
        register_director_session(conn, scheduled_id, run_id, session, reason="GSI verified play")
    if state.get("gsi") and (
        old_session != session or not _is_recent_iso_timestamp(state.get("gsi_received_at"))
    ):
        state.pop("gsi")
    data = dict(
        data, _80gotv=dict(identity, team_ct=_SIDES[side_map["CT"]], team_t=_SIDES[side_map["T"]])
    )
    active_round = (
        completed + 1
        if (phase == "live" and raw_round == completed and round_phase == "live")
        else None
    )
    _gsi_rounds(conn, run_id, data, state, side_map, scores, active_round)
    _gsi_player_events(
        conn, run_id, data, state, lineup, side_map, active_round, active_round or completed
    )
    state.update(
        gsi=data,
        observed_score=scores,
        gsi_session_id=session or None,
        gsi_frame_seq=seq,
        gsi_received_at=datetime.now(timezone.utc).isoformat(),
    )
    save_snapshot(conn, match_id, state)
    record_ingest_status(conn, "gsi", "ok", "已接收本局 GSI 观察", match_id, plan["map_name"])
    return dict(ack, map_run_id=run_id, applied=True)


def receive_gotv(
    conn,
    match_id,
    map_name,
    players,
    team_a_name,
    team_b_name,
    score_a,
    score_b,
    rounds_count,
    halftime,
    expected_run_id,
):
    require_start_authorization(conn, match_id)
    plan = resolve_schedule(conn, match_id, map_name)
    ack = {
        "ok": True,
        "map_slot": plan["legacy_slot"] - 1,
        "players_imported": 0,
        "players_created": 0,
    }
    completed = score_a + score_b
    if completed <= 1:
        return dict(ack, applied=False, reason="awaiting_play_evidence")
    if completed > _MAX_ROUNDS or rounds_count not in (completed, completed + 1):
        raise HostError("GOTV 回合进度与比分不一致，请核对现场数据")
    scheduled_id = plan["scheduled_map_id"]
    run = resolve_run(conn, scheduled_id, expected_run_id)
    if run and run["status"] != "active":
        raise HostError("该图已有正式裁定，GOTV 现场观察不能覆盖")
    run_id = run["map_run_id"] if run else None
    previous = load_snapshot(conn, match_id)
    if (
        run_id is not None
        and previous.get("map_run_id") == run_id
        and previous.get("gsi_session_id")
    ):
        raise HostError("导播数据已负责本局，GOTV 只能旁观不能覆盖")
    lineup = _feed_lineup(conn, match_id, scheduled_id, run_id)
    teams = {"A": set(), "B": set()}
    snapshots = {"home": [], "away": []}
    fielded = []
    for player in players:
        steam_id = str(player["steam_id"]).strip()
        member = lineup.get(steam_id)
        if not member:
            raise HostError("GOTV 选手不在本局批准名单内")
        side = member["side_key"]
        teams[player["team_letter"]].add(side)
        stats = {
            key: read_ingest_number(player, key, 0, 100000, integer=True)
            for key in ("kills", "deaths", "assists")
        }
        adr = read_ingest_number(player, "adr", 0, 10000)
        snapshots[side].append(dict(stats, steamid=steam_id, name=player["name"], adr=adr))
        # This relay copies the map's rounds_count to each player, so that
        # field alone is not a player-level or per-round participation fact.
        if any(stats.values()):
            fielded.append(member)
    if any(len(team) != 1 for team in teams.values()) or teams["A"] == teams["B"]:
        raise HostError("无法用本局名单核对 GOTV 的 A/B 归属")
    mapping = {letter: next(iter(team)) for letter, team in teams.items()}
    scores = _ordered_scores(mapping, "A", score_a, score_b)
    if run_id is None:
        run_id = operations.observe_start(
            conn,
            match_id,
            scheduled_id,
            source="gotv",
            evidence=f"GOTV rounds={completed}, score={scores[0]}:{scores[1]}, verified teams",
        )
    state = snapshot_for_run(previous, plan, run_id)
    _check_score_progress(state, scores)
    for number in range(sum(state.get("observed_score", [0, 0])) + 1, completed + 1):
        operations.record_round(conn, run_id, number, source="gotv")
    for member in fielded:
        operations.record_participation(
            conn, run_id, member["player_id"], member["match_participant_id"], source="gotv"
        )
    names = [team_a_name, team_b_name]
    if mapping["A"] != "home":
        names.reverse()
    state.update(
        observed_score=scores,
        gotv={
            "map_name": plan["map_name"],
            "map_slot": ack["map_slot"],
            "team_a_score": score_a,
            "team_b_score": score_b,
            "team1_score": scores[0],
            "team2_score": scores[1],
            "team1_name": names[0],
            "team2_name": names[1],
            "t1_players": snapshots["home"],
            "t2_players": snapshots["away"],
            "player_count": len(players),
            "rounds_count": rounds_count,
            "halftime": halftime,
            "last_push": datetime.now(timezone.utc).isoformat(),
        },
    )
    save_snapshot(conn, match_id, state)
    record_ingest_status(conn, "gotv", "ok", "已接收本局 GOTV 观察", match_id, plan["map_name"])
    return dict(ack, map_run_id=run_id, applied=True, players_imported=len(players))
