"""Create a legacy draw and persist confirmed rosters with their event history."""

import logging
from dataclasses import dataclass

from src.website.domains.events.legacy_registration import (
    clear_draft_assignments,
    has_individuals_on_teams,
)
from src.website.domains.events.legacy_team_registration import (
    has_legacy_captain_column,
    register_team,
    slot_is_open,
)
from src.website.domains.events.registration_reads import _load_event_registrations
from src.website.domains.events.steam_playtime_service import (
    attach_latest_playtime,
    build_balanced_assignments,
    build_balanced_roster_plan,
    refresh_registration_playtimes,
)
from src.website.domains.matches.match_roster_service import preserve_event_rosters
from src.website.runtime.database import write_transaction
from src.website.runtime.host import HostError

logger = logging.getLogger(__name__)
TEAM_SIZE = 5


@dataclass(frozen=True)
class FormationSummary:
    new_teams: int
    completed_teams: int
    reserves: int
    steam_configured: bool
    known_playtimes: int
    unknown_playtimes: int


def _require_event(conn, event_id):
    if not conn.execute("SELECT 1 FROM events WHERE id=?", (event_id,)).fetchone():
        raise HostError("赛事不存在", 404, code="missing_event")


def _candidate_rows(conn, event_id, *, signup_order=False):
    order = "created_at, id" if signup_order else "id"
    return conn.execute(
        f"""SELECT id, user_id, player_name, steam_id, created_at,
                   cs2_playtime_minutes, playtime_status, playtime_checked_at
            FROM event_individual_registrations WHERE event_id=? ORDER BY {order}""",
        (event_id,),
    ).fetchall()


def randomize_individual_teams(conn, event_id):
    _require_event(conn, event_id)
    if has_individuals_on_teams(conn, event_id):
        raise HostError("个人报名选手已经进入正式队伍", 409, code="any_teams_confirmed")
    rows = _candidate_rows(conn, event_id)
    if len(rows) < TEAM_SIZE:
        raise HostError("至少需要 5 名个人报名选手才能分队", 400, code="not_enough_for_draw")

    refresh = refresh_registration_playtimes(conn, rows)
    draw = build_balanced_assignments(_candidate_rows(conn, event_id), team_size=TEAM_SIZE)
    clear_draft_assignments(conn, event_id)
    conn.executemany(
        """UPDATE event_individual_registrations
           SET assignment_status='assigned', team_number=?, assigned_at=CURRENT_TIMESTAMP
           WHERE id=?""",
        [(team_number, entry_id) for entry_id, team_number in draw["assignments"].items()],
    )
    conn.executemany(
        """UPDATE event_individual_registrations
           SET assignment_status='reserve', team_number=NULL, assigned_at=CURRENT_TIMESTAMP
           WHERE id=?""",
        [(entry_id,) for entry_id in draw["reserves"]],
    )
    return FormationSummary(
        len(draw["team_totals"]),
        0,
        len(draw["reserves"]),
        refresh["configured"],
        draw["known_count"],
        draw["unknown_count"],
    )


def _partial_teams(conn, event_id):
    partial_teams = {}
    for group in _load_event_registrations(conn, event_id):
        open_slots = []
        occupied = []
        for slot in group["slots"]:
            (open_slots if slot_is_open(slot) else occupied).append(slot)
        if open_slots:
            reg_id = group["info"]["id"]
            partial_teams[reg_id] = {
                "registration_id": reg_id,
                "players": attach_latest_playtime(conn, occupied, "steam_id"),
                "open_slots": open_slots,
            }
    return partial_teams


def _fill_existing_team(conn, open_slots, assigned):
    if len(assigned) != len(open_slots):
        raise RuntimeError("分队计划与现有空位数量不一致")
    for slot, entry in zip(open_slots, assigned):
        changed = conn.execute(
            """UPDATE event_registration_slots
               SET user_id=?, player_name=?, steam_id=?, filled_by_creator=0
               WHERE id=? AND user_id IS NULL AND COALESCE(steam_id, '')=''
                 AND COALESCE(filled_by_creator, 0)=0""",
            (entry["user_id"], entry["player_name"], entry["steam_id"], slot["id"]),
        ).rowcount
        if changed != 1:
            raise RuntimeError("现有队伍空位已经发生变化，请刷新后重试")


def _create_formed_team(conn, event_id, team_name, assigned, *, has_old_captain):
    captain = min(assigned, key=lambda row: (str(row.get("created_at") or ""), row["id"]))
    ordered = [captain] + [row for row in assigned if row["id"] != captain["id"]]
    slots = [
        (index, entry["user_id"], entry["player_name"], entry["steam_id"], 0)
        for index, entry in enumerate(ordered)
    ]
    return register_team(
        conn, event_id, team_name, captain["user_id"], slots, has_old_captain=has_old_captain
    )


def _persist_formation(conn, event_id, candidates, partial_teams, draw):
    by_id = {row["id"]: row for row in candidates}
    existing_names = {
        str(row["team_name"] or "").strip().casefold()
        for row in conn.execute(
            "SELECT team_name FROM event_registrations WHERE event_id=?", (event_id,)
        )
    }
    has_old_captain = has_legacy_captain_column(conn)
    next_team_number = 1
    created = completed = 0
    for team in draw["teams"]:
        assigned = [by_id[entry_id] for entry_id in team["candidate_ids"]]
        reg_id = team["registration_id"]
        if reg_id is not None:
            _fill_existing_team(conn, partial_teams[reg_id]["open_slots"], assigned)
            completed += 1
        else:
            while True:
                team_name = f"个人报名队 {next_team_number}"
                next_team_number += 1
                if team_name.casefold() not in existing_names:
                    existing_names.add(team_name.casefold())
                    break
            reg_id = _create_formed_team(
                conn, event_id, team_name, assigned, has_old_captain=has_old_captain
            )
            created += 1
        conn.executemany(
            """UPDATE event_individual_registrations
               SET assignment_status='assigned', team_number=?, assigned_at=CURRENT_TIMESTAMP
               WHERE id=? AND event_id=?""",
            [(reg_id, entry["id"], event_id) for entry in assigned],
        )

    reserve_ids = sorted(set(draw["reserves"]))
    if reserve_ids:
        placeholders = ",".join("?" for _ in reserve_ids)
        conn.execute(
            f"""UPDATE event_individual_registrations
                SET assignment_status='reserve', team_number=NULL, assigned_at=CURRENT_TIMESTAMP
                WHERE event_id=? AND id IN ({placeholders})""",
            (event_id, *reserve_ids),
        )
    return created, completed, len(reserve_ids)


def confirm_individual_teams(conn, event_id):
    _require_event(conn, event_id)
    refresh_rows = _candidate_rows(conn, event_id, signup_order=True)
    if not refresh_rows:
        raise HostError("暂时没有个人报名选手", 400, code="no_individuals")
    refresh = refresh_registration_playtimes(conn, refresh_rows)
    conn.commit()

    try:
        # The Steam refresh is independent; snapshots and all roster writes succeed or fail together.
        with write_transaction(conn):
            preserve_event_rosters(conn, event_id)
            if has_individuals_on_teams(conn, event_id):
                raise HostError(
                    "个人报名已经完成正式分队，不能重复执行", 409, code="teams_already_confirmed"
                )
            candidates = [dict(row) for row in _candidate_rows(conn, event_id, signup_order=True)]
            partial_teams = _partial_teams(conn, event_id)
            needed = sum(len(team["open_slots"]) for team in partial_teams.values())
            if len(candidates) < needed:
                raise HostError(
                    f"个人报名人数不足：补满现有队伍还需要 {needed} 人",
                    409,
                    code="not_enough_to_fill",
                    params={"needed": needed},
                )
            if not partial_teams and len(candidates) < TEAM_SIZE:
                raise HostError(
                    "至少需要 5 名个人报名选手才能创建正式队伍",
                    409,
                    code="not_enough_for_confirmed_team",
                )
            draw = build_balanced_roster_plan(
                candidates, fixed_teams=list(partial_teams.values()), team_size=TEAM_SIZE
            )
            created, completed, reserves = _persist_formation(
                conn, event_id, candidates, partial_teams, draw
            )
    except HostError:
        raise
    except ValueError as exc:
        raise HostError(str(exc), 409) from exc
    except Exception as exc:
        logger.exception("Failed to finalize event registration teams")
        raise HostError("正式分队失败，请刷新后重试", 500, code="formation_failed") from exc

    return FormationSummary(
        created,
        completed,
        reserves,
        refresh["configured"],
        draw["known_count"],
        draw["unknown_count"],
    )
