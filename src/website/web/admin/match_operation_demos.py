"""Admin API and legacy form bridge for explicitly identified managed map runs."""

import json
from contextlib import closing

from flask import Blueprint, current_app, jsonify, request, send_file, session
from werkzeug.exceptions import RequestEntityTooLarge

from src.website.domains.demos import demo_analysis, demo_storage
from src.website.domains.demos.demo_naming import build_demo_download_name
from src.website.runtime.database import get_db
from src.website.runtime.host import HostError
from src.website.web.access import admin_required, csrf_required
from src.website.workflows import demo_review

match_operation_demos_bp = Blueprint(
    "match_operation_demos", __name__, url_prefix="/admin/matches/<int:match_id>/api/demos"
)


def demo_root():
    return demo_storage.private_root(
        current_app.instance_path,
        current_app.static_folder,
        current_app.config.get("HOST_DEMO_ROOT"),
    )


@match_operation_demos_bp.before_request
def _limit_upload():
    if any(not 0 < value <= 2**63 - 1 for value in (request.view_args or {}).values()):
        raise HostError("比赛、原件或解析编号无效", 400)
    if request.endpoint == "match_operation_demos.upload":
        maximum = demo_storage.MAX_DEMO_BYTES + 64 * 1024
        request.max_content_length = min(
            maximum, current_app.config.get("MAX_CONTENT_LENGTH") or maximum
        )


@match_operation_demos_bp.errorhandler(HostError)
def _host_error(exc):
    return jsonify(ok=False, error=exc.message), exc.status


@match_operation_demos_bp.errorhandler(RequestEntityTooLarge)
def _too_large(_exc):
    return jsonify(ok=False, error="Demo 文件超过上传大小限制"), 413


def _form_id(name):
    value = request.form.get(name, type=int)
    if value is None or not 0 < value <= 2**63 - 1:
        raise HostError("请选择有效的赛图、实际开局或解析编号", 400)
    return value


def _store_upload(conn, match_id, field):
    files = request.files.getlist(field)
    if len(files) != 1 or len(request.files) != 1 or not files[0].filename:
        raise HostError("每次请选择一份 .dem 原件", 400)
    return demo_storage.receive_original(
        conn,
        root=demo_root(),
        match_id=match_id,
        scheduled_map_id=_form_id("scheduled_map_id"),
        run_id=_form_id("map_run_id"),
        stream=files[0].stream,
        filename=files[0].filename,
        actor=session["admin_id"],
    )


def _parse_original(conn, match_id, demo_id):
    return demo_analysis.parse_original(
        conn, root=demo_root(), match_id=match_id, demo_id=demo_id, actor=session["admin_id"]
    )


@match_operation_demos_bp.get("")
@admin_required
def listing(match_id):
    with closing(get_db()) as conn:
        return jsonify(ok=True, originals=demo_storage.list_originals(conn, match_id))


@match_operation_demos_bp.post("")
@admin_required
@csrf_required
def upload(match_id):
    with closing(get_db()) as conn:
        stored = _store_upload(conn, match_id, "demo")
    return jsonify(ok=True, **stored), 200 if stored["duplicate"] else 201


@match_operation_demos_bp.get("/<int:demo_id>")
@admin_required
def original(match_id, demo_id):
    with closing(get_db()) as conn:
        detail = demo_storage.get_original_detail(conn, match_id, demo_id)
    return jsonify(ok=True, original=detail)


@match_operation_demos_bp.get("/<int:demo_id>/file")
@admin_required
def download_original(match_id, demo_id):
    with closing(get_db()) as conn:
        original = demo_storage.get_original(conn, match_id, demo_id)
    path = demo_storage.original_path(demo_root(), original)
    name = build_demo_download_name(
        f"demo-{demo_id}.dem", original["legacy_slot"] - 1, original["map_name"]
    )
    return send_file(path, as_attachment=True, download_name=name)


@match_operation_demos_bp.post("/<int:demo_id>/parse")
@admin_required
@csrf_required
def parse(match_id, demo_id):
    with closing(get_db()) as conn:
        job = _parse_original(conn, match_id, demo_id)
    ready = job["status"] == "ready"
    return jsonify(ok=ready, **job), 201 if ready else 422


@match_operation_demos_bp.get("/analyses/<int:analysis_id>")
@admin_required
def preview(match_id, analysis_id):
    with closing(get_db()) as conn:
        analysis = demo_review.preview(conn, match_id, analysis_id, actor=session["admin_id"])
    return jsonify(ok=True, analysis=analysis)


@match_operation_demos_bp.post("/adopt")
@admin_required
@csrf_required
def adopt(match_id):
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) != {"approvals"}:
        raise HostError("请提交要采纳的 Demo 预览", 400)
    with closing(get_db()) as conn:
        receipts = demo_review.adopt(
            conn, match_id, body["approvals"], root=demo_root(), actor=session["admin_id"]
        )
    return jsonify(ok=True, adoptions=receipts)


@admin_required
@csrf_required
def managed_import_post(match_id):
    """Delegate the old managed import POST here, before any legacy writes."""
    if request.method != "POST":
        return jsonify(ok=False, error="托管 Demo 表单只接受 POST"), 405
    try:
        step = request.form.get("step", "analyze")
        with closing(get_db()) as conn:
            if step == "analyze":
                field = next(iter(request.files), "demo")
                if field not in {"demo", *(f"demo_file_{i}" for i in range(5))}:
                    raise HostError("请选择一份 .dem 原件", 400)
                stored = _store_upload(conn, match_id, field)
                job = _parse_original(conn, match_id, stored["original"]["demo_id"])
                view = demo_review.preview(
                    conn, match_id, job["analysis_id"], actor=session["admin_id"]
                )
                ready = job["status"] == "ready"
                return jsonify(ok=ready, **stored, job=job, analysis=view), 201 if ready else 422
            if step == "parse":
                job = _parse_original(conn, match_id, _form_id("demo_id"))
                ready = job["status"] == "ready"
                return jsonify(ok=ready, **job), 201 if ready else 422
            if step == "preview":
                view = demo_review.preview(
                    conn, match_id, _form_id("analysis_id"), actor=session["admin_id"]
                )
                return jsonify(ok=True, analysis=view)
            if step in {"import_single", "import_all", "adopt"}:
                try:
                    approvals = json.loads(request.form.get("approvals", ""))
                except ValueError as exc:
                    raise HostError(
                        "请从托管 Demo 预览提交核准内容，不能使用旧导入数据", 400
                    ) from exc
                if step == "import_single" and (
                    not isinstance(approvals, list) or len(approvals) != 1
                ):
                    raise HostError("单图采纳必须明确选择一次 Demo 解析", 400)
                receipts = demo_review.adopt(
                    conn, match_id, approvals, root=demo_root(), actor=session["admin_id"]
                )
                return jsonify(ok=True, adoptions=receipts)
            raise HostError("未知的 Demo 表单操作", 400)
    except HostError as exc:
        return _host_error(exc)
    except RequestEntityTooLarge as exc:
        return _too_large(exc)
