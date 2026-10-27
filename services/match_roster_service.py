"""Resolve fixed player slots only from admin selections or event registration."""

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone

from utils.helpers import row_get, team_abbr

PLAYER_FIELDS = "id,nickname,group_username_override,steam_id,avatar,is_bashizhong_student,team_id"


def _player_id(value):
    text = str(value or "")
    return (
        int(text)
        if not isinstance(value, bool) and text.isascii() and text.isdigit() and int(text) > 0
        else None
    )


def _selected_ids(match, side):
    raw = row_get(match, f"team{side}_players")
    if raw is None or raw == "":
        return None
    try:
        values = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return []
    return values if isinstance(values, list) and len(values) <= 5 else []


def _players_by_id(conn, ids):
    ids = list(dict.fromkeys(player_id for value in ids if (player_id := _player_id(value))))
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    return {
        row["id"]: dict(row)
        for row in conn.execute(
            f"SELECT {PLAYER_FIELDS} FROM players WHERE id IN ({placeholders})", ids
        )
    }


def match_registration(conn, match, side):
    event_id = row_get(match, "event_id")
    if not event_id:
        return None
    registration_id = _player_id(row_get(match, f"team{side}_registration_id"))
    if registration_id:
        row = conn.execute(
            """SELECT id,team_name,team_logo,creator_user_id FROM event_registrations
               WHERE id=? AND event_id=? AND status='pending'""",
            (registration_id, event_id),
        ).fetchone()
        return dict(row) if row else None
    name = str(row_get(match, f"team{side}_name") or "").strip()
    team_id = _player_id(row_get(match, f"team{side}_id"))
    if team_id:
        team = conn.execute("SELECT name FROM teams WHERE id=?", (team_id,)).fetchone()
        if team:
            name = str(team["name"] or "").strip()
    registrations = conn.execute(
        """SELECT id,team_name,team_logo,creator_user_id FROM event_registrations
           WHERE event_id=? AND status='pending'""",
        (event_id,),
    ).fetchall()
    named = [
        row
        for row in registrations
        if name and str(row["team_name"] or "").strip().casefold() == name.casefold()
    ]
    if len(named) == 1:
        return dict(named[0])
    if named:
        return None
    selected = _selected_ids(match, side)
    if not selected:
        return None
    players = _players_by_id(conn, selected)
    steam_ids = [
        str(players.get(_player_id(value), {}).get("steam_id") or "").strip() for value in selected
    ]
    if len(steam_ids) < 2 or not all(steam_ids) or len(set(steam_ids)) != len(steam_ids):
        return None
    candidates = []
    for registration in registrations:
        registered_ids = [
            str(row["steam_id"] or "").strip()
            for row in conn.execute(
                """SELECT COALESCE(NULLIF(s.steam_id,''),u.steam_id64) AS steam_id
                   FROM event_registration_slots s LEFT JOIN users u ON u.id=s.user_id
                   WHERE s.registration_id=? ORDER BY s.slot_index""",
                (registration["id"],),
            )
        ]
        if len(registered_ids) == len(steam_ids) and set(registered_ids) == set(steam_ids):
            candidates.append(registration)
    return dict(candidates[0]) if len(candidates) == 1 else None


def frozen_match_teams(match):
    raw = row_get(match, "roster_snapshot")
    if not raw:
        return None
    try:
        snapshot = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return None
    if not isinstance(snapshot, dict) or snapshot.get("version") != 1:
        return None
    teams = snapshot.get("teams")
    if not isinstance(teams, dict):
        return None
    for side in (1, 2):
        team = teams.get(str(side))
        if not isinstance(team, dict) or not isinstance(team.get("players"), list):
            return None
        if "team_id" in team and _player_id(team["team_id"]) != _player_id(
            row_get(match, f"team{side}_id")
        ):
            return None
    return teams


def _historical_player_slots(conn, match, side):
    rows = conn.execute(
        """SELECT player_id,team_id,LOWER(TRIM(match_team_side)) AS match_side
           FROM match_stats WHERE match_id=? AND player_id IS NOT NULL
             AND COALESCE(data_status,'final')='final' ORDER BY id""",
        (row_get(match, "id"),),
    ).fetchall()
    if not rows:
        return None
    sides = defaultdict(set)
    for row in rows:
        recorded = {"t1": 1, "t2": 2}.get(row["match_side"])
        if recorded:
            sides[row["player_id"]].add(recorded)
    player_ids = [player_id for player_id, values in sides.items() if values == {side}]
    profiles = _players_by_id(conn, player_ids)
    return [
        {**profiles[player_id], "slot": index + 1, "roster_source": "history"}
        for index, player_id in enumerate(player_ids)
        if player_id in profiles
    ]


def match_player_slots(conn, match, side):
    frozen = frozen_match_teams(match)
    if frozen:
        return [
            {
                **player,
                "slot": player.get("slot") or index + 1,
                "roster_source": player.get("roster_source") or "snapshot",
                "roster_frozen": True,
            }
            for index, player in enumerate(frozen[str(side)]["players"])
            if isinstance(player, dict)
        ]
    if row_get(match, "roster_snapshot"):
        return []
    if str(row_get(match, "status") or "").lower() == "completed":
        # Complete final statistics outrank stale selections, never live or partial evidence.
        historical = {
            number: _historical_player_slots(conn, match, number) or [] for number in (1, 2)
        }
        if (
            all(len(slots) == 5 for slots in historical.values())
            and len({player["id"] for slots in historical.values() for player in slots}) == 10
        ):
            return historical[side]
    selected = _selected_ids(match, side)
    if selected is not None:
        players = _players_by_id(conn, selected)
        counts = Counter(_player_id(value) for value in selected)
        result = []
        for index, value in enumerate(selected):
            player_id = _player_id(value)
            player = players.get(player_id) if counts[player_id] == 1 else None
            result.append(
                {
                    **(player or {}),
                    "id": player["id"] if player else None,
                    "slot": index + 1,
                    "nickname": player["nickname"] if player else "",
                    "steam_id": player["steam_id"] if player else "",
                    "roster_source": "admin",
                }
            )
        return result

    historical = _historical_player_slots(conn, match, side)
    if historical is not None:
        return historical
    return registration_player_slots(conn, match, side)


def registration_player_slots(conn, match, side):
    registration = match_registration(conn, match, side)
    if not registration:
        return []
    slots = conn.execute(
        """SELECT s.*,u.steam_id64 AS account_steam_id,u.avatar AS account_avatar,
                  u.group_username,u.is_bashizhong_student
           FROM event_registration_slots s LEFT JOIN users u ON u.id=s.user_id
           WHERE s.registration_id=? ORDER BY s.slot_index""",
        (registration["id"],),
    ).fetchall()
    steam_ids = list(
        dict.fromkeys(
            str(slot["steam_id"] or slot["account_steam_id"] or "").strip() for slot in slots
        )
    )
    profiles = defaultdict(list)
    if any(steam_ids):
        placeholders = ",".join("?" for _ in steam_ids)
        for player in conn.execute(
            f"SELECT {PLAYER_FIELDS} FROM players WHERE steam_id IN ({placeholders})", steam_ids
        ):
            profiles[str(player["steam_id"])].append(dict(player))
    result = []
    for slot in slots:
        slot_index = slot["slot_index"]
        if not isinstance(slot_index, int) or slot_index not in range(5):
            continue
        steam_id = str(slot["steam_id"] or slot["account_steam_id"] or "").strip()
        found = profiles.get(steam_id, [])
        player = found[0] if steam_id and len(found) == 1 else {}
        identified = bool(steam_id or slot["user_id"] or slot["filled_by_creator"])
        result.append(
            {
                **player,
                "id": player.get("id"),
                "slot": slot_index + 1,
                "nickname": str(slot["player_name"] or player.get("nickname") or "")
                if identified
                else "",
                "steam_id": steam_id,
                "avatar": player.get("avatar") or slot["account_avatar"] or "",
                "group_username_override": player.get("group_username_override")
                or slot["group_username"]
                or "",
                "is_bashizhong_student": player.get(
                    "is_bashizhong_student", slot["is_bashizhong_student"]
                ),
                "roster_source": "registration",
            }
        )
    return result


def resolve_match_roster(conn, match):
    """Share the exact match slots and completeness checks across all consumers."""
    players = {side: match_player_slots(conn, match, side) for side in (1, 2)}
    event_id = row_get(match, "event_id")
    reserve_ids = (
        {
            str(row["steam_id"] or "").strip()
            for row in conn.execute(
                """SELECT steam_id FROM event_individual_registrations
               WHERE event_id=? AND assignment_status='reserve'""",
                (event_id,),
            )
        }
        if event_id
        else set()
    )
    issues = []
    identities = []
    for side, slots in players.items():
        if len(slots) != 5 or sorted(player["slot"] for player in slots) != [1, 2, 3, 4, 5]:
            issues.append(f"team{side}_needs_five_players")
        for player in slots:
            steam_id = str(player.get("steam_id") or "").strip()
            if not player.get("roster_frozen"):
                player["is_substitute"] = bool(
                    steam_id and player["roster_source"] == "admin" and steam_id in reserve_ids
                )
            else:
                player["is_substitute"] = bool(player.get("is_substitute"))
            if not steam_id:
                issues.append(f"team{side}_missing_steam_id")
            identities.append((steam_id, f"t{side}"))
    counts = Counter(steam_id for steam_id, _side in identities if steam_id)
    if any(count > 1 for count in counts.values()):
        issues.append("duplicate_steam_id")
    return {
        "players": players,
        "issues": issues,
        "locked": not issues,
        "steam_ids": [steam_id for steam_id, _side in identities],
        "side_by_steam_id": {
            steam_id: side for steam_id, side in identities if steam_id and counts[steam_id] == 1
        },
    }


def _bind_match_registrations(conn, match):
    match = dict(match)
    if frozen_match_teams(match):
        return match
    for side in (1, 2):
        field = f"team{side}_registration_id"
        if row_get(match, field):
            continue
        registration = match_registration(conn, match, side)
        if registration:
            conn.execute(
                f"UPDATE matches SET {field}=? WHERE id=? AND {field} IS NULL",
                (registration["id"], match["id"]),
            )
            match[field] = registration["id"]
    return match


def freeze_match_roster(conn, match, force=False, confirmed=False):
    """Persist match identity in the caller's transaction, never from a read request."""
    match = dict(match)
    if frozen_match_teams(match) and not force:
        snapshot = json.loads(match["roster_snapshot"])
        if confirmed and snapshot.get("evidence") != "confirmed_match":
            snapshot["evidence"] = "confirmed_match"
            snapshot["confirmed_at"] = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE matches SET roster_snapshot=? WHERE id=?",
                (json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")), match["id"]),
            )
            return True
        return False
    if force:
        match["roster_snapshot"] = None
    match = _bind_match_registrations(conn, match)
    roster = resolve_match_roster(conn, match)
    teams = {}
    for side in (1, 2):
        team_id = _player_id(row_get(match, f"team{side}_id"))
        team = (
            conn.execute("SELECT * FROM teams WHERE id=?", (team_id,)).fetchone()
            if team_id
            else None
        )
        registration = match_registration(conn, match, side)
        slots = roster["players"][side]
        identified = [player for player in slots if player.get("id") or player.get("steam_id")]
        name = (
            (registration["team_name"] if registration else None)
            or (team["name"] if team else None)
            or row_get(match, f"team{side}_name")
            or (identified[0].get("nickname") if len(identified) == 1 else None)
            or "TBD"
        )
        teams[str(side)] = {
            "team_id": team_id,
            "registration_id": registration["id"] if registration else None,
            "name": name,
            "short_name": row_get(match, f"t{side}s")
            or (team["short_name"] if team else None)
            or team_abbr(name),
            "logo": (registration["team_logo"] if registration else None)
            or (team["logo"] if team else None)
            or row_get(match, f"t{side}_logo")
            or "",
            "players": slots,
        }
    snapshot = json.dumps(
        {
            "version": 1,
            "teams": teams,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "evidence": "confirmed_match" if confirmed else "preserved",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    conn.execute("UPDATE matches SET roster_snapshot=? WHERE id=?", (snapshot, match["id"]))
    return True


def _preserve_matching_rosters(conn, condition, arguments, registration_id=None):
    conn.execute("UPDATE matches SET status=status WHERE 0")
    matches = conn.execute("SELECT * FROM matches WHERE " + condition, arguments).fetchall()
    for row in matches:
        if registration_id is not None and not any(
            registration and registration["id"] == registration_id
            for registration in (match_registration(conn, row, side) for side in (1, 2))
        ):
            continue
        match = _bind_match_registrations(conn, row)
        started = str(match.get("status") or "").lower() in {"live", "ongoing", "completed"}
        formal = conn.execute(
            """SELECT 1 FROM match_stats WHERE match_id=?
               AND COALESCE(data_status,'final')='final' LIMIT 1""",
            (match["id"],),
        ).fetchone()
        if (
            match.get("status") == "completed"
            or formal
            or ((started or match.get("bp_state")) and resolve_match_roster(conn, match)["locked"])
        ):
            freeze_match_roster(conn, match)


def preserve_event_rosters(conn, event_id, registration_id=None):
    _preserve_matching_rosters(conn, "event_id=?", (event_id,), registration_id)


def preserve_team_rosters(conn, team_id):
    _preserve_matching_rosters(conn, "team1_id=? OR team2_id=?", (team_id, team_id))


def match_snapshot_uses_logo(conn, filename):
    from services.team_logo_service import logo_relative_path

    wanted = logo_relative_path(filename)
    if not wanted:
        return False
    for row in conn.execute(
        "SELECT roster_snapshot FROM matches WHERE roster_snapshot IS NOT NULL"
    ):
        try:
            snapshot = json.loads(row["roster_snapshot"])
        except (TypeError, ValueError):
            continue
        teams = snapshot.get("teams") if isinstance(snapshot, dict) else None
        if isinstance(teams, dict) and any(
            isinstance(team, dict) and logo_relative_path(team.get("logo")) == wanted
            for team in teams.values()
        ):
            return True
    return False
