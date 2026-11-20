"""Inputs and shared limits for changing a match's pregame settings."""

from dataclasses import dataclass
from typing import Any

from src.website.runtime.database import row_get

MAP_FIELDS = tuple(f"map{slot}" for slot in range(1, 6))

LIVE_SCORE_FIELDS = (
    "team1_score",
    "team2_score",
    *(f"{field}_t{side}" for field in MAP_FIELDS for side in (1, 2)),
    "has_map3",
    "has_map4",
    "has_map5",
    "map_halves",
)

LOCKED_AFTER_START_FIELDS = ("event_id", "match_time", "bo_format", "stage", *MAP_FIELDS)
PREMATCH_RESULT_FIELDS = (
    *(field for field in LIVE_SCORE_FIELDS if not field.startswith("has_map")),
    "bp_process",
    "decider_knife_winner",
    "decider_start_side",
)


@dataclass(frozen=True)
class MatchSideInput:
    kind: str
    choice: str
    players: tuple[str, ...]
    roster: tuple[str, ...] | None
    provided: bool


@dataclass(frozen=True)
class MatchSetupInput:
    values: dict[str, Any]
    provided: frozenset[str]
    sides: tuple[MatchSideInput, MatchSideInput]
    requested_status: str | None
    result_entries: dict[str, str]
    clear_bp_password: bool
    freeze_rosters: bool


def setup_editable(match):
    status = row_get(match, "status") or "upcoming"
    return status == "upcoming" and not row_get(match, "bp_state")


def started_bp_setup_change(values, existing, provided):
    if not row_get(existing, "bp_state"):
        return False
    for field in LOCKED_AFTER_START_FIELDS:
        if field not in provided:
            continue
        submitted = str(values.get(field) or "").strip()
        current = str(row_get(existing, field) or "").strip()
        if field == "match_time":
            submitted, current = submitted[:16], current[:16]
        elif field == "bo_format":
            submitted, current = submitted.upper(), current.upper()
        if submitted != current:
            return True
    return False


def preserve_legacy_fields(values, existing, clear_bp_password):
    """Restore authoritative values while preparing a historical match update."""
    for field in LIVE_SCORE_FIELDS:
        values[field] = existing[field]

    current_status = existing["status"] or "upcoming"
    if current_status != "upcoming" or row_get(existing, "bp_state"):
        for field in LOCKED_AFTER_START_FIELDS:
            values[field] = existing[field]
        for field in MAP_FIELDS:
            values[f"{field}_pb"] = existing[f"{field}_picked_by"]

    if current_status == "completed":
        for field in ("server_address", "server_password", "bp_password"):
            values[field] = existing[field]
    else:
        if clear_bp_password:
            values["bp_password"] = None
        elif not values["bp_password"]:
            values["bp_password"] = existing["bp_password"]
        if values["server_address"] and not values["server_password"]:
            values["server_password"] = existing["server_password"]

    for field in ("decider_knife_winner", "decider_start_side"):
        if not values.get(field):
            values[field] = existing[field]
    return values


def validation_error(conn, values):
    if not values["event_id"]:
        return "请选择赛事"
    if (
        not str(values["event_id"]).isdigit()
        or not conn.execute("SELECT id FROM events WHERE id=?", (values["event_id"],)).fetchone()
    ):
        return "所选赛事不存在"
    if not values["match_time"]:
        return "比赛时间不能为空"
    if values["bo_format"] not in ("BO1", "BO3", "BO5"):
        return "BO 格式无效"
    if values.get("decider_knife_winner") not in ("t1", "t2") or values.get(
        "decider_start_side"
    ) not in ("CT", "T"):
        values["decider_knife_winner"] = None
        values["decider_start_side"] = None
    return None
