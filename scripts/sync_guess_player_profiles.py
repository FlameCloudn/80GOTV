"""Build the guess-player pool from HLTV team-ranking rosters.

Pro eligibility:
1. players on the latest world-ranking Top 50 teams;
2. players shown on a Top 20 team in any weekly HLTV ranking since 2015-10-01.

Noob eligibility is narrower:
1. annual HLTV Top 20 players since 2015;
2. players shown on a Top 5 team since 2018-01-01.

The command is resumable. Downloaded reader pages are cached under temp/.
"""

import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "guess_player_profiles.json"
CACHE_ROOT = ROOT / "temp" / "hltv-guess-player-sync"
READER_PREFIX = "https://r.jina.ai/"
USER_AGENT = "80GOTV team-ranking player sync"
BLAST_PLAYERS_URL = "https://data.blast.tv/minigames/counterstrikle/players.json"
BLAST_GUESS_URL = "https://api.blast.tv/v1/counterstrikle/guesses"
PROFILE_RE = re.compile(r"https://www\.hltv\.org/player/(\d+)/([^\s)#?\"]+)", re.I)
RANK_RE = re.compile(r"(?m)^#(\d+)(?=\D|$)")
POINTS_RE = re.compile(r"(?m)^([^\n(]+?)[ \t]*(?:\n)?\((\d+) HLTV points\)[ \t]*$")
MOVE_RE = re.compile(r"(?:[+-]\d+|-|NEW TEAM)", re.I)


KNOWN_AWPERS = {
    "zywoo",
    "m0nesy",
    "sh1ro",
    "device",
    "s1mple",
    "guardian",
    "kennys",
    "fallen",
    "oskar",
    "jame",
    "broky",
    "torzsi",
    "allu",
    "skadoodle",
    "woxic",
    "cerq",
    "syrson",
    "hen1",
    "sunpayus",
    "cadiaN",
    "wonderful",
    "molodoy",
    "chrisj",
    "nifty",
    "jdm64",
    "draken",
    "smooya",
    "xccurate",
    "degster",
    "mantuu",
    "poizon",
    "mhl",
    "hallzerk",
    "farlig",
    "afro",
    "nawwk",
    "nicoodoz",
    "headtr1ck",
    "sl3nd",
    "story",
    "nqz",
    "try",
    "saffee",
    "osee",
    "junior",
    "regali",
    "hades",
    "artfr0st",
}
MANUAL_PROFILE_URLS = {
    # These inactive players are omitted from HLTV's active/retired directory,
    # and their nicknames contain spaces or collide by letter case.
    "gob b": "https://www.hltv.org/player/136/gob-b",
    "disco doplan": "https://www.hltv.org/player/9256/disco-doplan",
    "h4rn": "https://www.hltv.org/player/20097/h4rn",
    "REDSTAR": "https://www.hltv.org/player/15369/redstar",
    "Bart4k": "https://www.hltv.org/player/19957/bart4k",
    "KrizzeN": "https://www.hltv.org/player/12161/krizzen",
    "MAiNLiNE": "https://www.hltv.org/player/9017/mainline",
    "mertz": "https://www.hltv.org/player/9895/mertz",
}
OFFLINE = False

COUNTRY_NAMES = {
    "AR": "Argentina",
    "AT": "Austria",
    "AU": "Australia",
    "AZ": "Azerbaijan",
    "BA": "Bosnia and Herzegovina",
    "BE": "Belgium",
    "BG": "Bulgaria",
    "BR": "Brazil",
    "BY": "Belarus",
    "CA": "Canada",
    "CH": "Switzerland",
    "CL": "Chile",
    "CN": "China",
    "CO": "Colombia",
    "CZ": "Czech Republic",
    "DE": "Germany",
    "DK": "Denmark",
    "EE": "Estonia",
    "ES": "Spain",
    "FI": "Finland",
    "FR": "France",
    "GB": "United Kingdom",
    "GE": "Georgia",
    "GR": "Greece",
    "GT": "Guatemala",
    "HK": "Hong Kong",
    "HR": "Croatia",
    "HU": "Hungary",
    "ID": "Indonesia",
    "IE": "Ireland",
    "IL": "Israel",
    "IN": "India",
    "IS": "Iceland",
    "IT": "Italy",
    "JO": "Jordan",
    "JP": "Japan",
    "KG": "Kyrgyzstan",
    "KR": "South Korea",
    "KZ": "Kazakhstan",
    "LT": "Lithuania",
    "LU": "Luxembourg",
    "LV": "Latvia",
    "MD": "Moldova",
    "ME": "Montenegro",
    "MK": "North Macedonia",
    "MN": "Mongolia",
    "MX": "Mexico",
    "MY": "Malaysia",
    "NL": "Netherlands",
    "NO": "Norway",
    "NZ": "New Zealand",
    "PE": "Peru",
    "PH": "Philippines",
    "PK": "Pakistan",
    "PL": "Poland",
    "PT": "Portugal",
    "RO": "Romania",
    "RS": "Serbia",
    "RU": "Russia",
    "SE": "Sweden",
    "SG": "Singapore",
    "SI": "Slovenia",
    "SK": "Slovakia",
    "TH": "Thailand",
    "TR": "Turkey",
    "TW": "Taiwan",
    "UA": "Ukraine",
    "US": "United States",
    "UY": "Uruguay",
    "UZ": "Uzbekistan",
    "VE": "Venezuela",
    "VN": "Vietnam",
    "XK": "Kosovo",
    "ZA": "South Africa",
}


def cache_path(group, name):
    safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "-", name).strip("-")
    return CACHE_ROOT / group / f"{safe_name}.md"


def fetch_text(url, cache_file, attempts=5):
    if cache_file.exists():
        text = cache_file.read_text(encoding="utf-8", errors="replace")
        if text.strip():
            return text
    if OFFLINE:
        raise RuntimeError(f"No cached copy for {url}")

    reader_url = url if url.startswith(READER_PREFIX) else READER_PREFIX + url
    last_error = None
    for attempt in range(attempts):
        try:
            request = Request(reader_url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=120) as response:
                text = response.read().decode("utf-8", "replace")
            if "Performing security verification" in text:
                raise RuntimeError("HLTV security verification page")
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(text, encoding="utf-8")
            return text
        except (OSError, RuntimeError, HTTPError) as exc:
            last_error = exc
            time.sleep(2 + attempt * 4)
    raise RuntimeError(f"Unable to read {url}: {last_error}")


def fetch_json(url, cache_file, payload=None, attempts=4):
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            pass
    if OFFLINE:
        raise RuntimeError(f"No cached copy for {url}")

    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "X-Service-Name": "portal-frontend-ssr",
        "Origin": "https://blast.tv",
        "Referer": "https://blast.tv/",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    last_error = None
    for attempt in range(attempts):
        try:
            request = Request(url, data=body, headers=headers)
            with urlopen(request, timeout=60) as response:
                result = json.loads(response.read().decode("utf-8", "replace"))
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            return result
        except (OSError, ValueError, TypeError, HTTPError) as exc:
            last_error = exc
            time.sleep(1 + attempt * 2)
    raise RuntimeError(f"Unable to read {url}: {last_error}")


def blast_cache_path(group, name):
    month = date.today().strftime("%Y-%m")
    return CACHE_ROOT / "blast-counterstrikle" / month / group / f"{name}.json"


def load_blast_player_metadata(workers):
    try:
        directory = fetch_json(
            BLAST_PLAYERS_URL,
            blast_cache_path("directory", "players"),
        )
    except Exception as exc:
        print(f"[BLAST directory failed] {exc}")
        return []
    if not isinstance(directory, list):
        return []

    records = []
    worker_count = max(1, min(workers, 4))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        pending = {}
        for player in directory:
            player_id = str(player.get("id") or "").strip()
            if not player_id:
                continue
            future = executor.submit(
                fetch_json,
                BLAST_GUESS_URL,
                blast_cache_path("details", player_id),
                {"playerId": player_id},
            )
            pending[future] = player
        done = 0
        for future in as_completed(pending):
            fallback = pending[future]
            try:
                detail = future.result()
            except Exception as exc:
                print(f"[BLAST player failed] {fallback.get('nickname', '')}: {exc}")
                continue
            if isinstance(detail, dict) and detail.get("nickname"):
                records.append(detail)
            done += 1
            if done % 50 == 0 or done == len(pending):
                print(f"BLAST player metadata: {done}/{len(pending)}")
    return records


def blast_player_record(detail):
    nickname = str(detail.get("nickname") or "").strip()
    full_name = (
        " ".join(
            part.strip()
            for part in (str(detail.get("firstName") or ""), str(detail.get("lastName") or ""))
            if part.strip()
        )
        or nickname
    )
    nationality = detail.get("nationality") or {}
    country_code = str(nationality.get("value") or "").upper()
    team_wrapper = detail.get("team") or {}
    team_data = team_wrapper.get("data") or {}
    team = str(team_data.get("name") or "").strip()
    retired = bool(detail.get("isRetired"))
    role = str(
        (detail.get("role") or {}).get("value")
        if isinstance(detail.get("role"), dict)
        else detail.get("role") or ""
    ).lower()
    if role not in {"rifler", "hybrid", "awper"}:
        role = ""
    age = detail.get("age") or {}
    age_value = age.get("value") if isinstance(age, dict) else age
    majors = detail.get("majorAppearances") or {}
    major_value = majors.get("value") if isinstance(majors, dict) else majors
    return {
        "nickname": nickname,
        "full_name": full_name,
        "team": "" if retired else team,
        "country_code": country_code,
        "country_name": COUNTRY_NAMES.get(country_code, country_code),
        "birth_date": "",
        "profile_age": int(age_value) if age_value is not None else None,
        "role": role,
        "sniping_score": None,
        "player_status": "retired" if retired else ("active" if team else "free_agent"),
        "major_appearances": int(major_value) if major_value is not None else -1,
        "source_url": "https://blast.tv/counter-strikle/daily",
        "source_checked_at": date.today().isoformat(),
        "noob_eligible": False,
        "eligibility": {
            "reasons": ["blast_counterstrikle_current_pool"],
            "best_team_rank": 999,
            "first_seen": date.today().isoformat(),
            "last_seen": date.today().isoformat(),
            "teams": [team] if team else [],
        },
    }


def merge_blast_metadata(players, blast_details):
    # BLAST 会增删 Counter-Strikle 题库。先清除上次同步标记，随后只给
    # 本次公开名单中的选手重新加回，避免退池选手永久残留。
    for player in players:
        eligibility = player.setdefault("eligibility", {})
        reasons = set(eligibility.get("reasons") or [])
        reasons.discard("blast_counterstrikle_current_pool")
        eligibility["reasons"] = sorted(reasons)

    exact = {player["nickname"]: player for player in players}
    folded = {}
    normalized = {}
    full_names = {}
    for player in players:
        folded.setdefault(player["nickname"].casefold(), []).append(player)
        normalized.setdefault(normalize(player["nickname"]), []).append(player)
        full_name_key = normalize(player.get("full_name", ""))
        if full_name_key:
            full_names.setdefault(full_name_key, []).append(player)

    matched = 0
    added = 0
    for detail in blast_details:
        blast = blast_player_record(detail)
        if not blast["nickname"]:
            continue
        target = None
        same_full_name = full_names.get(normalize(blast["full_name"]), [])
        if len(same_full_name) == 1:
            target = same_full_name[0]
        if target is None:
            target = exact.get(blast["nickname"])
        if target is None:
            candidates = folded.get(blast["nickname"].casefold(), [])
            if len(candidates) == 1 and (
                not candidates[0].get("full_name")
                or normalize(candidates[0]["full_name"]) == normalize(blast["full_name"])
            ):
                target = candidates[0]
        if target is None:
            candidates = normalized.get(normalize(blast["nickname"]), [])
            if len(candidates) == 1 and (
                not candidates[0].get("full_name")
                or normalize(candidates[0]["full_name"]) == normalize(blast["full_name"])
            ):
                target = candidates[0]
            elif len(candidates) > 1:
                same_person = [
                    candidate
                    for candidate in candidates
                    if normalize(candidate.get("full_name", "")) == normalize(blast["full_name"])
                ]
                if len(same_person) == 1:
                    target = same_person[0]

        if target is None:
            players.append(blast)
            exact[blast["nickname"]] = blast
            folded.setdefault(blast["nickname"].casefold(), []).append(blast)
            normalized.setdefault(normalize(blast["nickname"]), []).append(blast)
            full_name_key = normalize(blast["full_name"])
            if full_name_key:
                full_names.setdefault(full_name_key, []).append(blast)
            added += 1
            continue

        matched += 1
        unresolved_hltv = not target.get("profile_id")
        if unresolved_hltv and blast["full_name"]:
            target["full_name"] = blast["full_name"]
        if blast["country_code"] and (unresolved_hltv or not target.get("country_code")):
            target["country_code"] = blast["country_code"]
            target["country_name"] = blast["country_name"]
        if blast["profile_age"] is not None and (
            unresolved_hltv or target.get("profile_age") is None
        ):
            target["profile_age"] = blast["profile_age"]
        if blast["major_appearances"] >= 0:
            target["major_appearances"] = blast["major_appearances"]
        if blast["role"] and (unresolved_hltv or not target.get("role")):
            target["role"] = blast["role"]
        target["team"] = blast["team"]
        target["player_status"] = blast["player_status"]
        target["source_checked_at"] = date.today().isoformat()
        eligibility = target.setdefault("eligibility", {})
        reasons = set(eligibility.get("reasons") or [])
        reasons.add("blast_counterstrikle_current_pool")
        eligibility["reasons"] = sorted(reasons)
    print(f"BLAST metadata merged: {matched} matched, {added} Pro-only players added")
    return players


def disambiguate_duplicate_nicknames(players):
    groups = {}
    for player in players:
        base_nickname = re.sub(r"\s+\[[^]]+\]$", "", player["nickname"])
        player["nickname"] = base_nickname
        groups.setdefault(base_nickname.casefold(), []).append(player)
    changed = 0
    for group in groups.values():
        if len(group) < 2:
            continue
        preferred = min(
            group,
            key=lambda player: (
                not bool(player.get("noob_eligible")),
                int(player.get("eligibility", {}).get("best_team_rank", 999)),
                -int(player.get("major_appearances", -1)),
            ),
        )
        used = {preferred["nickname"].casefold()}
        for player in group:
            if player is preferred:
                continue
            suffix = player.get("country_code") or str(player.get("profile_id") or "player")
            nickname = f"{player['nickname']} [{suffix}]"
            counter = 2
            while nickname.casefold() in used:
                nickname = f"{player['nickname']} [{suffix}-{counter}]"
                counter += 1
            player["nickname"] = nickname
            used.add(nickname.casefold())
            changed += 1
    if changed:
        print(f"Disambiguated {changed} players with case-insensitive duplicate nicknames")
    return players


def ranking_dates(last_day=None):
    last_day = last_day or date.today()
    latest_monday = last_day - timedelta(days=last_day.weekday())
    yield date(2015, 10, 1)
    current = date(2015, 10, 5)
    while current <= latest_monday:
        yield current
        current += timedelta(days=7)


def ranking_url(day):
    return f"https://www.hltv.org/ranking/teams/{day.year}/{day.strftime('%B').lower()}/{day.day}"


def top20_url(year):
    return f"https://www.hltv.org/players/top20/{year}"


def unique_profile_urls(text):
    seen = set()
    urls = []
    for match in PROFILE_RE.finditer(text):
        url = f"https://www.hltv.org/player/{match.group(1)}/{match.group(2)}"
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def parse_top20_players(text, year):
    start = text.find("# HLTV TOP 20")
    if start < 0:
        return []
    section = text[start:]
    end = section.find("RECENT ACTIVITY")
    if end >= 0:
        section = section[:end]
    table_players = re.findall(
        r"\[\*\*([^*\n]+)\*\*[^\n]*\]\(https://www\.hltv\.org/news/[^)]+\)[^\n]*\*\*#(?:[1-9]|1\d|20)\*\*",
        section,
    )
    return list(dict.fromkeys(name.strip() for name in table_players if name.strip()))[:20]


def parse_ranking(text, limit):
    start = text.find("Counter-Strike World ranking on")
    if start < 0:
        return []
    text = text[start:]
    matches = list(RANK_RE.finditer(text))
    blocks = []
    for index, match in enumerate(matches):
        rank = int(match.group(1))
        if rank > limit:
            break
        block = text[
            match.start() : matches[index + 1].start() if index + 1 < len(matches) else len(text)
        ]
        points = POINTS_RE.search(block)
        if not points:
            continue
        team = points.group(1).strip()
        profile_urls = unique_profile_urls(block)[:7]
        after_points = block[points.end() :]
        lines = [line.strip() for line in after_points.splitlines()]
        marker = next((i for i, line in enumerate(lines) if MOVE_RE.fullmatch(line)), None)
        roster_text = ""
        repeated_names = []
        if marker is not None:
            roster_text = " ".join(line for line in lines[:marker] if line)
            for line in lines[marker + 1 :]:
                if line == "HLTV Team profile":
                    break
                if line and line != "\t" and not line.startswith("Ranking details"):
                    repeated_names.append(line)
        blocks.append(
            {
                "rank": rank,
                "team": team,
                "profile_urls": profile_urls,
                "roster_text": roster_text,
                "repeated_names": repeated_names,
            }
        )
    return blocks


def archive_section(text, kind):
    headings = (
        ("# Counter-Strike Players",) if kind == "active" else ("# Retired Counter-Strike Players",)
    )
    start = next((text.find(heading) for heading in headings if text.find(heading) >= 0), -1)
    if start < 0:
        return ""
    end = text.find("RECENT ACTIVITY", start)
    return text[start : end if end >= 0 else len(text)]


def parse_archive_cards(text, kind):
    section = archive_section(text, kind)
    records = []
    previous_end = 0
    for match in PROFILE_RE.finditer(section):
        url = f"https://www.hltv.org/player/{match.group(1)}/{match.group(2)}"
        before = section[previous_end : match.start()]
        previous_end = match.end()
        quoted_names = re.findall(r"Image \d+: [^\]\n]*'([^']+)'[^\]\n]*\]", before)
        nickname = quoted_names[-1] if quoted_names else match.group(2)
        records.append((nickname, url))
    return list(dict.fromkeys(records))


def load_player_directory(workers):
    jobs = []
    for kind in ("active", "retired"):
        jobs.append((kind, None))
        jobs.extend((kind, page) for page in range(1, 15))

    directory = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        pending = {}
        for kind, page in jobs:
            suffix = "" if page is None else f"&page={page}"
            url = f"https://www.hltv.org/players/archive/{kind}?filter=all{suffix}"
            name = f"{kind}-first" if page is None else f"{kind}-{page}"
            future = executor.submit(fetch_text, url, cache_path("player-lists", name))
            pending[future] = (kind, page)
        for future in as_completed(pending):
            kind, page = pending[future]
            try:
                cards = parse_archive_cards(future.result(), kind)
            except Exception as exc:
                print(f"[player list failed] {kind} page {page}: {exc}")
                continue
            if cards:
                directory.extend((nickname, url, kind) for nickname, url in cards)

    by_exact = {}
    by_normalized = {}
    retired_urls = set()
    for nickname, url, kind in dict.fromkeys(directory):
        aliases = {nickname, url.rsplit("/", 1)[-1]}
        for alias in aliases:
            by_exact.setdefault(alias, url)
            by_normalized.setdefault(normalize(alias), []).append((alias, url))
        if kind == "retired":
            retired_urls.add(url)
    for nickname, url in MANUAL_PROFILE_URLS.items():
        by_exact[nickname] = url
        by_normalized.setdefault(normalize(nickname), []).append((nickname, url))
    return by_exact, by_normalized, retired_urls


def normalize(value):
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def split_roster(roster_text, known_names):
    text = re.sub(r"\s+", " ", roster_text).strip()
    if not text:
        return []
    # Most nicknames are one word. Add each visible token as a fallback while
    # preferring known multi-word nicknames such as "gob b" and "disco doplan".
    candidates = sorted(set(known_names) | set(text.split()), key=len, reverse=True)
    memo = {}

    def solve(position):
        position = position + len(text[position:]) - len(text[position:].lstrip())
        if position == len(text):
            return []
        if position in memo:
            return memo[position]
        best = None
        for name in candidates:
            end = position + len(name)
            if text.startswith(name, position) and (end == len(text) or text[end] == " "):
                remainder = solve(end)
                if remainder is not None:
                    result = [name, *remainder]
                    if best is None or len(result) < len(best):
                        best = result
        memo[position] = best
        return best

    result = solve(0)
    if result and 2 <= len(result) <= 7:
        return result

    lower_names = {name.casefold(): name for name in candidates}
    lower_result = split_roster_casefold(text, lower_names)
    return lower_result if 2 <= len(lower_result) <= 7 else []


def split_roster_casefold(text, lower_names):
    lowered = text.casefold()
    candidates = sorted(lower_names, key=len, reverse=True)
    memo = {}

    def solve(position):
        position = position + len(lowered[position:]) - len(lowered[position:].lstrip())
        if position == len(lowered):
            return []
        if position in memo:
            return memo[position]
        for name in candidates:
            end = position + len(name)
            if lowered.startswith(name, position) and (end == len(lowered) or lowered[end] == " "):
                remainder = solve(end)
                if remainder is not None:
                    memo[position] = [lower_names[name], *remainder]
                    return memo[position]
        memo[position] = None
        return None

    return solve(0) or []


def resolve_profile_url(nickname, by_exact, by_normalized):
    if nickname in by_exact:
        return by_exact[nickname]
    matches = by_normalized.get(normalize(nickname), [])
    return matches[0][1] if len(matches) == 1 else ""


def clean_markdown(value):
    value = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    return re.sub(r"\s+", " ", value.replace("(?)", "")).strip()


def previous_number(lines, index):
    for line in reversed(lines[max(0, index - 6) : index]):
        value = line.strip()
        if value.isdigit():
            return int(value)
    return -1


def next_score(lines, index):
    for line in lines[index + 1 : index + 7]:
        match = re.search(r"(?:\*\*)?(\d{1,3})(?:\*\*)?/100", line.strip())
        if match:
            return int(match.group(1))
    return None


def role_from_sniping(score, nickname):
    if score is None:
        # Older or inactive profiles may not expose a current Sniping score.
        # Keep the known historical sniper fallback; all other players are
        # treated as riflers rather than presenting invented precision.
        return (
            "awper"
            if normalize(nickname) in {normalize(name) for name in KNOWN_AWPERS}
            else "rifler"
        )
    if score >= 60:
        return "awper"
    if score >= 30:
        return "hybrid"
    return "rifler"


def parse_profile(text, url, fallback_name):
    lines = text.splitlines()
    profile_id = url.split("/")[4]
    title_quote = re.search(r"(?m)^Title: [^\n']*'([^'\n]+)'[^\n]*$", text)
    title_match = re.search(r"(?m)^Title: ([^:\n|]+)(?::| \|)", text)
    nickname = (
        clean_markdown(title_quote.group(1))
        if title_quote
        else clean_markdown(title_match.group(1))
        if title_match
        else fallback_name
    )
    canonical_heading = next(
        (
            line.strip()[2:]
            for line in lines
            if line.strip().startswith("# ")
            and normalize(line.strip()[2:]) == normalize(nickname or fallback_name)
        ),
        "",
    )
    if canonical_heading:
        nickname = canonical_heading
    heading_index = next(
        (
            i
            for i, line in enumerate(lines)
            if line.strip().casefold() == f"# {nickname}".casefold()
        ),
        -1,
    )

    full_name = fallback_name
    country_code = ""
    country_name = ""
    search_area = (
        "\n".join(lines[max(0, heading_index) : heading_index + 12])
        if heading_index >= 0
        else text[:12000]
    )
    country_match = re.search(
        r"!\[Image \d+: ([^\]]+)\]\([^)]*/([A-Z]{2})\.gif[^)]*\)\s*([^\n]+)",
        search_area,
    )
    if country_match:
        country_name, country_code, full_name = country_match.groups()
        full_name = clean_markdown(full_name)

    age = None
    team = ""
    player_status = "unknown"
    sniping_score = None
    # HLTV only renders the Major achievements block after a player has
    # attended one. A fully parsed profile without that block therefore means 0.
    major_appearances = 0
    for index, line in enumerate(lines):
        age_match = re.match(r"Age (\d+) years?", line.strip())
        if age_match:
            age = int(age_match.group(1))
        if line.startswith("Current team Team"):
            if "Retired" in line:
                player_status = "retired"
            elif "No team" in line:
                player_status = "free_agent"
            else:
                player_status = "active"
                team_match = re.search(r"\[([^\]]+)\]\(https://www\.hltv\.org/team/", line)
                team = (
                    clean_markdown(team_match.group(1))
                    if team_match
                    else clean_markdown(line.removeprefix("Current team Team"))
                )
        if line.strip().strip("*") == "Sniping" and sniping_score is None:
            sniping_score = next_score(lines, index)
        if line.strip() in {"Major played", "Majors played"}:
            major_appearances = previous_number(lines, index)

    return {
        "profile_id": int(profile_id),
        "nickname": nickname or fallback_name,
        "full_name": full_name or fallback_name,
        "team": team,
        "country_code": country_code,
        "country_name": country_name,
        "birth_date": "",
        "profile_age": age,
        "role": role_from_sniping(sniping_score, nickname),
        "sniping_score": sniping_score,
        "player_status": player_status,
        "major_appearances": major_appearances,
        "source_url": url,
        "source_checked_at": date.today().isoformat(),
    }


def add_eligibility(eligible, identity, nickname, profile_url, team, rank, ranking_day, reason):
    record = eligible.setdefault(
        identity,
        {
            "nickname": nickname,
            "profile_url": profile_url,
            "current_team": "",
            "reasons": set(),
            "teams": set(),
            "best_rank": rank,
            "first_seen": ranking_day,
            "last_seen": ranking_day,
            "ranking_days": {ranking_day},
        },
    )
    record["reasons"].add(reason)
    record["teams"].add(team)
    record["best_rank"] = min(record["best_rank"], rank)
    record["first_seen"] = min(record["first_seen"], ranking_day)
    record["last_seen"] = max(record["last_seen"], ranking_day)
    record["ranking_days"].add(ranking_day)
    if reason == "current_top50":
        record["current_team"] = team


def ranking_player_links(day, context):
    cache_file = cache_path("ranking-links", day)
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))
    if OFFLINE:
        return []

    ranking_day = date.fromisoformat(day)
    last_error = None
    for _ in range(1):
        page = context.new_page()
        try:
            page.goto(ranking_url(ranking_day), wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector('a[href*="/player/"]', timeout=15000)
            links = page.locator('a[href*="/player/"]').evaluate_all(
                """elements => elements.map(element => ({
                    nickname: (element.innerText || '').trim(),
                    url: element.href
                })).filter(item => item.nickname && item.url)"""
            )
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(links, ensure_ascii=False), encoding="utf-8")
            return links
        except Exception as exc:
            last_error = exc
        finally:
            page.close()
    print(f"[browser ranking failed] {day}: {last_error}")
    return []


def resolve_missing_profile_urls(eligible):
    missing = {key for key, item in eligible.items() if not item["profile_url"]}
    if not missing:
        return
    day_coverage = {}
    for key in missing:
        for day in eligible[key]["ranking_days"]:
            day_coverage.setdefault(day, set()).add(key)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[browser resolver unavailable] install playwright to resolve old profile URLs")
        return

    attempted = set()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/140.0.0.0 Safari/537.36"
            )
        )
        while missing and len(attempted) < 4:
            choices = [
                (len(keys & missing), day)
                for day, keys in day_coverage.items()
                if day not in attempted and keys & missing
            ]
            if not choices:
                break
            _, day = max(choices)
            attempted.add(day)
            links = ranking_player_links(day, context)
            exact = {item["nickname"]: item["url"] for item in links}
            folded = {}
            for item in links:
                folded.setdefault(item["nickname"].casefold(), []).append(item["url"])
            for key in list(missing):
                nickname = eligible[key]["nickname"]
                url = exact.get(nickname, "")
                if not url:
                    candidates = set(folded.get(nickname.casefold(), []))
                    if len(candidates) == 1:
                        url = candidates.pop()
                if url:
                    eligible[key]["profile_url"] = url
                    missing.remove(key)
            print(f"Browser profile links: {len(eligible) - len(missing)}/{len(eligible)}")
        context.close()
        browser.close()


def merge_eligible_players(eligible):
    merged = {}
    for original_key, item in eligible.items():
        url = item["profile_url"]
        key = f"profile:{url.split('/')[4]}" if url else original_key
        if key not in merged:
            merged[key] = item
            continue
        target = merged[key]
        target["reasons"].update(item["reasons"])
        target["teams"].update(item["teams"])
        target["ranking_days"].update(item["ranking_days"])
        target["best_rank"] = min(target["best_rank"], item["best_rank"])
        target["first_seen"] = min(target["first_seen"], item["first_seen"])
        target["last_seen"] = max(target["last_seen"], item["last_seen"])
        target["current_team"] = target["current_team"] or item["current_team"]
    return merged


def main():
    global OFFLINE
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    OFFLINE = args.offline
    workers = max(1, min(args.workers, 12))

    print("Reading HLTV player directory...")
    by_exact, by_normalized, retired_urls = load_player_directory(workers)
    known_names = set(by_exact)
    print(f"Player directory: {len(by_exact)} names")

    dates = list(ranking_dates())
    ranking_pages = {}
    print(f"Reading {len(dates)} weekly team rankings...")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        pending = {
            executor.submit(
                fetch_text,
                ranking_url(day),
                cache_path("rankings", day.isoformat()),
            ): day
            for day in dates
        }
        done = 0
        for future in as_completed(pending):
            day = pending[future]
            try:
                text = future.result()
                blocks = parse_ranking(text, 50)
                if blocks:
                    ranking_pages[day] = blocks
            except Exception as exc:
                print(f"[ranking skipped] {day}: {exc}")
            done += 1
            if done % 50 == 0 or done == len(dates):
                print(f"Rankings: {done}/{len(dates)}")

    if not ranking_pages:
        raise RuntimeError("No HLTV team rankings could be parsed")
    latest_day = max(ranking_pages)
    eligible = {}
    unresolved_rosters = []

    for day, blocks in sorted(ranking_pages.items()):
        limit = 50 if day == latest_day else 20
        for block in blocks:
            if block["rank"] > limit:
                continue
            reason = "current_top50" if day == latest_day else "historical_top20"
            if block["profile_urls"]:
                for url in block["profile_urls"][:7]:
                    slug = url.rsplit("/", 1)[-1]
                    profile_id = url.split("/")[4]
                    add_eligibility(
                        eligible,
                        f"profile:{profile_id}",
                        slug,
                        url,
                        block["team"],
                        block["rank"],
                        day.isoformat(),
                        reason,
                    )
                    if day >= date(2018, 1, 1) and block["rank"] <= 5:
                        add_eligibility(
                            eligible,
                            f"profile:{profile_id}",
                            slug,
                            url,
                            block["team"],
                            block["rank"],
                            day.isoformat(),
                            "top5_team_since_2018",
                        )
                continue

            names = block["repeated_names"] or split_roster(block["roster_text"], known_names)
            if not names:
                unresolved_rosters.append(
                    (day.isoformat(), block["rank"], block["team"], block["roster_text"])
                )
                continue
            for nickname in names:
                url = resolve_profile_url(nickname, by_exact, by_normalized)
                identity = f"profile:{url.split('/')[4]}" if url else f"name:{nickname.casefold()}"
                add_eligibility(
                    eligible,
                    identity,
                    nickname,
                    url,
                    block["team"],
                    block["rank"],
                    day.isoformat(),
                    reason,
                )
                if day >= date(2018, 1, 1) and block["rank"] <= 5:
                    add_eligibility(
                        eligible,
                        identity,
                        nickname,
                        url,
                        block["team"],
                        block["rank"],
                        day.isoformat(),
                        "top5_team_since_2018",
                    )

    print(f"Eligible players: {len(eligible)}")

    top20_profiles = set()
    completed_year = date.today().year - 1
    print(f"Reading annual HLTV Top 20 lists from 2015 to {completed_year}...")
    for year in range(2015, completed_year + 1):
        try:
            text = fetch_text(top20_url(year), cache_path("top20", str(year)))
            names = parse_top20_players(text, year)
        except Exception as exc:
            print(f"[top20 skipped] {year}: {exc}")
            continue
        for nickname in names:
            url = resolve_profile_url(nickname, by_exact, by_normalized)
            identity = f"profile:{url.split('/')[4]}" if url else f"name:{nickname.casefold()}"
            top20_profiles.add(identity)
            if identity not in eligible:
                add_eligibility(
                    eligible,
                    identity,
                    nickname,
                    url,
                    "",
                    999,
                    f"{year}-12-31",
                    "annual_top20_since_2015",
                )
            else:
                eligible[identity]["reasons"].add("annual_top20_since_2015")
    print(f"Annual Top 20 profiles: {len(top20_profiles)}")

    resolve_missing_profile_urls(eligible)
    eligible = merge_eligible_players(eligible)
    print(f"Eligible player profiles after merging: {len(eligible)}")
    profile_records = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        pending = {}
        for identity, item in eligible.items():
            if not item["profile_url"]:
                continue
            profile_id = item["profile_url"].split("/")[4]
            future = executor.submit(
                fetch_text,
                item["profile_url"],
                cache_path("profiles", profile_id),
            )
            pending[future] = (identity, item)
        done = 0
        for future in as_completed(pending):
            identity, item = pending[future]
            try:
                profile_records[identity] = parse_profile(
                    future.result(), item["profile_url"], item["nickname"]
                )
            except Exception as exc:
                print(f"[profile failed] {item['nickname']}: {exc}")
            done += 1
            if done % 50 == 0 or done == len(pending):
                print(f"Profiles: {done}/{len(pending)}")

    players = []
    unresolved_profiles = []
    for identity, item in eligible.items():
        record = profile_records.get(identity)
        if not record:
            unresolved_profiles.append(item["nickname"])
            record = {
                "nickname": item["nickname"],
                "full_name": item["nickname"],
                "team": item["current_team"],
                "country_code": "",
                "country_name": "",
                "birth_date": "",
                "profile_age": None,
                "role": role_from_sniping(None, item["nickname"]),
                "sniping_score": None,
                "player_status": (
                    "retired"
                    if item["profile_url"] in retired_urls
                    else "active"
                    if item["current_team"]
                    else "free_agent"
                ),
                "major_appearances": -1,
                "source_url": item["profile_url"] or ranking_url(latest_day),
                "source_checked_at": date.today().isoformat(),
            }
        elif not record["team"] and item["current_team"]:
            record["team"] = item["current_team"]
        if record.get("player_status") == "unknown":
            if record.get("team"):
                record["player_status"] = "active"
            elif item["profile_url"] in retired_urls:
                record["player_status"] = "retired"
            else:
                record["player_status"] = "free_agent"
        record["eligibility"] = {
            "reasons": sorted(item["reasons"]),
            "best_team_rank": item["best_rank"],
            "first_seen": item["first_seen"],
            "last_seen": item["last_seen"],
            "teams": sorted(item["teams"]),
        }
        record["noob_eligible"] = bool(
            {"annual_top20_since_2015", "top5_team_since_2018"} & item["reasons"]
        )
        players.append(record)

    print("Reading BLAST Counter-Strikle metadata as a fallback...")
    blast_details = load_blast_player_metadata(workers)
    players = merge_blast_metadata(players, blast_details)
    players = disambiguate_duplicate_nicknames(players)
    incomplete_profiles = sorted(
        {
            player["nickname"]
            for player in players
            if not player.get("country_code")
            or player.get("profile_age") is None
            or not player.get("role")
            or int(player.get("major_appearances", -1)) < 0
        },
        key=str.casefold,
    )

    payload = {
        "generated_at": date.today().isoformat(),
        "latest_ranking_date": latest_day.isoformat(),
        "rules": [
            "pro_current_top50_teams",
            "pro_historical_top20_team_rosters_since_2015-10-01",
            "pro_blast_counterstrikle_current_pool",
            "noob_annual_top20_players_since_2015",
            "noob_top5_team_rosters_since_2018-01-01",
        ],
        "players": sorted(players, key=lambda player: player["nickname"].casefold()),
        "unresolved_profiles": incomplete_profiles,
        "unresolved_hltv_profiles": sorted(set(unresolved_profiles), key=str.casefold),
        "unresolved_rosters": unresolved_rosters,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(players)} eligible players to {OUTPUT}")
    print(f"Incomplete game profiles: {len(payload['unresolved_profiles'])}")
    print(f"Unresolved HLTV profiles: {len(payload['unresolved_hltv_profiles'])}")
    print(f"Unresolved roster rows: {len(unresolved_rosters)}")


if __name__ == "__main__":
    main()
