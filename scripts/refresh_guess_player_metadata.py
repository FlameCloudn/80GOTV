"""Refresh existing game profiles without renaming or deleting player records."""

import argparse
import copy
import json
import unicodedata
from datetime import date
from pathlib import Path

from scripts.sync_guess_player_profiles import BLAST_PLAYERS_URL, blast_player_record

POOL_REASON = "blast_counterstrikle_current_pool"
METADATA_FIELDS = ("team", "profile_age", "player_status", "role", "major_appearances")
TEAM_NAMES = {"team liquid": "Liquid", "fut esports": "FUT"}


def identity_text(value):
    normalized = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(character for character in normalized if character.isalnum())


def refresh_snapshot(snapshot, directory, fetched, hltv_checks, checked_at):
    date.fromisoformat(checked_at)
    expected_ids = {row["id"] for row in directory}
    details = fetched.get("records", [])
    if (
        not expected_ids
        or len(expected_ids) != len(directory)
        or fetched.get("failures")
        or fetched.get("expected") != len(directory)
        or len(details) != len(directory)
        or {row.get("id") for row in details} != expected_ids
    ):
        raise ValueError("BLAST 名单或资料不完整，未更新题库。")

    result = copy.deepcopy(snapshot)
    players = result["players"]
    original = {player["nickname"]: player for player in snapshot["players"]}
    if len(original) != len(players):
        raise ValueError("原题库含有重复昵称，未更新题库。")

    matched = set()
    aliases = []
    added_to_pool = []
    identity_matches = hltv_checks.get("identity_matches", [])
    for detail in details:
        incoming = blast_player_record(detail)
        incoming["team"] = TEAM_NAMES.get(incoming["team"].casefold(), incoming["team"])
        identity = (identity_text(incoming["full_name"]), incoming["country_code"])
        targets = [
            player
            for player in players
            if (identity_text(player.get("full_name")), player.get("country_code")) == identity
        ]
        if not targets:
            confirmed = [
                item
                for item in identity_matches
                if item["nickname"] == incoming["nickname"]
                and identity_text(item["blast_full_name"]) == identity[0]
                and item["blast_country"] == identity[1]
            ]
            if len(confirmed) == 1:
                targets = [
                    player
                    for player in players
                    if player.get("profile_id") == confirmed[0]["profile_id"]
                    and player["nickname"] == confirmed[0]["nickname"]
                ]
        if not targets:
            raise ValueError(f"需要核对选手身份：{incoming['nickname']}，未更新题库。")
        if len(targets) > 1:
            aliases.append([player["nickname"] for player in targets])
        if incoming["profile_age"] is None or not 12 <= incoming["profile_age"] <= 65:
            raise ValueError(f"选手年龄无效：{incoming['nickname']}，未更新题库。")
        if not incoming["role"] or incoming["major_appearances"] < 0:
            raise ValueError(f"选手资料缺失：{incoming['nickname']}，未更新题库。")
        if not any(
            POOL_REASON in player.get("eligibility", {}).get("reasons", []) for player in targets
        ):
            preferred = next(
                (player for player in targets if player["nickname"] == incoming["nickname"]),
                targets[0],
            )
            reasons = preferred.setdefault("eligibility", {}).setdefault("reasons", [])
            reasons.append(POOL_REASON)
            reasons.sort()
            added_to_pool.append(preferred["nickname"])
        for player in targets:
            nickname = player["nickname"]
            if nickname in matched:
                raise ValueError(f"多个来源指向同一记录：{nickname}，未更新题库。")
            matched.add(nickname)
            for field in METADATA_FIELDS:
                player[field] = incoming[field]
            player["source_url"] = incoming["source_url"]
            player["source_checked_at"] = checked_at
            player.setdefault("metadata_sources", {})["blast"] = {
                "player_id": detail["id"],
                "url": incoming["source_url"],
                "checked_at": checked_at,
            }

    not_listed = [
        player["nickname"]
        for player in players
        if player["nickname"] not in matched
        and POOL_REASON in player.get("eligibility", {}).get("reasons", [])
    ]

    conflicts = []
    checked_ids = set()
    for check in hltv_checks.get("players", []):
        profile_id = check["profile_id"]
        url = check["url"]
        if (
            hltv_checks.get("checked_at") != checked_at
            or profile_id in checked_ids
            or not url.startswith(f"https://www.hltv.org/player/{profile_id}/")
            or not 12 <= check["profile_age"] <= 65
            or check["player_status"] not in {"active", "free_agent", "retired"}
            or bool(check["team"]) != (check["player_status"] == "active")
        ):
            raise ValueError("HLTV 核对记录无效，未更新题库。")
        checked_ids.add(profile_id)
        identities = {
            (identity_text(player.get("full_name")), player.get("country_code"))
            for player in players
            if player.get("profile_id") == profile_id
        }
        if len(identities) != 1:
            raise ValueError(f"无法确认 HLTV 选手编号 {profile_id}，未更新题库。")
        targets = [
            player
            for player in players
            if (identity_text(player.get("full_name")), player.get("country_code")) in identities
        ]
        for player in targets:
            differences = {
                field: {"blast": player.get(field), "hltv": check[field]}
                for field in ("team", "profile_age", "player_status")
                if player.get(field) != check[field]
            }
            if differences:
                conflicts.append(
                    {"nickname": player["nickname"], "fields": differences, "url": url}
                )
            for field in ("team", "profile_age", "player_status"):
                player[field] = check[field]
            player["source_url"] = url
            player["source_checked_at"] = checked_at
            player.setdefault("metadata_sources", {})["hltv"] = {
                "url": url,
                "checked_at": checked_at,
                "fields": ["team", "profile_age", "player_status"],
            }

    changes = []
    for player in players:
        before = original[player["nickname"]]
        differences = {
            field: {"before": before.get(field), "after": player.get(field)}
            for field in METADATA_FIELDS
            if before.get(field) != player.get(field)
        }
        if differences:
            changes.append({"nickname": player["nickname"], "fields": differences})
    summary = {
        "checked_at": checked_at,
        "blast_directory_url": BLAST_PLAYERS_URL,
        "blast_players_checked": len(details),
        "existing_records_refreshed": len(matched),
        "hltv_profiles_checked": len(checked_ids),
        "changed_records": len(changes),
        "retained_records": len(players),
        "ranking_refreshed": False,
        "retained_outside_blast_directory": not_listed,
        "added_to_game_pool": added_to_pool,
    }
    result["metadata_refresh"] = summary
    return result, {
        **summary,
        "preserved_aliases": aliases,
        "source_conflicts": conflicts,
        "changes": changes,
    }


def main():
    parser = argparse.ArgumentParser(description="使用已核对的公开资料更新题库，保留所有原记录。")
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--fetched", type=Path, required=True)
    parser.add_argument("--hltv-checks", type=Path, required=True)
    parser.add_argument("--checked-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.report.exists():
        parser.error("输出文件已存在，请使用新的文件名。")

    def read(path):
        return json.loads(path.read_text(encoding="utf-8-sig"))

    result, report = refresh_snapshot(
        read(args.snapshot),
        read(args.directory),
        read(args.fetched),
        read(args.hltv_checks),
        args.checked_at,
    )
    for path, content in ((args.output, result), (args.report, report)):
        with path.open("x", encoding="utf-8") as target:
            json.dump(content, target, ensure_ascii=False, indent=2)
            target.write("\n")
    print(
        f"候选题库已生成：保留 {report['retained_records']} 条原记录，"
        f"更新 {report['changed_records']} 条资料，未覆盖原文件。"
    )


if __name__ == "__main__":
    main()
