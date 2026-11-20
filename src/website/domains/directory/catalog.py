"""Maintain the administrator's team and player directory without using HTTP state."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from werkzeug.datastructures import FileStorage

from src.website.domains.directory.player_service import (
    record_player_nickname,
    update_player_nickname,
)
from src.website.domains.events.steam_playtime_service import (
    attach_latest_playtime,
    refresh_player_playtimes,
)
from src.website.domains.identity import accounts
from src.website.domains.matches.match_roster_service import preserve_team_rosters
from src.website.runtime.uploads import save_uploaded_avatar, save_uploaded_team_logo

DeletionOutcome = Literal["missing", "in_use", "deleted"]


class CatalogEditError(ValueError):
    """An expected rejection of an administrator's input."""

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class TeamEdit:
    name: str
    short_name: str
    description: str


@dataclass(frozen=True)
class PlayerEdit:
    nickname: str
    group_username: str
    team_id: str
    steam_id: str
    is_bashizhong_student: int | None
    create_account: bool
    account: accounts.InitialPlayerAccount


def _value_in_use(conn, table, column, value, exclude_id):
    # Table and column are fixed at the call sites; form input is always bound.
    return conn.execute(
        f"SELECT id FROM {table} WHERE LOWER(TRIM({column}))=LOWER(TRIM(?)) AND id IS NOT ?",
        (value, exclude_id),
    ).fetchone()


def list_teams(conn):
    return conn.execute("SELECT * FROM teams ORDER BY created_at DESC").fetchall()


def team_choices(conn):
    return conn.execute("SELECT id, name FROM teams ORDER BY name").fetchall()


def team_for_edit(conn, team_id: int):
    return conn.execute("SELECT * FROM teams WHERE id=?", (team_id,)).fetchone()


def save_team(
    conn, edit: TeamEdit, *, team_id: int | None, logo: FileStorage | None, data_root: Path
):
    if not edit.name or not edit.short_name:
        raise CatalogEditError("队名和简称不能为空")
    if len(edit.name) > 40:
        raise CatalogEditError("队名不能超过 40 个字符")
    if len(edit.short_name) > 16:
        raise CatalogEditError("简称不能超过 16 个字符")
    if _value_in_use(conn, "teams", "name", edit.name, team_id):
        raise CatalogEditError("已存在同名队伍")
    if _value_in_use(conn, "teams", "short_name", edit.short_name, team_id):
        raise CatalogEditError("已存在相同简称的队伍")

    logo_path = None
    if logo:
        filename = save_uploaded_team_logo(logo, data_root)
        if not filename:
            raise CatalogEditError("队标无效，请上传不超过 10MB 的 PNG、JPG 或 GIF 图片")
        logo_path = f"team_logos/{filename}"

    fields = (edit.name, edit.short_name, edit.description, logo_path)
    if team_id is None:
        conn.execute(
            "INSERT INTO teams(name, short_name, description, logo) VALUES(?,?,?,?)", fields
        )
    else:
        preserve_team_rosters(conn, team_id)
        conn.execute(
            "UPDATE teams SET name=?, short_name=?, description=?, logo=COALESCE(?,logo) WHERE id=?",
            (*fields, team_id),
        )


def delete_team(conn, team_id: int) -> DeletionOutcome:
    if not conn.execute("SELECT id FROM teams WHERE id=?", (team_id,)).fetchone():
        return "missing"
    references = conn.execute(
        """SELECT
             (SELECT COUNT(*) FROM players WHERE team_id=?) +
             (SELECT COUNT(*) FROM matches WHERE team1_id=? OR team2_id=?) +
             (SELECT COUNT(*) FROM event_champions WHERE team_id=?) +
             (SELECT COUNT(*) FROM match_stats WHERE team_id=?)""",
        (team_id, team_id, team_id, team_id, team_id),
    ).fetchone()[0]
    if references:
        return "in_use"
    conn.execute("DELETE FROM teams WHERE id=?", (team_id,))
    return "deleted"


def list_players(conn):
    players = conn.execute(f"""
        SELECT p.*, t.name AS team_name, u.id AS user_id,
               u.username AS account_username, {accounts.MANAGED_PLAYER_IDENTITY_FIELDS}
        FROM players p
        LEFT JOIN teams t ON p.team_id=t.id
        {accounts.REGISTERED_PLAYER_ACCOUNT_JOIN}
        ORDER BY p.created_at DESC
    """).fetchall()
    return attach_latest_playtime(conn, players, "steam_id")


def player_for_edit(conn, player_id: int):
    row = conn.execute(
        f"""SELECT p.*, {accounts.MANAGED_PLAYER_IDENTITY_FIELDS}
            FROM players p {accounts.REGISTERED_PLAYER_ACCOUNT_JOIN} WHERE p.id=?""",
        (player_id,),
    ).fetchone()
    if row is None:
        return None
    player = dict(row)
    player["group_username"] = player.pop("managed_group_username")
    player["is_bashizhong_student"] = player.pop("managed_is_bashizhong_student")
    return player


def _validate_player_edit(conn, edit: PlayerEdit, previous):
    player_id = previous["id"] if previous is not None else None
    if not edit.nickname:
        raise CatalogEditError("选手昵称不能为空")
    if _value_in_use(conn, "players", "nickname", edit.nickname, player_id):
        raise CatalogEditError("已存在同名选手")
    if len(edit.group_username) > 40 or any(
        char in edit.group_username for char in ("\r", "\n", "\x00")
    ):
        raise CatalogEditError("群内昵称不能超过 40 个字符，也不能包含换行")
    if edit.is_bashizhong_student not in {0, 1}:
        raise CatalogEditError("请选择选手是否是或曾经是八十中学生")
    # Editing an older profile that never had an override does not require a new group name.
    if (
        edit.is_bashizhong_student == 1
        and not edit.group_username
        and (previous is None or previous["group_username_override"])
    ):
        raise CatalogEditError("八十中选手必须填写群内昵称")
    if edit.steam_id:
        if not re.fullmatch(r"\d{17}", edit.steam_id):
            raise CatalogEditError("Steam ID 必须为 17 位数字")
        if _value_in_use(conn, "players", "steam_id", edit.steam_id, player_id):
            raise CatalogEditError("该 Steam ID 已绑定其他选手")
    if edit.team_id:
        if not edit.team_id.isdigit():
            raise CatalogEditError("所选队伍无效")
        if not conn.execute("SELECT id FROM teams WHERE id=?", (edit.team_id,)).fetchone():
            raise CatalogEditError("所选队伍不存在")
    if edit.create_account:
        error = accounts.initial_player_account_error(
            conn, edit.steam_id, edit.nickname, edit.account
        )
        if error:
            raise CatalogEditError(error)


def save_player(conn, edit: PlayerEdit, *, previous, avatar: FileStorage | None, data_root: Path):
    _validate_player_edit(conn, edit, previous)
    avatar_name, _ = save_uploaded_avatar(avatar, data_root)
    if avatar and avatar.filename and not avatar_name:
        raise CatalogEditError("头像文件无效", code="invalid_avatar")

    school_status = cast(int, edit.is_bashizhong_student)
    fields = (
        edit.group_username or None,
        school_status,
        edit.team_id or None,
        edit.steam_id or None,
        avatar_name,
    )
    if previous is None:
        player_id = conn.execute(
            """INSERT INTO players(nickname, group_username_override, is_bashizhong_student,
                                   team_id, steam_id, avatar) VALUES(?,?,?,?,?,?)""",
            (edit.nickname, *fields),
        ).lastrowid
        if edit.create_account:
            accounts.create_approved_player_account(
                conn,
                steam_id=edit.steam_id,
                username=edit.nickname,
                password=edit.account.password,
                email=edit.account.email or None,
                school_status=school_status,
                group_username=edit.group_username,
                avatar=avatar_name,
            )
    else:
        player_id = previous["id"]
        update_player_nickname(conn, player_id, edit.nickname, "website")
        conn.execute(
            """UPDATE players SET group_username_override=?, is_bashizhong_student=?,
                                  team_id=?, steam_id=?, avatar=COALESCE(?,avatar) WHERE id=?""",
            (*fields, player_id),
        )

    if previous is not None or not edit.create_account:
        accounts.sync_registered_account_identity(
            conn, edit.steam_id, school_status, edit.group_username
        )
    if previous is None:
        record_player_nickname(conn, player_id, edit.nickname, "website")


def _player_used_in_roster(conn, player_id: int):
    for match in conn.execute(
        "SELECT team1_players, team2_players FROM matches "
        "WHERE team1_players IS NOT NULL OR team2_players IS NOT NULL"
    ).fetchall():
        for key in ("team1_players", "team2_players"):
            try:
                player_ids = json.loads(match[key]) if match[key] else []
            except (TypeError, json.JSONDecodeError):
                continue
            if any(str(value) == str(player_id) for value in player_ids):
                return True
    return False


def delete_player(conn, player_id: int) -> DeletionOutcome:
    player = conn.execute("SELECT id, steam_id FROM players WHERE id=?", (player_id,)).fetchone()
    if not player:
        return "missing"
    references = conn.execute(
        """SELECT
             (SELECT COUNT(*) FROM match_stats WHERE player_id=?) +
             (SELECT COUNT(*) FROM player_medals WHERE player_id=?)""",
        (player_id, player_id),
    ).fetchone()[0]
    linked_user = (
        player["steam_id"]
        and conn.execute(
            "SELECT id FROM users WHERE steam_id64=? LIMIT 1", (player["steam_id"],)
        ).fetchone()
    )
    if references or linked_user or _player_used_in_roster(conn, player_id):
        return "in_use"
    conn.execute("DELETE FROM player_nickname_history WHERE player_id=?", (player_id,))
    conn.execute("DELETE FROM players WHERE id=?", (player_id,))
    return "deleted"


def refresh_directory_playtimes(conn):
    players = conn.execute(
        """SELECT id, steam_id, cs2_playtime_minutes, playtime_status, playtime_checked_at
            FROM players WHERE TRIM(COALESCE(steam_id, '')) <> '' ORDER BY id"""
    ).fetchall()
    if not players:
        return None
    result = refresh_player_playtimes(conn, players, force=True)
    if not result["configured"]:
        return result

    # Legacy individual registrations mirror the canonical player cache.
    for player in conn.execute(
        """SELECT steam_id, cs2_playtime_minutes, playtime_status, playtime_checked_at
            FROM players WHERE TRIM(COALESCE(steam_id, '')) <> ''"""
    ).fetchall():
        conn.execute(
            """UPDATE event_individual_registrations
               SET cs2_playtime_minutes=?, playtime_status=?, playtime_checked_at=? WHERE steam_id=?""",
            (
                player["cs2_playtime_minutes"],
                player["playtime_status"],
                player["playtime_checked_at"],
                player["steam_id"],
            ),
        )
    return result
