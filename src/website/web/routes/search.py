"""Site-wide search pages and API."""

from contextlib import closing

from flask import jsonify, render_template, request

from src.website.domains.events.event_references import event_path
from src.website.domains.matches.match_display import match_opponents
from src.website.runtime.database import get_db
from src.website.web.presentation.filters import date_display_filter
from src.website.web.presentation.private_remarks import private_player_identity
from src.website.web.read_models.news_references import news_path
from src.website.web.read_models.search_service import search_catalog
from src.website.web.routing import site_routes


def _results_for_viewer(query, *, suggestions):
    with closing(get_db()) as conn:
        groups = search_catalog(conn, query, suggestions=suggestions)
    for player in groups["players"]:
        player["nickname"], player["group_username"] = private_player_identity(
            player["id"], player["nickname"], player["group_username"]
        )
    return groups


@site_routes.route("/search")
def search():
    q = request.args.get("q", "").strip()
    groups = _results_for_viewer(q, suggestions=False) if q else {}
    return render_template(
        "public/account/search.html", query=q, results=groups, has_results=any(groups.values())
    )


@site_routes.route("/api/search")
def api_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"results": []})
    groups = _results_for_viewer(q, suggestions=True)

    results = []
    for p in groups["players"]:
        results.append(
            {
                "type": "player",
                "label": p["nickname"],
                "sub": p.get("group_username")
                or ("🌐" if p.get("is_bashizhong_student") == 0 else ""),
                "url": f"/players/{p['id']}",
            }
        )
    for t in groups["teams"]:
        results.append(
            {
                "type": "team",
                "label": t["name"],
                "sub": t.get("short_name") or "",
                "url": f"/teams/{t['id']}",
            }
        )
    for e in groups["events"]:
        results.append(
            {
                "type": "event",
                "label": e["name"],
                "sub": date_display_filter(e.get("start_date") or ""),
                "url": event_path(e),
            }
        )
    for n in groups["news"]:
        results.append(
            {
                "type": "news",
                "label": n["title"],
                "sub": date_display_filter(n.get("publish_time") or ""),
                "url": news_path(n),
            }
        )
    for m in groups["matches"]:
        left_team, right_team = match_opponents(m)
        score_left = left_team["score"] if left_team["score"] is not None else "-"
        score_right = right_team["score"] if right_team["score"] is not None else "-"
        results.append(
            {
                "type": "match",
                "label": f"{left_team['short']} {score_left}:{score_right} {right_team['short']}",
                "sub": m.get("event_name") or "",
                "url": f"/matches/{m.get('slug') or m['id']}",
            }
        )

    # 搜索结果为空时返回友好提示，方便前端展示空状态
    if not results:
        return jsonify({"results": [], "empty_message": f'没有找到与"{q}"相关的结果'})

    return jsonify({"results": results})
