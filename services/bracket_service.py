"""Generate event matches and advance elimination brackets from real results."""

import json
from copy import deepcopy
from datetime import datetime

from services.match_service import _has_temp_players, get_series_result
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


class BracketDependencyError(ValueError):
    """A historical change would invalidate a prepared downstream match."""


def _nodes(spec):
    for _, rounds in spec["sections"]:
        for _, matches in rounds:
            for node in matches:
                yield node


def _flat_matches(tournament):
    if not isinstance(tournament, dict) or not isinstance(tournament.get("sections", []), list):
        raise ValueError("对阵图格式无效")
    result = {}
    for section in tournament.get("sections", []):
        if not isinstance(section, dict) or not isinstance(section.get("rounds", []), list):
            raise ValueError("对阵图分组格式无效")
        for round_data in section.get("rounds", []):
            if not isinstance(round_data, dict) or not isinstance(
                round_data.get("matches", []), list
            ):
                raise ValueError("对阵图轮次格式无效")
            for match in round_data.get("matches", []):
                if not isinstance(match, dict):
                    raise ValueError("对阵图比赛格式无效")
                if match.get("id"):
                    if not isinstance(match["id"], str) or match["id"] in result:
                        raise ValueError("对阵图比赛编号无效或重复")
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
    conn.execute("UPDATE events SET bracket_data=bracket_data WHERE id=?", (event_id,))
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not event:
        raise ValueError("赛事不存在")
    if not isinstance(payload, dict):
        raise ValueError("对阵图格式无效")
    payload = deepcopy(payload)
    tournament = payload.get("tournament", payload)
    if not isinstance(tournament, dict):
        raise ValueError("对阵图格式无效")
    format_key = tournament.get("format_key")
    spec = FORMAT_SPECS.get(format_key) if format_key is not None else None
    if not spec:
        raise ValueError("该赛制暂不支持自动生成比赛")

    submitted_matches = _flat_matches(tournament)
    submitted_teams = tournament.get("teams", [])
    if not isinstance(submitted_teams, list) or any(
        not isinstance(team, dict) for team in submitted_teams
    ):
        raise ValueError("对阵图队伍格式无效")
    team_keys = [team.get("id") for team in submitted_teams]
    if any(not isinstance(key, str) or not key for key in team_keys) or len(set(team_keys)) != len(
        team_keys
    ):
        raise ValueError("对阵图队伍编号无效或重复")
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
                    if not valid and submitted.get("match_id"):
                        raise ValueError("所选比赛不存在、已取消或不属于当前赛事")
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
                    current = conn.execute(
                        "SELECT * FROM matches WHERE id=?", (match_id,)
                    ).fetchone()
                    if current["bo_format"] != requested_bo and _match_has_started(current):
                        raise ValueError("比赛已开始或已进行 BP，不能更改比赛赛制")
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
    return refresh_event_bracket(conn, event_id, data=data)


def _match_result(match):
    if not match or match["status"] != "completed":
        return None, None
    winner, loser = get_series_result(
        match["bo_format"], match["team1_score"], match["team2_score"]
    )
    if not winner or not loser or not match["team1_id"] or not match["team2_id"]:
        return None, None
    return match[f"team{winner[-1]}_id"], match[f"team{loser[-1]}_id"]


def _match_has_started(match):
    if match["status"] not in (None, "upcoming") or match["bp_state"]:
        return True
    fields = ["team1_score", "team2_score"]
    fields.extend(f"map{slot}_t{side}" for slot in range(1, 6) for side in (1, 2))
    return any(match[field] not in (None, 0, "0", "") for field in fields)


def refresh_event_bracket(conn, event_id, data=None):
    """Validate every dependency before applying any participant changes."""
    conn.execute("UPDATE events SET bracket_data=bracket_data WHERE id=?", (event_id,))
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
    data = deepcopy(data)
    if not isinstance(data, dict):
        raise ValueError("对阵图格式无效")
    tournament = data.get("tournament", data)
    matches_by_node = _flat_matches(tournament)
    if not matches_by_node:
        return data

    ids = [m.get("match_id") for m in matches_by_node.values() if m.get("match_id")]
    if not ids:
        return data
    try:
        ids = [int(match_id) for match_id in ids]
    except (ValueError, TypeError, OverflowError):
        raise ValueError("对阵图关联比赛编号无效") from None
    if len(set(ids)) != len(ids):
        raise ValueError("同一场比赛不能绑定到多个对阵槽位")
    for match in matches_by_node.values():
        if match.get("match_id"):
            match["match_id"] = int(match["match_id"])
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
    if any(row["event_id"] != event_id for row in rows):
        raise ValueError("对阵图关联的比赛不属于当前赛事，不能修改其他赛事")
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
    if not isinstance(teams, list) or any(not isinstance(team, dict) for team in teams):
        raise ValueError("对阵图队伍格式无效")
    teams_by_key = {team.get("id"): team for team in teams if isinstance(team.get("id"), str)}
    results, assignments, resolving = {}, {}, set()

    def resolve(node_id):
        if node_id in results:
            return results[node_id]
        if node_id in resolving or node_id not in matches_by_node:
            raise ValueError("对阵图晋级关系无效，存在循环或不存在的比赛")
        resolving.add(node_id)
        bracket_match = matches_by_node[node_id]
        row = db_matches.get(bracket_match.get("match_id"))
        if not row:
            bracket_match.update(
                {"match_id": None, "score1": None, "score2": None, "status": "upcoming"}
            )
            for slot in (1, 2):
                source = bracket_match.get(f"team{slot}_source") or {}
                if not isinstance(source, dict) or "seed" not in source:
                    bracket_match[f"team{slot}"] = None
            resolving.remove(node_id)
            results[node_id] = {"winner": None, "loser": None}
            return results[node_id]
        desired = []
        for slot in (1, 2):
            source = bracket_match.get(f"team{slot}_source") or {}
            if not isinstance(source, dict):
                raise ValueError("对阵图队伍来源格式无效")
            if "winner" in source:
                team_id = resolve(source["winner"])["winner"]
            elif "loser" in source:
                team_id = resolve(source["loser"])["loser"]
            elif "seed" in source:
                key = bracket_match.get(f"team{slot}")
                team = teams_by_key.get(key)
                team_id = team.get("db_id") if team else None
            else:
                team_id = row[f"team{slot}_id"]
            desired.append(team_id)
        changed_roster = any(
            row[f"team{slot}_id"] != desired[slot - 1]
            and _has_temp_players(row[f"team{slot}_players"])
            for slot in (1, 2)
        )
        if tuple(desired) != (row["team1_id"], row["team2_id"]) and (
            _match_has_started(row) or changed_roster
        ):
            raise BracketDependencyError(
                "后续比赛已开始、已有比分、已进行 BP 或已锁定相关队伍名单，请先处理后续比赛，再修改历史结果或对阵"
            )
        assignments[node_id] = desired
        winner, loser = _match_result(row)
        results[node_id] = {"winner": winner, "loser": loser}
        resolving.remove(node_id)
        return results[node_id]

    for node_id in matches_by_node:
        resolve(node_id)

    for node_id, desired in assignments.items():
        bracket_match = matches_by_node[node_id]
        row = db_matches[bracket_match["match_id"]]
        if (row["team1_id"], row["team2_id"]) != tuple(desired):
            conn.execute(
                "UPDATE matches SET team1_id=?, team2_id=? WHERE id=? AND event_id=?",
                (*desired, row["id"], event_id),
            )
            _update_match_slug(conn, row["id"])
        for slot, team_id in enumerate(desired, 1):
            bracket_match[f"team{slot}"] = (
                (_team_key_by_db_id(teams, team_id) or _ensure_team(teams, team_rows.get(team_id)))
                if team_id
                else None
            )
        for side in (1, 2):
            bracket_match[f"score{side}"] = (
                int(row[f"team{side}_score"] or 0)
                if row["status"] in ("live", "ongoing", "completed")
                else None
            )
        bracket_match["status"] = row["status"]
        bracket_match["match_time"] = row["match_time"]
        bracket_match["bo_format"] = row["bo_format"] or tournament.get("bo_format", "BO3")

    if "rounds" in tournament:
        tournament["rounds"] = [
            round_data
            for section in tournament.get("sections", [])
            for round_data in section.get("rounds", [])
        ]
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
