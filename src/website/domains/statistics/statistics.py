"""Adopt evidenced player fields and refresh the site's current map contributions."""

import json
import math
from collections.abc import Mapping

from src.website.domains.statistics.stats_calc import (
    HLTV2_ESTIMATE_METHOD,
    calculate_rating,
    estimate_hltv2_impact,
    non_negative_impact,
)
from src.website.runtime.host import HostError

_SCOPES = ("all", "ct", "t")
_COUNTS = {
    "rounds_played",
    "kills",
    "deaths",
    "assists",
    "kast_rounds",
    "headshot_kills",
    "first_kills",
    "first_deaths",
    "multi1k",
    "multi2k",
    "multi3k",
    "multi4k",
    "multi5k",
    "mvp_count",
    "clutches_won",
    "clutch_1v1",
    "clutch_1v2",
    "clutch_1v3",
    "clutch_1v4",
    "clutch_1v5",
    "enemies_flashed",
    "flash_count",
    "he_count",
    "smoke_count",
    "molotov_count",
    "trade_kills",
    "trade_deaths",
    "bomb_plants",
    "bomb_defuses",
    "flash_assists",
}
_RATES_AND_AMOUNTS = {
    "damage",
    "adr",
    "kast",
    "headshot_percentage",
    "impact",
    "rating_impact",
    "rating",
    "utility_damage",
    "utility_damage_per_round",
    "flash_blinded_seconds",
    "flash_enemy_seconds",
    "damage_delta_per_round",
    "rws_basic",
}
FIELD_NAMES = tuple(sorted(_COUNTS | _RATES_AND_AMOUNTS))
_FIELD_ALIASES = {
    "rounds": "rounds_played",
    "rws": "rws_basic",
    "first_kill_count": "first_kills",
    "first_death_count": "first_deaths",
}
_SOURCE_KINDS = {
    "demo": "demo",
    "demo_review": "demo",
    "director": "director",
    "director_final": "director",
    "live": "director",
    "gotv": "director",
    "admin": "admin",
    "manual": "admin",
    "manual_review": "admin",
}


def _json(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _target(conn, run_id, player_id, scope, *, editing=False):
    if scope not in _SCOPES:
        raise HostError("统计范围必须是 all、ct 或 t", 400)
    if any(type(value) is not int or value <= 0 for value in (run_id, player_id)):
        raise HostError("开局和选手编号必须是正整数", 400)
    row = conn.execute(
        """
        SELECT rp.participation_id, rp.match_participant_id, sm.scheduled_map_id,
               run.status, rp.is_current, managed.archived_at, m.status
        FROM run_participations rp
        JOIN map_runs run ON run.map_run_id=rp.map_run_id
        JOIN scheduled_maps sm ON sm.scheduled_map_id=run.scheduled_map_id
        JOIN matches m ON m.id=sm.match_id
        JOIN event_registration_control managed ON managed.event_id=m.event_id
        JOIN match_participants mp ON mp.match_participant_id=rp.match_participant_id
                                  AND mp.match_id=sm.match_id
        WHERE rp.map_run_id=? AND rp.player_id=?
        """,
        (run_id, player_id),
    ).fetchone()
    if row is None:
        raise HostError("没有该选手在这次开局的实际出场记录")
    participation_id, participant_id, map_id, run_status, present, archived_at, match_status = row
    editable = (
        run_status != "void"
        and bool(present)
        and archived_at is None
        and match_status != "cancelled"
    )
    if editing and not editable:
        raise HostError("已作废、已撤回、已归档或已取消的统计只可查看")
    return participation_id, participant_id, map_id, run_status, present, editable


def _current_revision(conn, run_id):
    return conn.execute(
        "SELECT COALESCE(MAX(revision),0) FROM run_stats_revisions WHERE map_run_id=?", (run_id,)
    ).fetchone()[0]


def _state(conn, run_id, player_id, scope, participation_id, participant_id):
    row = conn.execute(
        f"""
        SELECT field_revisions,{",".join(FIELD_NAMES)} FROM run_player_stats
        WHERE participation_id=? AND scope=? AND map_run_id=?
          AND player_id=? AND match_participant_id=?
        """,
        (participation_id, scope, run_id, player_id, participant_id),
    ).fetchone()
    if row is None:
        return {}, {}
    revisions = json.loads(row[0])
    values = dict(zip(FIELD_NAMES, tuple(row)[1:]))
    return {key: values[key] for key in revisions}, revisions


def _revision_sources(conn, run_id, revisions):
    if not revisions:
        return {}
    placeholders = ",".join("?" for _ in revisions)
    return {
        row[0]: dict(
            zip(("revision", "source", "source_ref", "method", "actor", "reason", "at"), row)
        )
        for row in conn.execute(
            f"""SELECT revision,source,source_ref,method,actor,reason,created_at
                FROM run_stats_revisions
                WHERE map_run_id=? AND revision IN ({placeholders})""",
            (run_id, *revisions),
        )
    }


def read_fields(conn, run_id, player_id, scope):
    """Read adopted inputs and their provenance, not display-only derived values."""
    participation_id, participant_id, scheduled_map_id, run_status, present, editable = _target(
        conn, run_id, player_id, scope
    )
    values, revisions = _state(conn, run_id, player_id, scope, participation_id, participant_id)
    sources = _revision_sources(conn, run_id, set(revisions.values()))
    return {
        "run_id": run_id,
        "scheduled_map_id": scheduled_map_id,
        "player_id": player_id,
        "participation_id": participation_id,
        "run_status": run_status,
        "participation_current": bool(present),
        "editable": editable,
        "scope": scope,
        "revision": _current_revision(conn, run_id),
        "fields": values,
        "field_sources": {key: sources[revision] for key, revision in revisions.items()},
    }


def _parse_fields(fields):
    if not isinstance(fields, Mapping):
        raise HostError("统计字段必须是对象", 400)
    parsed = {}
    for name, value in fields.items():
        key = _FIELD_ALIASES.get(name, name)
        if key not in FIELD_NAMES or key in parsed:
            raise HostError(f"未知或重复的统计字段：{name}", 400)
        if value is not None:
            signed = key in ("rating_impact", "damage_delta_per_round")
            percent = key in ("kast", "headshot_percentage")
            if (
                type(value) not in (int, float)
                or (key in _COUNTS and (type(value) is not int or value > 2**31 - 1))
                or (type(value) is int and abs(value) > 2**63 - 1)
                or not math.isfinite(value)
                or (not signed and value < 0)
                or (percent and value > 100)
            ):
                raise HostError(f"统计字段 {name} 的数值无效", 400)
        parsed[key] = value
    return parsed


def _source(conn, source, actor, reason):
    if isinstance(source, str):
        source = {"kind": source}
    if not isinstance(source, Mapping) or source.keys() - {"kind", "ref", "method"}:
        raise HostError("统计来源应为 demo、director、admin 或带依据编号的来源对象", 400)
    kind = source.get("kind")
    kind = _SOURCE_KINDS.get(kind) if isinstance(kind, str) else None
    ref, method = source.get("ref", ""), source.get("method", "")
    if kind is None or any(not isinstance(value, str) for value in (ref, method, reason)):
        raise HostError("统计来源、方法或理由无效", 400)
    if kind == "admin":
        if (
            type(actor) is not int
            or actor <= 0
            or not conn.execute("SELECT 1 FROM admins WHERE id=?", (actor,)).fetchone()
        ):
            raise HostError("必须由已核实身份的管理员确认统计修订", 403)
    elif not ((type(actor) is int and actor > 0) or (isinstance(actor, str) and actor.strip())):
        raise HostError("统计来源缺少操作者", 400)
    return kind, ref.strip(), method.strip(), actor, reason.strip()


def _changes(conn, run_id, player_id, scope, target, fields, source, expected):
    participation_id, participant_id, scheduled_map_id = target[:3]
    fields = _parse_fields(fields)
    if expected is not None and (type(expected) is not int or expected < 0):
        raise HostError("统计版本必须是非负整数", 400)
    values, revisions = _state(conn, run_id, player_id, scope, participation_id, participant_id)
    revision = _current_revision(conn, run_id)
    sources = _revision_sources(conn, run_id, set(revisions.values()))
    changes, conflicts = {}, {}
    for key, value in fields.items():
        old_source = sources[revisions[key]] if key in revisions else None
        if value is None and (source != "admin" or old_source is None):
            continue
        if (
            old_source is not None
            and values[key] == value
            and (source != "admin" or old_source["source"] == "admin")
        ):
            continue
        diff = {"before": values.get(key), "after": value, "previous_source": old_source}
        if old_source is not None and source != "admin":
            conflicts[key] = diff
        else:
            changes[key] = diff

    stale = expected is not None and expected != revision
    return (
        {
            "ok": not stale,
            "applied": False,
            "status": "stale" if stale else "preview",
            "revision": revision,
            "base_revision": revision,
            "scheduled_map_id": scheduled_map_id,
            "run_id": run_id,
            "player_id": player_id,
            "participation_id": participation_id,
            "scope": scope,
            "changes": changes,
            "conflicts": conflicts,
        },
        values,
        revisions,
    )


def preview_fields(
    conn, run_id, player_id, scope, fields, *, source, actor, reason="", expected=None
):
    """Compare candidate fields without writing data or reserving a revision."""
    target = _target(conn, run_id, player_id, scope, editing=True)
    kind, *_ = _source(conn, source, actor, reason)
    result, _, _ = _changes(conn, run_id, player_id, scope, target, fields, kind, expected)
    return result


def apply_fields(
    conn,
    run_id,
    player_id,
    scope,
    fields,
    *,
    source,
    actor,
    reason="",
    expected=None,
    confirm=False,
):
    """Adopt independent fields; a caller-owned write transaction is required to change data."""
    target = _target(conn, run_id, player_id, scope, editing=True)
    provenance = _source(conn, source, actor, reason)
    kind, _, _, _, reason = provenance
    result, values, revisions = _changes(
        conn, run_id, player_id, scope, target, fields, kind, expected
    )
    if not result["ok"]:
        return result
    changes = result["changes"]
    if not changes:
        return {**result, "status": "conflict" if result["conflicts"] else "unchanged"}
    if kind == "admin" and (confirm is not True or expected is None or not reason):
        return {**result, "ok": False, "status": "needs_confirmation"}
    if not conn.in_transaction:
        raise RuntimeError("保存正式统计前，调用方必须开启写事务")
    participation_id, participant_id, scheduled_map_id = target[:3]
    revision = result["revision"] + 1
    conn.execute(
        """
        INSERT INTO run_stats_revisions(
            map_run_id,revision,participation_id,player_id,match_participant_id,scope,
            source,source_ref,method,actor,reason,changes_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            run_id,
            revision,
            participation_id,
            player_id,
            participant_id,
            scope,
            *provenance,
            _json(changes),
        ),
    )
    values.update({key: diff["after"] for key, diff in changes.items()})
    revisions.update(dict.fromkeys(changes, revision))
    conn.execute(
        f"""
        INSERT OR REPLACE INTO run_player_stats(
            participation_id,scope,map_run_id,player_id,match_participant_id,field_revisions,
            {",".join(FIELD_NAMES)}
        ) VALUES ({",".join("?" for _ in range(6 + len(FIELD_NAMES)))})
        """,
        (
            participation_id,
            scope,
            run_id,
            player_id,
            participant_id,
            _json(revisions),
            *(values.get(key) for key in FIELD_NAMES),
        ),
    )
    if conn.execute(
        """SELECT 1 FROM official_stat_participants
           WHERE scheduled_map_id=? AND map_run_id=? AND participation_id=?""",
        (scheduled_map_id, run_id, participation_id),
    ).fetchone():
        refresh_map(conn, scheduled_map_id)
    return {**result, "status": "applied", "revision": revision, "applied": True}


_DERIVED_FROM = {
    "adr": ("damage", "rounds_played"),
    "kast": ("kast_rounds", "rounds_played"),
    "headshot_percentage": ("headshot_kills", "kills"),
    "utility_damage_per_round": ("utility_damage", "rounds_played"),
    "impact": ("kills", "assists", "rounds_played"),
    "rating_impact": ("kills", "assists", "rounds_played", "impact"),
    "rating": (
        "kills",
        "deaths",
        "assists",
        "rounds_played",
        "damage",
        "adr",
        "kast",
        "kast_rounds",
        "impact",
        "rating_impact",
    ),
}


def _display_fields(values, revisions, sources, disputed=()):
    """Only compute rates from real denominators; retain independently confirmed inputs."""
    shown = dict(values)
    for key in disputed:
        shown[key] = None
    for field, inputs in _DERIVED_FROM.items():
        revision = revisions.get(field, 0)
        if (
            field in shown
            and shown[field] is not None
            and (
                any(key in disputed for key in inputs)
                or (
                    sources[revision]["source"] != "admin"
                    and any(
                        revisions.get(key, 0) > revision
                        and sources[revisions[key]]["source"] == "admin"
                        for key in inputs
                    )
                )
            )
        ):
            del shown[field]

    rounds = shown.get("rounds_played")
    for field, numerator, denominator, factor in (
        ("adr", "damage", rounds, 1),
        ("kast", "kast_rounds", rounds, 100),
        ("headshot_percentage", "headshot_kills", shown.get("kills"), 100),
        ("utility_damage_per_round", "utility_damage", rounds, 1),
    ):
        num = shown.get(numerator)
        revision = revisions.get(field)
        explicit = field in shown and (
            shown[field] is None or sources[revision]["source"] == "admin"
        )
        if num is not None and denominator and not explicit:
            shown[field] = num / denominator * factor if factor == 1 or num <= denominator else None

    kills, deaths, assists = (shown.get(key) for key in ("kills", "deaths", "assists"))
    estimate = estimate_hltv2_impact(kills, assists, rounds)
    raw = shown.get("rating_impact")
    if "rating_impact" not in shown:
        if "impact" not in shown:
            raw = estimate
        else:
            impact = shown["impact"]
            method = sources[revisions["impact"]]["method"]
            raw = estimate if impact is not None and method == HLTV2_ESTIMATE_METHOD else impact
    if "impact" not in shown:
        shown["impact"] = non_negative_impact(raw)
    if rounds:
        rating, kpr, dpr = calculate_rating(
            kills, deaths, rounds, adr=shown.get("adr"), kast=shown.get("kast"), impact=raw
        )
        shown.setdefault("rating", rating)
        shown["kpr"], shown["dpr"] = kpr, dpr
    return shown


def _projection(conn, run_id, player_id, participation_id, participant_id):
    data = {
        scope: _state(conn, run_id, player_id, scope, participation_id, participant_id)
        for scope in _SCOPES
    }
    overall, ct, t = (data[scope][0] for scope in _SCOPES)
    disputed = set()
    # Do not invent a new split if a confirmed total or split no longer reconciles.
    for key in (
        "rounds_played",
        "kills",
        "deaths",
        "assists",
        "damage",
        "kast_rounds",
        "headshot_kills",
    ):
        known = [side[key] for side in (ct, t) if side.get(key) is not None]
        total = overall.get(key)
        if (
            total is not None
            and known
            and (
                sum(known) > total + 1e-8
                or (len(known) == 2 and not math.isclose(sum(known), total, abs_tol=1e-8))
            )
        ):
            disputed.add(key)
        elif key not in overall and len(known) == 2:
            overall[key] = sum(known)
    sources = _revision_sources(
        conn,
        run_id,
        {revision for _, revisions in data.values() for revision in revisions.values()},
    )
    all_stats = _display_fields(*data["all"], sources)
    sides = {}
    for scope in ("ct", "t"):
        values, revisions = data[scope]
        if values:
            side = _display_fields(values, revisions, sources, disputed)
            side["rounds"] = side.pop("rounds_played", None)
            side["rws"] = side.pop("rws_basic", None)
            sides[scope] = side
    return _json(all_stats), _json(sides)


def refresh_map(conn, scheduled_map_id):
    """Replace one map's read rows and refresh the old/new player union, without committing."""
    if not conn.in_transaction:
        raise RuntimeError("刷新正式统计前，调用方必须开启写事务")
    if not conn.execute(
        "SELECT 1 FROM scheduled_maps WHERE scheduled_map_id=?", (scheduled_map_id,)
    ).fetchone():
        raise HostError("排定赛图不存在", 404)
    affected = {
        row[0]
        for row in conn.execute(
            "SELECT player_id FROM official_player_map_stats WHERE scheduled_map_id=?",
            (scheduled_map_id,),
        )
    }
    participants = conn.execute(
        """SELECT official_map_result_id,map_run_id,participation_id,player_id,match_participant_id
           FROM official_stat_participants WHERE scheduled_map_id=? ORDER BY player_id""",
        (scheduled_map_id,),
    ).fetchall()
    conn.execute(
        "DELETE FROM official_player_map_stats WHERE scheduled_map_id=?", (scheduled_map_id,)
    )
    revision = _current_revision(conn, participants[0][1]) if participants else 0
    for result_id, run_id, participation_id, player_id, participant_id in participants:
        overall, sides = _projection(conn, run_id, player_id, participation_id, participant_id)
        conn.execute(
            """
            INSERT INTO official_player_map_stats(
                scheduled_map_id,player_id,official_map_result_id,map_run_id,participation_id,
                match_participant_id,stats_revision,overall_json,sides_json
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                scheduled_map_id,
                player_id,
                result_id,
                run_id,
                participation_id,
                participant_id,
                revision,
                overall,
                sides,
            ),
        )
        affected.add(player_id)

    from src.website.domains.statistics.performance_service import refresh_player_performance

    refresh_player_performance(conn, affected)
    return {
        "scheduled_map_id": scheduled_map_id,
        "players": len(participants),
        "affected_player_ids": sorted(affected),
    }
