"""Promote event registration teams into the public team directory."""

import argparse
import re
import sqlite3
from pathlib import Path

from werkzeug.security import generate_password_hash

DEFAULT_TEST_TEAMS = (
    "星辰电竞社",
    "暴风战队",
    "夜枭俱乐部",
    "烈焰兵团",
    "寒冰军团",
    "雷霆战队",
    "幻影小队",
    "钢铁之师",
)


def registration_short_name(name):
    words = re.findall(r"[A-Za-z0-9]+", str(name or ""))
    if len(words) >= 2 and words[0].lower() == "team":
        return ("T" + words[1][0]).upper()
    if len(words) >= 2:
        return "".join(word[0] for word in words[:3]).upper()
    compact = re.sub(r"[^A-Za-z0-9]", "", str(name or ""))
    return (compact[:3] or "TM").upper()


def registration_logo(value):
    value = str(value or "").strip().replace("\\", "/")
    if not value:
        return None
    if value.startswith("team_logos/"):
        return value
    return f"team_logos/{Path(value).name}"


def split_player_identity(value):
    value = str(value or "").strip()
    if "@" not in value:
        return value, ""
    nickname, group_username = value.split("@", 1)
    return nickname.strip() or value, group_username.strip()


def find_or_create_player(
    conn,
    slot,
    team_id,
    create_missing_accounts=False,
    initial_password=None,
):
    steam_id = str(slot["steam_id"] or "").strip()
    player = conn.execute(
        "SELECT id, nickname FROM players WHERE steam_id=? ORDER BY id LIMIT 1",
        (steam_id,),
    ).fetchone()
    if player:
        return player, False, False

    nickname, _group_username = split_player_identity(slot["player_name"])
    group_username = ""
    user = conn.execute(
        """
        SELECT username, group_username, avatar, is_bashizhong_student
        FROM users
        WHERE steam_id64=?
        ORDER BY id LIMIT 1
        """,
        (steam_id,),
    ).fetchone()
    account_created = False
    if not user and create_missing_accounts:
        if not initial_password:
            raise ValueError("创建缺失账号时必须提供初始密码")
        username_conflict = conn.execute(
            "SELECT id, steam_id64 FROM users WHERE username=? COLLATE NOCASE",
            (nickname,),
        ).fetchone()
        if username_conflict and str(username_conflict["steam_id64"] or "") != steam_id:
            raise ValueError(f"用户名 {nickname} 已被其他 Steam 账号使用")
        if username_conflict:
            conn.execute(
                """
                UPDATE users
                SET steam_id64=?, password_hash=?, is_placeholder=0,
                    approval_status='approved', approved_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    steam_id,
                    generate_password_hash(initial_password),
                    username_conflict["id"],
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO users(
                    username, password_hash, steam_id64, group_username,
                    is_bashizhong_student, is_placeholder,
                    approval_status, approved_at
                ) VALUES(?, ?, ?, NULL, NULL, 0, 'approved', CURRENT_TIMESTAMP)
                """,
                (nickname, generate_password_hash(initial_password), steam_id),
            )
        user = conn.execute(
            """
            SELECT username, group_username, avatar, is_bashizhong_student
            FROM users WHERE steam_id64=? ORDER BY id LIMIT 1
            """,
            (steam_id,),
        ).fetchone()
        account_created = True
    if user:
        nickname = str(user["username"] or nickname).strip() or nickname
        group_username = str(user["group_username"] or group_username).strip()
        avatar = user["avatar"]
        is_student = user["is_bashizhong_student"]
    else:
        avatar = None
        is_student = None

    cursor = conn.execute(
        """
        INSERT INTO players(
            nickname, real_name, group_username_override,
            is_bashizhong_student, team_id, steam_id, avatar
        ) VALUES(?, NULL, ?, ?, ?, ?, ?)
        """,
        (
            nickname or f"Player {steam_id[-6:]}",
            group_username,
            is_student,
            team_id,
            steam_id,
            avatar,
        ),
    )
    created_player = conn.execute(
        "SELECT id, nickname FROM players WHERE id=?", (cursor.lastrowid,)
    ).fetchone()
    return created_player, True, account_created


def team_references(conn, team_id):
    references = []
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    for table_row in tables:
        table = table_row[0]
        for foreign_key in conn.execute(f'PRAGMA foreign_key_list("{table}")'):
            if foreign_key[2] != "teams":
                continue
            column = foreign_key[3]
            count = conn.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE "{column}"=?',
                (team_id,),
            ).fetchone()[0]
            if count:
                references.append((table, column, count))
    return references


def promote_event_teams(
    conn,
    event_id,
    remove_test_teams=False,
    apply=False,
    create_missing_accounts=False,
    initial_password=None,
):
    conn.row_factory = sqlite3.Row
    event = conn.execute("SELECT id, name FROM events WHERE id=?", (event_id,)).fetchone()
    if not event:
        raise ValueError(f"没有找到赛事 ID {event_id}")

    registrations = conn.execute(
        """
        SELECT id, team_name, team_logo, creator_user_id
        FROM event_registrations
        WHERE event_id=? AND status='pending'
        ORDER BY created_at, id
        """,
        (event_id,),
    ).fetchall()
    if not registrations:
        raise ValueError(f"赛事 {event['name']} 没有可用的报名队伍")

    result = {
        "event": event["name"],
        "teams": [],
        "assigned_players": [],
        "created_players": [],
        "created_accounts": [],
        "skipped_slots": [],
        "deleted_test_teams": [],
        "protected_test_teams": [],
    }

    if remove_test_teams:
        for team_name in DEFAULT_TEST_TEAMS:
            team = conn.execute("SELECT id, name FROM teams WHERE name=?", (team_name,)).fetchone()
            if not team:
                continue
            references = team_references(conn, team["id"])
            if references:
                result["protected_test_teams"].append({"name": team_name, "references": references})
                continue
            conn.execute("DELETE FROM teams WHERE id=?", (team["id"],))
            result["deleted_test_teams"].append(team_name)

    for registration in registrations:
        team_name = str(registration["team_name"] or "").strip()
        short_name = registration_short_name(team_name)
        logo = registration_logo(registration["team_logo"])
        existing = conn.execute(
            "SELECT id FROM teams WHERE name=? COLLATE NOCASE", (team_name,)
        ).fetchone()
        if existing:
            team_id = existing["id"]
            conn.execute(
                """
                UPDATE teams
                SET short_name=?, logo=COALESCE(?, logo), description=?
                WHERE id=?
                """,
                (short_name, logo, f"{event['name']} 参赛队伍", team_id),
            )
            action = "updated"
        else:
            cursor = conn.execute(
                """
                INSERT INTO teams(name, short_name, logo, description)
                VALUES(?, ?, ?, ?)
                """,
                (team_name, short_name, logo, f"{event['name']} 参赛队伍"),
            )
            team_id = cursor.lastrowid
            action = "created"

        result["teams"].append(
            {"id": team_id, "name": team_name, "short_name": short_name, "action": action}
        )
        slots = conn.execute(
            """
            SELECT slot_index, player_name, steam_id
            FROM event_registration_slots
            WHERE registration_id=?
            ORDER BY slot_index
            """,
            (registration["id"],),
        ).fetchall()
        for slot in slots:
            steam_id = str(slot["steam_id"] or "").strip()
            if not steam_id:
                result["skipped_slots"].append(
                    {"team": team_name, "slot": slot["slot_index"] + 1, "name": slot["player_name"]}
                )
                continue
            player, created, account_created = find_or_create_player(
                conn,
                slot,
                team_id,
                create_missing_accounts=create_missing_accounts,
                initial_password=initial_password,
            )
            conn.execute("UPDATE players SET team_id=? WHERE id=?", (team_id, player["id"]))
            result["assigned_players"].append(
                {"id": player["id"], "name": player["nickname"], "team": team_name}
            )
            if created:
                result["created_players"].append(
                    {"id": player["id"], "name": player["nickname"], "team": team_name}
                )
            if account_created:
                result["created_accounts"].append(
                    {"name": player["nickname"], "steam_id": steam_id}
                )

    if result["protected_test_teams"]:
        conn.rollback()
        names = ", ".join(item["name"] for item in result["protected_test_teams"])
        raise RuntimeError(f"以下测试队伍仍被正式数据使用，操作已取消：{names}")
    if apply:
        conn.commit()
    else:
        conn.rollback()
    return result


def print_result(result, apply):
    mode = "已执行" if apply else "预演"
    print(f"{mode}：{result['event']}")
    for team in result["teams"]:
        print(f"  队伍：{team['name']} ({team['short_name']}) [{team['action']}]")
    print(f"  已关联正式选手：{len(result['assigned_players'])}")
    print(f"  新建缺失选手：{len(result['created_players'])}")
    print(f"  新建登录账号：{len(result['created_accounts'])}")
    print(f"  未关联的空位或预留位：{len(result['skipped_slots'])}")
    print(f"  已删除测试队伍：{len(result['deleted_test_teams'])}")
    for name in result["deleted_test_teams"]:
        print(f"    - {name}")


def main():
    parser = argparse.ArgumentParser(description="把赛事报名队伍加入正式队伍列表")
    parser.add_argument("--database", required=True, help="SQLite 数据库路径")
    parser.add_argument("--event-id", type=int, required=True, help="赛事 ID")
    parser.add_argument(
        "--remove-test-teams",
        action="store_true",
        help="删除完全没有被引用的内置测试队伍",
    )
    parser.add_argument(
        "--create-missing-accounts",
        action="store_true",
        help="为有 Steam ID 但缺少账号的报名选手建立账号",
    )
    parser.add_argument(
        "--initial-password",
        help="新建账号的初始密码；仅与 --create-missing-accounts 一起使用",
    )
    parser.add_argument("--apply", action="store_true", help="确认写入；不加时只预演")
    args = parser.parse_args()

    conn = sqlite3.connect(args.database)
    try:
        result = promote_event_teams(
            conn,
            args.event_id,
            remove_test_teams=args.remove_test_teams,
            apply=args.apply,
            create_missing_accounts=args.create_missing_accounts,
            initial_password=args.initial_password,
        )
    finally:
        conn.close()
    print_result(result, args.apply)


if __name__ == "__main__":
    main()
