"""Solvable 3x3 player Bingo boards backed by the local HLTV player snapshot."""

import hashlib
import hmac
import json
import random
import secrets
import uuid
from datetime import date, datetime, timedelta

from config import Config
from services.guess_player_service import COUNTRY_REGIONS, country_flag, player_age


def _criterion(key, label, description, matches):
    return {"key": key, "label": label, "description": description, "matches": matches}


FAMILIES = {
    "region": (
        _criterion(
            "region-europe",
            "欧洲",
            "国籍属于欧洲",
            lambda p: COUNTRY_REGIONS.get((p["country_code"] or "").upper()) == "europe",
        ),
        _criterion(
            "region-cis",
            "CIS",
            "国籍属于 CIS 地区",
            lambda p: COUNTRY_REGIONS.get((p["country_code"] or "").upper()) == "cis",
        ),
        _criterion(
            "region-americas",
            "美洲",
            "国籍属于北美或南美",
            lambda p: (
                COUNTRY_REGIONS.get((p["country_code"] or "").upper())
                in {"north-america", "south-america"}
            ),
        ),
    ),
    "status": (
        _criterion(
            "status-active",
            "现役",
            "当前仍有队伍",
            lambda p: (p["player_status"] or "").lower() == "active",
        ),
        _criterion(
            "status-free",
            "Free Agent",
            "当前为自由选手",
            lambda p: (p["player_status"] or "").lower() == "free_agent",
        ),
        _criterion(
            "status-retired",
            "Retired",
            "资料标记为退役",
            lambda p: (p["player_status"] or "").lower() == "retired",
        ),
    ),
    "age": (
        _criterion(
            "age-young",
            "23 岁及以下",
            "当前年龄不超过 23 岁",
            lambda p: _age(p) is not None and _age(p) <= 23,
        ),
        _criterion(
            "age-prime",
            "24 至 28 岁",
            "当前年龄为 24 至 28 岁",
            lambda p: _age(p) is not None and 24 <= _age(p) <= 28,
        ),
        _criterion(
            "age-veteran",
            "29 岁及以上",
            "当前年龄至少 29 岁",
            lambda p: _age(p) is not None and _age(p) >= 29,
        ),
    ),
    "major": (
        _criterion(
            "major-zero",
            "0 次 Major",
            "没有 Major 参赛记录",
            lambda p: int(p["major_appearances"]) == 0,
        ),
        _criterion(
            "major-few",
            "1 至 3 次 Major",
            "Major 参赛 1 至 3 次",
            lambda p: 1 <= int(p["major_appearances"]) <= 3,
        ),
        _criterion(
            "major-many",
            "4 次以上 Major",
            "Major 参赛至少 4 次",
            lambda p: int(p["major_appearances"]) >= 4,
        ),
    ),
}

CRITERIA = {item["key"]: item for family in FAMILIES.values() for item in family}
FAMILY_PAIRS = (
    ("region", "status"),
    ("region", "age"),
    ("region", "major"),
    ("age", "status"),
    ("major", "status"),
    ("age", "major"),
)


def _age(player):
    try:
        return player_age(player, date.today())
    except (TypeError, ValueError):
        return None


def _as_date(value=None):
    if value is None:
        return datetime.now().date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def challenge_number(on_date=None):
    kickoff = date(2026, 7, 15)
    return max(1, (_as_date(on_date) - kickoff).days + 1)


def _players(conn):
    return conn.execute(
        """SELECT * FROM guess_players WHERE active=1
           ORDER BY nickname COLLATE NOCASE"""
    ).fetchall()


def player_matches(player, row_key, column_key):
    row = CRITERIA.get(row_key)
    column = CRITERIA.get(column_key)
    return bool(row and column and row["matches"](player) and column["matches"](player))


def candidate_ids(players, row_key, column_key):
    return [player["id"] for player in players if player_matches(player, row_key, column_key)]


def solve_board(players, rows, columns):
    """Return one unique-player solution, or None when a board is impossible."""
    candidates = {
        (row_index, column_index): candidate_ids(players, row_key, column_key)
        for row_index, row_key in enumerate(rows)
        for column_index, column_key in enumerate(columns)
    }
    ordered_cells = sorted(candidates, key=lambda cell: len(candidates[cell]))
    if any(not candidates[cell] for cell in ordered_cells):
        return None
    answer = {}
    used = set()

    def place(index):
        if index == len(ordered_cells):
            return True
        cell = ordered_cells[index]
        for player_id in candidates[cell]:
            if player_id in used:
                continue
            answer[cell] = player_id
            used.add(player_id)
            if place(index + 1):
                return True
            used.remove(player_id)
            answer.pop(cell, None)
        return False

    return answer if place(0) else None


def _build_board(players, seed):
    chooser = random.Random(seed)
    pairs = list(FAMILY_PAIRS)
    chooser.shuffle(pairs)
    for row_family, column_family in pairs:
        rows = [item["key"] for item in FAMILIES[row_family]]
        columns = [item["key"] for item in FAMILIES[column_family]]
        chooser.shuffle(rows)
        chooser.shuffle(columns)
        if solve_board(players, rows, columns):
            return {"rows": rows, "columns": columns}
    raise RuntimeError("当前选手资料不足以生成 Bingo 题板")


def _daily_seed(game_key):
    secret = str(getattr(Config, "SECRET_KEY", "80gotv-player-bingo"))
    digest = hmac.new(secret.encode(), f"player-bingo:{game_key}".encode(), hashlib.sha256).digest()
    return int.from_bytes(digest, "big")


def _create_game(conn, user_id, mode, game_key, seed):
    existing = conn.execute(
        "SELECT * FROM player_bingo_games WHERE user_id=? AND mode=? AND game_key=?",
        (user_id, mode, game_key),
    ).fetchone()
    if existing:
        return existing

    board = _build_board(_players(conn), seed)
    conn.execute(
        """INSERT OR IGNORE INTO player_bingo_games(
               user_id, mode, game_key, board_json
           ) VALUES(?,?,?,?)""",
        (user_id, mode, game_key, json.dumps(board, ensure_ascii=False)),
    )
    conn.commit()
    return conn.execute(
        "SELECT * FROM player_bingo_games WHERE user_id=? AND mode=? AND game_key=?",
        (user_id, mode, game_key),
    ).fetchone()


def get_daily_game_row(conn, user_id, on_date=None):
    game_key = _as_date(on_date).isoformat()
    return _create_game(conn, user_id, "daily", game_key, _daily_seed(game_key))


def get_practice_game_row(conn, user_id):
    row = conn.execute(
        """SELECT * FROM player_bingo_games
           WHERE user_id=? AND mode='practice' ORDER BY id DESC LIMIT 1""",
        (user_id,),
    ).fetchone()
    return row or create_practice_game(conn, user_id)


def create_practice_game(conn, user_id):
    return _create_game(conn, user_id, "practice", uuid.uuid4().hex, secrets.randbits(256))


def _board(game_row):
    raw = json.loads(game_row["board_json"])
    return {
        "row_keys": raw["rows"],
        "column_keys": raw["columns"],
        "rows": [CRITERIA[key] for key in raw["rows"]],
        "columns": [CRITERIA[key] for key in raw["columns"]],
    }


def _line_count(cells):
    filled = set(cells)
    return len(_completed_lines(filled))


def _completed_lines(filled):
    possible = []
    possible.extend([{(row, column) for column in range(3)} for row in range(3)])
    possible.extend([{(row, column) for row in range(3)} for column in range(3)])
    possible.append({(index, index) for index in range(3)})
    possible.append({(index, 2 - index) for index in range(3)})
    return [line for line in possible if line.issubset(set(filled))]


def load_game(conn, game_row):
    board = _board(game_row)
    rows = conn.execute(
        """SELECT c.row_index, c.column_index, p.*
           FROM player_bingo_cells c
           JOIN guess_players p ON p.id=c.player_id
           WHERE c.game_id=? ORDER BY c.row_index, c.column_index""",
        (game_row["id"],),
    ).fetchall()
    cells = {}
    for player in rows:
        item = dict(player)
        item["country_flag"] = country_flag(item.get("country_code"))
        cells[(player["row_index"], player["column_index"])] = item
    completed_lines = _completed_lines(cells)
    line_cells = set().union(*completed_lines) if completed_lines else set()
    return {
        "row": game_row,
        **board,
        "cells": cells,
        "filled": len(cells),
        "lines": len(completed_lines),
        "line_cells": line_cells,
        "mistakes": int(game_row["mistakes"]),
        "finished": bool(game_row["finished"]),
        "challenge_number": challenge_number(game_row["game_key"])
        if game_row["mode"] == "daily"
        else None,
    }


def submit_player(conn, game_row, row_index, column_index, player_id):
    game = load_game(conn, game_row)
    if game["finished"]:
        return game, "本局已经完成"
    if row_index not in range(3) or column_index not in range(3):
        return game, "格子位置无效"
    if (row_index, column_index) in game["cells"]:
        return game, "这个格子已经填过了"
    player = conn.execute(
        "SELECT * FROM guess_players WHERE id=? AND active=1", (player_id,)
    ).fetchone()
    if not player:
        return game, "请从候选列表中选择一名选手"
    duplicate = conn.execute(
        "SELECT 1 FROM player_bingo_cells WHERE game_id=? AND player_id=?",
        (game_row["id"], player_id),
    ).fetchone()
    if duplicate:
        return game, "同一名选手不能重复使用"
    row_key = game["row_keys"][row_index]
    column_key = game["column_keys"][column_index]
    if not player_matches(player, row_key, column_key):
        conn.execute(
            """UPDATE player_bingo_games
               SET mistakes=mistakes+1, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (game_row["id"],),
        )
        conn.commit()
        refreshed = conn.execute(
            "SELECT * FROM player_bingo_games WHERE id=?", (game_row["id"],)
        ).fetchone()
        return load_game(conn, refreshed), "这名选手不同时符合两个条件"

    conn.execute(
        """INSERT INTO player_bingo_cells(
               game_id, row_index, column_index, player_id
           ) VALUES(?,?,?,?)""",
        (game_row["id"], row_index, column_index, player_id),
    )
    coordinates = {
        (row["row_index"], row["column_index"])
        for row in conn.execute(
            "SELECT row_index, column_index FROM player_bingo_cells WHERE game_id=?",
            (game_row["id"],),
        ).fetchall()
    }
    lines = _line_count(coordinates)
    finished = len(coordinates) == 9
    conn.execute(
        """UPDATE player_bingo_games
           SET lines=?, finished=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
        (lines, int(finished), game_row["id"]),
    )
    conn.commit()
    refreshed = conn.execute(
        "SELECT * FROM player_bingo_games WHERE id=?", (game_row["id"],)
    ).fetchone()
    return load_game(conn, refreshed), None


def player_options(conn):
    return conn.execute(
        """SELECT id, nickname, full_name FROM guess_players
           WHERE active=1 ORDER BY nickname COLLATE NOCASE"""
    ).fetchall()


def user_statistics(conn, user_id, on_date=None):
    rows = conn.execute(
        """SELECT game_key, finished, mistakes FROM player_bingo_games g
           WHERE user_id=? AND mode='daily' AND EXISTS(
               SELECT 1 FROM player_bingo_cells c WHERE c.game_id=g.id
           ) ORDER BY game_key""",
        (user_id,),
    ).fetchall()
    completed = [date.fromisoformat(row["game_key"]) for row in rows if row["finished"]]
    current = 0
    if completed and completed[-1] in (_as_date(on_date), _as_date(on_date) - timedelta(days=1)):
        current = 1
        for index in range(len(completed) - 1, 0, -1):
            if completed[index - 1] == completed[index] - timedelta(days=1):
                current += 1
            else:
                break
    finished_mistakes = [row["mistakes"] for row in rows if row["finished"]]
    return {
        "games": len(rows),
        "completed": len(completed),
        "best_mistakes": min(finished_mistakes) if finished_mistakes else "-",
        "current_streak": current,
    }
