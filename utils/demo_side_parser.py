"""Derive side details from actual round participants and CSDA events."""

from collections import defaultdict

from utils.side_stats import SIDE_COUNTS
from utils.stats_calc import calculate_rating, estimate_hltv2_impact, non_negative_impact


def parse_side_stats(data):
    from utils.demo_parser import (
        _build_round_rosters,
        _empty_event_stats,
        _event_int,
        _kill_is_in_round_window,
        _reconstruct_clutch_stats,
        _steam_id,
        _winner_team_letter,
    )

    players = data.get("players")
    kills = data.get("kills")
    rounds = data.get("rounds")
    if not isinstance(players, dict) or not isinstance(kills, list) or not isinstance(rounds, list):
        return {}
    teams = {
        _steam_id(sid): (p.get("team") or {}).get("letter")
        for sid, p in players.items()
        if isinstance(p, dict)
    }
    round_map = {
        _event_int(r, "number", i): r for i, r in enumerate(rounds, 1) if isinstance(r, dict)
    }

    def scored_event(event, round_data):
        # CSDA scores post-round combat until the official round transition.
        window = {
            **round_data,
            "endTick": round_data.get("endOfficiallyTick") or round_data.get("endTick"),
        }
        return _kill_is_in_round_window(event, window)

    grouped = defaultdict(list)
    seen = set()
    for index, kill in enumerate(kills):
        if not isinstance(kill, dict):
            continue
        number = _event_int(kill, "roundNumber")
        if number not in round_map or not scored_event(kill, round_map[number]):
            continue
        identity = (
            _event_int(kill, "tick", index),
            _steam_id(kill.get("killerSteamId")),
            _steam_id(kill.get("victimSteamId")),
            _event_int(kill, "frame"),
        )
        if identity in seen:
            continue
        seen.add(identity)
        grouped[number].append((_event_int(kill, "tick", index), index, kill))
    rosters = _build_round_rosters(data, rounds, teams, grouped)
    records = {sid: {} for sid in teams}
    penalties = defaultdict(lambda: defaultdict(int))
    present = {}
    for number, round_data in round_map.items():
        roster = rosters.get(number, {})
        present[number] = {}
        for letter in ("A", "B"):
            side = _event_int(round_data, "teamASide" if letter == "A" else "teamBSide")
            if side not in (2, 3):
                continue
            label = "t" if side == 2 else "ct"
            for sid in roster.get(letter, set()):
                if sid not in records:
                    continue
                present[number][sid] = label
                item = records[sid].setdefault(
                    label,
                    {
                        **dict.fromkeys(SIDE_COUNTS, 0),
                        "rounds": 0,
                        "damage": 0,
                        "kast_rounds": 0,
                        "rws_points": 0.0,
                    },
                )
                item["rounds"] += 1

    def event_player(event, prefix):
        sid = _steam_id(event.get(prefix + "SteamId", event.get(prefix + "SteamId64")))
        side = _event_int(event, prefix + "Side")
        label = "t" if side == 2 else "ct" if side == 3 else ""
        number = _event_int(event, "roundNumber")
        if present.get(number, {}).get(sid) != label:
            return sid, side, None
        return sid, side, records[sid][label]

    for number in round_map:
        events = grouped.get(number, [])
        died, contributed = set(), set()
        opening = False
        for _, _, kill in sorted(events):
            killer, killer_side, k = event_player(kill, "killer")
            victim, victim_side, v = event_player(kill, "victim")
            assister, assister_side, a = event_player(kill, "assister")
            if v is not None and not kill.get("isVictimControllingBot"):
                disconnect = (
                    killer == victim and str(kill.get("weaponName") or "").casefold() == "world"
                )
                if not disconnect:
                    v["deaths"] += 1
                    died.add(victim)
                if kill.get("isTradeDeath"):
                    v["trade_deaths"] += 1
                    contributed.add(victim)
            enemy = (
                killer_side in (2, 3)
                and victim_side in (2, 3)
                and killer_side != victim_side
                and killer != victim
            )
            if (
                a is not None
                and assister_side != victim_side
                and not kill.get("isAssisterControllingBot")
            ):
                a["assists"] += 1
                a["flash_assists"] += int(bool(kill.get("isAssistedFlash")))
                contributed.add(assister)
            if not enemy:
                if (
                    k is not None
                    and killer_side == victim_side
                    and not kill.get("isKillerControllingBot")
                ):
                    penalties[killer]["t" if killer_side == 2 else "ct"] += 1
                continue
            if k is not None and not kill.get("isKillerControllingBot"):
                k["kills"] += 1
                k["headshot_kills"] += int(bool(kill.get("isHeadshot")))
                contributed.add(killer)
                if not opening:
                    k["first_kills"] += 1
            if not opening:
                if v is not None:
                    v["first_deaths"] += 1
                opening = True
        for sid, label in present.get(number, {}).items():
            if sid not in died or sid in contributed:
                records[sid][label]["kast_rounds"] += 1

    for raw_sid, player in players.items():
        sid = _steam_id(raw_sid)
        sides = records.get(sid, {})
        total = sum(item["kills"] for item in sides.values())
        deductions = sum(penalties[sid].values())
        recorded = player.get("killCount") if isinstance(player, dict) else None
        if recorded == total - deductions and deductions:
            for label, count in penalties[sid].items():
                sides[label]["kills"] -= count

    _reconstruct_clutch_stats(data, teams, {sid: _empty_event_stats() for sid in teams}, records)
    damage_events = data.get("damages")
    winning_damage = defaultdict(lambda: defaultdict(float))
    if isinstance(damage_events, list):
        for damage in damage_events:
            if not isinstance(damage, dict):
                continue
            number = _event_int(damage, "roundNumber")
            if number not in round_map or not scored_event(damage, round_map[number]):
                continue
            attacker, side, item = event_player(damage, "attacker")
            _, victim_side, _ = event_player(damage, "victim")
            amount = _event_int(damage, "healthDamage")
            if (
                item is None
                or side == victim_side
                or victim_side not in (2, 3)
                or amount <= 0
                or damage.get("isAttackerControllingBot")
            ):
                continue
            item["damage"] += amount
            winner = _winner_team_letter(round_map[number])
            winner_side = (
                _event_int(round_map[number], "teamASide" if winner == "A" else "teamBSide")
                if winner
                else 0
            )
            if side == winner_side:
                winning_damage[number][attacker] += amount
        for number, amounts in winning_damage.items():
            total = sum(amounts.values())
            for sid, amount in amounts.items():
                records[sid][present[number][sid]]["rws_points"] += amount * 100 / total

    flashes = data.get("playersFlashed")
    if isinstance(flashes, list):
        for event in flashes:
            if not isinstance(event, dict):
                continue
            number = _event_int(event, "roundNumber")
            if number not in round_map or not scored_event(event, round_map[number]):
                continue
            _, side, item = event_player(event, "flasher")
            if (
                item is not None
                and _event_int(event, "flashedSide") in (2, 3)
                and _event_int(event, "flashedSide") != side
                and (event.get("duration") or 0) > 0
                and not event.get("isFlasherControllingBot")
            ):
                item["enemies_flashed"] += 1
    for sid, sides in records.items():
        player = players.get(sid, {})
        damage_complete = isinstance(damage_events, list) and (
            player.get("healthDamage") is None
            or sum(item["damage"] for item in sides.values()) == player["healthDamage"]
        )
        for item in sides.values():
            rounds_played = item["rounds"]
            item["maps"] = 1
            item["adr"] = round(item.pop("damage") / rounds_played, 1) if damage_complete else None
            item["rws"] = (
                round(item.pop("rws_points") / rounds_played, 2) if damage_complete else None
            )
            item["kast"] = round(item.pop("kast_rounds") / rounds_played * 100, 1)
            raw_impact = estimate_hltv2_impact(item["kills"], item["assists"], rounds_played)
            item["impact"] = non_negative_impact(raw_impact)
            item["headshot_percentage"] = (
                round(item["headshot_kills"] / item["kills"] * 100, 1) if item["kills"] else 0
            )
            item["rating"] = calculate_rating(
                kills=item["kills"],
                deaths=item["deaths"],
                rounds_played=rounds_played,
                adr=item["adr"],
                kast=item["kast"],
                impact=raw_impact,
            )[0]
            if not isinstance(flashes, list):
                item["enemies_flashed"] = None
    return {
        sid: sides
        for sid, sides in records.items()
        if all(
            players.get(sid, {}).get(raw_key) is None
            or sum(item[key] for item in sides.values()) == players[sid][raw_key]
            for key, raw_key in (
                ("kills", "killCount"),
                ("deaths", "deathCount"),
                ("assists", "assistCount"),
            )
        )
    }
