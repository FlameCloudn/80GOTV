"""现场名单身份与 CT/T 对应关系，供接收端和公开比分共用。"""

from src.website.domains.matches.match_roster_service import resolve_match_roster
from src.website.domains.matches.participants import SIDE_NUMBERS


def _normalize_team_label(value):
    return "".join(character for character in str(value or "").casefold() if character.isalnum())


def roster_side_by_steamid(conn, row):
    """Map known Steam IDs to the fixed team slot used by the match."""
    return {
        steam_id: {"t1": "team1", "t2": "team2"}[side]
        for steam_id, side in resolve_match_roster(conn, row)["side_by_steam_id"].items()
    }


def roster_profiles_by_steamid(conn, row, *, run_id=None):
    """Return the exact website identity for every fixed match slot.

    Looking profiles up only by the live display name can pair a stale GSI
    name with the wrong avatar. A hosted run's lineup, not the original
    frozen roster, determines who belongs to the current attempt.
    """
    result = {}
    ambiguous = set()
    if run_id is None:
        roster = resolve_match_roster(conn, row)
        players = ((side, player) for side, slots in roster["players"].items() for player in slots)
    else:
        players = (
            (SIDE_NUMBERS[player["side_key"]], dict(player))
            for player in conn.execute(
                """SELECT l.player_id AS id,l.steam_id,l.roster_slot AS slot,m.side_key,
                          p.nickname,p.avatar,r.player_id IS NOT NULL AS has_appeared,
                          CASE WHEN f.player_id=l.player_id THEN f.is_substitute ELSE 1 END
                            AS is_substitute
                   FROM map_run_lineups l
                   JOIN match_participants m USING(match_participant_id)
                   JOIN players p ON p.id=l.player_id
                   LEFT JOIN match_roster_members f
                     ON f.match_participant_id=l.match_participant_id AND f.roster_slot=l.roster_slot
                   LEFT JOIN run_participations r
                     ON r.map_run_id=l.map_run_id AND r.player_id=l.player_id AND r.is_current=1
                   WHERE l.map_run_id=? AND m.match_id=?""",
                (run_id, row["id"]),
            )
        )
    for side, player in players:
        steam_id = str(player.get("steam_id") or "").strip()
        if not steam_id:
            continue
        if steam_id in result or steam_id in ambiguous:
            result.pop(steam_id, None)
            ambiguous.add(steam_id)
            continue
        avatar = str(player.get("avatar") or "")
        if avatar and not avatar.startswith(("/", "http://", "https://")):
            avatar = f"/static/avatars/{avatar}"
        result[steam_id] = {
            "player_id": player.get("id"),
            "name": player.get("nickname") or "",
            "avatar": avatar,
            "team": f"team{side}",
            "slot": player["slot"],
            "is_substitute": bool(player["is_substitute"]),
            "has_appeared": bool(player.get("has_appeared")),
        }
    return result


def _roster_gsi_mapping(gsi, roster_side_by_steamid):
    """Infer the current CT/T side from the registered player roster."""
    votes = {"team1": {"CT": 0, "T": 0}, "team2": {"CT": 0, "T": 0}}
    for steam_id, player in (gsi.get("allplayers", {}) or {}).items():
        team_slot = roster_side_by_steamid.get(str(steam_id))
        side = str((player or {}).get("team") or "").upper()
        if team_slot in votes and side in votes[team_slot]:
            votes[team_slot][side] += 1
    if not all(sum(votes[slot].values()) for slot in ("team1", "team2")):
        return None
    inferred = {}
    for slot, slot_votes in votes.items():
        strongest_side, strongest_count = max(slot_votes.items(), key=lambda item: item[1])
        other_count = min(slot_votes.values())
        # During knife/half-time transitions the roster can briefly contain
        # both sides.  Do not turn that transient mix into a scoreboard swap.
        if strongest_count < 3 or strongest_count <= other_count:
            return None
        inferred[slot] = strongest_side
    team1_side = inferred["team1"]
    team2_side = inferred["team2"]
    if team1_side == team2_side:
        return None
    return {
        "CT": "team1" if team1_side == "CT" else "team2",
        "T": "team1" if team1_side == "T" else "team2",
    }


def gsi_team_mapping(gsi, row, roster_side_by_steamid=None):
    roster_mapping = _roster_gsi_mapping(gsi, roster_side_by_steamid or {})
    if roster_mapping:
        return roster_mapping
    identity = (gsi.get("_80gotv") or {}) if isinstance(gsi, dict) else {}
    ct_identity = identity.get("team_ct")
    t_identity = identity.get("team_t")
    if {ct_identity, t_identity} == {"team1", "team2"}:
        return {"CT": ct_identity, "T": t_identity}

    gmap = gsi.get("map", {}) or {}
    ct_name = _normalize_team_label((gmap.get("team_ct", {}) or {}).get("name"))
    t_name = _normalize_team_label((gmap.get("team_t", {}) or {}).get("name"))
    team1_labels = {
        _normalize_team_label(row["scheduled_team1_name"]),
        _normalize_team_label(row["scheduled_team1_short"]),
    }
    team2_labels = {
        _normalize_team_label(row["scheduled_team2_name"]),
        _normalize_team_label(row["scheduled_team2_short"]),
    }
    team1_labels.discard("")
    team2_labels.discard("")
    if ct_name in team1_labels and t_name in team2_labels:
        return {"CT": "team1", "T": "team2"}
    if ct_name in team2_labels and t_name in team1_labels:
        return {"CT": "team2", "T": "team1"}
    # Guessing CT=team1 is worse than showing an unknown side: after a knife
    # round or halftime it silently swaps every score and player.
    return None
