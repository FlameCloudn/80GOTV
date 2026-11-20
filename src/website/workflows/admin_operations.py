"""Apply one administrator operation in a caller-managed write transaction."""

from src.website.domains.operations import run_control as operations
from src.website.runtime.host import HostError


def _number(body, name, *, optional=False, minimum=1):
    value = body.get(name)
    if optional and value is None:
        return None
    if type(value) is not int or not minimum <= value <= 2**63 - 1:
        raise HostError(f"{name} 必须是大于等于 {minimum} 的整数", 400)
    return value


def command_note(body, name, *, required=True):
    text = body.get(name, "")
    if not isinstance(text, str) or (required and not text.strip()) or len(text) > 2000:
        raise HostError(f"请填写有效的 {name}（最多 2000 字）", 400)
    return text.strip()


def dispatch_operation(conn, match_id, action, body, admin):
    from src.website.domains.matches import results

    if action == "authorize":
        return operations.authorize(conn, match_id, admin)
    if action == "start":
        run = operations.observe_start(
            conn,
            match_id,
            _number(body, "scheduled_map_id"),
            source=f"admin:{admin}",
            evidence=command_note(body, "evidence"),
            expected_run_id=_number(body, "map_run_id", optional=True),
            previous_map_run_id=_number(body, "previous_map_run_id", optional=True),
        )
        return {"map_run_id": run}
    if action == "technical-replay":
        return operations.technical_replay(
            conn,
            match_id,
            _number(body, "map_run_id"),
            admin_id=admin,
            outgoing_player_id=_number(body, "outgoing_player_id", optional=True),
            incoming_player_id=_number(body, "incoming_player_id", optional=True),
            reason=command_note(body, "reason"),
            expected_revision=_number(body, "expected_revision", optional=True, minimum=0),
            expected_series_revision=_number(
                body, "expected_series_revision", optional=True, minimum=0
            ),
            retain_downstream=body.get("retain_downstream"),
        )
    if action == "bind-director-session":
        from src.website.domains.operations.projection import bind_director_session

        return bind_director_session(
            conn,
            match_id,
            _number(body, "map_run_id"),
            command_note(body, "session_id"),
            actor=admin,
            reason=command_note(body, "reason"),
        )
    if action == "bracket-link":
        from src.website.domains.matches.managed_bracket import configure_bracket_link

        return configure_bracket_link(
            conn,
            match_id,
            body.get("outcome"),
            _number(body, "target_match_id"),
            body.get("target_side"),
            actor=admin,
        )
    if action == "participation":
        run_id = _number(body, "map_run_id")
        operations.match_run(conn, match_id, run_id)
        pid = operations.record_participation(
            conn,
            run_id,
            _number(body, "player_id"),
            _number(body, "match_participant_id"),
            source="admin",
            actor=admin,
            reason=command_note(body, "reason"),
            round_number=_number(body, "round_number", optional=True),
            side=body.get("side"),
        )
        return {"participation_id": pid}
    if action == "review-participation":
        if type(body.get("present")) is not bool:
            raise HostError("present 须明确填写 true 或 false", 400)
        return operations.review_participation(
            conn,
            match_id,
            _number(body, "participation_id"),
            present=body["present"],
            expected_revision=_number(body, "expected_revision"),
            admin_id=admin,
            reason=command_note(body, "reason"),
        )
    if action in {"stats", "preview-stats"}:
        from src.website.domains.statistics.statistics import apply_fields, preview_fields

        run_id = _number(body, "map_run_id")
        operations.match_run(conn, match_id, run_id)
        submit = action == "stats"
        kwargs = {"confirm": True} if submit else {}
        return (apply_fields if submit else preview_fields)(
            conn,
            run_id,
            _number(body, "player_id"),
            body.get("scope", "all"),
            body.get("fields"),
            source="admin",
            actor=admin,
            reason=command_note(body, "reason", required=submit),
            expected=_number(body, "expected_revision", optional=not submit, minimum=0),
            **kwargs,
        )
    if action == "confirm-map":
        return results.confirm_map(
            conn,
            match_id,
            _number(body, "scheduled_map_id"),
            _number(body, "map_run_id"),
            _number(body, "score1", minimum=0),
            _number(body, "score2", minimum=0),
            actor=admin,
            source="admin",
            reason=command_note(body, "reason", required=False),
            expected_revision=_number(body, "expected_revision", minimum=0),
            expected_series_revision=_number(
                body, "expected_series_revision", optional=True, minimum=0
            ),
            retain_downstream=body.get("retain_downstream"),
        )
    if action == "settle":
        return results.settle_series(
            conn,
            match_id,
            actor=admin,
            reason=command_note(body, "reason", required=False),
            expected_revision=_number(body, "expected_revision", optional=True, minimum=0),
        )
    if action == "reopen":
        return results.reopen_series(
            conn,
            match_id,
            actor=admin,
            reason=command_note(body, "reason"),
            expected_revision=_number(body, "expected_revision"),
            retain_downstream=body.get("retain_downstream"),
        )
    raise HostError("没有这项比赛运营操作", 404)
