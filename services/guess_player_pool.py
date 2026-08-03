"""BLAST Counter-Strikle public player pool used by the guessing game."""

import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = ROOT / "data" / "guess_player_profiles.json"
BLAST_PLAYER_SOURCE_URL = "https://data.blast.tv/minigames/counterstrikle/players.json"


# All fallback entries satisfy the team-ranking rule. The 2018 FaZe lineup is
# retained explicitly because it is also the regression example for the sync.
FALLBACK_PLAYERS = (
    {
        "nickname": "karrigan",
        "full_name": "Finn Andersen",
        "team": "Falcons",
        "country_code": "DK",
        "country_name": "Denmark",
        "birth_date": "1990-04-14",
        "profile_age": None,
        "role": "rifler",
        "major_appearances": 21,
        "source_url": "https://www.hltv.org/player/429/karrigan",
    },
    {
        "nickname": "NiKo",
        "full_name": "Nikola Kovac",
        "team": "Falcons",
        "country_code": "BA",
        "country_name": "Bosnia and Herzegovina",
        "birth_date": "1997-02-16",
        "profile_age": None,
        "role": "rifler",
        "major_appearances": 17,
        "source_url": "https://www.hltv.org/player/3741/niko",
    },
    {
        "nickname": "olofmeister",
        "full_name": "Olof Kajbjer",
        "team": "",
        "country_code": "SE",
        "country_name": "Sweden",
        "birth_date": "1992-01-31",
        "profile_age": None,
        "role": "rifler",
        "major_appearances": -1,
        "source_url": "https://www.hltv.org/player/885/olofmeister",
    },
    {
        "nickname": "GuardiaN",
        "full_name": "Ladislav Kovacs",
        "team": "",
        "country_code": "SK",
        "country_name": "Slovakia",
        "birth_date": "1991-07-09",
        "profile_age": None,
        "role": "awper",
        "major_appearances": -1,
        "source_url": "https://www.hltv.org/player/2757/guardian",
    },
    {
        "nickname": "rain",
        "full_name": "Havard Nygaard",
        "team": "100 Thieves",
        "country_code": "NO",
        "country_name": "Norway",
        "birth_date": "1994-08-27",
        "profile_age": None,
        "role": "rifler",
        "major_appearances": -1,
        "source_url": "https://www.hltv.org/player/8183/rain",
    },
    {
        "nickname": "advent",
        "full_name": "Zhuo Liang",
        "team": "",
        "country_code": "CN",
        "country_name": "China",
        "birth_date": "",
        "profile_age": 34,
        "role": "rifler",
        "major_appearances": 1,
        "source_url": "https://www.hltv.org/player/8600/advent",
    },
)


def _load_snapshot():
    if not SNAPSHOT_PATH.exists():
        return [dict(player) for player in FALLBACK_PLAYERS]
    try:
        payload = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return [dict(player) for player in FALLBACK_PLAYERS]
    records = payload.get("players", payload) if isinstance(payload, dict) else payload
    if not isinstance(records, list) or not records:
        return [dict(player) for player in FALLBACK_PLAYERS]
    blast_records = [
        player
        for player in records
        if "blast_counterstrikle_current_pool"
        in (player.get("eligibility", {}).get("reasons") or [])
    ]
    return blast_records or [dict(player) for player in FALLBACK_PLAYERS]


BLAST_GUESS_PLAYERS = tuple(_load_snapshot())
SOURCE_DATE = (
    max(
        (str(player.get("source_checked_at") or "") for player in BLAST_GUESS_PLAYERS),
        default=date.today().isoformat(),
    )
    or date.today().isoformat()
)
