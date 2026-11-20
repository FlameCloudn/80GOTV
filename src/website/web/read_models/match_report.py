"""赛后展示：固定对阵方、正式统计和地图时间线组成战报或海报。"""

from src.website.domains.matches.map_names import map_display_name, normalize_map_key
from src.website.domains.matches.opponents import read_opponents
from src.website.domains.operations.live_log import load_match_timeline, uses_run_timeline
from src.website.domains.statistics.match_reports import poster_ratings, report_players
from src.website.domains.statistics.stats_storage import match_stat_belongs_to_side, stats_for_slot
from src.website.runtime.database import row_get
from src.website.runtime.host import is_managed_event


def poster_data(conn, match_id):
    match = read_opponents(conn, match_id)
    if match is None:
        return None
    raw_maps = [
        (match["map1"], match["map1_t1"], match["map1_t2"], True),
        (match["map2"], match["map2_t1"], match["map2_t2"], True),
        (match["map3"], match["map3_t1"], match["map3_t2"], bool(match["has_map3"])),
        (match["map4"], match["map4_t1"], match["map4_t2"], bool(row_get(match, "has_map4", 1))),
        (match["map5"], match["map5_t1"], match["map5_t2"], bool(row_get(match, "has_map5", 1))),
    ]
    bo = (match["bo_format"] or "BO3").upper()
    if bo == "BO5":
        max_maps = 5
    elif bo == "BO3":
        max_maps = 3
    else:
        max_maps = 1

    map_scores = []
    for idx, (mn, t1, t2, active) in enumerate(raw_maps):
        if idx >= max_maps:
            break
        if idx < 2 and not mn:
            continue
        map_scores.append(
            {
                "name": mn or "TBA",
                "t1": t1,
                "t2": t2,
                "played": bool(mn and active and t1 is not None and t2 is not None),
            }
        )

    return match, map_scores, poster_ratings(conn, match_id)


def _report_timeline(conn, match, managed):
    match_id = match["id"]
    timeline = load_match_timeline(conn, match_id)
    if timeline and managed and uses_run_timeline(conn, match_id):
        run_plans = {
            row["map_run_id"]: row
            for row in conn.execute(
                """SELECT r.map_run_id,s.scheduled_map_id,s.legacy_slot,s.map_name
                   FROM scheduled_maps s JOIN map_runs r USING(scheduled_map_id)
                   WHERE s.match_id=?""",
                (match_id,),
            )
        }
        names = [normalize_map_key(match[f"map{i}"]) for i in range(1, 6)]
        for event in timeline:
            plan = run_plans[event["map_run_id"]]
            slot = plan["legacy_slot"]
            event.update(scheduled_map_id=plan["scheduled_map_id"], map_slot=slot)
            if names.count(normalize_map_key(plan["map_name"])) > 1:
                event["map_name"] = f"图{slot} · {map_display_name(plan['map_name'])}"
    return timeline


def report_context(conn, match_id):
    match = read_opponents(conn, match_id)
    if match is None:
        return None
    managed = is_managed_event(conn, match["event_id"])
    overall_rows, map_rows = report_players(conn, match, managed)
    mvp = None
    if overall_rows and (not managed or overall_rows[0]["rating"] is not None):
        mvp = dict(overall_rows[0])
    if mvp:
        for key in ("adr", "kast", "rating"):
            value = mvp.get(key)
            mvp[key] = round(value, 2) if value is not None else None

    team1_id = match.get("team1_id")
    team2_id = match.get("team2_id")

    def team_summary(expected_side, team_id):
        rows = [
            row for row in overall_rows if match_stat_belongs_to_side(row, expected_side, team_id)
        ]

        def sum_known(key):
            values = [row[key] for row in rows if row.get(key) is not None]
            return sum(values) if values and (managed or len(values) == len(rows)) else None

        def average_known(key, digits):
            values = [row[key] for row in rows if row.get(key) is not None]
            if not values or (not managed and len(values) != len(rows)):
                return None
            return round(sum(values) / len(values), digits)

        return {
            "kills": sum_known("kills"),
            "deaths": sum_known("deaths"),
            "adr": average_known("adr", 1),
            "rating": average_known("rating", 2),
        }

    t1 = team_summary("t1", team1_id)
    t2 = team_summary("t2", team2_id)
    team_stats = {
        "t1_k": t1["kills"],
        "t2_k": t2["kills"],
        "t1_d": t1["deaths"],
        "t2_d": t2["deaths"],
        "t1_adr": t1["adr"],
        "t2_adr": t2["adr"],
        "t1_rating": t1["rating"],
        "t2_rating": t2["rating"],
    }

    bo = (match.get("bo_format") or "BO1").upper()
    max_maps = 5 if bo == "BO5" else (3 if bo == "BO3" else 1)
    map_reports = []
    for index in range(1, max_maps + 1):
        map_name = match.get(f"map{index}")
        if not map_name:
            continue
        score1 = match.get(f"map{index}_t1")
        score2 = match.get(f"map{index}_t2")
        current_rows = stats_for_slot(map_rows, index, map_name)
        t1_rows = [row for row in current_rows if match_stat_belongs_to_side(row, "t1", team1_id)]
        t2_rows = [row for row in current_rows if match_stat_belongs_to_side(row, "t2", team2_id)]
        map_reports.append(
            {
                "idx": index,
                "name": map_name,
                "t1": score1,
                "t2": score2,
                "played": bool(
                    current_rows
                    or (score1 is not None and score1 != 0)
                    or (score2 is not None and score2 != 0)
                ),
                "t1_winner": score1 is not None and score2 is not None and score1 > score2,
                "t2_winner": score1 is not None and score2 is not None and score2 > score1,
                "t1_best": max(
                    t1_rows,
                    key=lambda row: (row.get("rating") is not None, row.get("rating") or 0),
                )
                if t1_rows
                else None,
                "t2_best": max(
                    t2_rows,
                    key=lambda row: (row.get("rating") is not None, row.get("rating") or 0),
                )
                if t2_rows
                else None,
            }
        )

    return {
        "match": match,
        "mvp": mvp,
        "map_reports": map_reports,
        "team_stats": team_stats,
        "timeline": _report_timeline(conn, match, managed),
    }
