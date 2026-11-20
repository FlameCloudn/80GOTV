"""Read official revisions and their consequences without changing current results."""

import json

from src.website.domains.operations.run_control import match_run
from src.website.domains.statistics.statistics import read_fields


def read_result_history(conn, match_id):
    maps = [
        dict(r)
        for r in conn.execute(
            "SELECT s.map_order,o.* FROM scheduled_maps s JOIN official_map_results o USING(scheduled_map_id) "
            "WHERE s.match_id=? ORDER BY s.map_order,o.revision",
            (match_id,),
        )
    ]
    series = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM series_settlements WHERE match_id=? ORDER BY revision", (match_id,)
        )
    ]
    for item in series:
        item["map_result_ids"] = json.loads(item["map_result_ids"])
    predictions = [
        dict(r)
        for r in conn.execute(
            "SELECT c.* FROM prediction_settlement_changes c JOIN series_settlements s USING(settlement_id) "
            "WHERE s.match_id=? ORDER BY s.revision,c.vote_id",
            (match_id,),
        )
    ]
    bracket = [
        dict(r)
        for r in conn.execute(
            "SELECT c.* FROM bracket_settlement_changes c JOIN series_settlements s USING(settlement_id) "
            "WHERE s.match_id=? ORDER BY s.revision,c.target_match_id,c.target_side",
            (match_id,),
        )
    ]
    retained = [
        dict(r)
        for r in conn.execute(
            "SELECT d.*,s.revision,s.actor,s.reason,s.recorded_at FROM bracket_retention_decisions d "
            "JOIN series_settlements s USING(settlement_id) WHERE d.source_match_id=? "
            "ORDER BY s.revision,d.target_match_id,d.target_side",
            (match_id,),
        )
    ]
    return {
        "maps": maps,
        "series": series,
        "bracket": bracket,
        "retained": retained,
        "predictions": predictions,
    }


def read_player_stats(conn, match_id, run_id, player_id, scope, *, include_history=False):
    match_run(conn, match_id, run_id)
    result = read_fields(conn, run_id, player_id, scope)
    if include_history:
        revisions = []
        for row in conn.execute(
            "SELECT revision,source,source_ref,method,actor,reason,changes_json,created_at "
            "FROM run_stats_revisions WHERE map_run_id=? AND player_id=? AND scope=? ORDER BY revision",
            (run_id, player_id, scope),
        ):
            item = dict(row)
            item["changes"] = json.loads(item.pop("changes_json"))
            revisions.append(item)
        result["history"] = revisions
    return result
