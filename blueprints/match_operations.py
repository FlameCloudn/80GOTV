"""管理员办理实际开赛、技术重赛和赛果，不复用可编辑的旧比分表单。"""

import json
from contextlib import closing

from flask import flash, jsonify, redirect, render_template, request, session, url_for

from blueprints.admin import admin_bp
from models import get_db
from site_core.host import HostError, is_managed_match, write
from site_core.matches import operations
from utils.web_helpers import admin_required, csrf_required


def _number(body, name, *, optional=False, minimum=1):
    value = body.get(name)
    if optional and value is None:
        return None
    if type(value) is not int or not minimum <= value <= 2**63 - 1:
        raise HostError(f"{name} 必须是大于等于 {minimum} 的整数", 400)
    return value


def _note(body, name, *, required=True):
    text = body.get(name, "")
    if not isinstance(text, str) or (required and not text.strip()) or len(text) > 2000:
        raise HostError(f"请填写有效的 {name}（最多 2000 字）", 400)
    return text.strip()


def _overview(conn, match_id):
    from site_core.matches.results import read_results

    maps = []
    for row in conn.execute(
        "SELECT * FROM scheduled_maps WHERE match_id=? AND is_enabled=1 ORDER BY map_order",
        (match_id,),
    ):
        map_id = row["scheduled_map_id"]
        item = dict(row)
        item["effective_roster"] = operations.effective_roster(conn, match_id, map_id)
        item["runs"] = []
        for run in conn.execute(
            "SELECT * FROM map_runs WHERE scheduled_map_id=? ORDER BY attempt_no", (map_id,)
        ):
            run_id = run["map_run_id"]
            replay = conn.execute(
                "SELECT * FROM technical_replays WHERE map_run_id=?", (run_id,)
            ).fetchone()
            item["runs"].append(
                {
                    **dict(run),
                    "replay": dict(replay) if replay else None,
                    "lineup": [
                        dict(r)
                        for r in conn.execute(
                            "SELECT * FROM map_run_lineups WHERE map_run_id=? ORDER BY match_participant_id,roster_slot",
                            (run_id,),
                        )
                    ],
                    "participations": [
                        dict(r)
                        for r in conn.execute(
                            "SELECT * FROM run_participations WHERE map_run_id=? ORDER BY participation_id",
                            (run_id,),
                        )
                    ],
                    "rounds": [
                        dict(r)
                        for r in conn.execute(
                            "SELECT * FROM map_run_rounds WHERE map_run_id=? ORDER BY round_number",
                            (run_id,),
                        )
                    ],
                }
            )
        maps.append(item)
    return {
        "match_id": match_id,
        **operations.start_state(conn, match_id),
        "maps": maps,
        "results": read_results(conn, match_id),
    }


@admin_bp.get("/matches/<int:match_id>/operations")
@admin_required
def managed_operations(match_id):
    with closing(get_db()) as conn:
        try:
            if not is_managed_match(conn, match_id):
                raise HostError("本场不属于新赛事流程", 404)
            conn.execute("BEGIN")
            return jsonify(ok=True, **_overview(conn, match_id))
        except HostError as exc:
            return jsonify(ok=False, error=exc.message), exc.status


@admin_bp.get("/matches/<int:match_id>/operations/runs/<int:run_id>/players/<int:player_id>/stats")
@admin_required
def managed_stat_fields(match_id, run_id, player_id):
    from site_core.matches.statistics import read_fields

    with closing(get_db()) as conn:
        try:
            if not is_managed_match(conn, match_id):
                raise HostError("本场不属于新赛事流程", 404)
            conn.execute("BEGIN")
            operations.match_run(conn, match_id, run_id)
            scope = request.args.get("scope", "all")
            result = read_fields(conn, run_id, player_id, scope)
            if request.args.get("history") == "1":
                revisions = []
                for row in conn.execute(
                    "SELECT revision,source,source_ref,method,actor,reason,changes_json,created_at "
                    "FROM run_stats_revisions WHERE map_run_id=? AND player_id=? AND scope=? ORDER BY revision",
                    (run_id, player_id, scope),
                ):
                    item = dict(row)
                    item["changes"] = json.loads(item.pop("changes_json"))
                    revisions.append(item)
                result["history"] = revisions
            return jsonify(ok=True, **result)
        except HostError as exc:
            return jsonify(ok=False, error=exc.message), exc.status


def _history(conn, match_id):
    maps = [
        dict(r)
        for r in conn.execute(
            "SELECT s.map_order,o.* FROM scheduled_maps s JOIN official_map_results o USING(scheduled_map_id) "
            "WHERE s.match_id=? ORDER BY s.map_order,o.revision",
            (match_id,),
        )
    ]
    series = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM series_settlements WHERE match_id=? ORDER BY revision", (match_id,)
        )
    ]
    for item in series:
        item["map_result_ids"] = json.loads(item["map_result_ids"])
    predictions = [
        dict(r)
        for r in conn.execute(
            "SELECT c.* FROM prediction_settlement_changes c JOIN series_settlements s USING(settlement_id) "
            "WHERE s.match_id=? ORDER BY s.revision,c.vote_id",
            (match_id,),
        )
    ]
    bracket = [
        dict(r)
        for r in conn.execute(
            "SELECT c.* FROM bracket_settlement_changes c JOIN series_settlements s USING(settlement_id) "
            "WHERE s.match_id=? ORDER BY s.revision,c.target_match_id,c.target_side",
            (match_id,),
        )
    ]
    retained = [
        dict(r)
        for r in conn.execute(
            "SELECT d.*,s.revision,s.actor,s.reason,s.recorded_at FROM bracket_retention_decisions d "
            "JOIN series_settlements s USING(settlement_id) WHERE d.source_match_id=? "
            "ORDER BY s.revision,d.target_match_id,d.target_side",
            (match_id,),
        )
    ]
    return {
        "maps": maps,
        "series": series,
        "bracket": bracket,
        "retained": retained,
        "predictions": predictions,
    }


def _panel_context(conn, match_id):
    from services.bracket_service import _slot_protection, get_bracket_links
    from services.match_service import supplement_temp_teams
    from site_core.events import public as event_rosters
    from site_core.matches import participants, statistics
    from site_core.predictions import managed_vote_open

    match_row = conn.execute(
        """SELECT m.id, m.event_id, m.bo_format, m.stage, m.status, m.match_time, m.slug,
                  m.bp_state, m.team1_score, m.team2_score,
                  e.name AS event_name, e.slug AS event_slug, e.status AS event_status,
                  c.archived_at AS event_archived_at,
                  a.authorized_at, a.admin_id AS authorized_by
           FROM matches m
           JOIN events e ON e.id=m.event_id
           JOIN event_registration_control c ON c.event_id=m.event_id
           LEFT JOIN match_start_authorizations a ON a.match_id=m.id
           WHERE m.id=?""",
        (match_id,),
    ).fetchone()
    if not match_row:
        raise HostError("比赛不存在或仍使用往届流程", 404)

    bp_state = None
    if match_row["bp_state"]:
        try:
            bp_state = json.loads(match_row["bp_state"])
        except ValueError:
            bp_state = None

    event_id = match_row["event_id"]
    admins = {
        str(r["id"]): r["username"]
        for r in conn.execute("SELECT id, username FROM admins").fetchall()
    }
    entrants = {}
    for er in conn.execute(
        """SELECT ee.event_entrant_id, r.team_name, g.club_id, t.name AS club_name
           FROM event_entrants ee
           JOIN event_registration_groups g ON g.registration_id=ee.registration_id
           JOIN event_registrations r ON r.id=ee.registration_id
           LEFT JOIN teams t ON t.id=g.club_id
           WHERE ee.event_id=?
           ORDER BY ee.event_entrant_id""",
        (event_id,),
    ).fetchall():
        entrants[str(er["event_entrant_id"])] = {
            "id": er["event_entrant_id"],
            "name": er["team_name"] or f"参赛队 #{er['event_entrant_id']}",
            "club_id": er["club_id"],
            "club_name": er["club_name"] or "",
        }

    fixed_sides = participants.sides(conn, match_id)
    rosters_frozen = participants.rosters_frozen(conn, match_id)
    participants_list = []
    player_ids = set()

    for side_num in (1, 2):
        side = fixed_sides.get(side_num)
        if not side:
            continue
        eid = side["event_entrant_id"]
        approved = event_rosters.roster(conn, event_id, eid)
        reserves = [
            dict(r)
            for r in conn.execute(
                """SELECT c.player_id, p.nickname, p.steam_id, e.registration_origin
                   FROM event_reserve_candidates c
                   JOIN event_signup_entries e USING(event_id, player_id)
                   JOIN players p ON p.id=c.player_id
                   WHERE c.event_id=? AND c.assigned_entrant_id=? AND c.withdrawn_at IS NULL
                     AND NOT EXISTS (
                       SELECT 1 FROM event_current_members cm
                       WHERE cm.event_id=c.event_id AND cm.player_id=c.player_id
                     )
                   ORDER BY c.player_id""",
                (event_id, eid),
            ).fetchall()
        ]
        for p in side["players"]:
            player_ids.add(p["id"])
        for r in reserves:
            player_ids.add(r["player_id"])
        player_ids.update(approved["initial_player_ids"])
        player_ids.update(approved["current_player_ids"])
        participants_list.append(
            {
                "side_num": side_num,
                "side_key": side["side_key"],
                "match_participant_id": side["match_participant_id"],
                "event_entrant_id": eid,
                "name": side["name"],
                "short_name": side["short_name"] or "",
                "club_name": (entrants.get(str(eid)) or {}).get("club_name", ""),
                "frozen": bool(side["frozen_at"]),
                "frozen_at": side["frozen_at"],
                "initial_player_ids": list(approved["initial_player_ids"]),
                "current_player_ids": list(approved["current_player_ids"]),
                "players": [
                    {
                        "id": p["id"],
                        "nickname": p["nickname"],
                        "steam_id": p["steam_id"] or "",
                        "slot": p["slot"],
                        "is_substitute": bool(p["is_substitute"]),
                    }
                    for p in side["players"]
                ],
                "assigned_reserves": reserves,
            }
        )

    for row in conn.execute(
        """SELECT l.player_id FROM map_run_lineups l
           JOIN map_runs r USING(map_run_id) JOIN scheduled_maps s USING(scheduled_map_id)
           WHERE s.match_id=?
           UNION
           SELECT rp.player_id FROM run_participations rp
           JOIN map_runs r USING(map_run_id) JOIN scheduled_maps s USING(scheduled_map_id)
           WHERE s.match_id=?
           UNION
           SELECT tr.outgoing_player_id FROM technical_replays tr
           JOIN map_runs r USING(map_run_id) JOIN scheduled_maps s USING(scheduled_map_id)
           WHERE s.match_id=? AND tr.outgoing_player_id IS NOT NULL
           UNION
           SELECT tr.incoming_player_id FROM technical_replays tr
           JOIN map_runs r USING(map_run_id) JOIN scheduled_maps s USING(scheduled_map_id)
           WHERE s.match_id=? AND tr.incoming_player_id IS NOT NULL""",
        (match_id, match_id, match_id, match_id),
    ).fetchall():
        if row[0] is not None:
            player_ids.add(row[0])

    players = {}
    if player_ids:
        placeholders = ",".join("?" for _ in player_ids)
        for p in conn.execute(
            f"SELECT id, nickname, steam_id FROM players WHERE id IN ({placeholders})",
            tuple(player_ids),
        ).fetchall():
            players[str(p["id"])] = {
                "id": p["id"],
                "nickname": p["nickname"],
                "steam_id": p["steam_id"] or "",
            }

    director_sessions = {}
    for row in conn.execute(
        """SELECT ds.scheduled_map_id, ds.map_run_id, ds.session_id, ds.actor, ds.reason, ds.bound_at
           FROM live_director_sessions ds
           JOIN scheduled_maps s USING(scheduled_map_id)
           WHERE s.match_id=? ORDER BY ds.bound_at, ds.session_id""",
        (match_id,),
    ).fetchall():
        director_sessions.setdefault(str(row["map_run_id"]), []).append(dict(row))

    event_matches_raw = conn.execute(
        """SELECT m.*, t1.name AS team1_name, t1.short_name AS t1s,
                  t2.name AS team2_name, t2.short_name AS t2s
           FROM matches m
           LEFT JOIN teams t1 ON m.team1_id=t1.id LEFT JOIN teams t2 ON m.team2_id=t2.id
           WHERE m.event_id=?
           ORDER BY CASE WHEN m.match_time IS NULL OR m.match_time='' THEN 1 ELSE 0 END,
                    m.match_time, m.id""",
        (event_id,),
    ).fetchall()
    event_matches_by_id = {}
    event_matches = []
    for raw in event_matches_raw:
        event_matches_by_id[raw["id"]] = raw
        disp = supplement_temp_teams(raw, conn)
        event_matches.append(
            {
                "id": disp["id"],
                "stage": disp["stage"] or "",
                "bo_format": disp["bo_format"] or "BO3",
                "status": disp["status"],
                "match_time": disp["match_time"] or "",
                "team1_name": disp["team1_name"] or "TBD",
                "team2_name": disp["team2_name"] or "TBD",
                "team1_score": disp["team1_score"],
                "team2_score": disp["team2_score"],
            }
        )

    downstream_links = []
    for link in get_bracket_links(conn, event_id):
        if link["source_match_id"] != match_id:
            continue
        target_row = event_matches_by_id.get(link["target_match_id"])
        protection_reason = None
        can_retain = False
        if target_row is not None:
            try:
                protection_reason = _slot_protection(conn, target_row, link["target_side"])
                can_retain = protection_reason is not None and link["event_entrant_id"] is not None
            except HostError as exc:
                protection_reason = exc.message
        target_summary = next(
            (m for m in event_matches if m["id"] == link["target_match_id"]), None
        )
        downstream_links.append(
            {
                **link,
                "target_stage": (target_summary or {}).get("stage", ""),
                "target_label": (
                    f"#{link['target_match_id']} "
                    f"{(target_summary or {}).get('stage') or (target_summary or {}).get('bo_format') or ''}"
                ).strip(),
                "current_entrant_name": (
                    (entrants.get(str(link["event_entrant_id"])) or {}).get("name")
                    if link["event_entrant_id"]
                    else None
                ),
                "protected": bool(protection_reason),
                "can_retain": can_retain,
                "protection_reason": protection_reason,
            }
        )

    vote_rows = [
        dict(r)
        for r in conn.execute(
            """SELECT v.id, v.user_id, u.username, v.voted_for, v.score1_guess, v.score2_guess,
                      v.points_earned, v.scored, v.created_at
               FROM match_votes v
               LEFT JOIN users u ON u.id=v.user_id
               WHERE v.match_id=? ORDER BY v.id""",
            (match_id,),
        ).fetchall()
    ]
    t1_votes = sum(1 for v in vote_rows if v["voted_for"] == "t1")
    t2_votes = sum(1 for v in vote_rows if v["voted_for"] == "t2")
    settled_votes = sum(1 for v in vote_rows if v["scored"])

    return {
        "match": {
            "id": match_row["id"],
            "event_id": event_id,
            "event_name": match_row["event_name"],
            "event_status": match_row["event_status"],
            "event_archived": match_row["event_archived_at"] is not None,
            "bo_format": match_row["bo_format"] or "BO3",
            "stage": match_row["stage"] or "",
            "status": match_row["status"],
            "match_time": match_row["match_time"] or "",
            "slug": match_row["slug"] or "",
            "bp_status": (bp_state or {}).get("status") if isinstance(bp_state, dict) else None,
            "rosters_frozen": rosters_frozen,
            "authorized_at": match_row["authorized_at"],
            "authorized_by_name": admins.get(str(match_row["authorized_by"]), "")
            if match_row["authorized_by"]
            else "",
            "bp_url": f"/bp/{match_row['id']}",
            "public_url": f"/matches/{match_row['slug'] or match_row['id']}",
            "edit_url": url_for("admin.admin_matches_edit", match_id=match_row["id"]),
            "event_roster_url": url_for("admin.admin_event_roster", event_id=event_id),
            "event_bracket_url": url_for("admin.admin_event_bracket", event_id=event_id),
        },
        "participants": participants_list,
        "players": players,
        "admins": admins,
        "entrants": entrants,
        "event_matches": event_matches,
        "downstream_links": downstream_links,
        "director_sessions": director_sessions,
        "predictions": {
            "vote_open": bool(managed_vote_open(conn, match_id)),
            "total_votes": len(vote_rows),
            "t1_votes": t1_votes,
            "t2_votes": t2_votes,
            "settled_count": settled_votes,
            "votes": vote_rows,
        },
        "stat_field_names": list(statistics.FIELD_NAMES),
        "count_fields": sorted(statistics._COUNTS),
    }


@admin_bp.get("/matches/<int:match_id>/operations/history")
@admin_required
def managed_result_history(match_id):
    with closing(get_db()) as conn:
        if not is_managed_match(conn, match_id):
            return jsonify(ok=False, error="本场不属于新赛事流程"), 404
        conn.execute("BEGIN")
        return jsonify(ok=True, **_history(conn, match_id))


def _panel_bundle(conn, match_id):
    from services.match_service import get_series_result
    from site_core.matches.demo_storage import list_originals
    from site_core.matches.results import map_change_options

    overview = _overview(conn, match_id)
    result = overview["results"]
    context = _panel_context(conn, match_id)
    context["map_change_options"] = map_change_options(result)
    context["series_decided"] = bool(get_series_result(result["bo_format"], result["score1"], result["score2"])[0])
    return {
        "context": context,
        "overview": overview,
        "history": _history(conn, match_id),
        "originals": list_originals(conn, match_id),
    }


@admin_bp.get("/matches/<int:match_id>/operations/panel-context")
@admin_required
def managed_operations_panel_context(match_id):
    with closing(get_db()) as conn:
        try:
            if not is_managed_match(conn, match_id):
                raise HostError("本场不属于新赛事流程", 404)
            conn.execute("BEGIN")
            return jsonify(ok=True, **_panel_bundle(conn, match_id))
        except HostError as exc:
            return jsonify(ok=False, error=exc.message), exc.status


@admin_bp.get("/matches/<int:match_id>/operate")
@admin_required
def managed_match_operate(match_id):
    with closing(get_db()) as conn:
        if not is_managed_match(conn, match_id):
            flash("该比赛属于往届流程，请使用比赛编辑、上传 Demo 和录入数据页面。", "info")
            return redirect(url_for("admin.admin_matches_edit", match_id=match_id))
        conn.execute("BEGIN")
        bundle = _panel_bundle(conn, match_id)
    return render_template(
        "admin/match_operations.html",
        match_id=match_id,
        match=bundle["context"]["match"],
        participants=bundle["context"]["participants"],
        panel_bundle=bundle,
    )


def _dispatch(conn, match_id, action, body, admin):
    from site_core.matches import results

    if action == "authorize":
        return operations.authorize(conn, match_id, admin)
    if action == "start":
        run = operations.observe_start(
            conn,
            match_id,
            _number(body, "scheduled_map_id"),
            source=f"admin:{admin}",
            evidence=_note(body, "evidence"),
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
            reason=_note(body, "reason"),
            expected_revision=_number(body, "expected_revision", optional=True, minimum=0),
            expected_series_revision=_number(
                body, "expected_series_revision", optional=True, minimum=0
            ),
            retain_downstream=body.get("retain_downstream"),
        )
    if action == "bind-director-session":
        from site_core.matches.live import bind_director_session

        return bind_director_session(
            conn,
            match_id,
            _number(body, "map_run_id"),
            _note(body, "session_id"),
            actor=admin,
            reason=_note(body, "reason"),
        )
    if action == "bracket-link":
        from services.bracket_service import configure_bracket_link

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
            reason=_note(body, "reason"),
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
            reason=_note(body, "reason"),
        )
    if action in {"stats", "preview-stats"}:
        from site_core.matches.statistics import apply_fields, preview_fields

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
            reason=_note(body, "reason", required=submit),
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
            reason=_note(body, "reason", required=False),
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
            reason=_note(body, "reason", required=False),
            expected_revision=_number(body, "expected_revision", optional=True, minimum=0),
        )
    if action == "reopen":
        return results.reopen_series(
            conn,
            match_id,
            actor=admin,
            reason=_note(body, "reason"),
            expected_revision=_number(body, "expected_revision"),
            retain_downstream=body.get("retain_downstream"),
        )
    raise HostError("没有这项比赛运营操作", 404)


@admin_bp.post("/matches/<int:match_id>/operations/<action>")
@csrf_required
@admin_required
def managed_operation(match_id, action):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(ok=False, error="请提交 JSON 对象"), 400
    with closing(get_db()) as conn:
        try:
            if not is_managed_match(conn, match_id):
                raise HostError("本场不属于新赛事流程", 404)
            with write(conn):
                result = _dispatch(conn, match_id, action, body, session["admin_id"])
            return jsonify({"ok": True, **result}), 409 if result.get("ok") is False else 200
        except HostError as exc:
            return jsonify(ok=False, error=exc.message), exc.status


@admin_bp.route("/events/<int:event_id>/operations/bracket", methods=["GET", "POST"])
@csrf_required
@admin_required
def managed_bracket(event_id):
    from services.bracket_service import create_bracket_match, get_bracket_links
    from site_core.host import is_managed_event

    with closing(get_db()) as conn:
        try:
            if not is_managed_event(conn, event_id):
                raise HostError("本届仍使用原签表", 404)
            if request.method == "GET":
                from blueprints.admin_events import _event_bracket_matches

                conn.execute("BEGIN")
                return jsonify(ok=True, links=get_bracket_links(conn, event_id), matches=_event_bracket_matches(conn, event_id))
            body = request.get_json(silent=True)
            if not isinstance(body, dict):
                raise HostError("请提交赛制、轮次及可选的开赛时间", 400)
            at = _note(body, "match_time", required=False) or None
            if at and conn.execute("SELECT datetime(?)", (at,)).fetchone()[0] is None:
                raise HostError("开赛时间无效", 400)
            with write(conn):
                result = create_bracket_match(
                    conn,
                    event_id,
                    bo_format=body.get("bo_format"),
                    stage=_note(body, "stage"),
                    actor=session["admin_id"],
                    match_time=at,
                )
            return jsonify(ok=True, **result), 201
        except HostError as exc:
            return jsonify(ok=False, error=exc.message), exc.status
