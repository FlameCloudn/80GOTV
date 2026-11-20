"""Resolve directory teams and explicitly chosen players on the historical form."""

import json
from typing import NamedTuple

from src.website.domains.matches.admin_queries import (
    _duplicate_match,
    _match_roster_options,
    _match_roster_selected,
)
from src.website.domains.matches.setup import MatchSideInput
from src.website.runtime.database import row_get


class LegacySide(NamedTuple):
    team_id: int | str | None = None
    players: str | None = None


LegacySides = tuple[LegacySide, LegacySide]


def select_side(conn, side: int, choice: MatchSideInput, *, is_test=False):
    prefix = f"side{side}"
    if choice.kind == "players":
        player_ids = [player_id for player_id in choice.players if player_id]
        if not player_ids and is_test:
            return LegacySide(), None
        if not is_test and len(player_ids) != 5:
            return LegacySide(), f"{prefix} 请选择 5 名选手"
        if len(set(player_ids)) != len(player_ids):
            return LegacySide(), f"{prefix} 不能重复选择同一名选手"
        placeholders = ",".join("?" * len(player_ids))
        count = conn.execute(
            f"SELECT COUNT(*) FROM players WHERE id IN ({placeholders})", player_ids
        ).fetchone()[0]
        if count != len(player_ids):
            return LegacySide(), f"{prefix} 包含不存在的选手"
        selected = [player_id or None for player_id in choice.players]
        while selected and selected[-1] is None:
            selected.pop()
        return LegacySide(players=json.dumps(selected)), None
    if choice.kind != "team":
        return LegacySide(), f"{prefix} 的参赛方类型无效"
    team_id = choice.choice
    if not team_id and is_test:
        return LegacySide(), None
    if not team_id:
        return LegacySide(), f"{prefix} 请选择队伍"
    if (
        not team_id.isdigit()
        or not conn.execute("SELECT id FROM teams WHERE id=?", (team_id,)).fetchone()
    ):
        return LegacySide(), f"{prefix} 所选队伍不存在"
    return LegacySide(team_id), None


def _roster_for_side(conn, match, side, roster, *, team_id=None):
    """Validate a submitted roster against that team's allowed players."""
    if roster is None:
        return None, None
    values = [value for value in roster if value]
    if len(values) != 5:
        return None, f"队伍{side} 必须选择 5 名本场选手"
    if len(set(values)) != 5:
        return None, f"队伍{side} 不能重复选择同一名选手"
    roster_match = match
    if team_id is not None and str(team_id) != str(row_get(match, f"team{side}_id")):
        roster_match = dict(match)
        roster_match[f"team{side}_id"] = team_id
        roster_match[f"team{side}_players"] = None
        roster_match[f"team{side}_registration_id"] = None
        roster_match["roster_snapshot"] = None
        other_side = 2 if side == 1 else 1
        if str(team_id) == str(row_get(match, f"team{other_side}_id")):
            roster_match[f"team{side}_players"] = json.dumps(
                _match_roster_selected(conn, match, other_side)
            )
            roster_match[f"team{side}_registration_id"] = row_get(
                match, f"team{other_side}_registration_id"
            )
    options = {
        str(option["id"]): option for option in _match_roster_options(conn, roster_match, side)
    }
    if any(value not in options for value in values):
        return None, f"队伍{side} 只能选择本队选手或已报名替补"
    if any(not options[value]["has_steam_id"] for value in values):
        return None, f"队伍{side} 有选手未绑定 Steam ID，不能锁定本场名单"
    return json.dumps([int(value) for value in values]), None


def _unchanged(conn, match, side, roster):
    if roster is None:
        return True
    previous = [
        str(player_id) if player_id is not None else ""
        for player_id in _match_roster_selected(conn, match, side)
    ]
    previous.extend([""] * (5 - len(previous)))
    return roster == tuple(previous)


def sides_for_create(conn, choices, *, is_test):
    home, error = select_side(conn, 1, choices[0], is_test=is_test)
    if error:
        return (home, LegacySide()), error
    away, error = select_side(conn, 2, choices[1], is_test=is_test)
    return (home, away), error


def sides_for_edit(conn, match, choices):
    home = LegacySide(match["team1_id"], match["team1_players"])
    away = LegacySide(match["team2_id"], match["team2_players"])
    if (match["status"] or "upcoming") != "upcoming":
        return (home, away), None

    selected = [home, away]
    changing_sides = choices[0].provided
    if changing_sides:
        for side, choice in enumerate(choices, start=1):
            if not choice.provided:
                continue
            selected[side - 1], error = select_side(
                conn, side, choice, is_test=bool(match["is_test_mode"])
            )
            if error:
                return (selected[0], selected[1]), error

    for side, choice in enumerate(choices, start=1):
        team_id, players = selected[side - 1]
        if changing_sides:
            if not choice.provided or choice.kind != "team":
                continue
            previous = (home, away)[side - 1]
            if team_id and previous.team_id and str(team_id) == str(previous.team_id):
                if _unchanged(conn, match, side, choice.roster):
                    selected[side - 1] = LegacySide(team_id, previous.players)
                    continue
            if not team_id or choice.roster is None:
                selected[side - 1] = LegacySide(team_id)
                continue
        roster, error = _roster_for_side(
            conn, match, side, choice.roster, team_id=team_id if changing_sides else None
        )
        if error:
            return (selected[0], selected[1]), error
        if roster is not None:
            selected[side - 1] = LegacySide(team_id, roster)
    return (selected[0], selected[1]), None


def sides_conflict(conn, values, sides: LegacySides, *, exclude_id=None):
    home, away = sides
    if home.team_id and away.team_id and home.team_id == away.team_id:
        return "same_team"
    if home.players and away.players:
        if {pid for pid in json.loads(home.players) if pid is not None} & {
            pid for pid in json.loads(away.players) if pid is not None
        }:
            return "shared_player"
    if _duplicate_match(
        conn, values, home.team_id, away.team_id, home.players, away.players, exclude_id
    ):
        return "duplicate"
    return None
