"""下载私有 Demo、生成海报、浏览战报的公开 HTTP 入口。"""

import logging
from contextlib import closing

from flask import (
    current_app,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
)

from src.website.domains.demos.demo_naming import build_demo_download_name
from src.website.domains.demos.demo_storage import default_download, legacy_download, private_root
from src.website.domains.matches.match_references import resolve_match_ref
from src.website.runtime.database import get_db
from src.website.runtime.host import HostError, is_managed_match
from src.website.web.presentation import poster
from src.website.web.read_models.match_report import poster_data, report_context
from src.website.web.routing import canonical_match_redirect, site_routes

logger = logging.getLogger("80gotv")


@site_routes.route("/matches/<slug>/download-demo")
def download_demo(slug):
    if not session.get("user_id") and not session.get("admin_id"):
        return redirect(url_for("user_login", next=request.full_path.rstrip("?")))
    match_ref = resolve_match_ref(slug)
    if not match_ref:
        return "比赛不存在", 404
    canonical_redirect = canonical_match_redirect("download_demo", slug, match_ref)
    if canonical_redirect:
        return canonical_redirect
    match_id = match_ref["id"]
    slot = request.args.get("slot", 0, type=int)
    with closing(get_db()) as conn:
        if is_managed_match(conn, match_id):
            if not 0 <= slot < 5:
                return "找不到这张地图的 Demo", 404
            try:
                root = private_root(
                    current_app.instance_path,
                    current_app.static_folder,
                    current_app.config.get("HOST_DEMO_ROOT"),
                )
                path, demo_id, map_name = default_download(conn, root, match_id, slot)
                download_name = build_demo_download_name(f"demo-{demo_id}.dem", slot, map_name)
                return send_file(path, as_attachment=True, download_name=download_name)
            except HostError as exc:
                if exc.status >= 500:
                    logger.warning(
                        "托管 Demo 下载失败：比赛 %s，槽 %s（%s）", match_id, slot, exc.message
                    )
                return exc.message, exc.status
            except (FileNotFoundError, NotADirectoryError):
                return "服务器找不到完整的 Demo 原件", 404
            except OSError as exc:
                logger.warning(
                    "托管 Demo 下载失败：比赛 %s，槽 %s（%s）", match_id, slot, type(exc).__name__
                )
                return "服务器暂时无法读取 Demo 原件", 503
        try:
            directory, filename, download_name = legacy_download(conn, match_id, slot)
        except HostError as exc:
            return exc.message, exc.status
    return send_from_directory(directory, filename, as_attachment=True, download_name=download_name)


@site_routes.route("/matches/<slug>/poster")
def match_poster(slug):
    match_ref = resolve_match_ref(slug)
    if not match_ref:
        return "比赛不存在", 404
    canonical_redirect = canonical_match_redirect("match_poster", slug, match_ref)
    if canonical_redirect:
        return canonical_redirect
    match_id = match_ref["id"]
    with closing(get_db()) as conn:
        data = poster_data(conn, match_id)
    if data is None:
        return "比赛不存在", 404
    return send_file(poster.generate_match_poster(*data), mimetype="image/png")


@site_routes.route("/matches/<int:match_id>/report")
def match_report(match_id):
    with closing(get_db()) as conn:
        context = report_context(conn, match_id)
    if context is None:
        return "比赛不存在", 404
    return render_template("public/matches/match_report.html", **context)
