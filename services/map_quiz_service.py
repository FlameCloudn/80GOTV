"""Server-side question and progress logic for the map location quiz."""

import hashlib
import hmac
import re
import secrets
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from config import Config

MAX_ATTEMPTS = 3
ASSET_ROOT = Path(__file__).resolve().parents[1] / "static" / "images" / "map-quiz"
SOURCE_COLLECTION = "https://prosettings.net/blog/cs2-maps/"

MAPS = (
    ("ancient", "Ancient"),
    ("anubis", "Anubis"),
    ("cache", "Cache"),
    ("dust2", "Dust II"),
    ("inferno", "Inferno"),
    ("mirage", "Mirage"),
    ("nuke", "Nuke"),
)


def _question(key, image, map_key, spot, aliases, source_url):
    return {
        "key": key,
        "image": image,
        "map_key": map_key,
        "map_name": dict(MAPS)[map_key],
        "spot": spot,
        "aliases": tuple(aliases),
        "source_url": source_url,
    }


QUESTIONS = (
    _question(
        "mq_11c7a9",
        "ancient.webp",
        "ancient",
        "A 包点",
        ("a", "a site", "a bombsite", "a包点", "a点", "a区"),
        "https://prosettings.net/blog/ancient-in-cs2/",
    ),
    _question(
        "mq_43dd82",
        "ancient-2.jpg",
        "ancient",
        "神庙",
        ("temple", "神庙", "temple room"),
        "https://prosettings.net/blog/ancient-in-cs2/",
    ),
    _question(
        "mq_7a092e",
        "ancient-3.jpg",
        "ancient",
        "B 包点",
        ("b", "b site", "b bombsite", "b包点", "b点", "b区"),
        "https://prosettings.net/blog/ancient-in-cs2/",
    ),
    _question(
        "mq_215dce",
        "anubis.webp",
        "anubis",
        "水路",
        ("water", "canal", "水路", "河道", "水道"),
        "https://prosettings.net/blog/anubis-in-cs2/",
    ),
    _question(
        "mq_5e140b",
        "anubis-1.jpg",
        "anubis",
        "A 包点",
        ("a", "a site", "a bombsite", "a包点", "a点", "a区"),
        "https://prosettings.net/blog/anubis-in-cs2/",
    ),
    _question(
        "mq_8ac251",
        "anubis-2.jpg",
        "anubis",
        "B 连接",
        ("b connector", "connector b", "b连接", "连接b", "b通道"),
        "https://prosettings.net/blog/anubis-in-cs2/",
    ),
    _question(
        "mq_9b6ef0",
        "cache.png",
        "cache",
        "B 包点",
        ("b", "b site", "b bombsite", "b包点", "b点", "b区"),
        SOURCE_COLLECTION,
    ),
    _question(
        "mq_b81136",
        "dust2.webp",
        "dust2",
        "A 大道",
        ("long", "long a", "a long", "a大道", "大道", "a大"),
        SOURCE_COLLECTION,
    ),
    _question(
        "mq_c2a541",
        "inferno.webp",
        "inferno",
        "中路",
        ("mid", "middle", "中路", "中门"),
        "https://prosettings.net/blog/inferno-in-cs2/",
    ),
    _question(
        "mq_d76c03",
        "inferno-1.jpg",
        "inferno",
        "匪口斜坡",
        ("t ramp", "ramp", "匪口斜坡", "t斜坡", "斜坡"),
        "https://prosettings.net/blog/inferno-in-cs2/",
    ),
    _question(
        "mq_e45912",
        "inferno-3.jpg",
        "inferno",
        "警家",
        ("ct", "ct spawn", "警家", "ct家", "警出生点"),
        "https://prosettings.net/blog/inferno-in-cs2/",
    ),
    _question(
        "mq_f7d225",
        "mirage.webp",
        "mirage",
        "中路窗口",
        ("window", "mid window", "sniper window", "中路窗口", "窗口", "狙击窗"),
        SOURCE_COLLECTION,
    ),
    _question(
        "mq_0a61bf",
        "nuke.webp",
        "nuke",
        "B 包点",
        ("b", "b site", "lower site", "b包点", "b点", "下层包点"),
        "https://prosettings.net/blog/nuke-in-cs2/",
    ),
    _question(
        "mq_3164aa",
        "nuke-17.jpg",
        "nuke",
        "外场",
        ("outside", "yard", "外场", "外面", "室外"),
        "https://prosettings.net/blog/nuke-in-cs2/",
    ),
    _question(
        "mq_694f0d",
        "nuke-19.jpg",
        "nuke",
        "T 红箱",
        ("t red", "red", "red box", "t红箱", "红箱", "红车"),
        "https://prosettings.net/blog/nuke-in-cs2/",
    ),
)

QUESTION_BY_KEY = {item["key"]: item for item in QUESTIONS}


def normalize_answer(value):
    value = (value or "").strip().casefold()
    return re.sub(r"[\s_\-./\\]+", "", value)


def question_for_key(question_key):
    return QUESTION_BY_KEY.get((question_key or "").strip())


def question_image_path(question_key, variant=None):
    question = question_for_key(question_key)
    if not question:
        return None
    asset_root = ASSET_ROOT.resolve()
    path = (asset_root / question["image"]).resolve()
    try:
        path.relative_to(asset_root)
    except ValueError:
        return None
    if variant == "mobile":
        mobile_path = (asset_root / "mobile" / f"{path.stem}.webp").resolve()
        if mobile_path.is_file():
            path = mobile_path
    return path if path.is_file() else None


def challenge_number(on_date=None):
    kickoff = date(2026, 7, 15)
    day = _as_date(on_date)
    return max(1, (day - kickoff).days + 1)


def _as_date(value=None):
    if value is None:
        return datetime.now().date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _daily_question_key(game_key):
    secret = str(getattr(Config, "SECRET_KEY", "80gotv-map-quiz"))
    digest = hmac.new(secret.encode(), f"map-quiz:{game_key}".encode(), hashlib.sha256).digest()
    return QUESTIONS[int.from_bytes(digest, "big") % len(QUESTIONS)]["key"]


def _create_game(conn, user_id, mode, game_key, question_key):
    conn.execute(
        """INSERT OR IGNORE INTO map_quiz_games(
               user_id, mode, game_key, question_key
           ) VALUES(?,?,?,?)""",
        (user_id, mode, game_key, question_key),
    )
    conn.commit()
    return conn.execute(
        "SELECT * FROM map_quiz_games WHERE user_id=? AND mode=? AND game_key=?",
        (user_id, mode, game_key),
    ).fetchone()


def get_daily_game_row(conn, user_id, on_date=None):
    game_key = _as_date(on_date).isoformat()
    return _create_game(conn, user_id, "daily", game_key, _daily_question_key(game_key))


def get_practice_game_row(conn, user_id):
    row = conn.execute(
        """SELECT * FROM map_quiz_games
           WHERE user_id=? AND mode='practice' ORDER BY id DESC LIMIT 1""",
        (user_id,),
    ).fetchone()
    if row:
        return row
    return create_practice_game(conn, user_id)


def create_practice_game(conn, user_id):
    previous = conn.execute(
        """SELECT question_key FROM map_quiz_games
           WHERE user_id=? AND mode='practice' ORDER BY id DESC LIMIT 1""",
        (user_id,),
    ).fetchone()
    candidates = [item for item in QUESTIONS if not previous or item["key"] != previous[0]]
    selected = secrets.choice(candidates or list(QUESTIONS))
    return _create_game(conn, user_id, "practice", uuid.uuid4().hex, selected["key"])


def load_game(conn, game_row):
    attempts = conn.execute(
        """SELECT * FROM map_quiz_attempts
           WHERE game_id=? ORDER BY attempt_number""",
        (game_row["id"],),
    ).fetchall()
    question = question_for_key(game_row["question_key"])
    finished = bool(game_row["finished"])
    return {
        "row": game_row,
        "question_key": game_row["question_key"],
        "attempts": attempts,
        "remaining": max(0, MAX_ATTEMPTS - len(attempts)),
        "finished": finished,
        "won": bool(game_row["won"]),
        "answer": question if finished else None,
        "challenge_number": challenge_number(game_row["game_key"])
        if game_row["mode"] == "daily"
        else None,
    }


def submit_guess(conn, game_row, guessed_map, guessed_spot):
    game = load_game(conn, game_row)
    if game["finished"]:
        return game, "本局已经结束"
    guessed_map = (guessed_map or "").strip().casefold()
    guessed_spot = (guessed_spot or "").strip()[:80]
    if guessed_map not in dict(MAPS) or not guessed_spot:
        return game, "请选择地图并填写点位"

    question = question_for_key(game_row["question_key"])
    map_correct = guessed_map == question["map_key"]
    accepted = {
        normalize_answer(question["spot"]),
        *(normalize_answer(alias) for alias in question["aliases"]),
    }
    spot_correct = normalize_answer(guessed_spot) in accepted
    attempt_number = len(game["attempts"]) + 1
    won = map_correct and spot_correct
    finished = won or attempt_number >= MAX_ATTEMPTS
    conn.execute(
        """INSERT INTO map_quiz_attempts(
               game_id, attempt_number, guessed_map, guessed_spot,
               map_correct, spot_correct
           ) VALUES(?,?,?,?,?,?)""",
        (
            game_row["id"],
            attempt_number,
            guessed_map,
            guessed_spot,
            int(map_correct),
            int(spot_correct),
        ),
    )
    conn.execute(
        """UPDATE map_quiz_games
           SET finished=?, won=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
        (int(finished), int(won), game_row["id"]),
    )
    conn.commit()
    refreshed = conn.execute(
        "SELECT * FROM map_quiz_games WHERE id=?", (game_row["id"],)
    ).fetchone()
    return load_game(conn, refreshed), None


def user_statistics(conn, user_id, on_date=None):
    rows = conn.execute(
        """SELECT game_key, won FROM map_quiz_games g
           WHERE user_id=? AND mode='daily' AND EXISTS(
               SELECT 1 FROM map_quiz_attempts a WHERE a.game_id=g.id
           ) ORDER BY game_key""",
        (user_id,),
    ).fetchall()
    wins = [date.fromisoformat(row["game_key"]) for row in rows if row["won"]]
    longest = 0
    run = 0
    previous = None
    for won_day in wins:
        run = run + 1 if previous and won_day == previous + timedelta(days=1) else 1
        longest = max(longest, run)
        previous = won_day
    current = 0
    if wins and wins[-1] in (_as_date(on_date), _as_date(on_date) - timedelta(days=1)):
        current = 1
        for index in range(len(wins) - 1, 0, -1):
            if wins[index - 1] == wins[index] - timedelta(days=1):
                current += 1
            else:
                break
    return {
        "games": len(rows),
        "win_rate": round(len(wins) / len(rows) * 100) if rows else 0,
        "current_streak": current,
        "longest_streak": longest,
    }


def public_spot_options():
    seen = set()
    values = []
    for question in QUESTIONS:
        if question["spot"] not in seen:
            seen.add(question["spot"])
            values.append(question["spot"])
    return values
