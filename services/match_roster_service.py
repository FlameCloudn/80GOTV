"""Resolve fixed player slots only from admin selections or event registration."""

import json
from collections import Counter, defaultdict

from utils.helpers import row_get

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
    return values[:5] if isinstance(values, list) else []


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
    name = str(row_get(match, f"team{side}_name") or "").strip()
    team_id = _player_id(row_get(match, f"team{side}_id"))
    if team_id:
        team = conn.execute("SELECT name FROM teams WHERE id=?", (team_id,)).fetchone()
        if team:
            name = str(team["name"] or "").strip()
    registrations = conn.execute(
        "SELECT id,team_name,team_logo,creator_user_id FROM event_registrations WHERE event_id=?",
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


def match_player_slots(conn, match, side):
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
