"""公开手枪局与武器榜读取已保存的旧赛证据，不解析录像或更改统计。"""

import json
import re
from collections import defaultdict

from services.match_service import supplement_temp_teams
from site_core.host import has_event_schema
from utils.demo_parser import _winner_team_letter
from utils.helpers import normalize_map_key
from utils.match_utils import get_demo_map_names, parse_map_halves
from utils.stats_storage import stat_map_key_sql


def _legacy_scope(conn, filters, months):
    clauses, params = [], []
    if has_event_schema(conn):
        clauses.append(
            "NOT EXISTS (SELECT 1 FROM event_registration_control c WHERE c.event_id=m.event_id)"
        )
    if months:
        clauses.append("m.match_time >= datetime('now', ?)")
        params.append(f"-{months} months")
    if filters.get("event") is not None:
        clauses.append("m.event_id=?")
        params.append(filters["event"])
    return clauses, params


def weapon_counts(conn, filters, months):
    clauses, params = _legacy_scope(conn, filters, months)
    clauses.append("TRIM(ke.weapon)<>''")
    if filters["map"] != "all":
        clauses.append(f"{stat_map_key_sql('ke.map_name')}=?")
        params.append(normalize_map_key(filters["map"]))
    if filters["side"] != "both":
        clauses.append("ke.killer_side=?")
        params.append(filters["side"].upper())
    return conn.execute(
        f"""SELECT ke.weapon,COUNT(*) AS kills FROM match_kill_events ke
            JOIN matches m ON m.id=ke.match_id WHERE {" AND ".join(clauses)}
            GROUP BY ke.weapon""",
        params,
    ).fetchall()


def pistol_match_teams(conn, match_ids):
    slots = ",".join("?" for _ in match_ids)
    rows = conn.execute(
        f"""SELECT m.id,m.event_id,m.team1_id,m.team2_id,m.team1_players,m.team2_players,
                   m.team1_registration_id,m.team2_registration_id,m.roster_snapshot,
                   m.bo_format,m.status,m.team1_score,m.team2_score,m.map_halves,
                   m.map1,m.map2,m.map3,m.map4,m.map5,
                   COALESCE(t1.name,t1.short_name) AS team1_name,
                   COALESCE(t2.name,t2.short_name) AS team2_name,
                   t1.short_name AS t1s,t2.short_name AS t2s,t1.logo AS t1_logo,t2.logo AS t2_logo
            FROM matches m LEFT JOIN teams t1 ON m.team1_id=t1.id LEFT JOIN teams t2 ON m.team2_id=t2.id
            WHERE m.id IN ({slots})""",
        tuple(match_ids),
    ).fetchall()
    matches = {}
    for row in rows:
        match = supplement_temp_teams(row, conn)
        matches[row["id"]] = {
            **match,
            "t1_name": match["team1_name"],
            "t2_name": match["team2_name"],
        }
    return matches


def _read_json(path):
    try:
        with path.open(encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _round_evidence(match, versions, cache_dir, analysis_dir):
    halves = parse_map_halves(match)
    for slot, map_name in enumerate(get_demo_map_names(match)):
        map_key = normalize_map_key(map_name)
        if map_key and map_key not in versions:
            continue
        half = halves.get(str(slot)) or halves.get(f"map{slot + 1}") or {}
        analysis = half.get("analysis") or {}
        if analysis.get("snapshot"):
            # 已确认导入的版本优先。改图或替换后，绝不用旧的无版本槽位文件补回来。
            ref = re.fullmatch(r"analysis/([0-9a-f]{32}\.json)", str(analysis["snapshot"]))
            if not ref or not map_key or analysis.get("data_version") != versions.get(map_key):
                continue
            data = _read_json(analysis_dir / ref[1])
            rounds = (
                (data.get("raw_events") or {}).get("rounds") if isinstance(data, dict) else None
            )
            if not isinstance(rounds, list):
                continue
            first = next((r for r in rounds if r.get("number") == 1), {})
            a_is_t1 = analysis.get("demo_a_to_t1")
            team_a = first.get("teamAName")
            if (
                a_is_t1 is None
                and half.get("opening_ct_team") in ("t1", "t2")
                and first.get("teamASide") in (2, 3)
            ):
                a_is_t1 = (first["teamASide"] == 3) == (half["opening_ct_team"] == "t1")
        else:
            data = _read_json(cache_dir / f"match_{match['id']}_slot_{slot}.json")
            if not isinstance(data, dict):
                continue
            cache_map = normalize_map_key(data.get("mapName"))
            if cache_map not in versions or (map_key and cache_map != map_key):
                continue
            rounds = data.get("rounds") or []
            team_a = (data.get("teamA") or {}).get("name")
            a_is_t1 = None
        if a_is_t1 is None:
            name = str(team_a or "").strip().casefold()
            t1, t2 = match["t1_name"].casefold(), match["t2_name"].casefold()
            a_matches = [bool(name and n and (n in name or name in n)) for n in (t1, t2)]
            if a_matches.count(True) == 1:
                a_is_t1 = a_matches[0]
            elif analysis.get("snapshot"):
                continue
            else:
                a_is_t1 = True  # 旧槽位缓存沿用原先的 A 对应队伍一约定。
        yield rounds, a_is_t1


def pistol_rankings(conn, filters, months, cache_dir, analysis_dir, limit=100):
    clauses, params = _legacy_scope(conn, filters, months)
    clauses.append("COALESCE(ms.data_status,'final')<>'superseded'")
    if filters["map"] != "all":
        clauses.append(f"{stat_map_key_sql()}=?")
        params.append(normalize_map_key(filters["map"]))
    versions = defaultdict(dict)
    for mid, name, version in conn.execute(
        f"""SELECT m.id,{stat_map_key_sql()},MAX(ms.data_version) FROM match_stats ms
            JOIN matches m ON m.id=ms.match_id WHERE {" AND ".join(clauses)}
            GROUP BY m.id,{stat_map_key_sql()}""",
        params,
    ):
        versions[mid][name] = version
    if not versions:
        return []

    totals = {}
    for mid, match in pistol_match_teams(conn, versions).items():
        for rounds, a_is_t1 in _round_evidence(match, versions[mid], cache_dir, analysis_dir):
            by_number = {}
            for rnd in rounds:
                if isinstance(rnd, dict) and type(rnd.get("number")) is int:
                    if rnd.get("teamBSide") is None and rnd.get("teamASide") in (2, 3):
                        rnd = {**rnd, "teamBSide": 5 - rnd["teamASide"]}
                    by_number[rnd["number"]] = rnd
            seen = set()
            for number, rnd in by_number.items():
                if rnd.get("teamAEconomyType") != "pistol":
                    continue
                winner = _winner_team_letter(rnd)
                if not winner:
                    continue
                following = _winner_team_letter(by_number.get(number + 1, {}))
                for side in (1, 2):
                    letter = "A" if (side == 1) == a_is_t1 else "B"
                    army = rnd.get(f"team{letter}Side")
                    if filters["side"] != "both" and army != {"ct": 3, "t": 2}[filters["side"]]:
                        continue
                    team_id = match[f"team{side}_id"]
                    key = team_id if team_id and team_id > 0 else (mid, side)
                    row = totals.setdefault(
                        key,
                        {
                            "team_name": match[f"t{side}_name"],
                            "team_id": key if isinstance(key, int) else None,
                            "logo": match[f"t{side}_logo"] or "",
                            "maps": 0,
                            "won": 0,
                            "lost": 0,
                            "following": 0,
                            "converted": 0,
                            "recovered": 0,
                        },
                    )
                    row["won" if winner == letter else "lost"] += 1
                    seen.add(key)
                    if following:
                        row["following"] += 1
                        if following == letter:
                            row["converted" if winner == letter else "recovered"] += 1
            for key in seen:
                totals[key]["maps"] += 1
    for row in totals.values():
        denominator = row.pop("following")
        row["pistol_win_pct"] = round(row["won"] * 100 / (row["won"] + row["lost"]), 1)
        for field, display in (("converted", "round2_conv"), ("recovered", "round2_break")):
            count = row.pop(field)
            row[display] = round(count * 100 / denominator, 1) if denominator else 0
    return sorted(totals.values(), key=lambda r: (-r["pistol_win_pct"], -r["maps"]))[:limit]
