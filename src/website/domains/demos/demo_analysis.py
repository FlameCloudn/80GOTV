"""Run the existing CSDA parser and keep only the evidence needed for review."""

import hashlib
import json
import logging
import os
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory

from src.website.domains.demos.demo_parser import get_match_info, parse_player_stats
from src.website.domains.demos.demo_rounds import _kill_is_in_round_window, _winner_team_letter
from src.website.domains.demos.demo_runner import find_csda, run_analysis
from src.website.domains.demos.demo_storage import get_original, original_path, require_idle_sqlite
from src.website.runtime.host import HostError, write

logger = logging.getLogger("80gotv")

_SIDES = {2: "T", 3: "CT"}
_COUNTS = {
    "kills": "killCount",
    "deaths": "deathCount",
    "assists": "assistCount",
    "damage": "healthDamage",
    "headshot_kills": "headshotCount",
    "first_kills": "firstKillCount",
    "first_deaths": "firstDeathCount",
    "trade_kills": "tradeKillCount",
    "trade_deaths": "tradeDeathCount",
    "mvp_count": "mvpCount",
    "bomb_plants": "bombPlantedCount",
    "bomb_defuses": "bombDefusedCount",
}


def _steam_id(value):
    if type(value) in (int, str):
        text = str(value)
        if text.isascii() and text.isdigit() and not text.startswith("0"):
            return text
    return None


def _evidence(data, rounds):
    """Use recorded in-round evidence, never the match roster or a final team label."""
    observed = defaultdict(lambda: defaultdict(set))
    for stream, id_key in (("playerEconomies", "steamId"), ("playersBuy", "playerSteamId")):
        for row in data.get(stream) or []:
            sid = _steam_id(row.get(id_key))
            number, side = row.get("roundNumber"), row.get("playerSide")
            if sid and number in rounds and side in _SIDES:
                observed[sid][number].add(side)
    for row in data.get("kills") or []:
        number = row.get("roundNumber")
        if number not in rounds:
            continue
        round_data = rounds[number]
        if not _kill_is_in_round_window(
            row,
            {
                **round_data,
                "endTick": round_data.get("endOfficiallyTick") or round_data.get("endTick"),
            },
        ):
            continue
        for role in ("killer", "victim", "assister"):
            sid = _steam_id(row.get(f"{role}SteamId", row.get(f"{role}SteamId64")))
            side = row.get(f"{role}Side")
            if sid and side in _SIDES and not row.get(f"is{role.title()}ControllingBot"):
                observed[sid][number].add(side)
    return observed


def _candidate(data):
    info = get_match_info(data)
    if not isinstance(info["map_name"], str) or not info["map_name"].strip():
        raise HostError("CSDA 没有读出地图名称", 422)
    raw_rounds, raw_players = data.get("rounds"), data.get("players")
    if not isinstance(raw_rounds, list) or not isinstance(raw_players, dict):
        raise HostError("CSDA 没有提供有效的回合或选手数据", 422)
    rounds = {}
    for row in raw_rounds:
        if not isinstance(row, dict):
            raise HostError("CSDA 的回合记录格式无效", 422)
        number = row.get("number")
        if type(number) is not int or not 1 <= number <= 1000 or number in rounds:
            raise HostError("CSDA 的回合编号缺失或重复", 422)
        if (row.get("teamASide"), row.get("teamBSide")) not in ((2, 3), (3, 2)):
            raise HostError("CSDA 的回合阵营无法核对", 422)
        rounds[number] = row

    scores = {
        letter: score if type(score) is int and score >= 0 else None
        for letter, score in (("A", info["team_a_score"]), ("B", info["team_b_score"]))
    }
    round_winners = {str(number): _winner_team_letter(row) for number, row in rounds.items()}
    wins = Counter(round_winners.values())
    coverage_complete = bool(rounds) and (
        sorted(rounds) == list(range(1, len(rounds) + 1))
        and not wins[""]
        and scores == {letter: wins[letter] for letter in ("A", "B")}
    )
    observed = _evidence(data, rounds)
    metrics = {_steam_id(row["steam_id"]): row for row in parse_player_stats(data)}
    players = {}
    for key, player in raw_players.items():
        sid = _steam_id(key)
        if sid is None:
            continue  # No human Steam identity to map for bots.
        if not isinstance(player, dict) or (
            player.get("steamId") is not None and _steam_id(player["steamId"]) != sid
        ):
            raise HostError("CSDA 的选手 Steam ID 记录互相矛盾", 422)
        letter = (player.get("team") or {}).get("letter")
        player_rounds = []
        conflict = False
        for number, sides in sorted(observed.get(sid, {}).items()):
            if len(sides) != 1 or letter not in ("A", "B"):
                conflict = True
                continue
            side = next(iter(sides))
            if side != rounds[number][f"team{letter}Side"]:
                conflict = True
                continue
            player_rounds.append({"number": number, "side": _SIDES[side]})

        parsed = metrics.get(sid, {})
        fields = {}
        if player_rounds and coverage_complete and not conflict:
            overall = {
                name: player[key]
                for name, key in _COUNTS.items()
                if type(player.get(key)) is int and player[key] >= 0
            }
            # The legacy overall rates and round count use the entire map as the denominator.
            if len(player_rounds) == len(rounds):
                overall["rounds_played"] = len(player_rounds)
                for name in ("adr", "kast", "rating", "impact"):
                    if parsed.get(name) is not None:
                        overall[name] = parsed[name]
            if overall:
                fields["all"] = overall
            counts = Counter(item["side"].lower() for item in player_rounds)
            scheduled_sides = Counter(
                _SIDES[row[f"team{letter}Side"]].lower() for row in rounds.values()
            )
            for scope, count in counts.items():
                if count != scheduled_sides[scope]:
                    continue
                values = {"rounds_played": count}
                record = parsed.get("side_stats", {}).get(scope, {})
                if record.get("rounds") == count:
                    values.update(
                        {
                            name: record[name]
                            for name in _COUNTS
                            if name in overall
                            and record.get(name) is not None
                            and record[name] >= 0
                        }
                    )
                    if "damage" in overall and record.get("adr") is not None:
                        values["adr"] = record["adr"]
                    if {"kills", "deaths", "assists"} <= values.keys():
                        for name in ("kast", "rating", "impact"):
                            if record.get(name) is not None:
                                values[name] = record[name]
                fields[scope] = values

        players[sid] = {
            "name": str(player.get("name") or ""),
            "team": letter,
            "rounds": player_rounds,
            "side_conflict": conflict,
            "fields": fields,
        }
    return {
        "map_name": info["map_name"],
        "teams": {"A": info["team_a_name"], "B": info["team_b_name"]},
        "scores": scores,
        "round_count": len(rounds),
        "round_winners": round_winners,
        "complete_rounds": coverage_complete,
        "unidentified_players": len(observed.keys() - players.keys()),
        "players": players,
    }


def _parser_build():
    executable = find_csda()
    if not executable:
        raise HostError("找不到 CSDA 解析程序，请检查服务器配置", 503)
    with Path(shutil.which(executable) or executable).open("rb") as binary:
        # This binary does not expose a version flag; identify its exact build instead.
        return hashlib.file_digest(binary, "blake2b").hexdigest()


def parse_original(conn, *, root: Path, match_id: int, demo_id: int, actor: int):
    """Start a job, release the write lock, and retain either its preview or failure."""
    require_idle_sqlite(conn)
    original = get_original(conn, match_id, demo_id)
    with write(conn):
        analysis_id = conn.execute(
            """INSERT INTO demo_analyses(demo_id,status,requested_by,parser_source)
               VALUES (?,'running',?,?)""",
            (demo_id, actor, os.environ.get("CSDA_SOURCE", "valve")),
        ).lastrowid

    parser_build = error = candidate_json = None
    try:
        path = original_path(root, original)
        parser_build = _parser_build()
        with TemporaryDirectory(prefix="csda-", dir=root) as output_dir:
            candidate = _candidate(run_analysis(str(path), output_dir=output_dir))
        candidate_json = json.dumps(candidate, ensure_ascii=False, allow_nan=False)
    except HostError as exc:
        error = exc.message
    except (
        OSError,
        RuntimeError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        OverflowError,
    ) as exc:
        error = "CSDA 未能解析这份 Demo；请核对原件或重试"
        if isinstance(exc, RuntimeError) and "超时" in str(exc):
            error = "CSDA 解析超时（超过 300 秒），原件仍保留"
        logger.warning("Demo %s 的解析任务 %s 失败：%s", demo_id, analysis_id, type(exc).__name__)

    status = "failed" if error else "ready"
    with write(conn):
        conn.execute(
            """UPDATE demo_analyses SET status=?,parser_build=?,candidate_json=?,error=?,
                                        finished_at=CURRENT_TIMESTAMP WHERE analysis_id=?""",
            (status, parser_build, candidate_json, error, analysis_id),
        )
    return {"analysis_id": analysis_id, "demo_id": demo_id, "status": status, "error": error}
