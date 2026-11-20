"""Assemble independent Flask application instances without opening the database."""

from pathlib import Path

from flask import Flask

from config import BASE_DIR, Config

from .runtime.storage import default_data_root, site_paths
from .web.assets import register_frontend_assets
from .web.routing import site_routes


def create_app(config=None):
    root = Path(BASE_DIR)
    paths = site_paths((config or {}).get("SITE_DATA_ROOT") or default_data_root())
    app = Flask(
        __name__,
        root_path=str(root),
        template_folder="src/website/web/templates",
        instance_path=str(paths.root),
    )
    app.config.from_object(Config)
    # Maintenance commands and the default app share the environment-derived database.
    # An explicit override belongs only to this app.
    app.config.pop("DATABASE", None)
    app.config["PROPAGATE_EXCEPTIONS"] = False
    if config is not None:
        if config.get("SITE_DATA_ROOT"):
            app.config.update(
                DATABASE=str(paths.database),
                HOST_DEMO_ROOT=str(paths.managed_demos),
                UPLOAD_FOLDER=str(paths.uploads),
            )
        app.config.update(config)

    from .web import match_detail  # noqa: F401
    from .web.admin.admin import admin_bp
    from .web.admin.match_operation_demos import match_operation_demos_bp
    from .web.bootstrap import configure_web
    from .web.routes import (  # noqa: F401
        account_profile,
        auth,
        awards,
        bp,
        bp_actions,
        bp_seats,
        broadcast,
        captcha,
        comments,
        email_verification,
        event_individual,
        event_registration,
        event_teams,
        events,
        feedback,
        forum,
        front_api,
        front_catalog,
        front_community,
        front_matches,
        games,
        guess_player,
        home,
        live,
        live_ingest,
        map_quiz,
        match_assets,
        matches,
        news,
        notifications,
        player_bingo,
        player_compare,
        players,
        predictions,
        search,
        sitemap,
        stats,
        steam_login,
        teams,
    )

    configure_web(app)
    register_frontend_assets(app)
    # Existing templates, auth and clients use the original endpoint names.
    app.register_blueprint(site_routes, name="")
    app.register_blueprint(admin_bp)
    app.register_blueprint(match_operation_demos_bp)
    return app
