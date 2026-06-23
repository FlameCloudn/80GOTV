"""Admin Blueprint assembly entry."""

from flask import Blueprint

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

# Importing these modules registers their pages on admin_bp.
from blueprints import (  # noqa: E402,F401
    admin_catalog,
    admin_core,
    admin_events,
    admin_matches,
    admin_news,
    admin_operations,
)
