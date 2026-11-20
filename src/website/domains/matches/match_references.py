"""Create and resolve canonical match URLs and historical aliases."""

from src.website.domains.events.event_references import event_short_slug
from src.website.domains.matches.match_roster_service import frozen_match_teams, managed_match_teams
from src.website.runtime.urls import slugify_url_part


def make_match_slug(team1_name, team2_name, match_time, event_short_name):
    """
    生成“赛事-队伍1-vs-队伍2-年-月-日”格式的网址名称。
    """
    event_part = event_short_slug(event_short_name) or "event"
    team1_part = slugify_url_part(team1_name, "team1")
    team2_part = slugify_url_part(team2_name, "team2")
    date_part = "date-tbd"
    if match_time:
        try:
            year, month, day = str(match_time)[:10].split("-")
            date_part = f"{int(year)}-{int(month)}-{int(day)}"
        except (TypeError, ValueError):
            pass
    return f"{event_part}-{team1_part}-vs-{team2_part}-{date_part}"[:180].rstrip("-")


def ensure_unique_match_slug(conn, match_id, slug_base):
    """保证当前网址不占用其他比赛的正式网址或旧网址。"""
    slug = slug_base
    counter = 2
    while True:
        existing = conn.execute(
            "SELECT id FROM matches WHERE slug=? AND id!=?", (slug, match_id)
        ).fetchone()
        alias = _match_alias_row(conn, slug)
        if not existing and (not alias or str(alias["match_id"]) == str(match_id)):
            return slug
        slug = f"{slug_base}-{counter}"
        counter += 1


def _match_alias_table_exists(conn):
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='match_slug_aliases'"
        ).fetchone()
    )


def _match_alias_row(conn, slug):
    if not _match_alias_table_exists(conn):
        return None
    return conn.execute("SELECT match_id FROM match_slug_aliases WHERE slug=?", (slug,)).fetchone()


def record_match_slug_alias(conn, old_slug, match_id):
    """保留旧网址，但不覆盖正式网址或指向其他比赛的旧网址。"""
    old_slug = str(old_slug or "").strip()
    if not old_slug or not match_id:
        return False
    target = conn.execute("SELECT id FROM matches WHERE id=?", (match_id,)).fetchone()
    if not target:
        return False
    canonical = conn.execute("SELECT id FROM matches WHERE slug=?", (old_slug,)).fetchone()
    if canonical and str(canonical["id"]) != str(match_id):
        return False

    existing = _match_alias_row(conn, old_slug)
    if existing:
        return str(existing["match_id"]) == str(match_id)
    if not _match_alias_table_exists(conn):
        return False
    conn.execute(
        "INSERT OR IGNORE INTO match_slug_aliases(slug,match_id) VALUES(?,?)",
        (old_slug, match_id),
    )
    saved = _match_alias_row(conn, old_slug)
    return bool(saved and str(saved["match_id"]) == str(match_id))


def resolve_match_ref(slug):
    """通过当前 slug、旧 slug 或数字 ID 找到比赛和当前规范 slug。"""
    from src.website.runtime.database import get_db

    conn = get_db()
    try:
        if str(slug).isdigit():
            row = conn.execute("SELECT id,slug FROM matches WHERE id=?", (int(slug),)).fetchone()
        else:
            row = conn.execute("SELECT id,slug FROM matches WHERE slug=?", (slug,)).fetchone()
            if not row:
                if not _match_alias_table_exists(conn):
                    return None
                row = conn.execute(
                    """SELECT m.id,m.slug FROM match_slug_aliases a
                       JOIN matches m ON m.id=a.match_id WHERE a.slug=?""",
                    (slug,),
                ).fetchone()
                if row:
                    return {"id": row["id"], "slug": row["slug"], "is_alias": True}
        return {"id": row["id"], "slug": row["slug"], "is_alias": False} if row else None
    finally:
        conn.close()


def resolve_match_slug(slug):
    """将比赛 slug 或数字 ID 统一转为数字 match_id。"""
    match = resolve_match_ref(slug)
    return match["id"] if match else None


def update_match_slug(conn, match_id):
    match = conn.execute(
        """SELECT m.id, m.event_id, m.team1_id, m.team2_id, m.roster_snapshot, m.slug, m.match_time,
                  e.short_name, e.slug AS event_slug,
                  COALESCE(NULLIF(t1.short_name,''),t1.name,r1.team_name,'tbd') AS first_name,
                  COALESCE(NULLIF(t2.short_name,''),t2.name,r2.team_name,'tbd') AS second_name
           FROM matches m JOIN events e ON e.id=m.event_id
           LEFT JOIN teams t1 ON t1.id=m.team1_id LEFT JOIN teams t2 ON t2.id=m.team2_id
           LEFT JOIN event_registrations r1 ON r1.id=m.team1_registration_id
           LEFT JOIN event_registrations r2 ON r2.id=m.team2_registration_id WHERE m.id=?""",
        (match_id,),
    ).fetchone()
    if not match:
        return
    sides = managed_match_teams(conn, match)
    if sides is not None:
        names = [sides.get(str(side), {}).get("short_name") or "tbd" for side in (1, 2)]
    else:
        frozen = frozen_match_teams(match) or {}
        names = [match["first_name"], match["second_name"]]
        for side in (1, 2):
            if (match[f"team{side}_id"] or 0) < 0 and str(side) in frozen:
                names[side - 1] = frozen[str(side)].get("name") or names[side - 1]
    base = make_match_slug(
        names[0], names[1], match["match_time"], match["short_name"] or match["event_slug"]
    )
    slug = ensure_unique_match_slug(conn, match_id, base)
    if match["slug"] != slug:
        if match["slug"]:
            record_match_slug_alias(conn, match["slug"], match_id)
        conn.execute("UPDATE matches SET slug=? WHERE id=?", (slug, match_id))
