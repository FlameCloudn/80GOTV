"""Attach write handlers to the isolated site only. The existing login, CSRF and Jinja still apply."""

import time
from contextlib import closing
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from flask import abort, current_app, flash, jsonify, redirect, request, send_file, session, url_for

from . import formation, registration
from .storage import SliceError, require_admin, write

FORM_MESSAGES = {
    "event_register": "队伍创建成功",
    "event_register_individual": "个人报名成功，等待按游戏时长平衡分队",
    "event_register_substitute": "替补报名已保存",
    "event_withdraw_individual": "报名已取消",
    "event_join_slot": "加入成功",
    "event_leave_slot": "已退出本人的位置",
    "event_registration_rename": "队伍已更名",
    "event_registration_remove_member": "位置已清空",
    "event_registration_update_member": "位置已更新",
    "event_registration_transfer_captain": "队长已移交",
    "event_registration_dissolve": "队伍已解散",
    "event_registration_upload_logo": "队标已更新",
    "event_registration_remove_logo": "队标已移除",
}


def _integer(value):
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise SliceError("需要正整数编号或版本", 400)
    return value


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise SliceError("文字或操作理由不能为空", 400)
    return value.strip()


def _digit(value):
    raw = str(value)
    if len(raw) > 19 or not raw.isascii() or not raw.isdecimal() or int(raw) > 2**63 - 1:
        raise SliceError("编号或位置格式不正确", 400)
    return int(raw)


def _badge(conn, folder, upload):
    from utils.db_helpers import save_uploaded_team_logo

    with TemporaryDirectory(prefix="badge-", dir=folder) as temp:
        name = save_uploaded_team_logo(upload, temp)
        if not name:
            raise SliceError("队标无效，请上传不超过 10MB 的 PNG、JPG 或 GIF 图片", 400)
        root = Path(temp)
        conn.execute(
            "INSERT INTO registration_logo VALUES(?,?,?)",
            (
                name,
                (root / "static/uploads/team_logos" / name).read_bytes(),
                (root / "instance/team_logo_originals" / name).read_bytes(),
            ),
        )
    return name


def _apply_form(conn, endpoint, event_id, group, slot, now):
    account, admin, fields = session.get("user_id"), session.get("admin_id"), request.form
    if endpoint.startswith("event_registration_"):
        return _manage_form(conn, endpoint, event_id, group, slot, account, admin, now)
    if account is None:
        raise SliceError("请先使用选手账号登录", 401)
    if endpoint == "event_register":
        my_slot = _digit(fields.get("my_slot"))
        reservations = {
            s: (fields.get(f"pname_{s}", ""), fields.get(f"psteam_{s}", ""))
            for s in range(5)
            if s != my_slot and (fields.get(f"pname_{s}") or fields.get(f"psteam_{s}"))
        }
        group = registration.create_group(
            conn,
            event_id,
            account,
            fields.get("team_name", ""),
            roster_slot=my_slot,
            reservations=reservations,
            now=now,
        )
        upload = request.files.get("team_logo")
        if upload and upload.filename:
            logo = _badge(conn, current_app.config["ENTRANT_WORKSPACE"], upload)
            registration.manage_group(conn, event_id, group, account, "logo", now=now, logo=logo)
    elif endpoint in ("event_register_individual", "event_register_substitute"):
        pref = fields.get("preferred_registration_id")
        registration.enroll(
            conn,
            event_id,
            account,
            "individual" if endpoint == "event_register_individual" else "independent_reserve",
            preferred_group_id=_digit(pref) if pref else None,
            now=now,
        )
    elif endpoint == "event_withdraw_individual":
        if not conn.execute(
            "SELECT 1 FROM registration_entry WHERE event_id=? AND account_id=? AND registration_origin<>'group'",
            (event_id, account),
        ).fetchone():
            raise SliceError("没有找到你的个人或候补报名", 404)
        registration.withdraw(conn, event_id, account, now=now)
    elif endpoint == "event_join_slot":
        registration.join_group(conn, event_id, group, account, slot, now=now)
    elif endpoint == "event_leave_slot":
        registration.leave_slot(conn, event_id, group, slot, account, now=now)


def _manage_form(conn, endpoint, event_id, group, slot, account, admin, now):
    fields = request.form
    if endpoint == "event_registration_rename":
        name = fields.get("team_name", "").strip()
        if not 2 <= len(name) <= 40:
            raise SliceError("队伍名需要为 2 至 40 个字符", 400)
        registration.rename_group(conn, event_id, group, account, name, admin_id=admin, now=now)
    elif endpoint == "event_registration_update_member":
        registration.set_reservation(
            conn,
            event_id,
            group,
            account,
            slot,
            fields.get("player_name", ""),
            fields.get("steam_id", ""),
            now=now,
            admin_id=admin,
        )
    else:
        action = {
            "event_registration_upload_logo": "logo",
            "event_registration_remove_logo": "logo",
            "event_registration_remove_member": "remove",
            "event_registration_transfer_captain": "captain",
            "event_registration_dissolve": "dissolve",
        }[endpoint]
        logo = None
        if endpoint == "event_registration_upload_logo":
            # Permission/deadline is checked before processing an uploaded image.
            registration.authorize_group_edit(
                conn, event_id, group, account, admin_id=admin, now=now
            )
            logo = _badge(
                conn, current_app.config["ENTRANT_WORKSPACE"], request.files.get("team_logo")
            )
        registration.manage_group(
            conn, event_id, group, account, action, admin_id=admin, slot=slot, logo=logo, now=now
        )


def install_writes(app, connect):
    from utils.web_helpers import csrf_required

    @csrf_required
    def legacy_form(event_id, reg_id=None, slot=None):
        endpoint = request.endpoint
        assert endpoint is not None
        ajax = (
            request.headers.get("X-Requested-With") == "XMLHttpRequest"
            and endpoint != "event_register"
        )
        try:
            # Site rate-limit storage has its own transaction: run before taking our writer lock.
            from utils.rate_limiter import rate_limit

            if endpoint in ("event_register", "event_register_substitute") and not rate_limit(
                endpoint, 10, 3600, by_ip=True
            ):
                raise SliceError("报名操作过于频繁，请稍后再试", 429)
            with closing(connect()) as conn, write(conn):
                _apply_form(conn, endpoint, event_id, reg_id, slot, int(time.time()))
        except SliceError as exc:
            if ajax:
                return jsonify(success=False, error=str(exc)), exc.status
            flash(str(exc), "error")
        else:
            message = FORM_MESSAGES[endpoint]
            if ajax:
                from .legacy import render_legacy_registration

                return jsonify(
                    success=True,
                    message=message,
                    html=render_legacy_registration(event_id, connect),
                )
            flash(message, "success")
        return redirect(url_for("event_detail", event_id=event_id))

    for name in FORM_MESSAGES:
        app.view_functions[name] = legacy_form

    @app.post("/admin/entrant-slice/events", endpoint="entrant_create_event")
    @csrf_required
    def create():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise SliceError("请求须为 JSON 对象", 400)
        with closing(connect()) as conn, write(conn):
            event = registration.create_event(
                conn,
                _text(body.get("name")),
                _text(body.get("slug")),
                _integer(body.get("registration_deadline")),
                admin_id=session.get("admin_id"),
                now=int(time.time()),
                starts_at=_integer(body["starts_at"])
                if body.get("starts_at") is not None
                else None,
                ends_at=_integer(body["ends_at"]) if body.get("ends_at") is not None else None,
            )
        return jsonify(event_id=event), 201

    @app.get("/admin/entrant-slice/events/<int:event_id>", endpoint="entrant_inspect")
    def inspect(event_id):
        with closing(connect()) as conn:
            conn.execute("BEGIN")
            require_admin(conn, session.get("admin_id"))
            row = conn.execute(
                """SELECT ee.*,b.formed_at,b.formation_revision FROM entrant_event ee
                              LEFT JOIN formation_batch b USING(event_id) WHERE ee.event_id=?""",
                (event_id,),
            ).fetchone()
            if row is None:
                raise SliceError("本届赛事不存在", 404)
            return jsonify(
                **dict(row),
                entrants=[
                    formation.get_roster(conn, event_id, e[0])
                    for e in conn.execute(
                        "SELECT event_entrant_id FROM event_entrant WHERE event_id=? ORDER BY event_entrant_id",
                        (event_id,),
                    )
                ],
                reserve_candidates=[
                    dict(c)
                    for c in conn.execute(
                        """SELECT c.player_id,e.registration_origin,e.preferred_group_id,
                    c.assigned_entrant_id FROM reserve_candidate c JOIN registration_entry e USING(event_id,player_id)
                    WHERE c.event_id=? AND c.withdrawn_at IS NULL ORDER BY c.player_id""",
                        (event_id,),
                    )
                ],
            )

    def id_list(value):
        if not isinstance(value, list) or not value:
            raise SliceError("请选择名单或参赛方", 400)
        return [_integer(x) for x in value]

    @app.post(
        "/admin/entrant-slice/events/<int:event_id>/<action>", endpoint="entrant_admin_action"
    )
    @csrf_required
    def admin_action(event_id, action):
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise SliceError("请求须为 JSON 对象", 400)
        admin = session.get("admin_id")
        with closing(connect()) as conn, write(conn):
            require_admin(conn, admin)
            now = int(time.time())
            if action == "form-due":
                result = formation.form_due_event(conn, event_id, now=now)
            elif action == "link-club":
                registration.link_club(
                    conn,
                    event_id,
                    _integer(body.get("registration_group_id")),
                    _integer(body.get("club_id")),
                    admin_id=admin,
                    now=now,
                )
                result = {"event_id": event_id}
            elif action == "archive":
                registration.archive_event(conn, event_id, admin_id=admin, now=now)
                result = {"event_id": event_id}
            elif action == "review-reservation":
                account = body.get("verified_account_id")
                registration.review_reservation(
                    conn,
                    event_id,
                    _integer(body.get("registration_group_id")),
                    _digit(body.get("roster_slot")),
                    _integer(account) if account is not None else None,
                    admin_id=admin,
                    reason=_text(body.get("reason")),
                    now=now,
                )
                result = {"event_id": event_id}
            elif action in (
                "confirm-initial",
                "adjust-formation",
                "assign-reserve",
                "replace-before-series",
            ):
                revision = _integer(body.get("expected_revision"))
                if action == "confirm-initial":
                    if set(body) != {"event_entrant_ids", "expected_revision"}:
                        raise SliceError("确认只能冻结当前五人，不接受替换名单或额外字段", 400)
                    result = formation.confirm_initial_rosters(
                        conn,
                        event_id,
                        id_list(body.get("event_entrant_ids")),
                        expected_revision=revision,
                        admin_id=admin,
                        now=now,
                    )
                elif action == "adjust-formation":
                    groups = body.get("assignments")
                    if not isinstance(groups, dict):
                        raise SliceError("需要分组后的五人名单", 400)
                    result = formation.adjust_formation(
                        conn,
                        event_id,
                        {_digit(k): id_list(v) for k, v in groups.items()},
                        expected_revision=revision,
                        admin_id=admin,
                        now=now,
                        reason=_text(body.get("reason")),
                    )
                elif action == "assign-reserve":
                    excluded = body.get("excluded_candidates", {})
                    if not isinstance(excluded, dict):
                        raise SliceError("排除候补时需给出各自的协商依据", 400)
                    result = formation.assign_reserve(
                        conn,
                        event_id,
                        _integer(body.get("event_entrant_id")),
                        _integer(body.get("player_id")),
                        excluded_candidates={_digit(k): _text(v) for k, v in excluded.items()},
                        expected_revision=revision,
                        admin_id=admin,
                        now=now,
                        reason=_text(body.get("reason")),
                    )
                else:
                    result = formation.replace_before_series(
                        conn,
                        event_id,
                        _integer(body.get("event_entrant_id")),
                        _integer(body.get("outgoing_player_id")),
                        _integer(body.get("incoming_player_id")),
                        expected_revision=revision,
                        admin_id=admin,
                        now=now,
                        reason=_text(body.get("reason")),
                    )
            else:
                raise SliceError("本切片没有这个操作", 404)
        return jsonify(result)

    @app.errorhandler(SliceError)
    def business_error(exc):
        return jsonify(success=False, error=str(exc)), exc.status

    allowed_reads = {
        "static",
        "event_detail",
        "events_list",
        "api_broadcast_events",
        "api_broadcast_event",
        "api_broadcast_matches",
        "current_csrf_token",
        "captcha_image",
        "reload_captcha",
        "serve_map_resource",
        "serve_font_resource",
        "notification_unread_count",
        "entrant_inspect",
        "user_login",
        "admin.admin_login",
        "user_logout",
        "admin.admin_logout",
    }

    def isolate_surface():
        endpoint = request.endpoint
        if (
            endpoint == "serve_resource"
            and request.method in ("GET", "HEAD", "OPTIONS")
            and (request.view_args or {}).get("filename") == "placeholders/ImageNotFound.jpg"
        ):
            return None
        if endpoint == "static":
            name = (request.view_args or {}).get("filename", "").replace("\\", "/")
            if name.startswith("uploads/team_logos/"):
                with closing(connect()) as conn:
                    row = conn.execute(
                        "SELECT public_png FROM registration_logo WHERE filename=?",
                        (name.removeprefix("uploads/team_logos/"),),
                    ).fetchone()
                if row:
                    return send_file(BytesIO(row[0]), mimetype="image/png")
            if name.split("/")[0].lower() in {"avatars", "uploads", "demos"} or ".." in name.split(
                "/"
            ):
                abort(404)
        if endpoint in allowed_reads and request.method in ("GET", "HEAD", "OPTIONS"):
            return None
        if endpoint in {
            "user_login",
            "admin.admin_login",
            "user_logout",
            "admin.admin_logout",
            "entrant_create_event",
            "entrant_admin_action",
            *FORM_MESSAGES,
        }:
            return None
        if request.method == "GET" and request.path == "/":
            return redirect(url_for("events_list"))
        return jsonify(success=False, error="隔离实例未接管这个操作，原网站没有被更改"), 404

    # Do not let an unrelated legacy route execute or start external work on this preview.
    app.before_request_funcs.setdefault(None, []).insert(0, isolate_surface)
