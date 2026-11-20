"""Select public match and event sources for the director and broadcast HUD."""

from contextlib import contextmanager

from src.website.domains.events.arg_event_service import is_arg_event, ordinary_event_condition
from src.website.domains.matches.match_utils import (
    get_sql_effective_status,
    get_sql_match_live,
    get_sql_match_upcoming,
)
from src.website.domains.operations.projection import live_schema_ready
from src.website.runtime.host import has_event_schema, is_managed_event
from src.website.web.read_models.director_event import read_event_payload
from src.website.web.read_models.director_match import read_match_payload

_SQL_MATCH_LIVE = get_sql_match_live()
_SQL_MATCH_UPCOMING = get_sql_match_upcoming()
_SQL_EFFECTIVE_STATUS = get_sql_effective_status()
_SQL_HOSTED = "EXISTS(SELECT 1 FROM event_registration_control c WHERE c.event_id=m.event_id)"


def _match_query(where_sql):
    return f"""
        SELECT m.*, t1.name AS team1_name, t1.short_name AS t1s,
               t1.logo AS team1_logo,
               t2.name AS team2_name, t2.short_name AS t2s,
               t2.logo AS team2_logo,
               e.name AS event_name, e.short_name AS event_short_name,
               {_SQL_EFFECTIVE_STATUS}
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id
        WHERE {where_sql}
    """


@contextmanager
def _broadcast_snapshot(conn):
    # 导播一次读取的 BP 版本、地图和阵容必须来自同一次提交。
    conn.execute("SAVEPOINT broadcast_snapshot")
    try:
        yield
    finally:
        conn.execute("RELEASE broadcast_snapshot")


def _match_payload(row, conn):
    if is_managed_event(conn, row["event_id"]):
        with _broadcast_snapshot(conn):
            row = conn.execute(_match_query("m.id=?"), (row["id"],)).fetchone()
            return read_match_payload(conn, row, hosted=True)
    return read_match_payload(conn, row, hosted=False)


def _event_roster_payload(conn, event):
    if is_managed_event(conn, event["id"]):
        with _broadcast_snapshot(conn):
            event = conn.execute("SELECT * FROM events WHERE id=?", (event["id"],)).fetchone()
            return read_event_payload(conn, event, hosted=True)
    return read_event_payload(conn, event, hosted=False)


def list_matches(conn):
    live, upcoming = _SQL_MATCH_LIVE, _SQL_MATCH_UPCOMING
    if has_event_schema(conn):
        live = f"({live} AND NOT {_SQL_HOSTED}) OR ({_SQL_HOSTED} AND m.status='live')"
        upcoming = f"({upcoming} AND NOT {_SQL_HOSTED}) OR ({_SQL_HOSTED} AND m.status='upcoming')"
    rows = conn.execute(
        _match_query("1=1")
        + f"""
        ORDER BY CASE WHEN {live} THEN 0
                      WHEN {upcoming} THEN 1 ELSE 2 END,
                 datetime(m.match_time) DESC, m.id DESC
        LIMIT 100
        """
    ).fetchall()
    matches = []
    for row in rows:
        payload = _match_payload(row, conn)
        # 只有“空名单凑出来的临时队名”才过滤（例如旧测试比赛 #5）；
        # 真实临时队伍（带选手名单的 TEAM 1 / TEAM 2）必须保留。
        temp_names = ("TEAM 1", "TEAM 2")
        if (payload["team1"]["name"] in temp_names and not payload["team1"]["players"]) or (
            payload["team2"]["name"] in temp_names and not payload["team2"]["players"]
        ):
            continue
        matches.append(payload)
    return matches


def list_events(conn):
    managed_reserves = (
        """OR EXISTS (SELECT 1 FROM host_individual_entries_read h
        WHERE h.event_id=e.id AND h.assignment_status='reserve')"""
        if has_event_schema(conn)
        else ""
    )
    rows = conn.execute(
        f"""
        SELECT e.*
        FROM events e
        WHERE {ordinary_event_condition("e")} AND (EXISTS(
            SELECT 1 FROM event_registrations r
            WHERE r.event_id=e.id AND r.status='pending'
        ) OR EXISTS(
            SELECT 1 FROM event_individual_registrations ir
            WHERE ir.event_id=e.id AND ir.assignment_status='reserve'
        ) {managed_reserves})
        ORDER BY date(e.start_date) DESC, e.id DESC
        LIMIT 100
        """
    ).fetchall()
    return [_event_roster_payload(conn, row) for row in rows]


def current_match(conn):
    live = _SQL_MATCH_LIVE
    eligible = f"({_SQL_MATCH_LIVE} OR {_SQL_MATCH_UPCOMING})"
    if has_event_schema(conn):
        live = f"({live}) AND NOT {_SQL_HOSTED}"
        if live_schema_ready(conn):
            # A managed match is not live just because its scheduled time passed.
            managed_open = """EXISTS(SELECT 1 FROM event_registration_control c
                WHERE c.event_id=m.event_id AND c.archived_at IS NULL)
                AND COALESCE(e.status,'')<>'completed'"""
            authorized = "EXISTS(SELECT 1 FROM match_start_authorizations a WHERE a.match_id=m.id)"
            actual_live = f"({managed_open} AND {authorized} AND m.status='live')"
            eligible = f"""(({eligible} AND NOT {_SQL_HOSTED}) OR {actual_live}
                OR ({managed_open} AND m.status='upcoming' AND ({_SQL_MATCH_UPCOMING} OR {authorized})))"""
            live = f"(({live}) OR {actual_live})"
        else:
            eligible += """ AND NOT EXISTS(SELECT 1 FROM event_registration_control c WHERE c.event_id=m.event_id
                AND (c.archived_at IS NOT NULL OR datetime(m.match_time)<=datetime('now','localtime')))"""
    row = conn.execute(
        _match_query(eligible)
        + f"""
        ORDER BY CASE WHEN {live} THEN 0 ELSE 1 END,
                 datetime(m.match_time) ASC, m.id ASC
        LIMIT 1
        """
    ).fetchone()
    return _match_payload(row, conn) if row else None


def event_detail(conn, event_id):
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not event or is_arg_event(event):
        return None
    return _event_roster_payload(conn, event)


def match_detail(conn, match_id):
    row = conn.execute(_match_query("m.id=?"), (match_id,)).fetchone()
    return _match_payload(row, conn) if row else None
