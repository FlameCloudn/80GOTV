"""把托管赛已配置的晋级关系读成原赛事页的对阵卡，不生成赛程或落位。"""

import json
from collections import defaultdict
from graphlib import TopologicalSorter

from services.bracket_service import get_bracket_links


def public_bracket_data(conn, event, matches):
    """matches 是原页面已按本场参赛方补齐队名、身份并排除取消场的赛程。"""
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='managed_bracket_links'"
    ).fetchone():
        return event["bracket_data"]
    by_id = {m["id"]: m for m in matches}
    graph = TopologicalSorter()
    sources = {}
    for link in get_bracket_links(conn, event["id"]):
        source, target = link["source_match_id"], link["target_match_id"]
        if source in by_id and target in by_id:
            graph.add(target, source)
            if not link.get("detached"):
                side = 1 if link["target_side"] == "home" else 2
                sources[target, side] = {link["outcome"]: f"M{source}"}
    graph.prepare()
    if not graph.is_active():
        return event["bracket_data"]

    maps = defaultdict(list)
    for row in conn.execute(
        """SELECT s.match_id,s.map_name,o.score1,o.score2 FROM matches m
           JOIN scheduled_maps s ON s.match_id=m.id
           JOIN official_map_results o ON o.scheduled_map_id=s.scheduled_map_id AND o.is_current=1
           JOIN map_runs r ON r.map_run_id=o.map_run_id AND r.status='closed'
           WHERE m.event_id=? AND s.is_enabled=1 ORDER BY s.match_id,s.map_order""",
        (event["id"],),
    ):
        maps[row["match_id"]].append(
            {"name": row["map_name"], "t1": row["score1"], "t2": row["score2"]}
        )

    rounds, teams = [], {}
    while graph.is_active():
        ready = sorted(graph.get_ready())
        stages = defaultdict(list)
        for mid in ready:
            match = by_id[mid]
            scores = maps[mid]
            wins = sum(m["t1"] > m["t2"] for m in scores)
            card = {
                "id": f"M{mid}",
                "match_id": mid,
                "status": match["status"],
                "bo_format": match["bo_format"],
                "match_time": match["match_time"],
                "score1": wins if scores else None,
                "score2": len(scores) - wins if scores else None,
                "maps": scores,
            }
            for side in (1, 2):
                field = f"team{side}"
                identity = match.get(f"_{field}_identity")
                key = f"entrant-{identity[1]}" if identity else None
                card[field] = key
                if key:
                    teams[key] = {
                        "id": key,
                        "db_id": match[f"{field}_id"],
                        "name": match[f"{field}_name"],
                        "short_name": match[f"t{side}s"],
                    }
                if (mid, side) in sources:
                    card[f"{field}_source"] = sources[mid, side]
            stages[match["stage"] or f"比赛 #{mid}"].append(card)
        rounds.extend({"name": name, "matches": cards} for name, cards in stages.items())
        graph.done(*ready)
    return json.dumps(
        {"tournament": {"rounds": rounds, "teams": list(teams.values())}}, ensure_ascii=False
    )
