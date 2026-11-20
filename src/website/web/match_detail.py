"""Public, read-only match detail routes."""

from contextlib import closing

from flask import current_app, render_template, request, session

from src.website.domains.matches.match_references import resolve_match_ref
from src.website.runtime.database import get_db
from src.website.web.routing import canonical_match_redirect, site_routes

from ..domains.matches.read_detail import build_match_detail_context, build_match_detailed_context


@site_routes.route("/matches/<slug>/stats")
@site_routes.route("/matches/<slug>")
def match_detail(slug):
    """比赛详情（支持 slug 或数字 ID；ID 访问时 301 跳转到 slug 版）"""
    match = resolve_match_ref(slug)
    if not match:
        return "比赛不存在", 404
    suffix = "/stats" if request.path.endswith("/stats") else ""
    if response := canonical_match_redirect("match_detail", slug, match, suffix=suffix):
        return response
    with closing(get_db()) as conn:
        context = build_match_detail_context(
            conn,
            match["id"],
            user_id=session.get("user_id"),
            show_stats=request.path.endswith("/stats"),
            instance_path=current_app.instance_path,
            static_folder=current_app.static_folder,
            demo_root=current_app.config.get("HOST_DEMO_ROOT"),
        )
    if context is None:
        return "比赛不存在", 404
    return render_template("public/matches/match_detail.html", **context)


@site_routes.route("/matches/<slug>/detailed")
def match_detailed_stats(slug):
    """HLTV 风格的比赛详细数据页。"""
    match = resolve_match_ref(slug)
    if not match:
        return "比赛不存在", 404
    if response := canonical_match_redirect("match_detailed_stats", slug, match):
        return response
    selected_tab = (request.args.get("tab") or "overview").strip().lower()
    if selected_tab not in ("overview", "performance"):
        selected_tab = "overview"
    with closing(get_db()) as conn:
        context = build_match_detailed_context(
            conn,
            match["id"],
            requested_map=(request.args.get("map") or "all").strip().lower(),
            selected_tab=selected_tab,
        )
    if not context:
        return "比赛不存在", 404
    return render_template("public/matches/match_detailed.html", **context)
