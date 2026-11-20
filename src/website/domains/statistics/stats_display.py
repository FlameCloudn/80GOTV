"""Small display helpers that distinguish an unknown statistic from a real zero."""

import math


def optional_number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def format_stat(value, digits=0, *, suffix="", signed=False, missing="-"):
    number = optional_number(value)
    if number is None:
        return missing
    return f"{number:{'+' if signed else ''}.{digits}f}{suffix}"


def resolve_match_team_side(stat, match):
    """Use the saved match side first, then historical team IDs; never today's roster."""
    stat, match = dict(stat or {}), dict(match or {})
    side = str(stat.get("match_team_side") or "").strip().lower()
    if side in {"t1", "t2"}:
        return side

    def identifier(value):
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    team_id = identifier(stat.get("team_id"))
    if team_id in {-1, -2}:
        return "t1" if team_id == -1 else "t2"
    if team_id is None or team_id <= 0:
        return None
    on_team1 = team_id == identifier(match.get("team1_id"))
    on_team2 = team_id == identifier(match.get("team2_id"))
    return ("t1" if on_team1 else "t2") if on_team1 != on_team2 else None
