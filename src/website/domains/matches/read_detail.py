"""Read-only match detail and historical statistics views."""

import json

from src.website.domains.community.interactions import build_comment_tree, list_comments
from src.website.domains.demos.demo_storage import available_download_slots
from src.website.domains.events.arg_event_service import ordinary_event_condition
from src.website.domains.events.status import add_effective_event_status
from src.website.domains.matches.bp_log import parse_bp_log
from src.website.domains.matches.map_names import normalize_map_key
from src.website.domains.matches.match_roster_service import resolve_match_roster
from src.website.domains.matches.match_utils import (
    get_map_half_scores,
    get_sql_effective_status,
    get_sql_match_completed,
    parse_map_halves,
)
from src.website.domains.matches.opponents import supplement_temp_teams
from src.website.domains.operations.broadcast_rosters import display_rosters, event_substitutes
from src.website.domains.predictions.votes import managed_vote_open, vote_summary
from src.website.domains.statistics.perf_overview_service import (
    build_perf_overview,
    load_metric_averages,
)
from src.website.domains.statistics.stats_storage import (
    match_stat_belongs_to_side,
    stats_for_slot,
    stats_relation,
)
from src.website.runtime.database import row_get
from src.website.runtime.host import is_managed_match
from src.website.runtime.urls import normalize_http_url

from ..statistics.match_duels import (
    _build_kill_matrix,
    _build_player_alias_map,
    _load_persisted_kill_events,
)
from ..statistics.match_view import (
    _aggregate_match_rows,
    _apply_rating_scale,
    _avg_values,
    _display_rows_from_raw,
    _highlight_rows,
    _match_rating_sort_key,
    _safe_int,
    _sum_known,
    _team_summary,
)

_SQL_MATCH_COMPLETED = get_sql_match_completed()
_SQL_EFFECTIVE_STATUS = get_sql_effective_status()


def build_match_detail_context(
    conn, match_id, *, user_id, show_stats, instance_path, static_folder, demo_root
):
    """读取比赛概况与模板所需的赛前、赛后资料。"""
    match = conn.execute(
        f"""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s,
               t1.logo AS t1_logo, t2.logo AS t2_logo,
               e.name AS event_name, e.id AS event_id, e.slug AS event_slug,
               e.stream_url AS event_stream_url,
               {_SQL_EFFECTIVE_STATUS}
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id
        WHERE m.id=?
    """,
        (match_id,),
    ).fetchone()

    if not match:
        return None

    # 补充临时队伍名称
    match = supplement_temp_teams(match, conn)

    # 获取比赛数据
    stats = conn.execute(
        f"""
        SELECT ms.*, p.nickname, p.id AS player_id, t.short_name AS team_short
        FROM {stats_relation(conn)} ms
        JOIN players p ON ms.player_id=p.id
        LEFT JOIN teams t ON ms.team_id=t.id
        WHERE ms.match_id=?
          AND COALESCE(ms.data_status, 'final') <> 'superseded'
        ORDER BY ms.map_name, ms.team_id DESC, ms.rating DESC
    """,
        (match_id,),
    ).fetchall()

    # 双方历史交锋记录
    h2h_matches = []
    t1_id = match["team1_id"]
    t2_id = match["team2_id"]
    if t1_id and t2_id:
        h2h_matches = conn.execute(
            """
            SELECT m.id, m.slug, m.match_time, m.team1_score, m.team2_score,
                   m.bo_format, e.name AS event_name,
                   t1.short_name AS t1s, t2.short_name AS t2s
            FROM matches m
            LEFT JOIN events e ON m.event_id = e.id
            LEFT JOIN teams t1 ON m.team1_id = t1.id
            LEFT JOIN teams t2 ON m.team2_id = t2.id
            WHERE m.id != ?
              AND COALESCE(m.status, '') = 'completed'
              AND m.team1_score IS NOT NULL
              AND m.team2_score IS NOT NULL
              AND (COALESCE(m.team1_score, 0) > 0 OR COALESCE(m.team2_score, 0) > 0)
              AND ((m.team1_id = ? AND m.team2_id = ?)
                OR (m.team1_id = ? AND m.team2_id = ?))
            ORDER BY m.match_time DESC LIMIT 10
        """,
            (match_id, t1_id, t2_id, t2_id, t1_id),
        ).fetchall()

    # 队伍名单（队标悬停浮窗用；只展示已生效的五人名单，替补用角色标记）
    rosters = display_rosters(
        resolve_match_roster(conn, match)["players"], event_substitutes(conn, match["event_id"])
    )
    team1_roster, team2_roster = rosters[1], rosters[2]
    managed_match = is_managed_match(conn, match_id)
    prediction_disabled = bool(managed_match and not managed_vote_open(conn, match_id))
    if managed_match:
        # The old template needs slot booleans, not names or storage keys.
        available = available_download_slots(
            conn,
            match_id,
            instance_path=instance_path,
            static_folder=static_folder,
            configured=demo_root,
        )
        match["demo_file"] = (
            json.dumps([slot in available for slot in range(5)]) if available else None
        )

    # 每图比分 + 分图 stats（按队伍分好）
    t1_key = match["team1_id"] if match["team1_id"] else -1
    t2_key = match["team2_id"] if match["team2_id"] else -2

    raw_maps = [
        (
            match["map1"],
            match["map1_t1"],
            match["map1_t2"],
            True,
            row_get(match, "map1_picked_by", ""),
        ),
        (
            match["map2"],
            match["map2_t1"],
            match["map2_t2"],
            True,
            row_get(match, "map2_picked_by", ""),
        ),
        (
            match["map3"],
            match["map3_t1"],
            match["map3_t2"],
            bool(match["has_map3"]),
            row_get(match, "map3_picked_by", ""),
        ),
        (
            match["map4"],
            match["map4_t1"],
            match["map4_t2"],
            bool(row_get(match, "has_map4", 1)),
            row_get(match, "map4_picked_by", ""),
        ),
        (
            match["map5"],
            match["map5_t1"],
            match["map5_t2"],
            bool(row_get(match, "has_map5", 1)),
            row_get(match, "map5_picked_by", ""),
        ),
    ]
    # 解析半场比分
    map_halves = parse_map_halves(match)

    bo = (match["bo_format"] or "BO3").upper()
    if bo == "BO5":
        max_maps = 5
    elif bo == "BO3":
        max_maps = 3
    else:
        max_maps = 1

    map_scores = []
    for idx, (mn, t1, t2, active, picked_by) in enumerate(raw_maps):
        if idx >= max_maps:
            break
        # 未开始的系列赛也要按 BO 数量完整显示地图槽位。
        all_for_map = stats_for_slot(stats, idx + 1, mn)
        t1s = _display_rows_from_raw(
            [s for s in all_for_map if match_stat_belongs_to_side(s, "t1", t1_key)],
            "t1",
            match["t1s"],
            match["team1_name"],
        )
        t2s = _display_rows_from_raw(
            [s for s in all_for_map if match_stat_belongs_to_side(s, "t2", t2_key)],
            "t2",
            match["t2s"],
            match["team2_name"],
        )
        halves = get_map_half_scores(match, idx, map_halves) if mn else None
        played = bool(mn and (t1 or t2))
        has_stats = bool(all_for_map)
        map_scores.append(
            {
                "name": mn or "TBA",
                "index": idx + 1,
                "t1": t1 or 0,
                "t2": t2 or 0,
                "picked_by": picked_by or "",
                "team1_stats": t1s,
                "team2_stats": t2s,
                "halves": halves,
                "played": played,
                "has_stats": has_stats,
                "display": bool(mn and (played or has_stats)),
            }
        )

    # Match and detailed views must use the same missing-value and side rules.
    overall_t1 = _aggregate_match_rows(
        [row for row in stats if match_stat_belongs_to_side(row, "t1", t1_key)],
        "t1",
        match["t1s"],
        match["team1_name"],
    )
    overall_t2 = _aggregate_match_rows(
        [row for row in stats if match_stat_belongs_to_side(row, "t2", t2_key)],
        "t2",
        match["t2s"],
        match["team2_name"],
    )

    all_overall = []
    for item in overall_t1:
        row = dict(item)
        row["team_side"] = "t1"
        row["team_short"] = match["t1s"]
        row["team_name"] = match["team1_name"]
        all_overall.append(row)
    for item in overall_t2:
        row = dict(item)
        row["team_side"] = "t2"
        row["team_short"] = match["t2s"]
        row["team_name"] = match["team2_name"]
        all_overall.append(row)

    def _avg(rows, key):
        return _avg_values([row.get(key) for row in rows])

    def _sum(rows, key):
        return _sum_known([row.get(key) for row in rows])

    def _top(rows, key):
        return max(
            (row for row in rows if row.get(key) is not None),
            key=lambda row: row[key],
            default=None,
        )

    match_breakdown = {
        "t1_rating": _avg(overall_t1, "rating"),
        "t2_rating": _avg(overall_t2, "rating"),
        "t1_first_kills": _sum(overall_t1, "first_kills"),
        "t2_first_kills": _sum(overall_t2, "first_kills"),
        "t1_clutches": _sum(overall_t1, "clutches_won"),
        "t2_clutches": _sum(overall_t2, "clutches_won"),
    }
    match_highlights = [
        {
            "label": "最高 RATING",
            "player": _top(all_overall, "rating"),
            "key": "rating",
            "unit": "",
        },
        {"label": "最高 ADR", "player": _top(all_overall, "adr"), "key": "adr", "unit": ""},
        {"label": "最多击杀", "player": _top(all_overall, "kills"), "key": "kills", "unit": ""},
        {"label": "最多助攻", "player": _top(all_overall, "assists"), "key": "assists", "unit": ""},
        {
            "label": "最多闪白",
            "player": _top(all_overall, "enemies_flashed"),
            "key": "enemies_flashed",
            "unit": "",
        },
    ]
    match_performance_rows = sorted(
        all_overall, key=lambda row: float(row.get("rating") or 0), reverse=True
    )
    match_rating_scale = _apply_rating_scale(match_performance_rows, minimum=1.8)

    # 胜者排前面：按地图胜场数判定（BO1/BO3/BO5 通用）
    t1_map_wins = 0
    t2_map_wins = 0
    for mn, t1s, t2s, active, _pb in raw_maps:
        if mn and active:
            s1 = int(t1s or 0)
            s2 = int(t2s or 0)
            if s1 > s2:
                t1_map_wins += 1
            elif s2 > s1:
                t2_map_wins += 1
    t1_win = t1_map_wins > t2_map_wins
    # 平局时用总比分判定
    if t1_map_wins == t2_map_wins:
        t1_win = int(match["team1_score"] or 0) > int(match["team2_score"] or 0)

    raw_comments = list_comments(conn, "match", match_id, user_id)

    comments = build_comment_tree(raw_comments)

    # 侧边栏：赛事 / 比赛 / 新闻
    sidebar_events = conn.execute(
        f"SELECT * FROM events WHERE {ordinary_event_condition()} ORDER BY start_date DESC LIMIT 9"
    ).fetchall()
    sidebar_events = [add_effective_event_status(e) for e in sidebar_events]
    sidebar_events.sort(
        key=lambda e: {"ongoing": 0, "upcoming": 1, "completed": 2}.get(
            e.get("effective_event_status", ""), 3
        )
    )
    sidebar_matches = conn.execute(f"""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s,
               {_SQL_EFFECTIVE_STATUS}
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        ORDER BY
        CASE WHEN {_SQL_MATCH_COMPLETED} THEN 3 ELSE 1 END,
        m.match_time DESC LIMIT 9
    """).fetchall()
    sidebar_matches = [supplement_temp_teams(row, conn) for row in sidebar_matches]
    sidebar_news = conn.execute(
        "SELECT id, title, created_at FROM news ORDER BY created_at DESC LIMIT 3"
    ).fetchall()
    vote_data = vote_summary(conn, match_id, user_id)

    # 观赛平台链接
    watch_urls = []
    if row_get(match, "watch_urls"):
        try:
            watch_urls = json.loads(match["watch_urls"])
        except (json.JSONDecodeError, TypeError):
            pass
    watch_urls = [
        {"name": str(item.get("name", "")), "url": safe_url}
        for item in watch_urls
        if isinstance(item, dict)
        if (safe_url := normalize_http_url(item.get("url")))
    ]

    # BP 记录拆成步骤（“T1 / T2”就是本场的队伍 1 / 队伍 2）
    bp_view = parse_bp_log(
        match["bp_process"],
        ["T1", match["team1_name"], match["t1s"]],
        ["T2", match["team2_name"], match["t2s"]],
    )

    return dict(
        match=match,
        bp_view=bp_view,
        map_scores=map_scores,
        overall_t1=overall_t1,
        overall_t2=overall_t2,
        t1_win=t1_win,
        match_breakdown=match_breakdown,
        match_highlights=match_highlights,
        match_performance_rows=match_performance_rows,
        match_rating_scale=match_rating_scale,
        show_match_stats=show_stats,
        comments=comments,
        sidebar_events=sidebar_events,
        sidebar_matches=sidebar_matches,
        sidebar_news=sidebar_news,
        watch_urls=watch_urls,
        vote_data=vote_data,
        h2h_matches=h2h_matches,
        team1_roster=team1_roster,
        team2_roster=team2_roster,
        is_managed_match=managed_match,
        prediction_disabled=prediction_disabled,
    )


def build_match_detailed_context(conn, match_id, *, requested_map, selected_tab):
    match = conn.execute(
        f"""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s,
               t1.logo AS t1_logo, t2.logo AS t2_logo,
               e.name AS event_name, e.id AS event_id, e.slug AS event_slug,
               {_SQL_EFFECTIVE_STATUS}
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id
        WHERE m.id=?
    """,
        (match_id,),
    ).fetchone()
    if not match:
        return None
    match = supplement_temp_teams(match, conn)

    stats = conn.execute(
        f"""
        SELECT ms.*, p.nickname, p.avatar, p.steam_id, p.id AS player_id
        FROM {stats_relation(conn)} ms
        JOIN players p ON ms.player_id=p.id
        WHERE ms.match_id=?
          AND COALESCE(ms.data_status, 'final') <> 'superseded'
        ORDER BY ms.map_name, ms.team_id, ms.rating DESC
    """,
        (match_id,),
    ).fetchall()
    player_ids = sorted({row["player_id"] for row in stats})
    player_aliases = _build_player_alias_map(conn, player_ids)
    persisted_kill_events = (
        [] if is_managed_match(conn, match_id) else _load_persisted_kill_events(conn, match_id)
    )
    metric_averages = load_metric_averages(conn)

    t1_key = match["team1_id"] if match["team1_id"] else -1
    t2_key = match["team2_id"] if match["team2_id"] else -2
    raw_maps = [
        (
            match["map1"],
            match["map1_t1"],
            match["map1_t2"],
            True,
            row_get(match, "map1_picked_by", ""),
        ),
        (
            match["map2"],
            match["map2_t1"],
            match["map2_t2"],
            True,
            row_get(match, "map2_picked_by", ""),
        ),
        (
            match["map3"],
            match["map3_t1"],
            match["map3_t2"],
            bool(match["has_map3"]),
            row_get(match, "map3_picked_by", ""),
        ),
        (
            match["map4"],
            match["map4_t1"],
            match["map4_t2"],
            bool(row_get(match, "has_map4", 1)),
            row_get(match, "map4_picked_by", ""),
        ),
        (
            match["map5"],
            match["map5_t1"],
            match["map5_t2"],
            bool(row_get(match, "has_map5", 1)),
            row_get(match, "map5_picked_by", ""),
        ),
    ]
    bo = (match["bo_format"] or "BO3").upper()
    max_maps = 5 if bo == "BO5" else 3 if bo == "BO3" else 1
    map_halves = parse_map_halves(match)

    map_scores = []
    for idx, (map_name, t1_score, t2_score, active, picked_by) in enumerate(raw_maps):
        if idx >= max_maps:
            break
        map_rows = stats_for_slot(stats, idx + 1, map_name)
        team1_raw = [row for row in map_rows if match_stat_belongs_to_side(row, "t1", t1_key)]
        team2_raw = [row for row in map_rows if match_stat_belongs_to_side(row, "t2", t2_key)]
        team1_rows = _display_rows_from_raw(team1_raw, "t1", match["t1s"], match["team1_name"])
        team2_rows = _display_rows_from_raw(team2_raw, "t2", match["t2s"], match["team2_name"])
        played = bool(map_name and (t1_score or t2_score))
        has_stats = bool(map_rows)
        map_scores.append(
            {
                "index": idx + 1,
                "name": map_name or "TBA",
                "t1": _safe_int(t1_score),
                "t2": _safe_int(t2_score),
                "active": active,
                "picked_by": picked_by or "",
                "halves": get_map_half_scores(match, idx, map_halves) if map_name else None,
                "played": played,
                "has_stats": has_stats,
                "team1_stats": team1_rows,
                "team2_stats": team2_rows,
                "performance_rows": sorted(
                    team1_rows + team2_rows, key=_match_rating_sort_key, reverse=True
                ),
                "summary": {"t1": _team_summary(team1_rows), "t2": _team_summary(team2_rows)},
            }
        )

    team1_all_raw = [row for row in stats if match_stat_belongs_to_side(row, "t1", t1_key)]
    team2_all_raw = [row for row in stats if match_stat_belongs_to_side(row, "t2", t2_key)]
    overall_t1 = _aggregate_match_rows(team1_all_raw, "t1", match["t1s"], match["team1_name"])
    overall_t2 = _aggregate_match_rows(team2_all_raw, "t2", match["t2s"], match["team2_name"])
    all_players = sorted(overall_t1 + overall_t2, key=_match_rating_sort_key, reverse=True)

    map_cards = [item for item in map_scores if item["name"] != "TBA"]
    selected_map = None
    if requested_map not in ("", "all"):
        try:
            requested_index = int(requested_map)
        except ValueError:
            requested_index = 0
        selected_map = next((item for item in map_cards if item["index"] == requested_index), None)
        if selected_map is None and requested_index == 0:
            selected_map = next(
                (
                    item
                    for item in map_cards
                    if normalize_map_key(item["name"]) == normalize_map_key(requested_map)
                ),
                None,
            )

    if selected_map:
        team1_rows = selected_map["team1_stats"]
        team2_rows = selected_map["team2_stats"]
        performance_rows = selected_map["performance_rows"]
        selected_map_index = selected_map["index"]
        selected_label = selected_map["name"]
        score_t1 = selected_map["t1"]
        score_t2 = selected_map["t2"]
    else:
        team1_rows = overall_t1
        team2_rows = overall_t2
        performance_rows = all_players
        selected_map_index = 0
        selected_label = "All"
        score_t1 = match["team1_score"] if match["team1_score"] is not None else "-"
        score_t2 = match["team2_score"] if match["team2_score"] is not None else "-"

    rating_scale = _apply_rating_scale(performance_rows)
    map_slots = {
        normalize_map_key(card["name"]): card["index"] - 1 for card in map_cards if card.get("name")
    }
    kill_events = []
    for event in persisted_kill_events:
        event_map_key = normalize_map_key(event.get("map_name") or "")
        if selected_map and event_map_key != normalize_map_key(selected_map["name"]):
            continue
        event["map_slot"] = map_slots.get(event_map_key, 0)
        kill_events.append(event)
    summary = {"t1": _team_summary(team1_rows), "t2": _team_summary(team2_rows)}
    perf_avg = build_perf_overview(team1_rows + team2_rows, metric_averages)
    kill_matrix = _build_kill_matrix(team1_rows, team2_rows, player_aliases, kill_events)

    return {
        "match": match,
        "map_cards": map_cards,
        "selected_map_index": selected_map_index,
        "selected_label": selected_label,
        "score_t1": score_t1,
        "score_t2": score_t2,
        "summary": summary,
        "team1_rows": team1_rows,
        "team2_rows": team2_rows,
        "performance_rows": performance_rows,
        "perf_avg": perf_avg,
        "rating_scale": rating_scale,
        "highlights": _highlight_rows(performance_rows),
        "kill_matrix": kill_matrix,
        "selected_tab": selected_tab,
        "has_any_stats": bool(stats),
    }
