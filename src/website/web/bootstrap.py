"""为每个 Flask 实例绑定公共行为。"""

from werkzeug.middleware.proxy_fix import ProxyFix

from src.website.domains.directory.team_names import team_abbr
from src.website.domains.events.arg_event_service import (
    ARG_EVENT_DATE,
    ARG_EVENT_FORMAT,
    is_arg_event,
)
from src.website.domains.events.event_references import event_abbr, event_path
from src.website.domains.matches.match_display import match_opponents
from src.website.runtime.database import close_request_connections
from src.website.web.localization import register_localization
from src.website.web.presentation.filters import (
    bilibili_embed_filter,
    cn_time_filter,
    compact_date_display_filter,
    date_display_filter,
    date_range_display_filter,
    datetime_display_filter,
    json_loads_filter,
    map_background_filter,
    map_display_cn_filter,
    map_display_filter,
    map_image_filter,
    map_pool_label_filter,
    rating_class_filter,
    rating_desc_filter,
    registration_team_abbr_filter,
    relative_date_display_filter,
    time_display_filter,
)
from src.website.web.presentation.private_remarks import (
    private_name_for_player,
    private_name_for_user,
    private_remark_for_player,
    private_remark_for_user,
)
from src.website.web.presentation.seo import canonical_page_url, public_site_url
from src.website.web.presentation.site_context import (
    _csrf_context,
    avatar_thumbnail_url,
    team_logo_url_filter,
    versioned_url,
)
from src.website.web.read_models.news_references import news_path
from src.website.web.request_policy import (
    _add_no_cache_headers,
    _block_public_demo_static,
    _csrf_before_request,
    _enforce_public_https,
    _limit_request_body,
    _reject_cross_site_writes,
    _require_profile_completion_before_request,
    _require_site_login,
    _start_timer,
)
from src.website.web.site_endpoints import (
    _handle_exception,
    favicon,
    healthz,
    public_avatar,
    public_upload,
    robots_txt,
    serve_font_resource,
    serve_map_resource,
    serve_resource,
)


def configure_web(app):
    """Register shared request behavior on this application instance."""
    app.jinja_env.auto_reload = True
    register_localization(app)
    app.teardown_request(close_request_connections)
    if app.config["TRUST_PROXY"]:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    app.template_filter("json_loads")(json_loads_filter)
    app.template_filter("cn_time")(cn_time_filter)
    app.template_filter("compact_date_display")(compact_date_display_filter)
    app.template_filter("date_display")(date_display_filter)
    app.template_filter("date_range_display")(date_range_display_filter)
    app.template_filter("datetime_display")(datetime_display_filter)
    app.template_filter("relative_date_display")(relative_date_display_filter)
    app.template_filter("time_display")(time_display_filter)
    app.template_filter("map_image")(map_image_filter)
    app.template_filter("map_background")(map_background_filter)
    app.template_filter("map_display")(map_display_filter)
    app.template_filter("map_display_cn")(map_display_cn_filter)
    app.template_filter("map_pool_label")(map_pool_label_filter)
    app.template_filter("rating_class")(rating_class_filter)
    app.template_filter("rating_desc")(rating_desc_filter)
    app.template_filter("registration_team_abbr")(registration_team_abbr_filter)
    app.template_filter("team_abbr")(team_abbr)
    app.template_filter("event_abbr")(event_abbr)
    app.template_filter("bilibili_embed")(bilibili_embed_filter)
    app.jinja_env.globals["event_path"] = event_path
    app.jinja_env.globals["is_arg_event"] = is_arg_event
    app.jinja_env.globals["arg_event_date"] = ARG_EVENT_DATE
    app.jinja_env.globals["arg_event_format"] = ARG_EVENT_FORMAT
    app.jinja_env.globals["news_path"] = news_path
    app.jinja_env.globals["match_opponents"] = match_opponents
    app.jinja_env.globals["public_site_url"] = public_site_url
    app.jinja_env.globals["canonical_page_url"] = canonical_page_url
    app.jinja_env.globals["private_name_for_player"] = private_name_for_player
    app.jinja_env.globals["private_name_for_user"] = private_name_for_user
    app.jinja_env.globals["private_remark_for_player"] = private_remark_for_player
    app.jinja_env.globals["private_remark_for_user"] = private_remark_for_user

    app.before_request(_start_timer)
    app.before_request(_limit_request_body)
    app.before_request(_enforce_public_https)
    app.before_request(_reject_cross_site_writes)
    app.before_request(_block_public_demo_static)
    app.before_request(_require_site_login)
    app.after_request(_add_no_cache_headers)
    app.before_request(_csrf_before_request)
    app.before_request(_require_profile_completion_before_request)
    app.template_global()(versioned_url)
    app.template_filter("team_logo_url")(team_logo_url_filter)
    app.template_global()(avatar_thumbnail_url)
    app.context_processor(_csrf_context)
    app.route("/healthz")(healthz)
    app.route("/robots.txt")(robots_txt)
    app.errorhandler(Exception)(_handle_exception)
    app.route("/favicon.ico")(favicon)
    app.route("/static/avatars/<path:filename>")(public_avatar)
    app.route("/static/uploads/<path:filename>")(public_upload)
    app.route("/resources/maps/<path:filename>")(serve_map_resource)
    app.route("/resources/fonts/<path:filename>")(serve_font_resource)
    app.route("/resources/<path:filename>")(serve_resource)
