"""Prepare event matches and protected bracket slots for the operations panel."""

from src.website.domains.matches.managed_bracket import _slot_protection, get_bracket_links
from src.website.domains.matches.opponents import supplement_temp_teams
from src.website.runtime.host import HostError


def bracket_context(conn, event_id, match_id, entrants):
    event_matches_raw = conn.execute(
        """SELECT m.*, t1.name AS team1_name, t1.short_name AS t1s,
                  t2.name AS team2_name, t2.short_name AS t2s
           FROM matches m
           LEFT JOIN teams t1 ON m.team1_id=t1.id LEFT JOIN teams t2 ON m.team2_id=t2.id
           WHERE m.event_id=?
           ORDER BY CASE WHEN m.match_time IS NULL OR m.match_time='' THEN 1 ELSE 0 END,
                    m.match_time, m.id""",
        (event_id,),
    ).fetchall()
    event_matches_by_id = {}
    event_matches = []
    for raw in event_matches_raw:
        event_matches_by_id[raw["id"]] = raw
        disp = supplement_temp_teams(raw, conn)
        event_matches.append(
            {
                "id": disp["id"],
                "stage": disp["stage"] or "",
                "bo_format": disp["bo_format"] or "BO3",
                "status": disp["status"],
                "match_time": disp["match_time"] or "",
                "team1_name": disp["team1_name"] or "TBD",
                "team2_name": disp["team2_name"] or "TBD",
                "team1_score": disp["team1_score"],
                "team2_score": disp["team2_score"],
            }
        )

    summaries = {match["id"]: match for match in event_matches}
    downstream_links = []
    for link in get_bracket_links(conn, event_id):
        if link["source_match_id"] != match_id:
            continue
        target_row = event_matches_by_id.get(link["target_match_id"])
        protection_reason = None
        can_retain = False
        if target_row is not None:
            try:
                protection_reason = _slot_protection(conn, target_row, link["target_side"])
                can_retain = protection_reason is not None and link["event_entrant_id"] is not None
            except HostError as exc:
                protection_reason = exc.message
        target_summary = summaries.get(link["target_match_id"])
        downstream_links.append(
            {
                **link,
                "target_stage": (target_summary or {}).get("stage", ""),
                "target_label": (
                    f"#{link['target_match_id']} "
                    f"{(target_summary or {}).get('stage') or (target_summary or {}).get('bo_format') or ''}"
                ).strip(),
                "current_entrant_name": (
                    (entrants.get(str(link["event_entrant_id"])) or {}).get("name")
                    if link["event_entrant_id"]
                    else None
                ),
                "protected": bool(protection_reason),
                "can_retain": can_retain,
                "protection_reason": protection_reason,
            }
        )

    return event_matches, downstream_links
