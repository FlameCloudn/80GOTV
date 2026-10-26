"""Public page sitemap."""

import xml.etree.ElementTree as ET
from datetime import datetime

from flask import make_response, url_for

from models import db
from utils.seo import public_site_url
from web_app import app

SITEMAP_NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"


def _lastmod(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).strip().replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


@app.route("/sitemap.xml")
def sitemap():
    pages: list[tuple[str, str, str, str | None]] = [
        ("/", "daily", "1.0", None),
        ("/news", "daily", "0.9", None),
        ("/matches", "hourly", "0.9", None),
        ("/results", "hourly", "0.8", None),
        ("/events", "daily", "0.8", None),
        ("/players", "weekly", "0.7", None),
        ("/teams", "weekly", "0.7", None),
        ("/stats", "weekly", "0.7", None),
        ("/predictions", "weekly", "0.6", None),
        ("/dashboard", "daily", "0.7", None),
        ("/search", "weekly", "0.5", None),
        ("/forum", "daily", "0.8", None),
    ]
    sources = (
        (
            "SELECT id,slug,created_at FROM matches ORDER BY id",
            "match_detail",
            "slug",
            "daily",
            "0.8",
        ),
        (
            "SELECT id,slug,created_at FROM events ORDER BY id",
            "event_detail",
            "event_id",
            "daily",
            "0.8",
        ),
        (
            "SELECT id,created_at FROM players ORDER BY id",
            "player_detail",
            "player_id",
            "weekly",
            "0.7",
        ),
        ("SELECT id,created_at FROM teams ORDER BY id", "team_detail", "team_id", "weekly", "0.7"),
        (
            "SELECT id,created_at FROM news WHERE COALESCE(TRIM(redirect_url),'')='' ORDER BY id",
            "news_detail",
            "news_id",
            "daily",
            "0.8",
        ),
    )
    with db() as conn:
        for sql, endpoint, argument, frequency, priority in sources:
            for item in conn.execute(sql).fetchall():
                row = dict(item)
                path = url_for(endpoint, **{argument: row.get("slug") or row["id"]})
                pages.append((path, frequency, priority, _lastmod(row["created_at"])))

    ET.register_namespace("", SITEMAP_NAMESPACE)
    root = ET.Element(f"{{{SITEMAP_NAMESPACE}}}urlset")
    for path, frequency, priority, modified in pages:
        entry = ET.SubElement(root, "url")
        ET.SubElement(entry, "loc").text = public_site_url(path)
        if modified:
            ET.SubElement(entry, "lastmod").text = modified
        ET.SubElement(entry, "changefreq").text = frequency
        ET.SubElement(entry, "priority").text = priority

    response = make_response(ET.tostring(root, encoding="utf-8", xml_declaration=True))
    response.headers["Content-Type"] = "application/xml; charset=utf-8"
    return response
