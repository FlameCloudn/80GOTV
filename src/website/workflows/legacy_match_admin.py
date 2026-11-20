"""Write historical match settings, keeping the bracket and associated records consistent."""

from src.website.domains.community.interactions import delete_target_comments
from src.website.domains.matches import setup
from src.website.domains.matches.admin_queries import _get_match_form_row
from src.website.domains.matches.bracket_service import (
    match_is_bound_to_bracket,
    refresh_bracket_for_match,
    refresh_event_bracket,
)
from src.website.domains.matches.legacy_roster_edit import LegacySides
from src.website.domains.matches.match_references import update_match_slug
from src.website.domains.matches.match_roster_service import freeze_match_roster
from src.website.domains.matches.series import completed_match_result_error
from src.website.domains.predictions.scoring import revoke_legacy_points, score_predictions
from src.website.domains.statistics.performance_service import refresh_player_performance
from src.website.runtime.database import write_transaction
from src.website.runtime.host import HostError, is_managed_event

_MATCH_COLUMNS = (
    "event_id, team1_id, team2_id, team1_score, team2_score, match_time, bo_format, stage, status,"
    " map1, map1_t1, map1_t2, map2, map2_t1, map2_t2, map3, map3_t1, map3_t2, has_map3,"
    " map4, map4_t1, map4_t2, map5, map5_t1, map5_t2, has_map4, has_map5,"
    " map1_picked_by, map2_picked_by, map3_picked_by, map4_picked_by, map5_picked_by,"
    " bp_process, bp_password, stream_url, map_halves, team1_players, team2_players,"
    " watch_urls, server_address, server_password, is_test_mode"
)
_INSERT_COLUMNS = tuple(column.strip() for column in _MATCH_COLUMNS.split(","))
_EDIT_COLUMNS = _INSERT_COLUMNS + ("decider_knife_winner", "decider_start_side")
_ROSTER_COLUMNS = ("team1_id", "team2_id", "team1_players", "team2_players")
BP_SETUP_CHANGED = "bp_setup_changed"


def _write_values(values, sides: LegacySides, columns):
    home, away = sides
    form = {
        **values,
        "team1_id": home.team_id,
        "team2_id": away.team_id,
        "team1_players": home.players,
        "team2_players": away.players,
        **{f"{field}_picked_by": values[f"{field}_pb"] for field in setup.MAP_FIELDS},
    }
    return {column: form[column] for column in columns}


def create_match(conn, values, sides: LegacySides):
    with write_transaction(conn):
        if is_managed_event(conn, values["event_id"]):
            raise HostError("赛事的报名流程已切换，请刷新后再创建比赛")
        row = _write_values(values, sides, _INSERT_COLUMNS)
        conn.execute(
            f"INSERT INTO matches({_MATCH_COLUMNS}) VALUES ({','.join('?' for _ in row)})",
            tuple(row.values()),
        )
        match_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        update_match_slug(conn, match_id)
        refresh_bracket_for_match(conn, match_id)


def locked_edit_target(conn, original, submission: setup.MatchSetupInput):
    """Recheck mutable facts after acquiring the write lock."""
    latest = _get_match_form_row(conn, original["id"])
    if not latest:
        raise ValueError("比赛已不存在，请刷新页面后重试")
    if is_managed_event(conn, latest["event_id"]) or is_managed_event(
        conn, submission.values["event_id"]
    ):
        raise ValueError("不能通过旧流程编辑托管赛事的比赛")
    if any(latest[field] != original[field] for field in _ROSTER_COLUMNS):
        raise ValueError("比赛阵容已更新，请刷新页面后再保存")
    return latest


def edit_match(conn, original, latest, submission: setup.MatchSetupInput, sides: LegacySides):
    """Apply one change in the caller's transaction, after locked_edit_target."""
    if setup.started_bp_setup_change(submission.values, latest, submission.provided):
        raise HostError("BP 已开始，不能更改赛制或地图等比赛设置", 400, code=BP_SETUP_CHANGED)
    match_id = latest["id"]
    values = setup.preserve_legacy_fields(submission.values, latest, submission.clear_bp_password)
    if error := setup.validation_error(conn, values):
        raise ValueError(error)
    event_changed = str(values["event_id"]) != str(latest["event_id"])
    if event_changed and match_is_bound_to_bracket(conn, latest["event_id"], match_id):
        raise ValueError("这场比赛已绑定原赛事的对阵图，请先解除绑定再更换赛事")

    # A live score may have changed since the form was read. Never write it here.
    editable = _write_values(
        values, sides, (column for column in _EDIT_COLUMNS if column not in setup.LIVE_SCORE_FIELDS)
    )
    roster_changed = False
    for side, selected in enumerate(sides, start=1):
        if (
            str(selected.team_id or "") != str(latest[f"team{side}_id"] or "")
            or selected.players != latest[f"team{side}_players"]
        ):
            editable[f"team{side}_registration_id"] = None
            roster_changed = True
    if event_changed:
        editable.update(team1_registration_id=None, team2_registration_id=None)
        if latest["status"] in {"live", "completed"} or latest["bp_state"]:
            freeze_match_roster(conn, latest)
        else:
            roster_changed = True
    if roster_changed:
        editable["roster_snapshot"] = None
    cursor = conn.execute(
        "UPDATE matches SET "
        + ",".join(f"{column}=?" for column in editable)
        + " WHERE id=? AND COALESCE(status,'upcoming')=? AND event_id IS ?",
        (*editable.values(), match_id, original["status"] or "upcoming", original["event_id"]),
    )
    if cursor.rowcount != 1:
        raise ValueError("比赛状态或所属赛事已更新，请刷新页面后再保存")

    completed_now = values["status"] == "completed"
    was_completed = latest["status"] == "completed"
    if completed_now and not was_completed:
        finished = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
        if error := completed_match_result_error(finished):
            raise ValueError(error)
    elif not completed_now and was_completed:
        revoke_legacy_points(conn, match_id)
    update_match_slug(conn, match_id)
    refresh_bracket_for_match(conn, match_id)
    if completed_now:
        finished = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
        freeze_match_roster(conn, finished, confirmed=not was_completed)
        score_predictions(conn, match_id)


def delete_match(conn, match_id):
    """Delete a legacy match and refresh affected summaries in the same write."""
    match = conn.execute("SELECT id,event_id FROM matches WHERE id=?", (match_id,)).fetchone()
    if not match:
        return False
    affected_player_ids = {
        row["player_id"]
        for row in conn.execute(
            "SELECT DISTINCT player_id FROM match_stats WHERE match_id=?", (match_id,)
        ).fetchall()
        if row["player_id"]
    }
    delete_target_comments(conn, "match", match_id)
    for table in (
        "match_stats",
        "player_medals",
        "match_votes",
        "live_match_data",
        "live_match_events",
        "match_kill_events",
    ):
        conn.execute(f"DELETE FROM {table} WHERE match_id=?", (match_id,))
    conn.execute("UPDATE news SET related_match_id=NULL WHERE related_match_id=?", (match_id,))
    conn.execute("UPDATE live_ingest_status SET match_id=NULL WHERE match_id=?", (match_id,))
    conn.execute("DELETE FROM match_slug_aliases WHERE match_id=?", (match_id,))
    conn.execute("DELETE FROM matches WHERE id=?", (match_id,))
    if match["event_id"]:
        refresh_event_bracket(conn, match["event_id"])
    refresh_player_performance(conn, affected_player_ids)
    return True
