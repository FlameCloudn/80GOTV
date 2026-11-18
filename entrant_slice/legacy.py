"""Project the entrant preview onto the original event readers, without old writes."""

from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from sqlite3 import Connection

from flask import (
    Flask,
    before_render_template,
    current_app,
    has_request_context,
    render_template,
    request,
)

_PROJECTION = Path(__file__).with_name("legacy_projection.sql").read_text(encoding="utf-8")


def _projected_connection(connect: Callable[[], Connection]) -> Connection:
    conn = connect()
    try:
        conn.executescript(_PROJECTION)
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")  # The old reader queries substitutes and teams separately.
    except BaseException:
        conn.close()
        raise
    return conn


def render_legacy_registration(event_id: int, connect: Callable[[], Connection]) -> str:
    """The actual registration partial, called only after a new-owner write commits."""
    from routes import events

    with closing(_projected_connection(connect)) as conn:
        row = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        event = events.add_effective_event_status(row)
        current_user = events._get_registration_user(conn)
        registrations = events._load_event_registrations(conn, event_id)
        individual_registration = events._load_individual_registrations(
            conn, event_id, current_user["id"] if current_user else None
        )
    return render_template(
        "_event_registration_list.html",
        event=event,
        registrations=registrations,
        individual_registration=individual_registration,
        individual_registration_open=events._individual_registration_is_open(),
        substitute_registration_open=event["effective_event_status"] != "completed",
        current_user=current_user,
    )


def install_legacy_reads(app: Flask, connect: Callable[[], Connection]) -> None:
    """Install only on the isolated preview app, before it handles any request."""
    from routes import broadcast, events

    def scoped_connection(
        ordinary_connect: Callable[[], Connection], *read_endpoints: str
    ) -> Callable[[], Connection]:
        def get_db() -> Connection:
            if (
                has_request_context()
                and current_app == app
                and request.method in {"GET", "HEAD"}
                and request.endpoint in read_endpoints
            ):
                return _projected_connection(connect)
            return ordinary_connect()

        return get_db

    events.get_db = scoped_connection(events.get_db, "event_detail")
    broadcast.get_db = scoped_connection(
        broadcast.get_db, "api_broadcast_events", "api_broadcast_event"
    )

    @before_render_template.connect_via(app)
    def show_entrant_roster(sender, template, context, **extra):
        full_page = request.endpoint == "event_detail" and template.name == "event_detail.html"
        if not full_page and template.name != "_event_registration_list.html":
            return
        event = context["event"]
        if not event:
            return
        with closing(connect()) as conn:
            owned = conn.execute(
                "SELECT archived_at FROM entrant_event WHERE event_id=?", (event["id"],)
            ).fetchone()
            if owned is None:
                return
            closed = (
                owned["archived_at"] is not None
                or event["status"] == "completed"
                or event["effective_event_status"] == "completed"
            )
            reserve_open = not closed
            if closed:
                event["registration_open"] = 0
            context["entrant_slice_event"] = True
            context["entrant_registration_closed"] = closed
            context["entrant_reserve_signup_open"] = reserve_open
            context["entrant_reserve_only"] = (
                reserve_open
                and event["start_date"]
                and not event["registration_open"]
                and event["effective_event_status"] != "upcoming"
            )
            context["substitute_registration_open"] = reserve_open
            if event["registration_open"]:
                # A standalone reserve before the deadline does not close normal individual signup.
                individual = context["individual_registration"]
                individual["has_assignment"] = any(
                    entry["assignment_status"] == "assigned" for entry in individual["entries"]
                )
            if not full_page or context["matches"]:
                return

            # The existing team cards otherwise derive exclusively from scheduled matches.
            rows = conn.execute(
                """
                SELECT entrant.event_entrant_id, g.display_name, g.logo, g.club_id,
                       club.short_name, p.id AS player_id, p.nickname, p.avatar, active.roster_slot
                FROM event_entrant entrant
                JOIN initial_roster frozen USING (event_entrant_id)
                JOIN registration_group g USING (registration_group_id)
                JOIN entrant_member active USING (event_entrant_id)
                JOIN players p ON p.id=active.player_id
                LEFT JOIN teams club ON club.id=g.club_id
                WHERE entrant.event_id=?
                ORDER BY g.club_id IS NULL, g.display_name, entrant.event_entrant_id, active.roster_slot
                """,
                (event["id"],),
            ).fetchall()
        teams = {}
        for row in rows:
            team = teams.setdefault(
                row["event_entrant_id"],
                {
                    "id": row["club_id"],
                    "name": row["display_name"],
                    "short_name": row["short_name"] or "",
                    "logo": row["logo"],
                    "is_temp": row["club_id"] is None,
                    "players": [],
                },
            )
            team["players"].append(
                {
                    "id": row["player_id"],
                    "nickname": row["nickname"],
                    "avatar": row["avatar"],
                    "slot": row["roster_slot"] + 1,
                }
            )
        context["teams"] = list(teams.values())
