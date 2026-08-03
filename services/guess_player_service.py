"""Daily professional-player guessing game."""

import hashlib
import hmac
import secrets
from datetime import date, datetime, timedelta

from config import Config
from services.guess_player_pool import BLAST_GUESS_PLAYERS, SOURCE_DATE

MAX_GUESSES = 8
POOL_MODES = {"noob", "pro"}
COUNTRY_REGIONS = {
    **{
        code: "north-america"
        for code in ("CA", "CR", "DO", "GT", "HN", "JM", "MX", "PA", "PR", "SV", "US")
    },
    **{
        code: "south-america"
        for code in ("AR", "BO", "BR", "CL", "CO", "EC", "PE", "PY", "UY", "VE")
    },
    **{
        code: "europe"
        for code in (
            "AT",
            "BA",
            "BE",
            "BG",
            "CH",
            "CY",
            "CZ",
            "DE",
            "DK",
            "EE",
            "ES",
            "FI",
            "FR",
            "GB",
            "GR",
            "HR",
            "HU",
            "IE",
            "IS",
            "IT",
            "LT",
            "LU",
            "LV",
            "ME",
            "MK",
            "NL",
            "NO",
            "PL",
            "PT",
            "RO",
            "RS",
            "SE",
            "SI",
            "SK",
            "XK",
        )
    },
    **{
        code: "cis"
        for code in ("AM", "AZ", "BY", "GE", "KG", "KZ", "MD", "RU", "TJ", "TM", "UA", "UZ")
    },
    **{
        code: "middle-east-africa"
        for code in (
            "AE",
            "DZ",
            "EG",
            "IL",
            "IQ",
            "IR",
            "JO",
            "KW",
            "LB",
            "MA",
            "QA",
            "SA",
            "TN",
            "TR",
            "ZA",
        )
    },
    **{
        code: "asia"
        for code in (
            "BD",
            "CN",
            "HK",
            "ID",
            "IN",
            "JP",
            "KR",
            "MN",
            "MY",
            "NP",
            "PH",
            "PK",
            "SG",
            "TH",
            "TW",
            "VN",
        )
    },
    **{code: "oceania" for code in ("AU", "NZ")},
}


def seed_guess_players(conn):
    """Keep the local professional-player pool ready for the game."""
    # Preserve old attempts while ensuring stale or incorrectly sourced rows can
    # no longer be selected as new answers.
    conn.execute("UPDATE guess_players SET active=0")
    conn.executemany(
        """
        INSERT INTO guess_players(
            nickname, full_name, team, country_code, country_name, birth_date,
            profile_age, role, sniping_score, player_status, noob_eligible,
            major_appearances, active, source_url, source_checked_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)
        ON CONFLICT(nickname) DO UPDATE SET
            full_name=excluded.full_name,
            team=excluded.team,
            country_code=excluded.country_code,
            country_name=excluded.country_name,
            birth_date=excluded.birth_date,
            profile_age=excluded.profile_age,
            role=excluded.role,
            sniping_score=excluded.sniping_score,
            player_status=excluded.player_status,
            noob_eligible=excluded.noob_eligible,
            major_appearances=excluded.major_appearances,
            active=1,
            source_url=excluded.source_url,
            source_checked_at=excluded.source_checked_at
        """,
        [
            (
                player.get("nickname", ""),
                player.get("full_name") or player.get("nickname", ""),
                player.get("team") or "",
                player.get("country_code") or "",
                player.get("country_name") or "",
                player.get("birth_date") or "",
                player.get("profile_age"),
                player.get("role") or "",
                player.get("sniping_score"),
                player.get("player_status") or ("active" if player.get("team") else "unknown"),
                int(bool(player.get("noob_eligible"))),
                int(player.get("major_appearances", -1)),
                player.get("source_url") or "https://www.hltv.org/ranking/teams",
                player.get("source_checked_at") or SOURCE_DATE,
            )
            for player in BLAST_GUESS_PLAYERS
            if player.get("nickname")
        ],
    )


def normalize_pool_mode(value):
    return value if value in POOL_MODES else "noob"


def pool_players(conn, pool_mode, columns="*"):
    mode = normalize_pool_mode(pool_mode)
    extra = " AND noob_eligible=1" if mode == "noob" else ""
    return conn.execute(
        f"SELECT {columns} FROM guess_players WHERE active=1{extra} ORDER BY nickname COLLATE NOCASE"
    ).fetchall()


def player_affiliation(player):
    status = (player["player_status"] or "unknown").strip().lower()
    if status == "retired":
        return "Retired"
    if status == "free_agent":
        return "Free Agent"
    return (player["team"] or "").strip()


def affiliation_feedback(guessed, answer):
    guessed_status = (guessed["player_status"] or "unknown").lower()
    answer_status = (answer["player_status"] or "unknown").lower()
    no_team = {"retired", "free_agent"}
    if guessed_status in no_team and answer_status in no_team:
        return "correct"
    return _text_feedback(player_affiliation(guessed), player_affiliation(answer))


def game_date(value=None):
    if value is None:
        return datetime.now().date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def player_age(player, on_date):
    birth_date = (player["birth_date"] or "").strip()
    if not birth_date:
        try:
            age = player["profile_age"]
        except (KeyError, IndexError):
            age = None
        return int(age) if age is not None else None
    born = date.fromisoformat(birth_date)
    day = game_date(on_date)
    return day.year - born.year - ((day.month, day.day) < (born.month, born.day))


def challenge_number(on_date):
    kickoff = date(2026, 7, 14)
    return max(1, (game_date(on_date) - kickoff).days + 1)


def get_daily_answer(conn, on_date=None):
    """Create today's answer once, then keep it stable even if the pool changes."""
    day = game_date(on_date).isoformat()
    existing = conn.execute(
        """SELECT p.* FROM guess_player_daily d
           JOIN guess_players p ON p.id=d.player_id WHERE d.game_date=?""",
        (day,),
    ).fetchone()
    if existing:
        return existing

    recent_cutoff = (game_date(on_date) - timedelta(days=14)).isoformat()
    candidates = conn.execute(
        """SELECT * FROM guess_players
           WHERE active=1 AND id NOT IN (
               SELECT player_id FROM guess_player_daily WHERE game_date>=?
           ) ORDER BY id""",
        (recent_cutoff,),
    ).fetchall()
    if not candidates:
        candidates = conn.execute(
            "SELECT * FROM guess_players WHERE active=1 ORDER BY id"
        ).fetchall()
    if not candidates:
        raise RuntimeError("猜选手题库为空")

    secret = str(getattr(Config, "SECRET_KEY", "80gotv-guess-player"))
    digest = hmac.new(secret.encode(), day.encode(), hashlib.sha256).hexdigest()
    selected = candidates[int(digest, 16) % len(candidates)]
    conn.execute(
        "INSERT OR IGNORE INTO guess_player_daily(game_date, player_id) VALUES(?,?)",
        (day, selected["id"]),
    )
    conn.commit()
    return conn.execute(
        """SELECT p.* FROM guess_player_daily d
           JOIN guess_players p ON p.id=d.player_id WHERE d.game_date=?""",
        (day,),
    ).fetchone()


def _number_feedback(guess_value, answer_value, close_distance=2):
    if guess_value is None or answer_value is None:
        return {"state": "neutral", "direction": ""}
    if int(guess_value) < 0 or int(answer_value) < 0:
        return {"state": "neutral", "direction": ""}
    if guess_value == answer_value:
        return {"state": "correct", "direction": ""}
    return {
        "state": "close" if abs(guess_value - answer_value) <= close_distance else "wrong",
        "direction": "up" if guess_value < answer_value else "down",
    }


def compare_players(guessed, answer, on_date=None):
    guessed_age = player_age(guessed, on_date)
    answer_age = player_age(answer, on_date)
    guessed_region = COUNTRY_REGIONS.get(guessed["country_code"], guessed["country_code"])
    answer_region = COUNTRY_REGIONS.get(answer["country_code"], answer["country_code"])
    if not guessed["country_code"] or not answer["country_code"]:
        country_state = "neutral"
    else:
        country_state = (
            "correct"
            if guessed["country_code"] == answer["country_code"]
            else ("close" if guessed_region == answer_region else "wrong")
        )
    is_correct = guessed["id"] == answer["id"]
    return {
        "player": guessed,
        "is_correct": is_correct,
        "name_state": "correct" if is_correct else "wrong",
        "team_state": affiliation_feedback(guessed, answer),
        "affiliation": player_affiliation(guessed),
        "country_state": country_state,
        "country_flag": country_flag(guessed["country_code"]),
        "age": guessed_age,
        "age_feedback": _number_feedback(guessed_age, answer_age),
        "role_state": _text_feedback(guessed["role"], answer["role"]),
        "major_feedback": _number_feedback(
            guessed["major_appearances"], answer["major_appearances"]
        ),
    }


def _text_feedback(guess_value, answer_value):
    if not guess_value or not answer_value:
        return "neutral"
    return "correct" if guess_value == answer_value else "wrong"


def country_flag(country_code):
    code = (country_code or "").strip().upper()
    if len(code) != 2 or not code.isalpha():
        return ""
    return "".join(chr(127397 + ord(letter)) for letter in code)


def load_game(conn, user_id, on_date=None):
    day = game_date(on_date).isoformat()
    answer = get_daily_answer(conn, day)
    guessed_rows = conn.execute(
        """SELECT p.*, a.attempt_number, a.is_correct
           FROM guess_player_attempts a
           JOIN guess_players p ON p.id=a.guessed_player_id
           WHERE a.user_id=? AND a.game_date=? ORDER BY a.attempt_number""",
        (user_id, day),
    ).fetchall()
    results = [compare_players(row, answer, day) for row in guessed_rows]
    won = any(result["is_correct"] for result in results)
    finished = won or len(results) >= MAX_GUESSES
    return {
        "mode": "daily",
        "date": day,
        "answer": answer if finished else None,
        "answer_affiliation": player_affiliation(answer) if finished else "",
        "answer_row": answer,
        "results": results,
        "won": won,
        "finished": finished,
        "remaining": max(0, MAX_GUESSES - len(results)),
        "challenge_number": challenge_number(day),
    }


def create_practice_game(conn, user_id, pool_mode="noob"):
    """Start a fresh practice round and avoid the user's five latest answers."""
    pool_mode = normalize_pool_mode(pool_mode)
    conn.execute(
        "UPDATE guess_player_practice_games SET status='abandoned' WHERE user_id=? AND status='active'",
        (user_id,),
    )
    recent_ids = [
        row[0]
        for row in conn.execute(
            """SELECT player_id FROM guess_player_practice_games
               WHERE user_id=? AND pool_mode=? ORDER BY id DESC LIMIT 5""",
            (user_id, pool_mode),
        ).fetchall()
    ]
    candidates = pool_players(conn, pool_mode)
    preferred = [row for row in candidates if row["id"] not in recent_ids]
    choices = preferred or candidates
    if not choices:
        raise RuntimeError("猜选手题库为空")
    answer = choices[secrets.randbelow(len(choices))]
    cursor = conn.execute(
        """INSERT INTO guess_player_practice_games(user_id, player_id, pool_mode, status)
           VALUES(?,?,?,'active')""",
        (user_id, answer["id"], pool_mode),
    )
    conn.commit()
    return cursor.lastrowid


def load_practice_game(conn, user_id, pool_mode="noob"):
    pool_mode = normalize_pool_mode(pool_mode)
    game_row = conn.execute(
        """SELECT g.*, p.nickname AS answer_nickname
           FROM guess_player_practice_games g
           JOIN guess_players p ON p.id=g.player_id
           WHERE g.user_id=? AND g.pool_mode=? AND g.status IN ('active','finished')
           ORDER BY g.id DESC LIMIT 1""",
        (user_id, pool_mode),
    ).fetchone()
    if not game_row:
        game_id = create_practice_game(conn, user_id, pool_mode)
        game_row = conn.execute(
            "SELECT * FROM guess_player_practice_games WHERE id=?", (game_id,)
        ).fetchone()

    answer = conn.execute(
        "SELECT * FROM guess_players WHERE id=?", (game_row["player_id"],)
    ).fetchone()
    guessed_rows = conn.execute(
        """SELECT p.*, a.attempt_number, a.is_correct
           FROM guess_player_practice_attempts a
           JOIN guess_players p ON p.id=a.guessed_player_id
           WHERE a.game_id=? ORDER BY a.attempt_number""",
        (game_row["id"],),
    ).fetchall()
    results = [compare_players(row, answer) for row in guessed_rows]
    won = any(result["is_correct"] for result in results)
    finished = won or len(results) >= MAX_GUESSES
    if finished and game_row["status"] == "active":
        conn.execute(
            """UPDATE guess_player_practice_games
               SET status='finished', completed_at=CURRENT_TIMESTAMP WHERE id=?""",
            (game_row["id"],),
        )
        conn.commit()
    return {
        "mode": "practice",
        "pool_mode": pool_mode,
        "id": game_row["id"],
        "answer": answer if finished else None,
        "answer_affiliation": player_affiliation(answer) if finished else "",
        "answer_row": answer,
        "results": results,
        "won": won,
        "finished": finished,
        "remaining": max(0, MAX_GUESSES - len(results)),
        "challenge_number": None,
    }


ROOM_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _room_code():
    return "".join(secrets.choice(ROOM_ALPHABET) for _ in range(6))


def _cleanup_rooms(conn):
    conn.execute(
        """UPDATE guess_player_rooms SET status='abandoned', finished_at=CURRENT_TIMESTAMP
           WHERE status='waiting' AND created_at < datetime('now', '-6 hours')"""
    )
    conn.execute(
        """UPDATE guess_player_rooms SET status='abandoned', finished_at=CURRENT_TIMESTAMP
           WHERE status='active' AND started_at < datetime('now', '-24 hours')"""
    )


def create_multiplayer_room(conn, user_id, pool_mode="noob"):
    pool_mode = normalize_pool_mode(pool_mode)
    choices = pool_players(conn, pool_mode)
    if not choices:
        raise RuntimeError("猜选手题库为空")
    answer = choices[secrets.randbelow(len(choices))]
    _cleanup_rooms(conn)
    for _ in range(20):
        code = _room_code()
        try:
            cursor = conn.execute(
                """INSERT INTO guess_player_rooms(
                       room_code, host_user_id, player_id, pool_mode, host_last_seen
                   ) VALUES(?,?,?,?,CURRENT_TIMESTAMP)""",
                (code, user_id, answer["id"], pool_mode),
            )
            conn.commit()
            return cursor.lastrowid, code
        except Exception as exc:
            if "unique" not in str(exc).lower():
                raise
            conn.rollback()
    raise RuntimeError("房间码生成失败，请重试")


def get_multiplayer_room(conn, room_code):
    return conn.execute(
        "SELECT * FROM guess_player_rooms WHERE room_code=?",
        ((room_code or "").strip().upper(),),
    ).fetchone()


def join_multiplayer_room(conn, room_code, user_id):
    room = get_multiplayer_room(conn, room_code)
    if not room:
        return None, "房间不存在"
    if user_id in (room["host_user_id"], room["guest_user_id"]):
        return room, ""
    if room["status"] != "waiting" or room["guest_user_id"] is not None:
        return None, "房间已经满员或比赛已经开始"
    conn.execute(
        """UPDATE guess_player_rooms
           SET guest_user_id=?, guest_last_seen=CURRENT_TIMESTAMP,
               status='active', started_at=CURRENT_TIMESTAMP
           WHERE id=? AND guest_user_id IS NULL AND status='waiting'""",
        (user_id, room["id"]),
    )
    conn.commit()
    return get_multiplayer_room(conn, room_code), ""


def _room_participant(room, user_id):
    if user_id == room["host_user_id"]:
        return "host"
    if user_id == room["guest_user_id"]:
        return "guest"
    return ""


def _attempt_rows(conn, room_id, user_id):
    return conn.execute(
        """SELECT p.*, a.attempt_number, a.is_correct
           FROM guess_player_room_attempts a
           JOIN guess_players p ON p.id=a.guessed_player_id
           WHERE a.room_id=? AND a.user_id=? ORDER BY a.attempt_number""",
        (room_id, user_id),
    ).fetchall()


def submit_multiplayer_guess(conn, room_code, user_id, guessed_player_id):
    conn.execute("BEGIN IMMEDIATE")
    room = get_multiplayer_room(conn, room_code)
    side = _room_participant(room, user_id) if room else ""
    if not room or not side:
        conn.rollback()
        return "你不在这个房间里"
    if room["status"] != "active":
        conn.rollback()
        return "比赛还没有开始或已经结束"
    pool_mode = normalize_pool_mode(room["pool_mode"])
    extra = " AND noob_eligible=1" if pool_mode == "noob" else ""
    guessed = conn.execute(
        f"SELECT * FROM guess_players WHERE id=? AND active=1{extra}",
        (guessed_player_id,),
    ).fetchone()
    if not guessed:
        conn.rollback()
        return "这名选手不在当前题库中"
    existing = conn.execute(
        """SELECT 1 FROM guess_player_room_attempts
           WHERE room_id=? AND user_id=? AND guessed_player_id=?""",
        (room["id"], user_id, guessed["id"]),
    ).fetchone()
    if existing:
        conn.rollback()
        return "这名选手本局已经猜过了"
    attempt_number = (
        conn.execute(
            "SELECT COUNT(*) FROM guess_player_room_attempts WHERE room_id=? AND user_id=?",
            (room["id"], user_id),
        ).fetchone()[0]
        + 1
    )
    if attempt_number > MAX_GUESSES:
        conn.rollback()
        return "你的 8 次机会已经用完"
    is_correct = int(guessed["id"] == room["player_id"])
    conn.execute(
        """INSERT INTO guess_player_room_attempts(
               room_id, user_id, guessed_player_id, attempt_number, is_correct
           ) VALUES(?,?,?,?,?)""",
        (room["id"], user_id, guessed["id"], attempt_number, is_correct),
    )
    if is_correct:
        conn.execute(
            """UPDATE guess_player_rooms
               SET status='finished', winner_user_id=?, finished_at=CURRENT_TIMESTAMP
               WHERE id=? AND status='active'""",
            (user_id, room["id"]),
        )
    elif room["guest_user_id"] is not None:
        opponent_id = room["guest_user_id"] if side == "host" else room["host_user_id"]
        opponent_attempts = conn.execute(
            "SELECT COUNT(*) FROM guess_player_room_attempts WHERE room_id=? AND user_id=?",
            (room["id"], opponent_id),
        ).fetchone()[0]
        if attempt_number >= MAX_GUESSES and opponent_attempts >= MAX_GUESSES:
            conn.execute(
                """UPDATE guess_player_rooms
                   SET status='finished', finished_at=CURRENT_TIMESTAMP
                   WHERE id=? AND status='active'""",
                (room["id"],),
            )
    seen_column = "host_last_seen" if side == "host" else "guest_last_seen"
    conn.execute(
        f"UPDATE guess_player_rooms SET {seen_column}=CURRENT_TIMESTAMP WHERE id=?",
        (room["id"],),
    )
    conn.commit()
    return ""


def _result_payload(result):
    player = result["player"]
    return {
        "player_id": player["id"],
        "nickname": player["nickname"],
        "affiliation": result["affiliation"] or "未知",
        "country_flag": result["country_flag"],
        "country_name": player["country_name"],
        "age": result["age"],
        "role": player["role"] or "",
        "major_appearances": player["major_appearances"],
        "is_correct": result["is_correct"],
        "name_state": result["name_state"],
        "team_state": result["team_state"],
        "country_state": result["country_state"],
        "age_feedback": result["age_feedback"],
        "role_state": result["role_state"],
        "major_feedback": result["major_feedback"],
    }


def multiplayer_room_state(conn, room_code, user_id, touch=True):
    room = get_multiplayer_room(conn, room_code)
    side = _room_participant(room, user_id) if room else ""
    if not room or not side:
        return None
    if touch:
        seen_column = "host_last_seen" if side == "host" else "guest_last_seen"
        conn.execute(
            f"UPDATE guess_player_rooms SET {seen_column}=CURRENT_TIMESTAMP WHERE id=?",
            (room["id"],),
        )
        conn.commit()
        room = get_multiplayer_room(conn, room_code)

    opponent_id = room["guest_user_id"] if side == "host" else room["host_user_id"]
    answer = conn.execute("SELECT * FROM guess_players WHERE id=?", (room["player_id"],)).fetchone()
    own_rows = _attempt_rows(conn, room["id"], user_id)
    opponent_rows = _attempt_rows(conn, room["id"], opponent_id) if opponent_id else []
    own_results = [compare_players(row, answer) for row in own_rows]
    own_name = conn.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()
    opponent_name = (
        conn.execute("SELECT username FROM users WHERE id=?", (opponent_id,)).fetchone()
        if opponent_id
        else None
    )
    finished = room["status"] == "finished"
    winner_id = room["winner_user_id"]
    if not finished:
        outcome = ""
    elif winner_id is None:
        outcome = "draw"
    elif winner_id == user_id:
        outcome = "win"
    else:
        outcome = "loss"
    return {
        "room_code": room["room_code"],
        "pool_mode": normalize_pool_mode(room["pool_mode"]),
        "status": room["status"],
        "side": side,
        "results": [_result_payload(result) for result in own_results],
        "remaining": max(0, MAX_GUESSES - len(own_rows)),
        "can_guess": room["status"] == "active" and len(own_rows) < MAX_GUESSES,
        "outcome": outcome,
        "answer": (
            {
                "nickname": answer["nickname"],
                "full_name": answer["full_name"],
                "affiliation": player_affiliation(answer),
            }
            if finished
            else None
        ),
        "me": {
            "username": own_name["username"] if own_name else "选手 1",
            "attempts": len(own_rows),
            "solved": any(row["is_correct"] for row in own_rows),
        },
        "opponent": {
            "username": opponent_name["username"] if opponent_name else "等待对手",
            "attempts": len(opponent_rows),
            "solved": any(row["is_correct"] for row in opponent_rows),
            "joined": bool(opponent_id),
        },
    }


def user_statistics(conn, user_id, on_date=None):
    rows = conn.execute(
        """SELECT game_date, MAX(is_correct) AS won,
                  MIN(CASE WHEN is_correct=1 THEN attempt_number END) AS win_attempt
           FROM guess_player_attempts WHERE user_id=?
           GROUP BY game_date ORDER BY game_date""",
        (user_id,),
    ).fetchall()
    wins = [date.fromisoformat(row["game_date"]) for row in rows if row["won"]]
    longest = 0
    run = 0
    previous = None
    for won_day in wins:
        run = run + 1 if previous and won_day == previous + timedelta(days=1) else 1
        longest = max(longest, run)
        previous = won_day

    current = 0
    if wins:
        latest_allowed = game_date(on_date)
        if wins[-1] in (latest_allowed, latest_allowed - timedelta(days=1)):
            current = 1
            for index in range(len(wins) - 1, 0, -1):
                if wins[index - 1] == wins[index] - timedelta(days=1):
                    current += 1
                else:
                    break
    games = len(rows)
    won_count = len(wins)
    return {
        "games": games,
        "wins": won_count,
        "win_rate": round(won_count / games * 100) if games else 0,
        "current_streak": current,
        "longest_streak": longest,
    }
