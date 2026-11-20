"""Reconstruct live participants, kills and clutches from recorded Demo rounds."""

from collections import defaultdict


def _extract_halftime_scores(match_data):
    """从 rounds 数据统计半场比分（teamA 视角）"""
    rounds = match_data.get("rounds", [])
    if not isinstance(rounds, list):
        rounds = []

    h1_a, h1_b = 0, 0
    h2_a, h2_b = 0, 0
    first_a_side = None
    second_half = False

    for r in rounds:
        if not isinstance(r, dict) or _event_int(r, "overtimeNumber") > 0:
            continue
        winner_side = _event_int(r, "winnerSide")
        team_a_side = _event_int(r, "teamASide")
        if winner_side not in (2, 3) or team_a_side not in (2, 3):
            continue
        if first_a_side is None and team_a_side:
            first_a_side = team_a_side
        elif first_a_side and team_a_side and team_a_side != first_a_side:
            second_half = True

        if not second_half:
            if winner_side == team_a_side:
                h1_a += 1
            else:
                h1_b += 1
        else:
            if winner_side == team_a_side:
                h2_a += 1
            else:
                h2_b += 1

    return {"h1_a": h1_a, "h1_b": h1_b, "h2_a": h2_a, "h2_b": h2_b}


def _steam_id(value):
    """Normalize Steam IDs from JSON numbers/strings for dictionary lookups."""
    if value in (None, "", 0, "0"):
        return ""
    return str(value).strip()


def _empty_event_stats():
    return {
        "clutches_won": 0,
        "clutch_1v1": 0,
        "clutch_1v2": 0,
        "clutch_1v3": 0,
        "clutch_1v4": 0,
        "clutch_1v5": 0,
        "multi1k": 0,
        "multi2k": 0,
        "multi3k": 0,
        "multi4k": 0,
        "multi5k": 0,
    }


def _winner_team_letter(round_data):
    """Resolve the winner only when the recorded name/side agree.

    A round can finish through elimination, bomb explosion, defuse, or time.
    The finish reason does not change who won, so the winner fields are the
    single outcome source.  Conflicting fields make the round unsafe to use.
    """
    winner_name = str(round_data.get("winnerName", "") or "")
    team_a_name = str(round_data.get("teamAName", "") or "")
    team_b_name = str(round_data.get("teamBName", "") or "")
    name_letter = ""
    if winner_name and winner_name == team_a_name:
        name_letter = "A"
    elif winner_name and winner_name == team_b_name:
        name_letter = "B"

    winner_side = _event_int(round_data, "winnerSide")
    side_letter = ""
    if winner_side and winner_side == _event_int(round_data, "teamASide"):
        side_letter = "A"
    elif winner_side and winner_side == _event_int(round_data, "teamBSide"):
        side_letter = "B"

    if name_letter and side_letter and name_letter != side_letter:
        return ""
    return name_letter or side_letter


def _event_int(event, key, default=0):
    """Read a numeric event field without letting malformed cache data abort parsing."""
    try:
        return int(event.get(key, default) or default)
    except (AttributeError, TypeError, ValueError):
        return default


def _round_team_letter(round_data, side=0, team_name="", fallback=""):
    """Resolve a participant's fixed A/B team for one round."""
    team_name = str(team_name or "")
    if team_name and team_name == str(round_data.get("teamAName", "") or ""):
        return "A"
    if team_name and team_name == str(round_data.get("teamBName", "") or ""):
        return "B"

    team_a_side = _event_int(round_data, "teamASide")
    team_b_side = _event_int(round_data, "teamBSide")
    if side in (2, 3) and team_a_side != team_b_side:
        if side == team_a_side:
            return "A"
        if side == team_b_side:
            return "B"
    return fallback if fallback in ("A", "B") else ""


def _kill_is_in_round_window(kill, round_data):
    """Ignore events assigned to a round after that round has already ended."""
    if not isinstance(round_data, dict):
        return True
    try:
        tick = int(kill.get("tick"))
    except (AttributeError, TypeError, ValueError):
        return True

    start_tick = _event_int(round_data, "startTick")
    end_tick = _event_int(round_data, "endTick")
    return (not start_tick or tick >= start_tick) and (not end_tick or tick <= end_tick)


def _build_round_rosters(match_data, rounds, player_team_map, kills_by_round):
    """Build round rosters from actual per-round CSDA participant records.

    ``players`` describes everybody who appeared in the whole match.  It is
    not a round roster, so it must never fill a missing player after a
    disconnect or substitution.  Economies are preferred; buy records are a
    fallback for old cache payloads.  Kill events can add a demonstrably
    present player only after a per-round source established both teams.
    """
    rounds_by_number = {}
    for index, round_data in enumerate(rounds, start=1):
        if isinstance(round_data, dict):
            rounds_by_number[_event_int(round_data, "number", index)] = round_data

    rosters_by_source = {}
    for field_name, steam_id_field in (
        ("playerEconomies", "steamId"),
        ("playersBuy", "playerSteamId"),
    ):
        reported_rosters = defaultdict(lambda: {"A": set(), "B": set()})
        entries = match_data.get(field_name, [])
        if not isinstance(entries, list):
            rosters_by_source[field_name] = reported_rosters
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            round_number = _event_int(entry, "roundNumber")
            round_data = rounds_by_number.get(round_number)
            sid = _steam_id(entry.get(steam_id_field, ""))
            if not round_data or not sid:
                continue
            letter = _round_team_letter(
                round_data,
                side=_event_int(entry, "playerSide"),
                fallback=player_team_map.get(sid, ""),
            )
            if letter:
                reported_rosters[round_number][letter].add(sid)
        rosters_by_source[field_name] = reported_rosters

    round_rosters = {}
    for round_number, round_data in rounds_by_number.items():
        economy_roster = rosters_by_source["playerEconomies"][round_number]
        buy_roster = rosters_by_source["playersBuy"][round_number]
        source_roster = economy_roster if any(economy_roster.values()) else buy_roster
        roster = {
            "A": set(source_roster["A"]),
            "B": set(source_roster["B"]),
        }

        # Do not build a clutch from only part of a round roster.  This avoids
        # treating a disconnected or substituted player as still alive.
        if not roster["A"] or not roster["B"]:
            round_rosters[round_number] = roster
            continue

        # A player who killed or died in the round is incontrovertibly present,
        # even if an incomplete economy list omitted them.
        for _, _, kill in kills_by_round.get(round_number, []):
            if not _kill_is_in_round_window(kill, round_data):
                continue
            for role in ("killer", "victim"):
                sid = _steam_id(kill.get(f"{role}SteamId", kill.get(f"{role}SteamId64", "")))
                if not sid:
                    continue
                letter = _round_team_letter(
                    round_data,
                    side=_event_int(kill, f"{role}Side"),
                    team_name=kill.get(f"{role}TeamName", ""),
                    fallback=player_team_map.get(sid, ""),
                )
                if letter:
                    roster[letter].add(sid)
        round_rosters[round_number] = roster
    return round_rosters


def _reconstruct_clutch_stats(match_data, player_team_map, result, side_result=None):
    """Reconstruct won clutches from the chronological round kill timeline.

    The analyzer's clutch array is optional and has historically contained
    inconsistent values. A clutch is therefore only credited when the real
    round roster shows the winner's final survivor alone against 1-5 enemies.
    """
    rounds = match_data.get("rounds", [])
    kills = match_data.get("kills", [])
    if not isinstance(rounds, list) or not isinstance(kills, list):
        return

    kills_by_round = defaultdict(list)
    for index, kill in enumerate(kills):
        if not isinstance(kill, dict):
            continue
        round_number = _event_int(kill, "roundNumber")
        if round_number > 0:
            tick = _event_int(kill, "tick", index)
            kills_by_round[round_number].append((tick, index, kill))

    round_rosters = _build_round_rosters(match_data, rounds, player_team_map, kills_by_round)
    for index, round_data in enumerate(rounds, start=1):
        if not isinstance(round_data, dict):
            continue
        round_number = _event_int(round_data, "number", index)
        winner_letter = _winner_team_letter(round_data)
        round_kills = [
            item
            for item in kills_by_round.get(round_number, [])
            if _kill_is_in_round_window(item[2], round_data)
        ]
        roster = round_rosters.get(round_number, {"A": set(), "B": set()})
        if (
            winner_letter not in ("A", "B")
            or not round_kills
            or not roster["A"]
            or not roster["B"]
            or len(roster["A"]) > 5
            or len(roster["B"]) > 5
        ):
            continue

        alive = {letter: set(members) for letter, members in roster.items()}
        member_team_map = {sid: letter for letter, members in roster.items() for sid in members}
        clutch_candidate = None
        invalid_timeline = False
        unique_events = []
        seen_events = set()
        for tick, event_index, kill in sorted(round_kills, key=lambda item: (item[0], item[1])):
            killer_sid = _steam_id(kill.get("killerSteamId", kill.get("killerSteamId64", "")))
            victim_sid = _steam_id(kill.get("victimSteamId", kill.get("victimSteamId64", "")))
            # A repeated death event cannot be a second real kill.  Keep the
            # first chronological copy and ignore cache duplicates.
            event_key = (
                tick,
                _event_int(kill, "frame"),
                killer_sid,
                victim_sid,
                _event_int(kill, "killerSide"),
                _event_int(kill, "victimSide"),
                str(kill.get("killerTeamName", "") or ""),
                str(kill.get("victimTeamName", "") or ""),
            )
            if event_key in seen_events:
                continue
            seen_events.add(event_key)
            unique_events.append((tick, event_index, kill, killer_sid, victim_sid))

        cursor = 0
        while cursor < len(unique_events) and not invalid_timeline:
            tick = unique_events[cursor][0]
            tick_events = []
            while cursor < len(unique_events) and unique_events[cursor][0] == tick:
                tick_events.append(unique_events[cursor])
                cursor += 1

            prior_winner_count = len(alive[winner_letter])
            deaths = []
            seen_victims = set()
            for _, _, kill, killer_sid, victim_sid in tick_events:
                victim_letter = member_team_map.get(victim_sid) or _round_team_letter(
                    round_data,
                    side=_event_int(kill, "victimSide"),
                    team_name=kill.get("victimTeamName", ""),
                    fallback=player_team_map.get(victim_sid, ""),
                )
                killer_letter = member_team_map.get(killer_sid) or _round_team_letter(
                    round_data,
                    side=_event_int(kill, "killerSide"),
                    team_name=kill.get("killerTeamName", ""),
                    fallback=player_team_map.get(killer_sid, ""),
                )

                # A dead player cannot score a later kill.  Simultaneous
                # trades are handled together, so this only rejects events
                # from an earlier tick that contradict the known timeline.
                if killer_sid and killer_letter in alive and killer_sid not in alive[killer_letter]:
                    invalid_timeline = True
                    break
                if (
                    not victim_sid
                    or victim_sid in seen_victims
                    or victim_letter not in alive
                    or victim_sid not in alive[victim_letter]
                ):
                    continue
                seen_victims.add(victim_sid)
                deaths.append((victim_letter, victim_sid))

            for victim_letter, victim_sid in deaths:
                alive[victim_letter].remove(victim_sid)

            # A clutch begins when the eventual winning side is reduced from
            # at least two actual players to one.  Starting a round 1vN after
            # a disconnect is deliberately not counted as a clutch.
            if (
                clutch_candidate is None
                and prior_winner_count > 1
                and len(alive[winner_letter]) == 1
            ):
                opponent_letter = "B" if winner_letter == "A" else "A"
                opponent_count = len(alive[opponent_letter])
                if 1 <= opponent_count <= 5:
                    clutch_candidate = (
                        next(iter(alive[winner_letter])),
                        opponent_count,
                    )

        if not invalid_timeline and clutch_candidate:
            sid, opponent_count = clutch_candidate
            if sid in result and sid in alive[winner_letter]:
                result[sid]["clutches_won"] += 1
                result[sid][f"clutch_1v{opponent_count}"] += 1
                side = _event_int(round_data, "teamASide" if winner_letter == "A" else "teamBSide")
                label = "t" if side == 2 else "ct" if side == 3 else ""
                if side_result is not None and label in side_result.get(sid, {}):
                    side_result[sid][label]["clutches_won"] += 1
                    side_result[sid][label][f"clutch_1v{opponent_count}"] += 1


def calculate_event_player_stats(match_data):
    """Count real multi-kills and won clutches from chronological demo events."""
    players_data = match_data.get("players", {}) or {}
    if not isinstance(players_data, dict):
        return {}

    player_team_map = {}
    result = {}
    for raw_sid, player in players_data.items():
        sid = _steam_id(raw_sid)
        if not sid or not isinstance(player, dict):
            continue
        player_team_map[sid] = str((player.get("team") or {}).get("letter", "") or "")
        result[sid] = _empty_event_stats()

    round_data_by_number = {}
    rounds = match_data.get("rounds", [])
    if isinstance(rounds, list):
        for index, round_data in enumerate(rounds, start=1):
            if isinstance(round_data, dict):
                round_data_by_number[_event_int(round_data, "number", index)] = round_data

    round_kills = defaultdict(lambda: defaultdict(int))
    kills = match_data.get("kills", [])
    if isinstance(kills, list):
        for kill in kills:
            if not isinstance(kill, dict):
                continue
            killer_sid = _steam_id(kill.get("killerSteamId", kill.get("killerSteamId64", "")))
            victim_sid = _steam_id(kill.get("victimSteamId", kill.get("victimSteamId64", "")))
            round_number = _event_int(kill, "roundNumber")
            if not killer_sid or not victim_sid or killer_sid == victim_sid or round_number <= 0:
                continue
            if not _kill_is_in_round_window(kill, round_data_by_number.get(round_number)):
                continue

            killer_side = _event_int(kill, "killerSide")
            victim_side = _event_int(kill, "victimSide")
            letters_differ = (
                player_team_map.get(killer_sid)
                and player_team_map.get(victim_sid)
                and player_team_map[killer_sid] != player_team_map[victim_sid]
            )
            if killer_side in (2, 3) and victim_side in (2, 3):
                is_enemy_kill = killer_side != victim_side
            else:
                is_enemy_kill = letters_differ
            if is_enemy_kill and killer_sid in result:
                round_kills[killer_sid][round_number] += 1

    for sid, per_round in round_kills.items():
        for kill_count in per_round.values():
            bucket = min(max(int(kill_count), 1), 5)
            result[sid][f"multi{bucket}k"] += 1

    # Raw ``clutches`` counters are deliberately ignored.  They are not a
    # chronological round record and have already disagreed with this cache.
    _reconstruct_clutch_stats(match_data, player_team_map, result)
    return result
