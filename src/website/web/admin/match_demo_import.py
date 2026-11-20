"""Historical Demo upload and import HTTP endpoints."""

import json
import os
import re
import shutil
import tempfile
import uuid

from flask import flash, redirect, render_template, request, url_for

from src.website.domains.demos.demo_naming import build_demo_filename
from src.website.domains.demos.preview import analyze_demo
from src.website.domains.matches.match_utils import get_demo_upload_slot_count
from src.website.domains.matches.opponents import supplement_temp_teams
from src.website.runtime.database import get_db, row_get
from src.website.runtime.host import is_managed_match
from src.website.runtime.storage import site_paths
from src.website.web.access import admin_required as login_required
from src.website.web.access import csrf_required
from src.website.web.admin.admin import admin_bp
from src.website.web.localization import t as ui_message
from src.website.workflows.demo_import import import_demo_data


def _render_import_demo(match, **context):
    return render_template(
        "admin/operations/import_demo.html",
        match=match,
        demo_slot_count=get_demo_upload_slot_count(match),
        **context,
    )


def _invalid_demo_upload_fields(files, slot_count):
    invalid = []
    for field, file in files.items():
        if not field.startswith("demo_file_") or not file or not file.filename:
            continue
        match = re.fullmatch(r"demo_file_(\d+)", field)
        if not match or int(match.group(1)) >= slot_count:
            invalid.append(field)
    return invalid


@admin_bp.route("/matches/<int:match_id>/import-demo", methods=["GET", "POST"])
@csrf_required
@login_required
def admin_import_demo(match_id):
    conn = get_db()
    if is_managed_match(conn, match_id):
        if request.method == "GET":
            conn.close()
            return redirect(url_for("admin.managed_match_operate", match_id=match_id) + "#demos")
        has_run = conn.execute(
            "SELECT 1 FROM map_runs r JOIN scheduled_maps s USING(scheduled_map_id) WHERE s.match_id=? LIMIT 1",
            (match_id,),
        ).fetchone()
        conn.close()
        if not has_run:
            return "本场尚没有可以关联录像的实际开局。", 409
        from src.website.web.admin.match_operation_demos import managed_import_post

        return managed_import_post(match_id)
    match = conn.execute(
        """SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
        e.name AS event_name, e.short_name AS event_short_name
        FROM matches m LEFT JOIN teams t1 ON m.team1_id=t1.id LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id WHERE m.id=?""",
        (match_id,),
    ).fetchone()
    if not match:
        conn.close()
        return "比赛不存在", 404
    match = supplement_temp_teams(match, conn)
    demo_slot_count = get_demo_upload_slot_count(match)
    if request.method == "POST":
        step = request.form.get("step", "analyze")
        if step == "analyze":
            invalid_fields = _invalid_demo_upload_fields(request.files, demo_slot_count)
            if invalid_fields:
                flash(
                    ui_message(
                        "flash.match_demo_import.this_match_allows_up_to_demo",
                        demo_slot_count=demo_slot_count,
                    ),
                    "error",
                )
                conn.close()
                return _render_import_demo(match)
            previews = []
            tmpdirs = []
            has_file = False
            for i in range(demo_slot_count):
                field = f"demo_file_{i}"
                if field not in request.files:
                    continue
                file = request.files[field]
                if not file or not file.filename or not file.filename.lower().endswith(".dem"):
                    continue
                has_file = True
                tmpdir = tempfile.mkdtemp(prefix=f"demo_import_{i}_")
                tmpdirs.append(tmpdir)
                demo_path = os.path.join(tmpdir, "upload.dem")
                file.save(demo_path)
                try:
                    pv = analyze_demo(conn, match, demo_path)
                    demo_dir = site_paths().demos
                    demo_dir.mkdir(parents=True, exist_ok=True)
                    map_slot = int(pv.get("map_slot", i))
                    if not 0 <= map_slot < demo_slot_count:
                        raise ValueError(f"地图编号超出当前比赛范围：{map_slot + 1}")
                    map_name = row_get(match, f"map{map_slot + 1}", "") or pv.get("map_name", "")
                    demo_filename = build_demo_filename(
                        match_id, map_slot, match["event_short_name"], map_name
                    )
                    # Keep the previous file intact until the new reference is committed.
                    demo_stem, demo_ext = os.path.splitext(demo_filename)
                    demo_filename = f"{demo_stem}_{uuid.uuid4().hex}{demo_ext}"
                    shutil.copy2(demo_path, demo_dir / demo_filename)
                    existing_raw = row_get(match, "demo_file", "") or "[]"
                    demo_list = (
                        json.loads(existing_raw) if existing_raw and existing_raw != "[]" else []
                    )
                    while len(demo_list) <= map_slot:
                        demo_list.append(None)
                    demo_list[map_slot] = demo_filename
                    conn.execute(
                        "UPDATE matches SET demo_file=? WHERE id=?",
                        (json.dumps(demo_list, ensure_ascii=False), match_id),
                    )
                    conn.commit()
                    match["demo_file"] = json.dumps(demo_list, ensure_ascii=False)
                    previews.append(pv)
                except Exception as e:
                    conn.rollback()
                    flash(
                        ui_message(
                            "flash.match_demo_import.demo_value1_analysis_failed_value2",
                            value1=i + 1,
                            value2=str(e),
                        ),
                        "error",
                    )
            for d in tmpdirs:
                shutil.rmtree(d, ignore_errors=True)
            if not has_file:
                flash(ui_message("flash.match_demo_import.select_at_least_one_dem_file"), "error")
                conn.close()
                return _render_import_demo(match)
            if not previews:
                conn.close()
                return _render_import_demo(match)
            all_demo_data = json.dumps(previews, ensure_ascii=False)
            conn.close()
            return _render_import_demo(match, previews=previews, all_demo_data=all_demo_data)
        elif step in ("import_single", "import_all"):
            conn.execute("BEGIN TRANSACTION")
            try:
                if step == "import_single":
                    demo_data_str = request.form.get("demo_data", "{}")
                    map_slot = request.form.get("map_slot", 0)
                    result, msg = import_demo_data(conn, match_id, match, demo_data_str, map_slot)
                    if result is None:
                        conn.rollback()
                        flash(msg, "error")
                    else:
                        conn.commit()
                        flash(msg, "success")
                else:
                    all_demo_data = json.loads(request.form.get("all_demo_data", "[]"))
                    if not isinstance(all_demo_data, list) or not all_demo_data:
                        raise ValueError("请选择至少一个有效 Demo，未保存任何导入数据")
                    imported_count = 0
                    messages = []
                    for pv in all_demo_data:
                        if not isinstance(pv, dict):
                            raise ValueError("Demo 数据格式无效，整批导入未保存")
                        result, msg = import_demo_data(
                            conn, match_id, match, pv.get("demo_data", "{}"), pv.get("map_slot", 0)
                        )
                        if result is None or result <= 0:
                            raise ValueError(f"{msg}；整批导入未保存")
                        imported_count += 1
                        messages.append(msg)
                    conn.commit()
                    for msg in messages:
                        flash(msg, "info")
                    flash(
                        ui_message(
                            "flash.match_demo_import.bulk_import_complete_imported_count_demos",
                            imported_count=imported_count,
                        ),
                        "success",
                    )
            except Exception as e:
                conn.rollback()
                flash(
                    ui_message("flash.match_demo_import.import_failed_value1", value1=str(e)),
                    "error",
                )
            conn.close()
            return redirect(url_for("admin.admin_match_stats", match_id=match_id))
    conn.close()
    return _render_import_demo(match)
