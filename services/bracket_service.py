"""Generate event matches and advance elimination brackets from real results."""

import json
from datetime import datetime

from utils.helpers import ensure_unique_match_slug, make_match_slug

FORMAT_SPECS = {
    "4se": {
        "name": "4 队单败淘汰",
        "type": "single_elim",
        "total_teams": 4,
        "sections": [
            (
                "淘汰赛",
                [
                    (
                        "半决赛",
                        [
                            ("SF_M1", "半决赛 1", ("seed", 1), ("seed", 4)),
                            ("SF_M2", "半决赛 2", ("seed", 2), ("seed", 3)),
                        ],
                    ),
                    (
                        "决赛",
                        [
                            ("F_M1", "决赛", ("winner", "SF_M1"), ("winner", "SF_M2")),
                        ],
                    ),
                ],
            ),
        ],
    },
    "8se": {
        "name": "8 队单败淘汰",
        "type": "single_elim",
        "total_teams": 8,
        "sections": [
            (
                "淘汰赛",
                [
                    (
                        "四分之一决赛",
                        [
                            ("QF_M1", "四分之一决赛 1", ("seed", 1), ("seed", 8)),
                            ("QF_M2", "四分之一决赛 2", ("seed", 4), ("seed", 5)),
                            ("QF_M3", "四分之一决赛 3", ("seed", 2), ("seed", 7)),
                            ("QF_M4", "四分之一决赛 4", ("seed", 3), ("seed", 6)),
                        ],
                    ),
                    (
                        "半决赛",
                        [
                            ("SF_M1", "半决赛 1", ("winner", "QF_M1"), ("winner", "QF_M2")),
                            ("SF_M2", "半决赛 2", ("winner", "QF_M3"), ("winner", "QF_M4")),
                        ],
                    ),
                    (
                        "决赛",
                        [
                            ("F_M1", "决赛", ("winner", "SF_M1"), ("winner", "SF_M2")),
                        ],
                    ),
                ],
            ),
        ],
    },
    "4de": {
        "name": "4 队双败淘汰",
        "type": "double_elim",
        "total_teams": 4,
        "sections": [
            (
                "胜者组",
                [
                    (
                        "UB 第一轮",
                        [
                            ("UB_R1_M1", "胜者组第一轮 1", ("seed", 1), ("seed", 4)),
                            ("UB_R1_M2", "胜者组第一轮 2", ("seed", 2), ("seed", 3)),
                        ],
                    ),
                    (
                        "UB 第二轮",
                        [
                            (
                                "UB_R2_M1",
                                "胜者组决赛",
                                ("winner", "UB_R1_M1"),
                                ("winner", "UB_R1_M2"),
                            ),
                        ],
                    ),
                ],
            ),
            (
                "败者组",
                [
                    (
                        "LB 第一轮",
                        [
                            (
                                "LB_R1_M1",
                                "败者组第一轮",
                                ("loser", "UB_R1_M1"),
                                ("loser", "UB_R1_M2"),
                            ),
                        ],
                    ),
                    (
                        "败者组决赛",
                        [
                            (
                                "LB_R2_M1",
                                "败者组决赛",
                                ("winner", "LB_R1_M1"),
                                ("loser", "UB_R2_M1"),
                            ),
                        ],
                    ),
                ],
            ),
            (
                "总决赛",
                [
                    (
                        "总决赛",
                        [
                            ("GF_R1_M1", "总决赛", ("winner", "UB_R2_M1"), ("winner", "LB_R2_M1")),
                        ],
                    ),
                ],
            ),
        ],
    },
    "8de": {
        "name": "8 队双败淘汰",
        "type": "double_elim",
        "total_teams": 8,
        "sections": [
            (
                "胜者组",
                [
                    (
                        "UB 第一轮",
                        [
                            ("UB_R1_M1", "胜者组第一轮 1", ("seed", 1), ("seed", 8)),
                            ("UB_R1_M2", "胜者组第一轮 2", ("seed", 4), ("seed", 5)),
                            ("UB_R1_M3", "胜者组第一轮 3", ("seed", 2), ("seed", 7)),
                            ("UB_R1_M4", "胜者组第一轮 4", ("seed", 3), ("seed", 6)),
                        ],
                    ),
                    (
                        "UB 第二轮",
                        [
                            (
                                "UB_R2_M1",
                                "胜者组第二轮 1",
                                ("winner", "UB_R1_M1"),
                                ("winner", "UB_R1_M2"),
                            ),
                            (
                                "UB_R2_M2",
                                "胜者组第二轮 2",
                                ("winner", "UB_R1_M3"),
                                ("winner", "UB_R1_M4"),
                            ),
                        ],
                    ),
                    (
                        "UB 决赛",
                        [
                            (
                                "UB_F_M1",
                                "胜者组决赛",
                                ("winner", "UB_R2_M1"),
                                ("winner", "UB_R2_M2"),
                            ),
                        ],
                    ),
                ],
            ),
            (
                "败者组",
                [
                    (
                        "LB 第一轮",
                        [
                            (
                                "LB_R1_M1",
                                "败者组第一轮 1",
                                ("loser", "UB_R1_M1"),
                                ("loser", "UB_R1_M2"),
                            ),
                            (
                                "LB_R1_M2",
                                "败者组第一轮 2",
                                ("loser", "UB_R1_M3"),
                                ("loser", "UB_R1_M4"),
                            ),
                        ],
                    ),
                    (
                        "LB 第二轮",
                        [
                            (
                                "LB_R2_M1",
                                "败者组第二轮 1",
                                ("winner", "LB_R1_M1"),
                                ("loser", "UB_R2_M2"),
                            ),
                            (
                                "LB_R2_M2",
                                "败者组第二轮 2",
                                ("winner", "LB_R1_M2"),
                                ("loser", "UB_R2_M1"),
                            ),
                        ],
                    ),
                    (
                        "LB 第三轮",
                        [
                            (
                                "LB_R3_M1",
                                "败者组第三轮",
                                ("winner", "LB_R2_M1"),
                                ("winner", "LB_R2_M2"),
                            ),
                        ],
                    ),
                    (
                        "LB 决赛",
                        [
                            ("LB_F_M1", "败者组决赛", ("winner", "LB_R3_M1"), ("loser", "UB_F_M1")),
                        ],
                    ),
                ],
            ),
            (
                "总决赛",
                [
                    (
                        "总决赛",
                        [
                            ("GF_R1_M1", "总决赛", ("winner", "UB_F_M1"), ("winner", "LB_F_M1")),
                        ],
                    ),
                ],
            ),
        ],
    },
}


def _nodes(spec):
    for _, rounds in spec["sections"]:
        for _, matches in rounds:
            for node in matches:
                yield node


def _flat_matches(tournament):
    result = {}
    for section in tournament.get("sections", []):
        for round_data in section.get("rounds", []):
            for match in round_data.get("matches", []):
                if match.get("id"):
                    result[match["id"]] = match
    return result


def _team_key_by_db_id(teams, team_id):
    for team in teams:
        if team.get("db_id") == team_id:
            return team.get("id")
    return None


def _ensure_team(teams, team_row):
    if not team_row:
        return None
    team_id = team_row["id"]
    existing = _team_key_by_db_id(teams, team_id)
    if existing:
        return existing
    key = f"db_{team_id}"
    teams.append(
        {
            "id": key,
            "db_id": team_id,
            "name": team_row["name"],
            "short_name": team_row["short_name"] or team_row["name"],
        }
    )
    return key


def _update_match_slug(conn, match_id):
    row = conn.execute(
        """SELECT m.match_time,
                  COALESCE(t1.short_name,t1.name,'tbd') AS t1n,
                  COALESCE(t2.short_name,t2.name,'tbd') AS t2n,
                  COALESCE(e.slug,e.short_name,e.name,'event') AS event_name
           FROM matches m
           LEFT JOIN teams t1 ON m.team1_id=t1.id
           LEFT JOIN teams t2 ON m.team2_id=t2.id
           LEFT JOIN events e ON m.event_id=e.id
           WHERE m.id=?""",
        (match_id,),
    ).fetchone()
    if not row:
        return
    base = make_match_slug(row["t1n"], row["t2n"], row["match_time"], row["event_name"])
    conn.execute(
        "UPDATE matches SET slug=? WHERE id=?",
        (ensure_unique_match_slug(conn, match_id, base), match_id),
    )


def _read_existing_bracket(event):
    raw = event["bracket_data"]
    if not raw:
        return {}, []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}, []
    tournament = data.get("tournament", data) if isinstance(data, dict) else {}
    return _flat_matches(tournament), list(tournament.get("teams", []))


def _seed_assignments(payload, spec, submitted_matches, submitted_teams):
    teams_by_key = {team.get("id"): team for team in submitted_teams if team.get("id")}
    assignments = {}
    for node_id, _, source1, source2 in _nodes(spec):
        match = submitted_matches.get(node_id, {})
        for slot, source in enumerate((source1, source2), 1):
            if source[0] != "seed":
                continue
            key = match.get(f"team{slot}")
            team = teams_by_key.get(key)
            assignments[source[1]] = team if team and team.get("db_id") else None
    return assignments


def _create_match(conn, event_id, stage, bo_format):
    conn.execute(
        """INSERT INTO matches(
               event_id, team1_id, team2_id, team1_score, team2_score,
               match_time, bo_format, stage, status, has_map3, has_map4, has_map5
           ) VALUES(?,?,?,0,0,NULL,?,?, 'upcoming',1,1,1)""",
        (event_id, None, None, bo_format, stage),
    )
    match_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    _update_match_slug(conn, match_id)
    return match_id


def _normalise_match_time(value):
    value = str(value or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("比赛时间格式无效") from None
    return parsed.strftime("%Y-%m-%dT%H:%M")


def _find_reusable_seed_match(conn, event_id, team1_id, team2_id, claimed_ids):
    """Reuse a single existing first-round match instead of creating a duplicate."""
    rows = conn.execute(
        """SELECT id
           FROM matches
           WHERE event_id=?
             AND status NOT IN ('completed','live','ongoing','cancelled')
             AND ((team1_id=? AND team2_id=?) OR (team1_id=? AND team2_id=?))
           ORDER BY CASE WHEN match_time IS NULL OR match_time='' THEN 1 ELSE 0 END,
                    match_time, id""",
        (event_id, team1_id, team2_id, team2_id, team1_id),
    ).fetchall()
    available = [int(row["id"]) for row in rows if int(row["id"]) not in claimed_ids]
    return available[0] if len(available) == 1 else None


def _find_reusable_stage_match(conn, event_id, stage, claimed_ids):
    """Link a previously created match when its bracket stage is unambiguous."""
    rows = conn.execute(
        """SELECT id
           FROM matches
           WHERE event_id=?
             AND TRIM(COALESCE(stage,''))=TRIM(?)
             AND status!='cancelled'
           ORDER BY id""",
        (event_id, stage),
    ).fetchall()
    available = [int(row["id"]) for row in rows if int(row["id"]) not in claimed_ids]
    return available[0] if len(available) == 1 else None


def build_event_bracket(conn, event_id, payload):
    """Save a supported format and create every match exactly once."""
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not event:
        raise ValueError("赛事不存在")
    tournament = (payload or {}).get("tournament", payload or {})
    format_key = tournament.get("format_key")
    spec = FORMAT_SPECS.get(format_key)
    if not spec:
        raise ValueError("该赛制暂不支持自动生成比赛")

    submitted_matches = _flat_matches(tournament)
    submitted_teams = list(tournament.get("teams", []))
    for team in submitted_teams:
        try:
            team["db_id"] = int(team["db_id"]) if team.get("db_id") is not None else None
        except (TypeError, ValueError):
            team["db_id"] = None
    seed_assignments = _seed_assignments(payload, spec, submitted_matches, submitted_teams)
    if any(not seed_assignments.get(seed) for seed in range(1, spec["total_teams"] + 1)):
        raise ValueError(f"请先把 {spec['total_teams']} 支队伍全部放入首轮")
    try:
        seed_team_ids = [
            int(seed_assignments[seed]["db_id"]) for seed in range(1, spec["total_teams"] + 1)
        ]
    except (TypeError, ValueError, KeyError):
        raise ValueError("首轮包含无效队伍") from None
    if len(set(seed_team_ids)) != len(seed_team_ids):
        raise ValueError("同一支队伍不能重复出现在首轮")
    placeholders = ",".join("?" * len(seed_team_ids))
    valid_count = conn.execute(
        f"SELECT COUNT(*) FROM teams WHERE id IN ({placeholders})", tuple(seed_team_ids)
    ).fetchone()[0]
    if valid_count != len(seed_team_ids):
        raise ValueError("首轮包含已删除或不存在的队伍")

    existing_matches, existing_teams = _read_existing_bracket(event)
    teams = submitted_teams or existing_teams
    team_keys_by_seed = {seed: seed_assignments[seed]["id"] for seed in seed_assignments}
    bo_format = tournament.get("bo_format", "BO3")
    if bo_format not in ("BO1", "BO3", "BO5"):
        bo_format = "BO3"

    sections = []
    compatible_rounds = []
    claimed_match_ids = set()
    for section_label, rounds in spec["sections"]:
        section = {"label": section_label, "rounds": []}
        for round_name, nodes in rounds:
            round_data = {"name": round_name, "matches": []}
            for node_id, stage, source1, source2 in nodes:
                old = existing_matches.get(node_id, {})
                submitted = submitted_matches.get(node_id, {})
                if "match_id" in submitted:
                    match_id = submitted.get("match_id")
                else:
                    match_id = old.get("match_id")
                if match_id:
                    valid = conn.execute(
                        """SELECT id FROM matches
                           WHERE id=? AND event_id=? AND status!='cancelled'""",
                        (match_id, event_id),
                    ).fetchone()
                    match_id = int(match_id) if valid else None
                if match_id and match_id in claimed_match_ids:
                    raise ValueError("同一场比赛不能绑定到多个对阵槽位")
                if not match_id and source1[0] == "seed" and source2[0] == "seed":
                    match_id = _find_reusable_seed_match(
                        conn,
                        event_id,
                        int(seed_assignments[source1[1]]["db_id"]),
                        int(seed_assignments[source2[1]]["db_id"]),
                        claimed_match_ids,
                    )
                if not match_id:
                    match_id = _find_reusable_stage_match(conn, event_id, stage, claimed_match_ids)
                if not match_id:
                    match_id = _create_match(conn, event_id, stage, bo_format)
                claimed_match_ids.add(match_id)
                requested_bo = submitted.get("bo_format")
                if requested_bo in ("BO1", "BO3", "BO5"):
                    conn.execute(
                        "UPDATE matches SET bo_format=? WHERE id=? AND event_id=?",
                        (requested_bo, match_id, event_id),
                    )
                if "match_time" in submitted:
                    match_time = _normalise_match_time(submitted.get("match_time"))
                    conn.execute(
                        "UPDATE matches SET match_time=? WHERE id=? AND event_id=?",
                        (match_time, match_id, event_id),
                    )
                    _update_match_slug(conn, match_id)
                else:
                    time_row = conn.execute(
                        "SELECT match_time FROM matches WHERE id=?", (match_id,)
                    ).fetchone()
                    match_time = time_row["match_time"] if time_row else None
                match_row = conn.execute(
                    "SELECT bo_format FROM matches WHERE id=?", (match_id,)
                ).fetchone()
                match_bo_format = (
                    match_row["bo_format"] if match_row and match_row["bo_format"] else bo_format
                )
                match_data = {
                    "id": node_id,
                    "team1": team_keys_by_seed.get(source1[1]) if source1[0] == "seed" else None,
                    "team2": team_keys_by_seed.get(source2[1]) if source2[0] == "seed" else None,
                    "team1_source": {source1[0]: source1[1]},
                    "team2_source": {source2[0]: source2[1]},
                    "score1": None,
                    "score2": None,
                    "match_id": match_id,
                    "match_time": match_time,
                    "bo_format": match_bo_format,
                    "maps": [],
                }
                round_data["matches"].append(match_data)
            section["rounds"].append(round_data)
            compatible_rounds.append(round_data)
        sections.append(section)

    data = {
        "tournament": {
            "name": event["name"],
            "format_key": format_key,
            "type": spec["type"],
            "total_teams": spec["total_teams"],
            "bo_format": bo_format,
            "teams": teams,
            "sections": sections,
            "rounds": compatible_rounds,
        }
    }
    conn.execute(
        "UPDATE events SET bracket_data=?, format=? WHERE id=?",
        (json.dumps(data, ensure_ascii=False), spec["name"], event_id),
    )
    refresh_event_bracket(conn, event_id, data=data)
    return data


def _match_result(match):
    if not match or match["status"] != "completed":
        return None, None
    score1 = int(match["team1_score"] or 0)
    score2 = int(match["team2_score"] or 0)
    if score1 == score2 or not match["team1_id"] or not match["team2_id"]:
        return None, None
    if score1 > score2:
        return match["team1_id"], match["team2_id"]
    return match["team2_id"], match["team1_id"]


def refresh_event_bracket(conn, event_id, data=None):
    """Mirror live scores and route completed-match winners/losers into TBD slots."""
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not event:
        return None
    if data is None:
        if not event["bracket_data"]:
            return None
        try:
            data = json.loads(event["bracket_data"])
        except (TypeError, ValueError):
            return None
    tournament = data.get("tournament", data)
    matches_by_node = _flat_matches(tournament)
    if not matches_by_node:
        return data

    ids = [m.get("match_id") for m in matches_by_node.values() if m.get("match_id")]
    if not ids:
        return data
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"""SELECT m.*, t1.name AS t1_name, t1.short_name AS t1_short,
                           t2.name AS t2_name, t2.short_name AS t2_short
                    FROM matches m
                    LEFT JOIN teams t1 ON m.team1_id=t1.id
                    LEFT JOIN teams t2 ON m.team2_id=t2.id
                    WHERE m.id IN ({placeholders})""",
        tuple(ids),
    ).fetchall()
    db_matches = {row["id"]: row for row in rows}
    team_ids = {row["team1_id"] for row in rows if row["team1_id"]}
    team_ids.update(row["team2_id"] for row in rows if row["team2_id"])
    team_rows = {}
    if team_ids:
        ph = ",".join("?" * len(team_ids))
        team_rows = {
            row["id"]: row
            for row in conn.execute(
                f"SELECT id,name,short_name FROM teams WHERE id IN ({ph})", tuple(team_ids)
            ).fetchall()
        }
    teams = tournament.setdefault("teams", [])

    results = {}
    for node_id, bracket_match in matches_by_node.items():
        row = db_matches.get(bracket_match.get("match_id"))
        if not row:
            continue
        if row["status"] in ("live", "ongoing", "completed"):
            bracket_match["score1"] = int(row["team1_score"] or 0)
            bracket_match["score2"] = int(row["team2_score"] or 0)
        else:
            bracket_match["score1"] = None
            bracket_match["score2"] = None
        bracket_match["status"] = row["status"]
        bracket_match["match_time"] = row["match_time"]
        bracket_match["bo_format"] = row["bo_format"] or tournament.get("bo_format", "BO3")
        for slot in (1, 2):
            team_id = row[f"team{slot}_id"]
            source = bracket_match.get(f"team{slot}_source") or {}
            if team_id:
                bracket_match[f"team{slot}"] = _team_key_by_db_id(teams, team_id) or _ensure_team(
                    teams, team_rows.get(team_id)
                )
            elif "seed" not in source:
                bracket_match[f"team{slot}"] = None
        winner, loser = _match_result(row)
        results[node_id] = {"winner": winner, "loser": loser}

    for node_id, bracket_match in matches_by_node.items():
        row = db_matches.get(bracket_match.get("match_id"))
        if not row or row["status"] not in (None, "upcoming"):
            continue
        updates = []
        for slot in (1, 2):
            source = bracket_match.get(f"team{slot}_source") or {}
            team_id = None
            if "winner" in source:
                team_id = (results.get(source["winner"]) or {}).get("winner")
            elif "loser" in source:
                team_id = (results.get(source["loser"]) or {}).get("loser")
            elif "seed" in source:
                key = bracket_match.get(f"team{slot}")
                team = next((item for item in teams if item.get("id") == key), None)
                team_id = team.get("db_id") if team else None
            updates.append(team_id)
        if row["team1_id"] != updates[0] or row["team2_id"] != updates[1]:
            conn.execute(
                "UPDATE matches SET team1_id=?, team2_id=? WHERE id=?",
                (updates[0], updates[1], row["id"]),
            )
            _update_match_slug(conn, row["id"])
            bracket_match["team1"] = (
                (
                    _team_key_by_db_id(teams, updates[0])
                    or _ensure_team(teams, team_rows.get(updates[0]))
                )
                if updates[0]
                else None
            )
            bracket_match["team2"] = (
                (
                    _team_key_by_db_id(teams, updates[1])
                    or _ensure_team(teams, team_rows.get(updates[1]))
                )
                if updates[1]
                else None
            )

    conn.execute(
        "UPDATE events SET bracket_data=? WHERE id=?",
        (json.dumps(data, ensure_ascii=False), event_id),
    )
    return data


def refresh_bracket_for_match(conn, match_id):
    row = conn.execute("SELECT event_id FROM matches WHERE id=?", (match_id,)).fetchone()
    if row and row["event_id"]:
        return refresh_event_bracket(conn, row["event_id"])
    return None
