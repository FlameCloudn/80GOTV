"""Manage explicitly awarded event medals and published yearly Top 10 lists."""

import re
from collections import defaultdict
from datetime import date

from src.website.domains.awards.champion_service import save_champion
from src.website.domains.awards.championship import championship_final_match_id
from src.website.domains.events.registration import require_admin
from src.website.runtime.host import HostError, has_event_schema, is_managed_event

FIRST_AWARD_YEAR = 2026


def _editable_event_medals(conn, event_id: int):
    return conn.execute(
        """SELECT pm.id, pm.player_id, UPPER(type) AS type, evp_rank, pm.created_at, p.nickname
           FROM player_medals pm LEFT JOIN players p ON p.id=pm.player_id
           WHERE pm.event_id=? AND pm.match_id IS NULL AND UPPER(type) IN ('MVP', 'EVP')
           ORDER BY CASE WHEN UPPER(type)='EVP' THEN COALESCE(NULLIF(evp_rank, 0), 999) END,
                    pm.id""",
        (event_id,),
    ).fetchall()


def event_medal_selections(conn, event_id: int):
    """The legacy event form edits event medals, not individual match medals."""
    rows = _editable_event_medals(conn, event_id)
    mvp = next(({"id": row["player_id"]} for row in rows if row["type"] == "MVP"), None)
    evps = [
        {"id": row["player_id"], "evp_rank": row["evp_rank"]}
        for row in rows
        if row["type"] == "EVP"
    ]
    return mvp, evps


def save_legacy_event_awards(
    conn,
    event_id: int,
    *,
    champion_team_id: int | None,
    mvp_player_id: int | None,
    evp_player_ids: tuple[int, ...],
):
    """Save selections within the event edit transaction, without committing it."""
    if is_managed_event(conn, event_id):
        raise HostError("本届尚未接管赛后授奖")
    if (
        champion_team_id is not None
        and not conn.execute("SELECT 1 FROM teams WHERE id=?", (champion_team_id,)).fetchone()
    ):
        raise HostError("所选冠军队伍不存在", 400)

    recipients = set(evp_player_ids)
    if mvp_player_id is not None:
        recipients.add(mvp_player_id)
    if recipients:
        placeholders = ",".join("?" for _ in recipients)
        if conn.execute(
            f"SELECT COUNT(*) FROM players WHERE id IN ({placeholders})",
            tuple(recipients),
        ).fetchone()[0] != len(recipients):
            raise HostError("所选获奖选手中存在无效档案", 400)

    save_champion(conn, event_id, champion_team_id)
    _save_event_medals(conn, event_id, mvp_player_id, evp_player_ids, explicit_order=False)


def _save_event_medals(
    conn,
    event_id: int,
    mvp_player_id: int | None,
    evp_player_ids: tuple[int, ...],
    *,
    explicit_order: bool,
):
    rows = _editable_event_medals(conn, event_id)
    current_mvp = next((row["player_id"] for row in rows if row["type"] == "MVP"), None)
    if current_mvp != mvp_player_id:
        conn.execute(
            "DELETE FROM player_medals WHERE event_id=? AND match_id IS NULL AND UPPER(type)='MVP'",
            (event_id,),
        )
        if mvp_player_id is not None:
            conn.execute(
                "INSERT INTO player_medals(player_id, type, event_id) VALUES(?,'MVP',?)",
                (mvp_player_id, event_id),
            )

    current_evps = [row for row in rows if row["type"] == "EVP"]
    ordered = dict.fromkeys(evp_player_ids)
    if not explicit_order:
        retained = dict.fromkeys(row["player_id"] for row in current_evps)
        if retained.keys() == ordered.keys():
            return
        # The legacy checkbox form sends display order, not a new published order.
        ordered = {player_id: None for player_id in retained if player_id in ordered} | ordered
    ranks = {player_id: rank for rank, player_id in enumerate(ordered, start=1)}
    for row in current_evps:
        rank = ranks.pop(row["player_id"], None)
        if rank is None:
            conn.execute("DELETE FROM player_medals WHERE id=?", (row["id"],))
        elif row["evp_rank"] != rank:
            conn.execute("UPDATE player_medals SET evp_rank=? WHERE id=?", (rank, row["id"]))
    conn.executemany(
        "INSERT INTO player_medals(player_id, type, event_id, evp_rank) VALUES(?,'EVP',?,?)",
        ((player_id, event_id, rank) for player_id, rank in ranks.items()),
    )


def _managed_medal_candidates(conn, event_id: int):
    event = (
        conn.execute(
            """SELECT e.status, c.archived_at FROM events e
               JOIN event_registration_control c ON c.event_id=e.id WHERE e.id=?""",
            (event_id,),
        ).fetchone()
        if has_event_schema(conn)
        else None
    )
    if not event:
        raise HostError("本届不是托管赛事，请使用原授奖入口", 404)
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='view' AND name='official_stat_participants'"
    ).fetchone():
        raise HostError("数据库尚未安装正式出场记录结构", 503)

    matches = conn.execute(
        """SELECT m.status, s.settlement_id, s.state
           FROM matches m LEFT JOIN series_settlements s ON s.settlement_id=(
               SELECT settlement_id FROM series_settlements WHERE match_id=m.id ORDER BY revision DESC LIMIT 1
           )
           WHERE m.event_id=? AND m.status IS NOT 'cancelled'""",
        (event_id,),
    ).fetchall()
    if not matches or any(r["status"] != "completed" or r["state"] != "settled" for r in matches):
        raise HostError("本届仍有未正式完赛的比赛，或没有正式赛果")
    if event["archived_at"] is None and event["status"] != "completed":
        championship_final_match_id(conn, event_id)

    settlements = tuple(row["settlement_id"] for row in matches)
    placeholders = ",".join("?" for _ in settlements)
    candidates = [
        dict(row)
        for row in conn.execute(
            f"""SELECT p.player_id, pl.nickname, mp.event_entrant_id, r.team_name,
                       COUNT(DISTINCT p.scheduled_map_id) AS maps
                FROM official_stat_participants p
                JOIN series_settlements s ON s.match_id=p.match_id
                JOIN match_participants mp ON mp.match_participant_id=p.match_participant_id
                JOIN event_entrants ee ON ee.event_entrant_id=mp.event_entrant_id
                JOIN event_registrations r ON r.id=ee.registration_id
                JOIN players pl ON pl.id=p.player_id
                WHERE s.settlement_id IN ({placeholders})
                  AND p.official_map_result_id IN (SELECT value FROM json_each(s.map_result_ids))
                GROUP BY p.player_id HAVING COUNT(DISTINCT mp.event_entrant_id)=1
                ORDER BY pl.nickname COLLATE NOCASE, p.player_id""",
            settlements,
        )
    ]
    if not candidates:
        raise HostError("本届没有能确认参赛方和正式有效出场的候选选手")
    return candidates


def managed_event_medals(conn, event_id: int):
    blocked_reason = None
    try:
        candidates = _managed_medal_candidates(conn, event_id)
    except HostError as exc:
        if exc.status != 409:
            raise
        candidates, blocked_reason = [], exc.message
    awards = [dict(row) for row in _editable_event_medals(conn, event_id)]
    eligible = {row["player_id"] for row in candidates}
    return {
        "awards": awards,
        "candidates": candidates,
        "blocked_reason": blocked_reason,
        "needs_review": any(row["player_id"] not in eligible for row in awards),
    }


def save_managed_event_medals(
    conn,
    event_id: int,
    *,
    mvp_player_id: int | None,
    evp_player_ids: tuple[int, ...],
    admin_id: int,
):
    """Explicitly publish the reviewed order without writing results or team awards."""
    if not conn.in_transaction:
        raise HostError("请在写事务中办理个人奖")
    require_admin(conn, admin_id)
    candidates = _managed_medal_candidates(conn, event_id)
    requested = set(evp_player_ids)
    if mvp_player_id is not None:
        requested.add(mvp_player_id)
    if not requested <= {row["player_id"] for row in candidates}:
        raise HostError("所选获奖人缺少可核对的本届正式出场或参赛方，请先核实")
    _save_event_medals(conn, event_id, mvp_player_id, evp_player_ids, explicit_order=True)
    return {
        "awards": [dict(row) for row in _editable_event_medals(conn, event_id)],
        "candidates": candidates,
        "blocked_reason": None,
        "needs_review": False,
    }


def delete_event_awards(conn, event_id: int):
    """Remove related awards only when the administrator deletes the legacy event."""
    save_champion(conn, event_id, None)
    conn.execute("DELETE FROM player_medals WHERE event_id=?", (event_id,))


def find_event_award_player(conn, event_id: int, award_type="MVP", *, player_id: int | None = None):
    """Find an awarded player eligible for a public poster."""
    return conn.execute(
        """SELECT p.id, p.nickname FROM player_medals pm
           JOIN players p ON p.id=pm.player_id
           WHERE pm.event_id=? AND UPPER(pm.type)=? AND (? IS NULL OR pm.player_id=?)
           ORDER BY pm.match_id IS NOT NULL, pm.id LIMIT 1""",
        (event_id, award_type, player_id, player_id),
    ).fetchone()


def list_event_award_players(conn, event_id: int):
    return conn.execute(
        """SELECT p.id, p.nickname, UPPER(pm.type) AS type, pm.evp_rank
           FROM player_medals pm JOIN players p ON p.id=pm.player_id
           WHERE pm.event_id=? AND UPPER(pm.type) IN ('MVP', 'EVP')
           ORDER BY CASE UPPER(pm.type) WHEN 'MVP' THEN 0 ELSE 1 END,
                    COALESCE(NULLIF(pm.evp_rank, 0), 999), pm.id""",
        (event_id,),
    ).fetchall()


def list_event_medals(conn, event_id: int):
    """Keep the public event API's broader legacy medal list and ordering."""
    return conn.execute(
        """SELECT pm.type, pm.player_id, p.nickname, p.avatar, pm.evp_rank, pm.reason
           FROM player_medals pm JOIN players p ON pm.player_id=p.id
           WHERE pm.event_id=?
           ORDER BY CASE pm.type WHEN 'MVP' THEN 0 ELSE 1 END, pm.evp_rank, p.nickname""",
        (event_id,),
    ).fetchall()


def yearly_top10_editor(conn, year: int):
    players = conn.execute(
        "SELECT id, nickname FROM players ORDER BY nickname COLLATE NOCASE, id"
    ).fetchall()
    return players, yearly_top10_selections(conn, year), published_top10_years(conn)


def yearly_top10_selections(conn, year: int):
    return {
        row["rank"]: row["player_id"]
        for row in conn.execute(
            "SELECT rank, player_id FROM yearly_top_players WHERE year=? ORDER BY rank",
            (year,),
        )
    }


def published_top10_years(conn):
    return [
        row["year"]
        for row in conn.execute("SELECT DISTINCT year FROM yearly_top_players ORDER BY year DESC")
    ]


def save_yearly_top10(conn, year: int, player_ids: tuple[int, ...] | None, *, admin_id: int):
    """Publish ten ordered players, or explicitly clear with None; caller commits."""
    if player_ids is not None:
        if len(player_ids) != 10:
            raise ValueError("必须完整选择第 1 至第 10 名")
        if len(set(player_ids)) != 10:
            raise ValueError("同一名选手不能重复出现")
        placeholders = ",".join("?" for _ in player_ids)
        if (
            conn.execute(
                f"SELECT COUNT(*) FROM players WHERE id IN ({placeholders})",
                player_ids,
            ).fetchone()[0]
            != 10
        ):
            raise ValueError("所选选手中存在无效档案")
        selections = dict(enumerate(player_ids, start=1))
        if selections == yearly_top10_selections(conn, year):
            return

    conn.execute("DELETE FROM yearly_top_players WHERE year=?", (year,))
    if player_ids is not None:
        conn.executemany(
            """INSERT INTO yearly_top_players(year, rank, player_id, decided_by)
               VALUES(?,?,?,?)""",
            ((year, rank, player_id, admin_id) for rank, player_id in selections.items()),
        )


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
