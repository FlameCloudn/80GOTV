"""Create downloadable local backups without changing source files."""

import io
import os
import zipfile
from datetime import datetime

from config import BASE_DIR, Config


def _add_tree(archive, folder, archive_root):
    if not os.path.isdir(folder):
        return
    for root, _, files in os.walk(folder):
        for filename in files:
            source = os.path.join(root, filename)
            relative = os.path.relpath(source, folder)
            archive.write(source, os.path.join(archive_root, relative))


def create_backup_zip():
    """Return an in-memory ZIP containing the database and uploaded files."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if os.path.isfile(Config.DATABASE):
            archive.write(Config.DATABASE, "database/cs_site.db")
        _add_tree(archive, os.path.join(BASE_DIR, "static", "avatars"), "static/avatars")
        _add_tree(archive, os.path.join(BASE_DIR, "static", "demos"), "static/demos")
        _add_tree(archive, os.path.join(BASE_DIR, "static", "uploads"), "static/uploads")
        archive.writestr(
            "BACKUP_INFO.txt",
            "80GOTV backup\n"
            f"Created: {datetime.now().isoformat(timespec='seconds')}\n"
            "Includes: database, avatars, demos and uploaded images.\n",
        )
    buffer.seek(0)
    return buffer
