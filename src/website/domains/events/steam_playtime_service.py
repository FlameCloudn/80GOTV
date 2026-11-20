"""Fetch cached CS2 playtime and build balanced individual-registration teams."""

import json
import secrets
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from statistics import median
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import Config

CS2_APP_ID = 730
STEAM_OWNED_GAMES_URL = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/"
PUBLIC_CACHE_AGE = timedelta(days=7)
ERROR_CACHE_AGE = timedelta(minutes=15)
MAX_RESPONSE_BYTES = 512 * 1024


def _checked_at_age(value, now):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        checked_at = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone.utc)
    return now - checked_at.astimezone(timezone.utc)


def _cache_is_fresh(row, now):
    age = _checked_at_age(row.get("playtime_checked_at"), now)
    if age is None or age < timedelta(0):
        return False
    status = str(row.get("playtime_status") or "unknown")
    if status in ("public", "private"):
        return age < PUBLIC_CACHE_AGE
    if status == "unavailable":
        return age < ERROR_CACHE_AGE
    return False


def fetch_cs2_playtime_minutes(steam_id64, api_key=None, timeout=4):
    """Return a status and CS2 playtime for one public Steam account."""
    steam_id64 = str(steam_id64 or "").strip()
    key = str(api_key if api_key is not None else Config.STEAM_WEB_API_KEY).strip()
    if not key:
        return {"status": "not_configured", "minutes": None}
    if not steam_id64.isdigit() or len(steam_id64) != 17:
        return {"status": "invalid", "minutes": None}

    query = urlencode(
        {
            "key": key,
            "steamid": steam_id64,
            "format": "json",
            "include_appinfo": 0,
            "include_played_free_games": 1,
            "appids_filter[0]": CS2_APP_ID,
        }
    )
    request = Request(
        f"{STEAM_OWNED_GAMES_URL}?{query}",
        headers={"User-Agent": "80GOTV/1.0"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
        if len(payload) > MAX_RESPONSE_BYTES:
            raise ValueError("Steam response is too large")
        body = json.loads(payload.decode("utf-8"))
    except Exception:
        return {"status": "unavailable", "minutes": None}

    result = body.get("response") if isinstance(body, dict) else None
    if not isinstance(result, dict) or not result:
        return {"status": "private", "minutes": None}

    for game in result.get("games") or []:
        if int(game.get("appid") or 0) == CS2_APP_ID:
            return {
                "status": "public",
                "minutes": max(0, int(game.get("playtime_forever") or 0)),
            }
    return {"status": "public", "minutes": 0}


def _refresh_playtime_rows(
    conn,
    source_rows,
    *,
    table,
    steam_id_field,
    api_key=None,
    now=None,
    force=False,
):
    """Refresh one trusted playtime cache table without blocking on a slow profile."""
    allowed_targets = {
        ("players", "steam_id"),
        ("event_individual_registrations", "steam_id"),
    }
    if (table, steam_id_field) not in allowed_targets:
        raise ValueError("Unsupported playtime cache target")

    rows = [dict(row) for row in source_rows]
    key = str(api_key if api_key is not None else Config.STEAM_WEB_API_KEY).strip()
    if not key:
        return {"configured": False, "refreshed": 0, "unavailable": len(rows)}

    checked_now = now or datetime.now(timezone.utc)
    stale_rows = rows if force else [row for row in rows if not _cache_is_fresh(row, checked_now)]
    if not stale_rows:
        unavailable = sum(row.get("cs2_playtime_minutes") is None for row in rows)
        return {"configured": True, "refreshed": 0, "unavailable": unavailable}

    results = {}
    steam_ids = sorted({str(row.get(steam_id_field) or "").strip() for row in stale_rows})
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(steam_ids)))) as executor:
        futures = {
            executor.submit(fetch_cs2_playtime_minutes, steam_id, key): steam_id
            for steam_id in steam_ids
        }
        for future in as_completed(futures):
            steam_id = futures[future]
            try:
                results[steam_id] = future.result()
            except Exception:
                results[steam_id] = {"status": "unavailable", "minutes": None}

    checked_at = checked_now.astimezone(timezone.utc).isoformat(timespec="seconds")
    for row in stale_rows:
        result = results.get(
            str(row.get(steam_id_field) or "").strip(),
            {"status": "unavailable", "minutes": None},
        )
        conn.execute(
            f"""
            UPDATE {table}
            SET cs2_playtime_minutes=?, playtime_status=?, playtime_checked_at=?
            WHERE id=?
            """,
            (result.get("minutes"), result.get("status"), checked_at, row["id"]),
        )

    unavailable = sum(result.get("minutes") is None for result in results.values())
    return {
        "configured": True,
        "refreshed": len(stale_rows),
        "unavailable": unavailable,
    }


def refresh_registration_playtimes(conn, registrations, api_key=None, now=None, force=False):
    """Refresh individual-registration playtime cache rows."""
    return _refresh_playtime_rows(
        conn,
        registrations,
        table="event_individual_registrations",
        steam_id_field="steam_id",
        api_key=api_key,
        now=now,
        force=force,
    )


def refresh_player_playtimes(conn, players, api_key=None, now=None, force=False):
    """Refresh the canonical playtime cache for website players."""
    return _refresh_playtime_rows(
        conn,
        players,
        table="players",
        steam_id_field="steam_id",
        api_key=api_key,
        now=now,
        force=force,
    )


def attach_latest_playtime(conn, rows, steam_id_field):
    """Attach player cache first, then fall back to registration cache."""
    items = [dict(row) for row in rows]
    steam_ids = sorted(
        {
            str(item.get(steam_id_field) or "").strip()
            for item in items
            if str(item.get(steam_id_field) or "").strip()
        }
    )
    latest_by_steam_id = {}
    for item in items:
        steam_id = str(item.get(steam_id_field) or "").strip()
        direct_cache = {
            "cs2_playtime_minutes": item.get("cs2_playtime_minutes"),
            "playtime_status": item.get("playtime_status") or "unknown",
            "playtime_checked_at": item.get("playtime_checked_at"),
        }
        if steam_id and (
            direct_cache["cs2_playtime_minutes"] is not None
            or direct_cache["playtime_checked_at"]
            or direct_cache["playtime_status"] != "unknown"
        ):
            latest_by_steam_id[steam_id] = direct_cache

    if steam_ids:
        placeholders = ",".join("?" for _ in steam_ids)
        player_rows = conn.execute(
            f"""
            SELECT steam_id, cs2_playtime_minutes, playtime_status,
                   playtime_checked_at
            FROM players
            WHERE steam_id IN ({placeholders})
            ORDER BY CASE WHEN playtime_checked_at IS NULL THEN 1 ELSE 0 END,
                     playtime_checked_at DESC, id DESC
            """,
            tuple(steam_ids),
        ).fetchall()
        for cached in player_rows:
            candidate = dict(cached)
            if (
                candidate.get("cs2_playtime_minutes") is not None
                or candidate.get("playtime_checked_at")
                or (candidate.get("playtime_status") or "unknown") != "unknown"
            ):
                latest_by_steam_id.setdefault(cached["steam_id"], candidate)

        cached_rows = conn.execute(
            f"""
            SELECT steam_id, cs2_playtime_minutes, playtime_status,
                   playtime_checked_at
            FROM event_individual_registrations
            WHERE steam_id IN ({placeholders})
            ORDER BY CASE WHEN playtime_checked_at IS NULL THEN 1 ELSE 0 END,
                     playtime_checked_at DESC, id DESC
            """,
            tuple(steam_ids),
        ).fetchall()
        for cached in cached_rows:
            latest_by_steam_id.setdefault(cached["steam_id"], dict(cached))

    for item in items:
        cached = latest_by_steam_id.get(str(item.get(steam_id_field) or "").strip(), {})
        item["cs2_playtime_minutes"] = cached.get("cs2_playtime_minutes")
        item["playtime_status"] = cached.get("playtime_status") or "unknown"
        item["playtime_checked_at"] = cached.get("playtime_checked_at")
    return items


def build_balanced_assignments(registrations, team_size=5, rng=None):
    """Balance fixed-size teams by total CS2 playtime; keep leftovers as reserves."""
    rows = [dict(row) for row in registrations]
    randomizer = rng or secrets.SystemRandom()
    randomizer.shuffle(rows)

    full_player_count = (len(rows) // team_size) * team_size
    active_rows = rows[:full_player_count]
    reserve_rows = rows[full_player_count:]
    team_count = full_player_count // team_size
    if not team_count:
        return {
            "assignments": {},
            "reserves": [row["id"] for row in reserve_rows],
            "team_totals": [],
            "known_count": 0,
            "unknown_count": len(active_rows),
            "fallback_minutes": 0,
        }

    known_values = [
        max(0, int(row["cs2_playtime_minutes"]))
        for row in active_rows
        if row.get("cs2_playtime_minutes") is not None
    ]
    fallback_minutes = int(median(known_values)) if known_values else 0
    for row in active_rows:
        value = row.get("cs2_playtime_minutes")
        row["_balance_minutes"] = max(0, int(value)) if value is not None else fallback_minutes

    randomizer.shuffle(active_rows)
    active_rows.sort(key=lambda row: row["_balance_minutes"], reverse=True)
    teams = [
        {"number": index + 1, "players": [], "total_minutes": 0} for index in range(team_count)
    ]
    for row in active_rows:
        available = [team for team in teams if len(team["players"]) < team_size]
        best_key = min((team["total_minutes"], len(team["players"])) for team in available)
        candidates = [
            team for team in available if (team["total_minutes"], len(team["players"])) == best_key
        ]
        team = randomizer.choice(candidates)
        team["players"].append(row)
        team["total_minutes"] += row["_balance_minutes"]

    assignments = {row["id"]: team["number"] for team in teams for row in team["players"]}
    return {
        "assignments": assignments,
        "reserves": [row["id"] for row in reserve_rows],
        "team_totals": [team["total_minutes"] for team in teams],
        "known_count": len(known_values),
        "unknown_count": len(active_rows) - len(known_values),
        "fallback_minutes": fallback_minutes,
    }


def build_balanced_roster_plan(
    registrations,
    fixed_teams=None,
    team_size=5,
    rng=None,
    attempts=80,
):
    """Fill partial rosters and create full teams while balancing playtime."""
    rows = [dict(row) for row in registrations]
    fixed = [dict(team) for team in (fixed_teams or [])]
    randomizer = rng or secrets.SystemRandom()

    teams = []
    for team in fixed:
        players = [dict(player) for player in team.get("players") or []]
        if len(players) >= team_size:
            continue
        teams.append(
            {
                "registration_id": team.get("registration_id"),
                "fixed_players": players,
                "needed": team_size - len(players),
            }
        )

    open_slots = sum(team["needed"] for team in teams)
    if len(rows) < open_slots:
        raise ValueError("Not enough individual registrations to fill partial teams")

    remaining_count = len(rows) - open_slots
    new_team_count = remaining_count // team_size
    for _ in range(new_team_count):
        teams.append(
            {
                "registration_id": None,
                "fixed_players": [],
                "needed": team_size,
            }
        )

    if not teams:
        raise ValueError("Not enough individual registrations to form a team")

    active_count = sum(team["needed"] for team in teams)
    active_rows = rows[:active_count]
    reserve_rows = rows[active_count:]
    known_values = [
        max(0, int(item["cs2_playtime_minutes"]))
        for item in (active_rows + [player for team in teams for player in team["fixed_players"]])
        if item.get("cs2_playtime_minutes") is not None
    ]
    fallback_minutes = int(median(known_values)) if known_values else 0

    def balance_minutes(item):
        value = item.get("cs2_playtime_minutes")
        return max(0, int(value)) if value is not None else fallback_minutes

    fixed_totals = [
        sum(balance_minutes(player) for player in team["fixed_players"]) for team in teams
    ]

    def score(candidate_groups):
        totals = [
            fixed_totals[index] + sum(balance_minutes(item) for item in candidate_groups[index])
            for index in range(len(teams))
        ]
        spread = max(totals) - min(totals) if len(totals) > 1 else 0
        average = sum(totals) / len(totals)
        deviation = sum(abs(total - average) for total in totals)
        return (spread, deviation, max(totals)), totals

    def split_rows(order):
        groups = []
        offset = 0
        for team in teams:
            next_offset = offset + team["needed"]
            groups.append(list(order[offset:next_offset]))
            offset = next_offset
        return groups

    def improve(groups):
        current_score, _ = score(groups)
        changed = True
        while changed:
            changed = False
            for left in range(len(groups)):
                for right in range(left + 1, len(groups)):
                    for left_index in range(len(groups[left])):
                        for right_index in range(len(groups[right])):
                            groups[left][left_index], groups[right][right_index] = (
                                groups[right][right_index],
                                groups[left][left_index],
                            )
                            candidate_score, _ = score(groups)
                            if candidate_score < current_score:
                                current_score = candidate_score
                                changed = True
                                break
                            groups[left][left_index], groups[right][right_index] = (
                                groups[right][right_index],
                                groups[left][left_index],
                            )
                        if changed:
                            break
                    if changed:
                        break
                if changed:
                    break
        return groups

    descending = sorted(active_rows, key=balance_minutes, reverse=True)
    greedy_groups = [[] for _ in teams]
    greedy_totals = list(fixed_totals)
    for item in descending:
        available = [
            index for index, team in enumerate(teams) if len(greedy_groups[index]) < team["needed"]
        ]
        minimum = min(greedy_totals[index] for index in available)
        choices = [index for index in available if greedy_totals[index] == minimum]
        selected = randomizer.choice(choices)
        greedy_groups[selected].append(item)
        greedy_totals[selected] += balance_minutes(item)

    best_groups = improve(greedy_groups)
    best_score, best_totals = score(best_groups)
    restart_count = min(max(0, int(attempts)), 200)
    for _ in range(restart_count):
        order = list(active_rows)
        randomizer.shuffle(order)
        candidate_groups = improve(split_rows(order))
        candidate_score, candidate_totals = score(candidate_groups)
        if candidate_score < best_score:
            best_groups = candidate_groups
            best_score = candidate_score
            best_totals = candidate_totals
            if best_score[0] == 0:
                break

    team_plans = []
    assignments = {}
    for index, team in enumerate(teams):
        candidate_ids = [item["id"] for item in best_groups[index]]
        for entry_id in candidate_ids:
            assignments[entry_id] = index
        team_plans.append(
            {
                "registration_id": team["registration_id"],
                "candidate_ids": candidate_ids,
                "fixed_player_count": len(team["fixed_players"]),
                "total_minutes": best_totals[index],
            }
        )

    all_active = active_rows + [player for team in teams for player in team["fixed_players"]]
    return {
        "assignments": assignments,
        "reserves": [row["id"] for row in reserve_rows],
        "teams": team_plans,
        "team_totals": best_totals,
        "known_count": sum(item.get("cs2_playtime_minutes") is not None for item in all_active),
        "unknown_count": sum(item.get("cs2_playtime_minutes") is None for item in all_active),
        "fallback_minutes": fallback_minutes,
    }
