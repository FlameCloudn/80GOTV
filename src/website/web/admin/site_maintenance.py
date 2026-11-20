"""Authenticated site maintenance: receiver diagnostics and full backup download."""

import shutil
import tempfile
from contextlib import closing

from flask import render_template, send_file

from src.website.domains.operations.inspection import read_live_diagnostics
from src.website.runtime.backup_service import create_backup_file
from src.website.runtime.database import get_db
from src.website.web.access import admin_required as login_required
from src.website.web.admin.admin import admin_bp


@admin_bp.route("/live")
@login_required
def admin_live_status():
    """Show whether GSI, GOTV and scheduled live matches are healthy."""
    with closing(get_db()) as conn:
        receivers, matches = read_live_diagnostics(conn)
    return render_template(
        "admin/operations/live_status.html", receivers=receivers, matches=matches
    )


@admin_bp.route("/backup/download")
@login_required
def admin_backup_download():
    """Download database, avatar, demo and upload files as one ZIP."""
    temp_dir = tempfile.mkdtemp(prefix="80gotv-admin-backup-")
    backup_path = create_backup_file(temp_dir, include_demos=True)
    response = send_file(
        backup_path,
        mimetype="application/zip",
        as_attachment=True,
        download_name=backup_path.name,
    )
    response.call_on_close(lambda: shutil.rmtree(temp_dir, ignore_errors=True))
    return response
