"""Public awards page."""

from flask import render_template

from src.website.domains.awards.public_awards import _award_groups
from src.website.runtime.database import get_db
from src.website.web.routing import site_routes


@site_routes.route("/awards")
def awards_page():
    """独立荣誉堂页面。"""
    conn = get_db()
    event_groups, champions = _award_groups(conn)
    conn.close()
    return render_template(
        "public/stats/awards.html", event_groups=event_groups, championship_teams=champions
    )
