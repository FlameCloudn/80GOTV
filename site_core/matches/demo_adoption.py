"""Review immutable CSDA candidates; only the owning modules write live facts."""

import hashlib
import json
from collections import Counter, defaultdict

from site_core.host import HostError, write
from site_core.matches import operations, statistics
from site_core.matches.demo_storage import get_original, original_path
from utils.demo_parser import normalize_map_name
from utils.stats_calc import HLTV2_ESTIMATE_METHOD

_SCOPES = ("all", "ct", "t")
_RATE_INPUTS = {
    "adr": ("damage", "rounds_played"),
    "kast": ("kills", "deaths", "assists", "rounds_played"),
    "impact": ("kills", "assists", "rounds_played"),
    "rating": ("kills", "deaths", "assists", "rounds_played", "damage", "adr", "kast", "impact"),
}


def _source(demo_id, analysis_id, *, replace=False):
    return {
        "kind": "admin" if replace else "demo",
        "ref": f"demo:{demo_id}/analysis:{analysis_id}",
        "method": HLTV2_ESTIMATE_METHOD,
    }


def preview(conn, match_id, analysis_id, *, actor):
    # One deferred read snapshot keeps the returned differences and revision in agreement.
    if conn.in_transaction:
        return _preview(conn, match_id, analysis_id, actor=actor)
    with conn:
        conn.execute("BEGIN")
        return _preview(conn, match_id, analysis_id, actor=actor)


def _preview(conn, match_id, analysis_id, *, actor):
    job = conn.execute(
        """SELECT a.* FROM demo_analyses a JOIN demo_originals d USING(demo_id)
           JOIN map_runs r USING(map_run_id) JOIN scheduled_maps m USING(scheduled_map_id)
           WHERE a.analysis_id=? AND m.match_id=?""",
        (analysis_id, match_id),
    ).fetchone()
    if job is None:
        raise HostError("本场没有这次 Demo 解析", 404)
    result = dict(job)
    candidate_json = result.pop("candidate_json")
    original = get_original(conn, match_id, job["demo_id"])
    result["original"] = {key: value for key, value in original.items() if key != "storage_key"}
    if job["status"] != "ready":
        return result

    candidate = json.loads(candidate_json)
    run_id = original["map_run_id"]
    lineup = conn.execute(
        """SELECT l.steam_id,l.player_id,l.match_participant_id,l.roster_slot,p.side_key,p.event_entrant_id
           FROM map_run_lineups l JOIN match_participants p USING(match_participant_id)
           WHERE l.map_run_id=? AND p.match_id=?""",
        (run_id, match_id),
    ).fetchall()
    roster = {str(row["steam_id"]): dict(row) for row in lineup}
    teams = defaultdict(set)
    for steam_id, observed in candidate["players"].items():
        member = roster.get(steam_id)
        if member and observed["rounds"]:
            teams[observed["team"]].add(member["match_participant_id"])
    mapping = None
    if set(teams) == {"A", "B"} and all(len(teams[letter]) == 1 for letter in teams):
        a, b = (next(iter(teams[letter])) for letter in ("A", "B"))
        if a != b:
            mapping = {"A": a, "B": b}

    official = conn.execute(
        """SELECT map_run_id,score1,score2,revision FROM official_map_results
           WHERE scheduled_map_id=? AND is_current=1""",
        (original["scheduled_map_id"],),
    ).fetchone()
    candidate_score = None
    if mapping is not None:
        parties = {row["match_participant_id"]: row["side_key"] for row in lineup}
        demo_sides = {letter: parties[participant] for letter, participant in mapping.items()}
        scores = {side: candidate["scores"][letter] for letter, side in demo_sides.items()}
        if set(scores) == {"home", "away"}:
            candidate_score = {"score1": scores["home"], "score2": scores["away"]}

    blocks = []
    if original["event_archived"] or original["match_status"] == "cancelled":
        blocks.append("赛事已归档或比赛已取消，只能接收和查看 Demo，不能采纳或指定默认下载")
    if original["run_status"] == "void":
        blocks.append("这次开局已作废，只能保存和查看原件及解析")
    if not original["map_name"] or normalize_map_name(original["map_name"].strip()) != (
        normalize_map_name(candidate["map_name"].strip())
    ):
        blocks.append("录像地图和这次开局的排定赛图不一致")
    if (
        Counter(row["side_key"] for row in lineup) != {"home": 5, "away": 5}
        or len(roster) != len(lineup)
        or mapping is None
        or not candidate_score
        or candidate["unidentified_players"]
        or any(
            p["side_conflict"]
            or steam_id not in roster
            or mapping.get(p["team"]) != roster[steam_id]["match_participant_id"]
            for steam_id, p in candidate["players"].items()
        )
    ):
        blocks.append("录像选手或 A/B 队伍无法与本次开局的准许名单唯一对应")
    if official and official["map_run_id"] != run_id:
        blocks.append("当前正式赛果采用的是另一次开局")
    if (
        official
        and candidate_score
        and any(candidate_score[key] != official[key] for key in ("score1", "score2"))
    ):
        blocks.append("录像比分与当前正式比分不一致，不会更改正式比分")
    if mapping and any(
        row["winner_side"] != demo_sides[letter]
        for row in conn.execute(
            "SELECT round_number,winner_side FROM map_run_rounds WHERE map_run_id=? AND winner_side IS NOT NULL",
            (run_id,),
        )
        if (letter := candidate["round_winners"].get(str(row["round_number"])))
    ):
        blocks.append("录像回合胜方与这次开局已有的记录不一致")
    stats_block = None
    if not official or original["run_status"] != "closed":
        stats_block = "请先在正式赛果入口确定本图结果，再采纳整图统计或指定下载原件"
    elif not candidate["complete_rounds"]:
        stats_block = "录像的回合与比分不能完整核对，不能作为整图统计或默认下载"

    current = {
        row["player_id"]: dict(row)
        for row in conn.execute(
            "SELECT player_id,revision FROM run_participations WHERE map_run_id=? AND is_current=1",
            (run_id,),
        )
    }
    withdrawn = {
        row["player_id"]
        for row in conn.execute(
            "SELECT player_id FROM run_participations WHERE map_run_id=? AND is_current=0",
            (run_id,),
        )
    }
    round_sides = {
        (row["player_id"], row["round_number"]): row["side"]
        for row in conn.execute(
            """SELECT p.player_id,r.round_number,r.side FROM run_round_participations r
               JOIN run_participations p USING (map_run_id,participation_id)
               WHERE r.map_run_id=? AND p.is_current=1 AND r.side IS NOT NULL""",
            (run_id,),
        )
    }
    stats_revision = None
    source = _source(job["demo_id"], analysis_id)
    for steam_id, observed in candidate["players"].items():
        member = roster.get(steam_id)
        player_id = member["player_id"] if member else None
        present = current.get(player_id)
        observed["lineup"] = member
        observed["participation_revision"] = present["revision"] if present else None
        observed["withdrawn"] = player_id in withdrawn
        observed["round_side_conflict"] = any(
            round_sides.get((player_id, round_["number"]), round_["side"]) != round_["side"]
            for round_ in observed["rounds"]
        )
        observed["diffs"] = {}
        if blocks or stats_block or observed["withdrawn"] or observed["round_side_conflict"]:
            continue
        for scope, fields in observed["fields"].items():
            if present:
                diff = statistics.preview_fields(
                    conn, run_id, player_id, scope, fields, source=source, actor=actor
                )
                stats_revision = diff["revision"]
            else:
                diff = {
                    "changes": {
                        key: {"before": None, "after": value, "previous_source": None}
                        for key, value in fields.items()
                    },
                    "conflicts": {},
                }
            observed["diffs"][scope] = diff

    return {
        **result,
        **candidate,
        "mapping": mapping,
        "candidate_score": candidate_score,
        "official_result": dict(official) if official else None,
        "blocks": blocks,
        "stats_block": stats_block,
        "stats_revision": stats_revision,
        "rate_inputs": _RATE_INPUTS,
        "adoptions": [
            dict(row)
            for row in conn.execute(
                """SELECT adoption_id,actor,reason,adopted_at,download_default
                   FROM demo_adoptions WHERE analysis_id=? ORDER BY adoption_id""",
                (analysis_id,),
            )
        ],
    }


def _positive_int(value):
    return type(value) is int and 0 < value <= 2**63 - 1


def _validate_approval(approval):
    if not isinstance(approval, dict) or approval.keys() - {
        "analysis_id",
        "mapping",
        "result_revision",
        "stats_revision",
        "players",
        "download_default",
        "reason",
    }:
        raise HostError("Demo 采纳内容格式无效", 400)
    mapping, selections = approval.get("mapping"), approval.get("players", {})
    download = approval.get("download_default", False)
    reason = approval.get("reason")
    if (
        not _positive_int(approval.get("analysis_id"))
        or not isinstance(mapping, dict)
        or set(mapping) != {"A", "B"}
        or not all(_positive_int(value) for value in mapping.values())
        or "result_revision" not in approval
        or (
            approval["result_revision"] is not None
            and not _positive_int(approval["result_revision"])
        )
        or not isinstance(selections, dict)
        or len(selections) > 10
        or type(download) is not bool
        or (not selections and not download)
        or not isinstance(reason, str)
        or not 0 < len(reason.strip()) <= 500
    ):
        raise HostError("请确认解析编号、录像双方、赛果版本、采纳范围，并填写理由", 400)
    revision = approval.get("stats_revision")
    if revision is not None and (type(revision) is not int or not 0 <= revision <= 2**63 - 1):
        raise HostError("统计预览版本无效", 400)
    for selection in selections.values():
        if not isinstance(selection, dict) or selection.keys() - {
            "player_id",
            "participation_revision",
            "record",
            "fields",
        }:
            raise HostError("选手采纳内容格式无效", 400)
        record = selection.get("record", False)
        fields = selection.get("fields", {})
        participation = selection.get("participation_revision")
        if (
            not _positive_int(selection.get("player_id"))
            or "participation_revision" not in selection
            or (participation is not None and not _positive_int(participation))
            or type(record) is not bool
            or (not record and not fields)
            or not isinstance(fields, dict)
            or fields.keys() - set(_SCOPES)
        ):
            raise HostError("请确认选手编号、出场版本和要采纳的范围", 400)
        if any(
            not isinstance(group, dict)
            or not group
            or any(action not in ("accept", "replace") for action in group.values())
            for group in fields.values()
        ):
            raise HostError("请明确每个字段是采纳还是替换", 400)


def _prepare(approval, reviewed):
    if reviewed["status"] != "ready":
        raise HostError("请先取得成功的 Demo 解析预览")
    if reviewed["blocks"]:
        raise HostError("；".join(reviewed["blocks"]))
    if approval["mapping"] != reviewed["mapping"]:
        raise HostError("录像双方与本次开局的固定参赛方不一致，请重新核对映射")
    official = reviewed["official_result"]
    if approval["result_revision"] != (official["revision"] if official else None):
        raise HostError("正式图结果已经变化，请重新预览")
    if approval.get("download_default") and reviewed["stats_block"]:
        raise HostError(reviewed["stats_block"])

    for steam_id, selected in approval.get("players", {}).items():
        row = reviewed["players"].get(steam_id)
        if not row or row["lineup"]["player_id"] != selected["player_id"]:
            raise HostError("选手映射与当前预览不符，请重新预览")
        if row["withdrawn"]:
            raise HostError("这条出场已被人工撤回，请先通过出场核准入口处理")
        if not row["rounds"] or row["round_side_conflict"]:
            raise HostError("选手没有可采纳的实际出场依据，或回合阵营存在冲突")
        if selected["participation_revision"] != row["participation_revision"]:
            raise HostError("选手出场状态已经变化，请重新预览")
        fields = selected.get("fields", {})
        if not fields:
            continue
        if reviewed["stats_block"]:
            raise HostError(reviewed["stats_block"])
        if row["participation_revision"] is None and not selected.get("record"):
            raise HostError("请先核准实际出场，不能仅凭准许名单写入统计")
        if approval.get("stats_revision") != reviewed["stats_revision"]:
            raise HostError("已有统计已变更，请重新预览")
        for scope, choices in fields.items():
            available = row["fields"].get(scope, {})
            if choices.keys() - available.keys():
                raise HostError("所选统计字段在服务器解析结果中没有可靠值", 400)
            conflicts = row["diffs"][scope]["conflicts"]
            if any(
                (action == "replace") != (field in conflicts) for field, action in choices.items()
            ):
                raise HostError("字段采纳方式与当前差异不符，请重新预览后明确保留或替换")
            if any(
                dep in conflicts and choices.get(dep) != "replace"
                for field in choices
                for dep in _RATE_INPUTS.get(field, ())
            ):
                raise HostError("所选统计依赖有冲突的原值，请先核对相关字段")


def _apply(conn, approval, reviewed, *, actor):
    original = reviewed["original"]
    run_id, demo_id = original["map_run_id"], original["demo_id"]
    analysis_id, reason = approval["analysis_id"], approval["reason"].strip()
    revision = reviewed["stats_revision"]
    decisions = {}
    for steam_id, selected in approval.get("players", {}).items():
        observed = reviewed["players"][steam_id]
        member = observed["lineup"]
        player_id = member["player_id"]
        entry = {"player_id": player_id, "match_participant_id": member["match_participant_id"]}
        if selected.get("record"):
            for round_ in observed["rounds"]:
                participation_id = operations.record_participation(
                    conn,
                    run_id,
                    player_id,
                    member["match_participant_id"],
                    source="demo",
                    actor=actor,
                    reason=reason,
                    round_number=round_["number"],
                    side=round_["side"],
                )
            entry["participation_id"] = participation_id
            entry["rounds"] = observed["rounds"]
        entry["statistics"] = []
        for scope, choices in selected.get("fields", {}).items():
            if revision is None:
                revision = statistics.read_fields(conn, run_id, player_id, scope)["revision"]
            for action in ("accept", "replace"):
                fields = {
                    key: observed["fields"][scope][key]
                    for key, choice in choices.items()
                    if choice == action
                }
                if fields:
                    change = statistics.apply_fields(
                        conn,
                        run_id,
                        player_id,
                        scope,
                        fields,
                        expected=revision,
                        source=_source(demo_id, analysis_id, replace=(action == "replace")),
                        actor=actor,
                        reason=reason,
                        confirm=True,
                    )
                    if not change["ok"] or change["conflicts"]:
                        raise HostError("统计未能完整采纳，请重新预览")
                    revision = change["revision"]
                    entry["statistics"].append(change)
        decisions[steam_id] = entry
    return {"mapping": reviewed["mapping"], "players": decisions}


def adopt(conn, match_id, approvals, *, root, actor):
    """Validate all selected jobs first, then commit the whole approval batch together."""
    if not isinstance(approvals, list) or not 1 <= len(approvals) <= 5:
        raise HostError("请选择一至五次 Demo 解析预览进行采纳", 400)
    for approval in approvals:
        _validate_approval(approval)
    with write(conn):
        pending, run_ids = [], set()
        for approval in approvals:
            reviewed = preview(conn, match_id, approval["analysis_id"], actor=actor)
            run_id = reviewed["original"]["map_run_id"]
            if run_id in run_ids:
                raise HostError("同一开局每批只能选择一份解析预览", 400)
            run_ids.add(run_id)
            approval_key = hashlib.blake2b(
                json.dumps([actor, approval], sort_keys=True, ensure_ascii=True).encode("ascii"),
                digest_size=20,
            ).hexdigest()
            previous = conn.execute(
                "SELECT adoption_id FROM demo_adoptions WHERE analysis_id=? AND approval_key=?",
                (approval["analysis_id"], approval_key),
            ).fetchone()
            if not previous:
                _prepare(approval, reviewed)
                original_path(root, get_original(conn, match_id, reviewed["demo_id"]))
            pending.append((approval, reviewed, approval_key, previous))
        receipts = []
        for approval, reviewed, approval_key, previous in pending:
            analysis_id = approval["analysis_id"]
            if previous:
                receipts.append(
                    {"analysis_id": analysis_id, "adoption_id": previous[0], "duplicate": True}
                )
                continue
            decisions = _apply(conn, approval, reviewed, actor=actor)
            adoption_id = conn.execute(
                """INSERT INTO demo_adoptions(analysis_id,approval_key,actor,reason,result_revision,
                                              download_default,decisions_json) VALUES(?,?,?,?,?,?,?)""",
                (
                    analysis_id,
                    approval_key,
                    actor,
                    approval["reason"].strip(),
                    approval["result_revision"],
                    int(approval.get("download_default", False)),
                    json.dumps(decisions, ensure_ascii=False),
                ),
            ).lastrowid
            receipts.append(
                {
                    "analysis_id": analysis_id,
                    "adoption_id": adoption_id,
                    "duplicate": False,
                    "decisions": decisions,
                }
            )
    return receipts
