"""Award one managed event champion from the official final and actual participation."""

from site_core.events.registration import require_admin
from site_core.host import HostError, is_managed_event
from site_core.matches.results import read_results


def has_championship_schema(conn) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='managed_event_champions'"
        ).fetchone()
        is not None
    )


def _require_managed_event(conn, event_id: int):
    if not is_managed_event(conn, event_id):
        raise HostError("本届不是托管赛事，请使用原授奖入口", 404)
    if not has_championship_schema(conn):
        raise HostError("数据库尚未升级至托管冠军授奖结构", 503)


def championship_final_match_id(conn, event_id: int) -> int:
    # The bracket's single and double-elimination championship slots use these exact labels.
    finals = conn.execute(
        """SELECT id FROM matches WHERE event_id=? AND status IS NOT 'cancelled'
           AND LOWER(TRIM(stage)) IN ('决赛', '总决赛', 'final', 'grand final')""",
        (event_id,),
    ).fetchall()
    if len(finals) != 1:
        raise HostError("本届没有唯一明确标记的总决赛，请核对赛程")
    match_id = finals[0]["id"]
    if conn.execute(
        "SELECT 1 FROM managed_bracket_links WHERE source_match_id=? LIMIT 1", (match_id,)
    ).fetchone():
        raise HostError("该场仍有下游签位，不是本届冠军决赛")
    return match_id


def _candidate(conn, event_id: int):
    if conn.execute("SELECT 1 FROM event_champions WHERE event_id=?", (event_id,)).fetchone():
        raise HostError("本届已有历史冠军记录，不能另发一份托管冠军")
    match_id = championship_final_match_id(conn, event_id)
    state = read_results(conn, match_id)
    settlement = state["series"]
    if state["status"] != "completed" or not settlement or settlement["state"] != "settled":
        raise HostError("决赛尚未正式完赛")
    maps = [m for m in state["maps"] if m["is_enabled"] and m["official_map_result_id"] is not None]
    if (
        not maps
        or [m["official_map_result_id"] for m in maps] != settlement["map_result_ids"]
        or any(m["run_status"] != "closed" for m in maps)
    ):
        raise HostError("正式决赛结果与有效开局不一致，请核对赛果")
    final_map = maps[-1]
    winner_side = settlement["winner_side"]
    winner_id = settlement[f"{winner_side}_participant_id"]
    team = conn.execute(
        """SELECT p.event_entrant_id, g.club_id, r.team_name, r.short_name AS team_short_name,
                  r.team_logo
           FROM match_participants p JOIN match_rosters r USING(match_participant_id)
           JOIN event_entrants e ON e.event_id=p.event_id AND e.event_entrant_id=p.event_entrant_id
           JOIN event_registration_groups g USING(registration_id)
           WHERE p.match_participant_id=? AND p.event_id=?""",
        (winner_id, event_id),
    ).fetchone()
    if not team:
        raise HostError("决赛胜方缺少已冻结的本届参赛身份")

    run_ids = tuple(m["map_run_id"] for m in maps)
    placeholders = ",".join("?" for _ in run_ids)
    rows = conn.execute(
        f"""SELECT r.map_run_id, r.player_id, r.participation_id,
                   r.revision AS participation_revision, l.roster_slot, p.nickname
            FROM run_participations r
            JOIN map_run_lineups l USING(map_run_id, player_id, match_participant_id)
            JOIN players p ON p.id=r.player_id
            WHERE r.is_current=1 AND r.match_participant_id=? AND r.map_run_id IN ({placeholders})
            ORDER BY l.roster_slot""",
        (winner_id, *run_ids),
    ).fetchall()
    players = [dict(row) for row in rows if row["map_run_id"] == final_map["map_run_id"]]
    if len(players) != 5:
        raise HostError("决胜局尚没有五名已确认实际出场的胜方选手")
    if {row["player_id"] for row in rows} != {row["player_id"] for row in players}:
        raise HostError("有效决赛地图出现不同获胜方成员，须先核对冠军人选")
    return {
        "event_id": event_id,
        "match_id": match_id,
        "match_participant_id": winner_id,
        "settlement_id": settlement["settlement_id"],
        "official_map_result_id": final_map["official_map_result_id"],
        **dict(team),
        "players": players,
    }


def _stored(conn, event_id: int):
    award = conn.execute(
        "SELECT * FROM managed_event_champions WHERE event_id=?", (event_id,)
    ).fetchone()
    if not award:
        return None
    players = [
        dict(row)
        for row in conn.execute(
            """SELECT player_id, roster_slot, nickname, participation_id, participation_revision
               FROM managed_event_champion_players WHERE event_id=? ORDER BY roster_slot""",
            (event_id,),
        )
    ]
    return {**dict(award), "players": players}


def _selection(award):
    return award["match_id"], award["settlement_id"], {row["player_id"] for row in award["players"]}


def _status_with_award(conn, event_id: int, award):
    candidate, blocked_reason = None, None
    try:
        candidate = _candidate(conn, event_id)
    except HostError as exc:
        blocked_reason = exc.message
    if award:
        if candidate and _selection(award) != _selection(candidate):
            blocked_reason = "决赛或获奖依据已改变，原奖保留，待人工复核"
        award["needs_review"] = blocked_reason is not None
    return {"championship": award, "candidate": candidate, "blocked_reason": blocked_reason}


def championship_status(conn, event_id: int):
    _require_managed_event(conn, event_id)
    return _status_with_award(conn, event_id, _stored(conn, event_id))


def award_championship(
    conn,
    event_id: int,
    *,
    match_id: int,
    settlement_id: int,
    player_ids: tuple[int, ...],
    admin_id: int,
):
    """Freeze an explicitly reviewed championship within the caller's transaction."""
    if not conn.in_transaction:
        raise HostError("请在写事务中办理冠军授予")
    require_admin(conn, admin_id)
    _require_managed_event(conn, event_id)
    selection = match_id, settlement_id, set(player_ids)
    existing = _stored(conn, event_id)
    if existing:
        if selection == _selection(existing):
            return {**_status_with_award(conn, event_id, existing), "duplicate": True}
        raise HostError("本届已授予冠军，不自动覆盖原奖")

    candidate = _candidate(conn, event_id)
    if selection != _selection(candidate):
        raise HostError("决赛赛果或实际出场名单与核对时不同，请重新核对")
    conn.execute(
        """INSERT INTO managed_event_champions(event_id, event_entrant_id, match_id, match_participant_id,
                  settlement_id, official_map_result_id, club_id, team_name, team_short_name, team_logo, awarded_by)
           VALUES(:event_id, :event_entrant_id, :match_id, :match_participant_id, :settlement_id,
                  :official_map_result_id, :club_id, :team_name, :team_short_name, :team_logo, :awarded_by)""",
        {**candidate, "awarded_by": admin_id},
    )
    conn.executemany(
        """INSERT INTO managed_event_champion_players(
                   event_id, player_id, roster_slot, nickname, participation_id, participation_revision)
           VALUES(:event_id, :player_id, :roster_slot, :nickname, :participation_id, :participation_revision)""",
        ({**player, "event_id": event_id} for player in candidate["players"]),
    )
    award = _stored(conn, event_id)
    assert award is not None
    return {
        "championship": {**award, "needs_review": False},
        "duplicate": False,
        "blocked_reason": None,
    }
