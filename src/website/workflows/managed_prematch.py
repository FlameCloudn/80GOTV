"""Schedule matches for managed events without bypassing fixed match participants."""

import json
from time import time

from src.website.domains.events.registration import active_event
from src.website.domains.matches import participants, setup
from src.website.domains.matches.admin_queries import _get_match_form_row
from src.website.domains.matches.legacy_roster_edit import select_side
from src.website.domains.matches.maps import sync_scheduled_maps
from src.website.domains.matches.match_references import update_match_slug
from src.website.runtime.database import row_get
from src.website.runtime.host import PREMATCH_ONLY, HostError, is_managed_event, write

_SETUP_COLUMNS = (
    "event_id",
    "match_time",
    "bo_format",
    "stage",
    "bp_password",
    "stream_url",
    "watch_urls",
    "server_address",
    "server_password",
)


def _select_entrant(conn, event_id, side, choice):
    if choice.kind == "entrant":
        entrant_id = choice.choice
        if not (entrant_id.isascii() and entrant_id.isdigit() and 0 < len(entrant_id) < 20):
            raise HostError(f"请选择第 {side} 方的本届参赛队伍", 400)
        return participants.select_entrant(conn, event_id, entrant_id=entrant_id)
    selected, error = select_side(conn, side, choice)
    if error:
        raise HostError(error, 400)
    if selected.team_id:
        return participants.select_entrant(conn, event_id, club_id=selected.team_id)
    if not selected.players:
        raise HostError("请选择已确认的本届队伍或完整五人名单", 400)
    return participants.select_entrant(conn, event_id, player_ids=json.loads(selected.players))


def _sync_maps(conn, match_id, values):
    scheduled = {key: values[key] for key in ("bo_format", *setup.MAP_FIELDS)}
    scheduled.update({f"{key}_picked_by": values[f"{key}_pb"] for key in setup.MAP_FIELDS})
    scheduled.update({f"has_map{slot}": values[f"has_map{slot}"] for slot in (3, 4, 5)})
    sync_scheduled_maps(conn, match_id, setup=scheduled)


def _assert_prematch_input(submission, match=None):
    if submission.requested_status not in (None, "upcoming"):
        raise HostError(PREMATCH_ONLY)
    for field, submitted in submission.result_entries.items():
        accepted = {"", str(row_get(match, field) or "").strip()}
        if field.endswith(("score", "_t1", "_t2")):
            accepted.add("0")
        if submitted not in accepted:
            raise HostError(PREMATCH_ONLY)


def create_match(conn, submission: setup.MatchSetupInput):
    _assert_prematch_input(submission)
    values = submission.values
    if values["is_test_mode"]:
        raise HostError("托管赛事必须选择两支已确认的参赛队伍，测试空位请使用原流程", 400)
    with write(conn):
        entrant_ids = [
            _select_entrant(conn, values["event_id"], side, choice)
            for side, choice in enumerate(submission.sides, start=1)
        ]
        conn.execute(
            f"INSERT INTO matches({','.join(_SETUP_COLUMNS)},status) VALUES (?,?,?,?,?,?,?,?,?,'upcoming')",
            tuple(values[field] for field in _SETUP_COLUMNS),
        )
        match_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        participants.bind(conn, match_id, *entrant_ids)
        update_match_slug(conn, match_id)
        _sync_maps(conn, match_id, values)


def _settings_for_existing_match(match, submission):
    values = submission.values.copy()
    provided = submission.provided
    if "event_id" in provided and str(values["event_id"]) != str(match["event_id"]):
        raise HostError("托管比赛不能更换所属赛事")
    for field in ("event_id", "match_time", "bo_format", "stage", *setup.MAP_FIELDS):
        if field not in provided:
            values[field] = match[field]
    for field in setup.MAP_FIELDS:
        if f"{field}_pb" not in provided:
            values[f"{field}_pb"] = match[f"{field}_picked_by"]
    for slot in (3, 4, 5):
        field = f"has_map{slot}"
        if field not in provided:
            values[field] = (
                match[field]
                if values["bo_format"] == match["bo_format"]
                else int(slot <= {"BO1": 1, "BO3": 3, "BO5": 5}.get(values["bo_format"], 0))
            )

    if submission.clear_bp_password:
        values["bp_password"] = None
    elif not values["bp_password"]:
        values["bp_password"] = match["bp_password"]
    for field in ("server_address", "stream_url", "watch_urls"):
        if field not in provided:
            values[field] = match[field]
    if values["server_address"] and not values["server_password"]:
        values["server_password"] = match["server_password"]
    return values


def _check_fixed_sides(conn, match, choices):
    fixed = participants.sides(conn, match["id"])
    if len(fixed) != 2:
        raise HostError("托管比赛缺少固定双方，请核对比赛资料")
    for side, team in fixed.items():
        choice = choices[side - 1]
        current_ids = tuple(str(player["id"]) for player in team["players"])
        if choice.provided:
            if choice.kind == "players" and team["frozen_at"]:
                same = len(current_ids) == 5 and sorted(choice.players) == sorted(current_ids)
            else:
                same = (
                    _select_entrant(conn, match["event_id"], side, choice)
                    == team["event_entrant_id"]
                )
            if not same:
                raise HostError("比赛双方已绑定，不能互换或改绑")
        if choice.roster is not None and choice.roster != current_ids:
            raise HostError("本场名单须从已批准阵容冻结；请先办理赛前换人，再确认本场名单")
    return [team["event_entrant_id"] for team in fixed.values()]


def edit_match(conn, match_id, submission: setup.MatchSetupInput, *, admin_id):
    with write(conn):
        match = _get_match_form_row(conn, match_id)
        if not match or not is_managed_event(conn, match["event_id"]):
            raise HostError("比赛已变化，请刷新页面")
        active_event(conn, match["event_id"], int(time()))
        if match["status"] != "upcoming":
            raise HostError(PREMATCH_ONLY)
        _assert_prematch_input(submission, match)
        values = _settings_for_existing_match(match, submission)
        if error := setup.validation_error(conn, values):
            raise HostError(error, 400)

        maps_changed = (
            values["bo_format"] != match["bo_format"]
            or any(
                (values[key] or None) != match[key]
                or values[f"{key}_pb"] != match[f"{key}_picked_by"]
                for key in setup.MAP_FIELDS
            )
            or any(values[f"has_{key}"] != match[f"has_{key}"] for key in setup.MAP_FIELDS[2:])
        )
        if setup.started_bp_setup_change(values, match, submission.provided) or (
            match["bp_state"] and maps_changed
        ):
            raise HostError("BP 已开始，不能更改赛制或地图等比赛设置")
        entrant_ids = _check_fixed_sides(conn, match, submission.sides)
        participants.check_duplicate(
            conn, match["event_id"], values["match_time"], entrant_ids, exclude_id=match_id
        )
        conn.execute(
            "UPDATE matches SET "
            + ",".join(f"{field}=?" for field in _SETUP_COLUMNS)
            + " WHERE id=?",
            (*[values[field] for field in _SETUP_COLUMNS], match_id),
        )
        if maps_changed:
            _sync_maps(conn, match_id, values)
        if submission.freeze_rosters:
            participants.freeze_rosters(conn, match_id, admin_id)
        update_match_slug(conn, match_id)
