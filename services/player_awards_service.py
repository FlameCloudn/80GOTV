"""Build the public MVP, EVP and yearly Top 10 tables from saved site data."""

import re
from collections import defaultdict
from datetime import date

FIRST_AWARD_YEAR = 2026


def _row_dict(row):
    return dict(row)


def _event_year(value):
    match = re.match(r"\s*(\d{4})", str(value or ""))
    return int(match.group(1)) if match else None


def is_80_major_event(name="", short_name="", slug=""):
    """Only events explicitly named 80 Major count as the site's Major."""
    combined = " ".join(str(value or "") for value in (name, short_name, slug))
    normalized = re.sub(r"[^a-z0-9]+", "", combined.casefold())
    return "80major" in normalized


def _player_bucket(row):
    return {
        "id": row["player_id"],
        "nickname": row["nickname"],
        "avatar": row["avatar"],
        "total": 0,
        "major": 0,
        "years": defaultdict(int),
    }


def build_award_page(conn, award_type, start_year=FIRST_AWARD_YEAR, today=None):
    award_type = str(award_type or "").upper()
    if award_type not in {"MVP", "EVP"}:
        raise ValueError("award_type must be MVP or EVP")

    rows = [
        _row_dict(row)
        for row in conn.execute(
            """
            SELECT pm.id, pm.player_id, pm.type, pm.created_at,
                   p.nickname, p.avatar,
                   e.id AS event_id, e.name AS event_name,
                   e.short_name AS event_short_name,
                   e.slug AS event_slug, e.start_date AS event_date
            FROM player_medals pm
            JOIN players p ON p.id=pm.player_id
            LEFT JOIN events e ON e.id=pm.event_id
            WHERE UPPER(pm.type)=?
            ORDER BY COALESCE(e.start_date, pm.created_at) DESC, pm.id DESC
            """,
            (award_type,),
        ).fetchall()
    ]

    players = {}
    latest = []
    max_data_year = start_year
    for row in rows:
        player = players.setdefault(row["player_id"], _player_bucket(row))
        player["total"] += 1
        year = _event_year(row["event_date"])
        if year is not None and year >= start_year:
            player["years"][year] += 1
            max_data_year = max(max_data_year, year)
        if is_80_major_event(row["event_name"], row["event_short_name"], row["event_slug"]):
            player["major"] += 1
        if row["event_name"] and len(latest) < 5:
            latest.append(row)

    current_year = (today or date.today()).year
    years = list(range(start_year, max(start_year, current_year, max_data_year) + 1))
    ranking = sorted(
        players.values(),
        key=lambda item: (-item["total"], item["nickname"].casefold(), item["id"]),
    )
    for player in ranking:
        player["year_counts"] = [player["years"].get(year, 0) for year in years]
        del player["years"]

    major_leaders = sorted(
        (player for player in ranking if player["major"] > 0),
        key=lambda item: (-item["major"], -item["total"], item["nickname"].casefold()),
    )[:5]
    total_leaders = ranking[:5]
    return {
        "kind": award_type,
        "years": years,
        "ranking": ranking,
        "major_leaders": major_leaders,
        "total_leaders": total_leaders,
        "latest": latest,
    }


def build_top10_page(conn, start_year=FIRST_AWARD_YEAR):
    """Build the public TOP 10 history from rankings published by an admin."""
    rows = [
        _row_dict(row)
        for row in conn.execute(
            """
            SELECT y.year AS stat_year, y.rank,
                   p.id AS player_id, p.nickname, p.avatar
            FROM yearly_top_players y
            JOIN players p ON p.id=y.player_id
            WHERE y.year >= ?
            ORDER BY y.year ASC, y.rank ASC
            """,
            (start_year,),
        ).fetchall()
    ]

    players = {}
    years = sorted({row["stat_year"] for row in rows})
    for row in rows:
        rank = row["rank"]
        player = players.setdefault(
            row["player_id"],
            {
                "id": row["player_id"],
                "nickname": row["nickname"],
                "avatar": row["avatar"],
                "first": 0,
                "second": 0,
                "third": 0,
                "fourth_fifth": 0,
                "sixth_tenth": 0,
                "total": 0,
            },
        )
        player["total"] += 1
        if rank == 1:
            player["first"] += 1
        elif rank == 2:
            player["second"] += 1
        elif rank == 3:
            player["third"] += 1
        elif rank <= 5:
            player["fourth_fifth"] += 1
        else:
            player["sixth_tenth"] += 1

    ranking = sorted(
        players.values(),
        key=lambda item: (
            -item["total"],
            -item["first"],
            -item["second"],
            -item["third"],
            item["nickname"].casefold(),
        ),
    )
    for player in ranking:
        player["top5"] = (
            player["first"] + player["second"] + player["third"] + player["fourth_fifth"]
        )

    most_top1 = sorted(
        (player for player in ranking if player["first"] > 0),
        key=lambda item: (-item["first"], -item["top5"], item["nickname"].casefold()),
    )[:5]
    most_top5 = sorted(
        (player for player in ranking if player["top5"] > 0),
        key=lambda item: (-item["top5"], -item["first"], item["nickname"].casefold()),
    )[:5]
    return {
        "start_year": start_year,
        "years": years,
        "ranking": ranking,
        "most_top1": most_top1,
        "most_top5": most_top5,
    }
