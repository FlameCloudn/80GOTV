"""Public player list, comparison and detail pages."""

import json

from flask import redirect, render_template, request, url_for

from models import get_db
from services.match_service import supplement_temp_teams
from services.steam_profile_service import enrich_player_from_steam
from utils.demo_parser import normalize_map_name
from utils.filters import date_display_filter
from web_app import app

PLAYER_TIME_FILTERS = [
    {"value": "all", "label": "全部", "months": None},
    {"value": "3m", "label": "最近 3 个月", "months": 3},
    {"value": "6m", "label": "最近 6 个月", "months": 6},
    {"value": "12m", "label": "最近 12 个月", "months": 12},
]
PLAYER_TIME_MAP = {item["value"]: item for item in PLAYER_TIME_FILTERS}
PLAYER_SIDE_OPTIONS = [
    {"value": "both", "label": "双方"},
    {"value": "ct", "label": "CT 方"},
    {"value": "t", "label": "T 方"},
]
PLAYER_SIDE_VALUES = {item["value"] for item in PLAYER_SIDE_OPTIONS}


def _num(value):
    return float(value or 0)


def _pct(value, target):
    if target <= 0:
        return 0
    return max(0, min(100, round(_num(value) / target * 100)))


def _fmt(value, digits=2, suffix=""):
    if value is None:
        return "-"
    return f"{float(value):.{digits}f}{suffix}"


def _player_current_filters():
    time_key = request.args.get("time") or request.args.get("period") or "all"
    if time_key not in PLAYER_TIME_MAP:
        time_key = "all"
    map_key = (request.args.get("map") or "all").strip() or "all"
    side_key = (request.args.get("side") or "both").strip().lower()
    if side_key not in PLAYER_SIDE_VALUES:
        side_key = "both"
    return {"time": time_key, "map": map_key, "side": side_key}


def _player_available_maps(conn):
    rows = conn.execute("""
        SELECT DISTINCT map_name
        FROM match_stats
        WHERE map_name IS NOT NULL AND map_name != ''
        ORDER BY map_name
    """).fetchall()
    seen = set()
    maps = []
    for row in rows:
        key = normalize_map_name(row["map_name"])
        if not key or key in seen:
            continue
        seen.add(key)
        maps.append({"value": row["map_name"], "label": row["map_name"]})
    return maps


def _player_stat_where(player_id, filters):
    clauses = ["ms.player_id=?"]
    params = [player_id]
    months = PLAYER_TIME_MAP[filters["time"]]["months"]
    if months:
        clauses.append("m.match_time >= datetime('now', ?)")
        params.append(f"-{months} months")
    if filters["map"] != "all":
        clauses.append("ms.map_name=?")
        params.append(filters["map"])
    return " WHERE " + " AND ".join(clauses), params


def _player_side_expr(side):
    if side == "t":
        return {
            "kills": "SUM(COALESCE(ms.t_kills, 0))",
            "deaths": "SUM(COALESCE(ms.t_deaths, 0))",
            "rating": "AVG(NULLIF(ms.t_rating, 0))",
            "adr": "AVG(NULLIF(ms.t_adr, 0))",
            "row_rating": "NULLIF(ms.t_rating, 0)",
            "row_adr": "NULLIF(ms.t_adr, 0)",
        }
    if side == "ct":
        return {
            "kills": "SUM(COALESCE(ms.ct_kills, 0))",
            "deaths": "SUM(COALESCE(ms.ct_deaths, 0))",
            "rating": "AVG(NULLIF(ms.ct_rating, 0))",
            "adr": "AVG(NULLIF(ms.ct_adr, 0))",
            "row_rating": "NULLIF(ms.ct_rating, 0)",
            "row_adr": "NULLIF(ms.ct_adr, 0)",
        }
    return {
        "kills": "SUM(COALESCE(ms.kills, 0))",
        "deaths": "SUM(COALESCE(ms.deaths, 0))",
        "rating": "AVG(ms.rating)",
        "adr": "AVG(ms.adr)",
        "row_rating": "ms.rating",
        "row_adr": "ms.adr",
    }


def _build_player_blocks(overall):
    rounds = _num(overall["rounds_played"])
    maps = int(overall["matches"] or 0)
    kills = _num(overall["total_kills"])
    deaths = _num(overall["total_deaths"])
    assists = _num(overall["total_assists"])
    first_kills = _num(overall["first_kills"])
    first_deaths = _num(overall["first_deaths"])
    trade_kills = _num(overall["trade_kills"])
    trade_deaths = _num(overall["trade_deaths"])
    utility_damage = _num(overall["utility_damage"])
    kd_ratio = kills / deaths if deaths else None
    assists_per_round = assists / rounds if rounds else 0
    multi_total = (
        _num(overall["multi2k"])
        + _num(overall["multi3k"])
        + _num(overall["multi4k"])
        + _num(overall["multi5k"])
    )
    rating_val = _num(overall["avg_rating"])
    if rating_val >= 1.15:
        rating_label = "Good"
        rating_label_cn = "优秀"
    elif rating_val >= 0.95:
        rating_label = "Average"
        rating_label_cn = "一般"
    else:
        rating_label = "Bad"
        rating_label_cn = "较差"
    player_summary = {
        "maps": maps,
        "rounds": int(rounds),
        "rating": rating_val,
        "rating_pct": min(100, max(0, (rating_val - 0.5) / 1.5 * 100)),
        "rating_label": rating_label,
        "rating_label_cn": rating_label_cn,
        "t_rating": overall["avg_t_rating"],
        "ct_rating": overall["avg_ct_rating"],
        "round_swing": overall["damage_delta_per_round"],
        "dpr": overall["avg_dpr"],
        "kast": overall["avg_kast"],
        "multi_kill": (multi_total / rounds * 100) if rounds else 0,
        "adr": overall["avg_adr"],
        "kpr": overall["avg_kpr"],
    }
    # HLTV 风格 7 分类
    trade_pct = trade_kills / kills * 100 if kills else 0
    trade_death_pct = trade_deaths / deaths * 100 if deaths else 0
    opening_attempts = first_kills + first_deaths
    opening_success_rate = first_kills / opening_attempts * 100 if opening_attempts else 0
    multi_round_pct = multi_total / rounds * 100 if rounds else 0
    clutch_per_round = _num(overall["clutches_won"]) / rounds if rounds else 0

    player_category_cards = [
        {
            "title": "火力",
            "desc": "综合击杀、伤害、多杀的火力输出",
            "score": _pct(
                rating_val * 0.4
                + (overall["avg_kpr"] or 0) * 0.3
                + (overall["avg_adr"] or 0) / 120 * 0.3,
                1.5,
            ),
            "items": [
                {
                    "label": "每回合击杀",
                    "value": _fmt(overall["avg_kpr"]),
                    "pct": _pct(overall["avg_kpr"], 1.0),
                },
                {
                    "label": "每回合伤害",
                    "value": _fmt(overall["avg_adr"], 1),
                    "pct": _pct(overall["avg_adr"], 120),
                },
                {
                    "label": "多杀回合占比",
                    "value": _fmt(multi_round_pct, 1, "%"),
                    "pct": _pct(multi_round_pct, 30),
                },
                {
                    "label": "影响力",
                    "value": _fmt(overall["avg_impact"]),
                    "pct": _pct(overall["avg_impact"], 1.5),
                },
                {"label": "RATING 2.0", "value": _fmt(rating_val), "pct": _pct(rating_val, 1.5)},
            ],
        },
        {
            "title": "协作",
            "desc": "补枪、救援队友的团队协作能力",
            "score": _pct(trade_kills / max(trade_kills + trade_deaths, 1) * 100, 60),
            "items": [
                {
                    "label": "补枪击杀/回合",
                    "value": _fmt(trade_kills / rounds if rounds else 0),
                    "pct": _pct(trade_kills / rounds if rounds else 0, 0.25),
                },
                {
                    "label": "补枪击杀占比",
                    "value": _fmt(trade_pct, 1, "%"),
                    "pct": _pct(trade_pct, 35),
                },
                {
                    "label": "被补枪死亡/回合",
                    "value": _fmt(trade_deaths / rounds if rounds else 0),
                    "pct": _pct(trade_deaths / rounds if rounds else 0, 0.25),
                },
                {
                    "label": "被补枪占比",
                    "value": _fmt(trade_death_pct, 1, "%"),
                    "pct": _pct(trade_death_pct, 35),
                },
                {
                    "label": "每回合助攻",
                    "value": _fmt(assists / rounds if rounds else 0),
                    "pct": _pct(assists / rounds if rounds else 0, 0.35),
                },
            ],
        },
        {
            "title": "突破",
            "desc": "率先对枪、为队伍打开局面的能力",
            "score": _pct(
                opening_success_rate * 0.5 + first_kills / rounds * 100 if rounds else 0, 60
            ),
            "items": [
                {
                    "label": "开局对枪参与率",
                    "value": _fmt(opening_attempts / rounds * 100 if rounds else 0, 1, "%"),
                    "pct": _pct(opening_attempts / rounds * 100 if rounds else 0, 35),
                },
                {
                    "label": "被补率",
                    "value": _fmt(trade_death_pct, 1, "%"),
                    "pct": _pct(trade_death_pct, 35),
                },
                {
                    "label": "每回合补枪",
                    "value": _fmt(trade_kills / rounds if rounds else 0),
                    "pct": _pct(trade_kills / rounds if rounds else 0, 0.25),
                },
                {
                    "label": "每回合被补",
                    "value": _fmt(trade_deaths / rounds if rounds else 0),
                    "pct": _pct(trade_deaths / rounds if rounds else 0, 0.25),
                },
            ],
        },
        {
            "title": "开局",
            "desc": "首杀能力与开局对枪成功率",
            "score": _pct(opening_success_rate, 75),
            "items": [
                {
                    "label": "开局成功率",
                    "value": _fmt(opening_success_rate, 1, "%"),
                    "pct": _pct(opening_success_rate, 75),
                },
                {
                    "label": "每回合首杀",
                    "value": _fmt(first_kills / rounds if rounds else 0),
                    "pct": _pct(first_kills / rounds if rounds else 0, 0.25),
                },
                {
                    "label": "每回合首死",
                    "value": _fmt(first_deaths / rounds if rounds else 0),
                    "pct": _pct(first_deaths / rounds if rounds else 0, 0.25),
                },
                {
                    "label": "首杀/首死比",
                    "value": _fmt(first_kills / first_deaths if first_deaths else 0),
                    "pct": _pct(first_kills / first_deaths if first_deaths else 0, 2),
                },
            ],
        },
        {
            "title": "残局",
            "desc": "1vn 残局处理能力",
            "score": _pct(clutch_per_round * 100, 8),
            "items": [
                {
                    "label": "残局获胜",
                    "value": str(int(_num(overall["clutches_won"]))),
                    "pct": _pct(overall["clutches_won"], max(maps, 1)),
                },
                {
                    "label": "残局得分/回合",
                    "value": _fmt(clutch_per_round),
                    "pct": _pct(clutch_per_round * 100, 6),
                },
                {
                    "label": "下包数",
                    "value": str(int(_num(overall["bomb_plants"]))),
                    "pct": _pct(overall["bomb_plants"], max(maps * 2, 1)),
                },
                {
                    "label": "拆包数",
                    "value": str(int(_num(overall["bomb_defuses"]))),
                    "pct": _pct(overall["bomb_defuses"], max(maps, 1)),
                },
            ],
        },
        {
            "title": "狙击",
            "desc": "AWP 使用数据（需 demo 武器数据支持）",
            "score": 0,
            "items": [
                {"label": "每回合狙击击杀", "value": "-", "pct": 0},
                {"label": "狙击击杀占比", "value": "-", "pct": 0},
                {"label": "有狙击击杀回合", "value": "-", "pct": 0},
                {"label": "狙击首杀", "value": "-", "pct": 0},
            ],
        },
        {
            "title": "道具",
            "desc": "投掷物伤害与闪光辅助",
            "score": _pct(
                (overall["utility_damage_per_round"] or 0) * 8
                + (_num(overall["enemies_flashed"]) / max(_num(overall["flash_count"]), 1)) * 20,
                12,
            ),
            "items": [
                {
                    "label": "每回合道具伤害",
                    "value": _fmt(overall["utility_damage_per_round"]),
                    "pct": _pct(overall["utility_damage_per_round"], 10),
                },
                {
                    "label": "总道具伤害",
                    "value": str(int(utility_damage)),
                    "pct": _pct(utility_damage, max(rounds * 8, 1)),
                },
                {
                    "label": "每回合致盲敌人",
                    "value": _fmt(_num(overall["enemies_flashed"]) / rounds if rounds else 0),
                    "pct": _pct(_num(overall["enemies_flashed"]) / rounds if rounds else 0, 0.9),
                },
                {
                    "label": "闪光成功率",
                    "value": _fmt(
                        _num(overall["enemies_flashed"])
                        / max(_num(overall["flash_count"]), 1)
                        * 100,
                        1,
                        "%",
                    ),
                    "pct": _pct(
                        _num(overall["enemies_flashed"])
                        / max(_num(overall["flash_count"]), 1)
                        * 100,
                        100,
                    ),
                },
            ],
        },
    ]
    player_statistics = [
        {"label": "总击杀", "value": str(int(kills))},
        {"label": "总回合", "value": str(int(rounds))},
        {"label": "HS%", "value": _fmt(overall["avg_hs"], 1, "%")},
        {"label": "每回合击杀", "value": _fmt(overall["avg_kpr"])},
        {"label": "总死亡", "value": str(int(deaths))},
        {"label": "每回合助攻", "value": _fmt(assists_per_round)},
        {"label": "K/D", "value": _fmt(kd_ratio)},
        {"label": "每回合死亡", "value": _fmt(overall["avg_dpr"])},
        {"label": "每回合伤害", "value": _fmt(overall["avg_adr"], 1)},
        {"label": "每回合被队友补枪", "value": _fmt(trade_deaths / rounds if rounds else 0)},
        {"label": "每回合道具伤害", "value": _fmt(overall["utility_damage_per_round"])},
        {"label": "每回合补枪队友", "value": _fmt(trade_kills / rounds if rounds else 0)},
        {"label": "地图数", "value": str(maps)},
        {"label": "影响力 RATING", "value": _fmt(overall["avg_impact"])},
    ]
    return player_summary, player_category_cards, player_statistics


@app.route("/players")
def players_list():
    """选手列表"""
    team_filter = request.args.get("team", "")
    filter_type = request.args.get("filter", "")  # mvps, evps, top10
    if filter_type == "top20":
        return redirect(url_for("players_list", filter="top10"))

    conn = get_db()

    if filter_type == "mvps":
        query = """
            SELECT p.*, t.name AS team_name, t.short_name AS team_short,
                   AVG(ms.rating) AS avg_rating, AVG(ms.kills) AS avg_kills,
                   AVG(ms.deaths) AS avg_deaths, COUNT(ms.id) AS match_count
            FROM players p
            JOIN player_medals pm ON p.id = pm.player_id AND pm.type = 'MVP'
            LEFT JOIN teams t ON p.team_id=t.id
            LEFT JOIN match_stats ms ON p.id=ms.player_id
            GROUP BY p.id ORDER BY avg_rating DESC
        """
        players = conn.execute(query).fetchall()
    elif filter_type == "evps":
        query = """
            SELECT p.*, t.name AS team_name, t.short_name AS team_short,
                   AVG(ms.rating) AS avg_rating, AVG(ms.kills) AS avg_kills,
                   AVG(ms.deaths) AS avg_deaths, COUNT(ms.id) AS match_count
            FROM players p
            JOIN player_medals pm ON p.id = pm.player_id AND pm.type = 'EVP'
            LEFT JOIN teams t ON p.team_id=t.id
            LEFT JOIN match_stats ms ON p.id=ms.player_id
            GROUP BY p.id ORDER BY avg_rating DESC
        """
        players = conn.execute(query).fetchall()
    elif filter_type == "top10":
        query = """
            SELECT p.*, t.name AS team_name, t.short_name AS team_short,
                   AVG(ms.rating) AS avg_rating, AVG(ms.kills) AS avg_kills,
                   AVG(ms.deaths) AS avg_deaths, COUNT(ms.id) AS match_count
            FROM players p
            LEFT JOIN teams t ON p.team_id=t.id
            JOIN match_stats ms ON p.id=ms.player_id
            GROUP BY p.id ORDER BY avg_rating DESC LIMIT 10
        """
        players = conn.execute(query).fetchall()
    else:
        query = """
            SELECT p.*, t.name AS team_name, t.short_name AS team_short,
                   AVG(ms.rating) AS avg_rating, AVG(ms.kills) AS avg_kills,
                   AVG(ms.deaths) AS avg_deaths, COUNT(ms.id) AS match_count
            FROM players p
            LEFT JOIN teams t ON p.team_id=t.id
            LEFT JOIN match_stats ms ON p.id=ms.player_id
        """
        params = []
        if team_filter:
            query += " WHERE p.team_id=?"
            params.append(team_filter)
        query += " GROUP BY p.id ORDER BY avg_rating DESC"
        players = conn.execute(query, params).fetchall()

    teams = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
    conn.close()

    return render_template(
        "players.html",
        players=players,
        teams=teams,
        team_filter=team_filter,
        filter_type=filter_type,
    )


@app.route("/players/compare")
def player_compare():
    """选手对比工具"""
    id1 = request.args.get("id1", type=int)
    id2 = request.args.get("id2", type=int)
    conn = get_db()
    all_players = conn.execute(
        "SELECT p.*, t.name AS team_name FROM players p LEFT JOIN teams t ON p.team_id=t.id ORDER BY p.nickname"
    ).fetchall()
    p1 = p2 = stats1 = stats2 = compare_bars = None

    if id1 and id2:
        p1 = conn.execute(
            "SELECT p.*, t.name AS team_name FROM players p LEFT JOIN teams t ON p.team_id=t.id WHERE p.id=?",
            (id1,),
        ).fetchone()
        p2 = conn.execute(
            "SELECT p.*, t.name AS team_name FROM players p LEFT JOIN teams t ON p.team_id=t.id WHERE p.id=?",
            (id2,),
        ).fetchone()
        if p1 and p2:

            def _get_stats(pid):
                r = conn.execute(
                    """SELECT COUNT(*) as m, AVG(rating) as r, AVG(adr) as a, AVG(kast) as k,
                    AVG(impact) as i, AVG(headshot_percentage) as h,
                    SUM(kills)*1.0/NULLIF(SUM(deaths),0) as kd, AVG(kpr) as kpr
                    FROM match_stats WHERE player_id=?""",
                    (pid,),
                ).fetchone()
                return r

            r1, r2 = _get_stats(id1), _get_stats(id2)
            stats1 = [
                {"label": "RATING", "value": round(r1["r"] or 0, 2)},
                {"label": "K/D", "value": round(r1["kd"] or 0, 2)},
                {"label": "ADR", "value": round(r1["a"] or 0, 1)},
                {"label": "KAST%", "value": str(round(r1["k"] or 0, 1)) + "%"},
                {"label": "影响力", "value": round(r1["i"] or 0, 2)},
                {"label": "HS%", "value": str(round(r1["h"] or 0, 1)) + "%"},
                {"label": "KPR", "value": round(r1["kpr"] or 0, 2)},
                {"label": "场次", "value": r1["m"] or 0},
            ]
            stats2 = [
                {"label": "RATING", "value": round(r2["r"] or 0, 2)},
                {"label": "K/D", "value": round(r2["kd"] or 0, 2)},
                {"label": "ADR", "value": round(r2["a"] or 0, 1)},
                {"label": "KAST%", "value": str(round(r2["k"] or 0, 1)) + "%"},
                {"label": "影响力", "value": round(r2["i"] or 0, 2)},
                {"label": "HS%", "value": str(round(r2["h"] or 0, 1)) + "%"},
                {"label": "KPR", "value": round(r2["kpr"] or 0, 2)},
                {"label": "场次", "value": r2["m"] or 0},
            ]

            # 水平对比条（百分比相对）
            def _pct(v1, v2):
                t = v1 + v2
                if t == 0:
                    return 50, 50
                return round(v1 / t * 100), round(v2 / t * 100)

            def _nv(d, k, default=0):
                return (d[k] or default) if d else default

            compare_bars = []
            for key, label, v1, v2 in [
                ("r", "RATING", _nv(r1, "r"), _nv(r2, "r")),
                ("kd", "K/D", _nv(r1, "kd"), _nv(r2, "kd")),
                ("a", "ADR", _nv(r1, "a"), _nv(r2, "a")),
                ("k", "KAST", _nv(r1, "k"), _nv(r2, "k")),
                ("i", "Impact", _nv(r1, "i"), _nv(r2, "i")),
                ("h", "HS%", _nv(r1, "h"), _nv(r2, "h")),
            ]:
                pa, pb = _pct(v1, v2)
                compare_bars.append(
                    {
                        "label": label,
                        "s1": {"val": str(round(v1, 2) if v1 else "-"), "pct": pa},
                        "s2": {"val": str(round(v2, 2) if v2 else "-"), "pct": pb},
                    }
                )
    conn.close()
    return render_template(
        "player_compare.html",
        all_players=all_players,
        p1=p1,
        p2=p2,
        stats1=stats1,
        stats2=stats2,
        compare_bars=compare_bars,
    )


@app.route("/players/<int:player_id>")
def player_detail(player_id):
    """选手详情"""
    period = request.args.get("period", "all")  # all, 3m, 6m
    event_filter = request.args.get("event", "")
    time_filter = ""
    if period == "3m":
        time_filter = " AND m.match_time >= datetime('now', '-3 months')"
    elif period == "6m":
        time_filter = " AND m.match_time >= datetime('now', '-6 months')"
    stat_filter = time_filter
    stat_params = []
    if event_filter:
        stat_filter += " AND m.event_id=?"
        stat_params.append(event_filter)

    conn = get_db()
    player = conn.execute(
        """
        SELECT p.*, t.name AS team_name, t.short_name AS team_short
        FROM players p
        LEFT JOIN teams t ON p.team_id=t.id
        WHERE p.id=?
    """,
        (player_id,),
    ).fetchone()

    if not player:
        conn.close()
        return "选手不存在", 404
    if enrich_player_from_steam(conn, player, app.root_path):
        conn.commit()
        player = conn.execute(
            """
            SELECT p.*, t.name AS team_name, t.short_name AS team_short
            FROM players p
            LEFT JOIN teams t ON p.team_id=t.id
            WHERE p.id=?
        """,
            (player_id,),
        ).fetchone()

    # 总体统计（含 KPR, DPR, Impact, T/CT Rating）
    overall = conn.execute(
        f"""
        SELECT COUNT(DISTINCT ms.match_id) AS matches, SUM(ms.kills) AS total_kills,
               SUM(ms.deaths) AS total_deaths, SUM(ms.assists) AS total_assists,
               AVG(ms.rating) AS avg_rating, AVG(ms.adr) AS avg_adr,
               AVG(ms.kast) AS avg_kast, AVG(ms.headshot_percentage) AS avg_hs,
               AVG(ms.kpr) AS avg_kpr, AVG(ms.dpr) AS avg_dpr,
               AVG(ms.impact) AS avg_impact,
               AVG(CASE WHEN ms.t_rating > 0 THEN ms.t_rating END) AS avg_t_rating,
               AVG(CASE WHEN ms.ct_rating > 0 THEN ms.ct_rating END) AS avg_ct_rating,
               SUM(ms.rounds_played) AS rounds_played,
               SUM(ms.multi1k) AS multi1k, SUM(ms.multi2k) AS multi2k,
               SUM(ms.multi3k) AS multi3k, SUM(ms.multi4k) AS multi4k,
               SUM(ms.multi5k) AS multi5k,
               SUM(ms.first_kills) AS first_kills,
               SUM(ms.first_deaths) AS first_deaths,
               SUM(ms.trade_kills) AS trade_kills,
               SUM(ms.trade_deaths) AS trade_deaths,
               SUM(ms.clutches_won) AS clutches_won,
               SUM(ms.utility_damage) AS utility_damage,
               AVG(ms.utility_damage_per_round) AS utility_damage_per_round,
               SUM(ms.enemies_flashed) AS enemies_flashed,
               SUM(ms.flash_count) AS flash_count,
               SUM(ms.bomb_plants) AS bomb_plants,
               SUM(ms.bomb_defuses) AS bomb_defuses,
               AVG(ms.damage_delta_per_round) AS damage_delta_per_round,
               AVG(ms.rws_basic) AS rws_basic
        FROM match_stats ms
        JOIN matches m ON ms.match_id=m.id
        WHERE ms.player_id=? {stat_filter}
    """,
        (player_id, *stat_params),
    ).fetchone()

    # 全时段统计（用于对比）
    overall_alltime = conn.execute(
        """
        SELECT COUNT(DISTINCT match_id) AS matches, SUM(kills) AS total_kills,
               SUM(deaths) AS total_deaths, AVG(rating) AS avg_rating,
               AVG(adr) AS avg_adr, AVG(kast) AS avg_kast,
               AVG(impact) AS avg_impact
        FROM match_stats WHERE player_id=?
    """,
        (player_id,),
    ).fetchone()

    # 最近比赛（表格用）
    recent_matches = conn.execute(
        f"""
        SELECT m.*,
               CASE WHEN SUM(CASE WHEN ms.team_id=COALESCE(m.team1_id, -1) THEN 1 ELSE 0 END) > 0
                    THEN COALESCE(m.team1_id, -1)
                    ELSE COALESCE(m.team2_id, -2)
               END AS stat_team_id,
               SUM(ms.kills) AS kills, SUM(ms.deaths) AS deaths, SUM(ms.assists) AS assists,
               AVG(ms.rating) AS rating, AVG(ms.adr) AS adr,
               t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s,
               e.name AS event_name
        FROM match_stats ms
        JOIN matches m ON ms.match_id=m.id
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id
        WHERE ms.player_id=? {stat_filter}
        GROUP BY m.id
        ORDER BY m.match_time DESC LIMIT 10
    """,
        (player_id, *stat_params),
    ).fetchall()
    recent_matches = [supplement_temp_teams(m, conn) for m in recent_matches]

    # 趋势图数据（时间升序，最多 30 场）
    chart_rows = conn.execute(
        f"""
        SELECT m.match_time, AVG(ms.rating) AS rating, AVG(ms.adr) AS adr,
               SUM(ms.kills) AS kills, SUM(ms.deaths) AS deaths
        FROM match_stats ms
        JOIN matches m ON ms.match_id=m.id
        WHERE ms.player_id=? {stat_filter}
        GROUP BY m.id
        ORDER BY m.match_time ASC LIMIT 30
    """,
        (player_id, *stat_params),
    ).fetchall()
    import json as _json

    chart_data = _json.dumps(
        {
            "labels": [date_display_filter(r["match_time"]) for r in chart_rows],
            "rating": [round(r["rating"], 2) if r["rating"] else None for r in chart_rows],
            "adr": [round(r["adr"], 1) if r["adr"] else None for r in chart_rows],
        },
        ensure_ascii=False,
    )

    # MVP / EVP 勋章
    medals = conn.execute(
        """
        SELECT pm.*, e.name AS event_name, e.id AS event_id, e.start_date AS event_date
        FROM player_medals pm
        LEFT JOIN events e ON pm.event_id = e.id
        WHERE pm.player_id = ?
        ORDER BY e.start_date DESC
    """,
        (player_id,),
    ).fetchall()

    # 冠军
    championships = conn.execute(
        """
        SELECT ec.*, e.name AS event_name, e.id AS event_id, e.start_date AS event_date
        FROM event_champions ec
        JOIN events e ON ec.event_id = e.id
        JOIN players p ON p.team_id = ec.team_id
        WHERE p.id = ?
        ORDER BY e.start_date DESC
    """,
        (player_id,),
    ).fetchall()

    nickname_history = conn.execute(
        """
        SELECT nickname, source, created_at
        FROM player_nickname_history
        WHERE player_id=? AND nickname != ? COLLATE NOCASE
        ORDER BY created_at DESC, id DESC
        LIMIT 12
    """,
        (player_id, player["nickname"]),
    ).fetchall()

    filter_events = conn.execute(
        "SELECT id, name FROM events ORDER BY start_date DESC LIMIT 30"
    ).fetchall()

    teammates = []
    if player["team_id"]:
        teammates = conn.execute(
            """
            SELECT id, nickname, avatar
            FROM players
            WHERE team_id=? AND id!=?
            ORDER BY nickname
            LIMIT 8
        """,
            (player["team_id"], player_id),
        ).fetchall()

    def _num(value):
        return float(value or 0)

    def _pct(value, target):
        if target <= 0:
            return 0
        return max(0, min(100, round(_num(value) / target * 100)))

    def _fmt(value, digits=2, suffix=""):
        if value is None:
            return "-"
        return f"{float(value):.{digits}f}{suffix}"

    rounds = _num(overall["rounds_played"])
    maps = int(overall["matches"] or 0)
    kills = _num(overall["total_kills"])
    deaths = _num(overall["total_deaths"])
    assists = _num(overall["total_assists"])
    first_kills = _num(overall["first_kills"])
    first_deaths = _num(overall["first_deaths"])
    trade_kills = _num(overall["trade_kills"])
    trade_deaths = _num(overall["trade_deaths"])
    enemies_flashed = _num(overall["enemies_flashed"])
    flash_count = _num(overall["flash_count"])
    utility_damage = _num(overall["utility_damage"])
    kd_ratio = kills / deaths if deaths else None
    assists_per_round = assists / rounds if rounds else 0
    multi_total = (
        _num(overall["multi2k"])
        + _num(overall["multi3k"])
        + _num(overall["multi4k"])
        + _num(overall["multi5k"])
    )
    first_attempts = first_kills + first_deaths
    opening_success = first_kills / first_attempts * 100 if first_attempts else 0
    sniping_score = 0
    player_summary = {
        "maps": maps,
        "rounds": int(rounds),
        "rating": _num(overall["avg_rating"]),
        "t_rating": overall["avg_t_rating"],
        "ct_rating": overall["avg_ct_rating"],
        "round_swing": overall["damage_delta_per_round"],
        "dpr": overall["avg_dpr"],
        "kast": overall["avg_kast"],
        "multi_kill": (multi_total / rounds * 100) if rounds else 0,
        "adr": overall["avg_adr"],
        "kpr": overall["avg_kpr"],
    }
    player_category_cards = [
        {
            "title": "火力",
            "score": _pct(overall["avg_rating"], 1.5),
            "items": [
                {
                    "label": "每回合击杀",
                    "value": _fmt(overall["avg_kpr"]),
                    "pct": _pct(overall["avg_kpr"], 1.0),
                },
                {
                    "label": "每回合伤害",
                    "value": _fmt(overall["avg_adr"], 1),
                    "pct": _pct(overall["avg_adr"], 120),
                },
                {
                    "label": "K-D 差",
                    "value": f"{int(kills - deaths):+d}",
                    "pct": _pct(kills - deaths + 50, 100),
                },
                {
                    "label": "影响力 RATING",
                    "value": _fmt(overall["avg_impact"]),
                    "pct": _pct(overall["avg_impact"], 1.5),
                },
                {
                    "label": "爆头率",
                    "value": _fmt(overall["avg_hs"], 1, "%"),
                    "pct": _pct(overall["avg_hs"], 80),
                },
            ],
        },
        {
            "title": "突破",
            "score": _pct(first_kills, max(first_attempts, 1)),
            "items": [
                {
                    "label": "每回合首杀",
                    "value": _fmt(first_kills / rounds if rounds else 0),
                    "pct": _pct(first_kills / rounds if rounds else 0, 0.25),
                },
                {
                    "label": "每回合首死",
                    "value": _fmt(first_deaths / rounds if rounds else 0),
                    "pct": _pct(first_deaths / rounds if rounds else 0, 0.25),
                },
                {
                    "label": "开局对枪参与率",
                    "value": _fmt(first_attempts / rounds * 100 if rounds else 0, 1, "%"),
                    "pct": _pct(first_attempts / rounds * 100 if rounds else 0, 35),
                },
                {
                    "label": "开局成功率",
                    "value": _fmt(
                        first_kills / first_attempts * 100 if first_attempts else 0, 1, "%"
                    ),
                    "pct": _pct(first_kills / first_attempts * 100 if first_attempts else 0, 75),
                },
            ],
        },
        {
            "title": "补枪",
            "score": _pct(trade_kills + trade_deaths, max(kills + deaths, 1)),
            "items": [
                {
                    "label": "每回合补枪击杀",
                    "value": _fmt(trade_kills / rounds if rounds else 0),
                    "pct": _pct(trade_kills / rounds if rounds else 0, 0.25),
                },
                {
                    "label": "每回合被补枪死亡",
                    "value": _fmt(trade_deaths / rounds if rounds else 0),
                    "pct": _pct(trade_deaths / rounds if rounds else 0, 0.25),
                },
                {
                    "label": "补枪击杀占比",
                    "value": _fmt(trade_kills / kills * 100 if kills else 0, 1, "%"),
                    "pct": _pct(trade_kills / kills * 100 if kills else 0, 30),
                },
                {
                    "label": "被补枪死亡占比",
                    "value": _fmt(trade_deaths / deaths * 100 if deaths else 0, 1, "%"),
                    "pct": _pct(trade_deaths / deaths * 100 if deaths else 0, 35),
                },
                {
                    "label": "每回合助攻",
                    "value": _fmt(assists_per_round),
                    "pct": _pct(assists_per_round, 0.35),
                },
            ],
        },
        {
            "title": "开局",
            "score": _pct(opening_success, 75),
            "items": [
                {
                    "label": "开局成功率",
                    "value": _fmt(opening_success, 1, "%"),
                    "pct": _pct(opening_success, 75),
                },
                {
                    "label": "每回合开局对枪",
                    "value": _fmt(first_attempts / rounds if rounds else 0),
                    "pct": _pct(first_attempts / rounds if rounds else 0, 0.35),
                },
                {
                    "label": "首杀 / 首死比",
                    "value": _fmt(first_kills / first_deaths if first_deaths else 0),
                    "pct": _pct(first_kills / first_deaths if first_deaths else 0, 2),
                },
            ],
        },
        {
            "title": "残局",
            "score": _pct(overall["clutches_won"], max(maps, 1)),
            "items": [
                {
                    "label": "每回合残局得分",
                    "value": _fmt(_num(overall["clutches_won"]) / rounds if rounds else 0),
                    "pct": _pct(_num(overall["clutches_won"]) / rounds if rounds else 0, 0.08),
                },
                {
                    "label": "残局获胜数",
                    "value": str(int(overall["clutches_won"] or 0)),
                    "pct": _pct(overall["clutches_won"], max(maps, 1)),
                },
                {
                    "label": "下包数",
                    "value": str(int(overall["bomb_plants"] or 0)),
                    "pct": _pct(overall["bomb_plants"], max(maps * 2, 1)),
                },
                {
                    "label": "拆包数",
                    "value": str(int(overall["bomb_defuses"] or 0)),
                    "pct": _pct(overall["bomb_defuses"], max(maps, 1)),
                },
            ],
        },
        {
            "title": "狙击",
            "score": sniping_score,
            "items": [
                {"label": "每回合狙击击杀", "value": _fmt(0), "pct": 0},
                {"label": "狙击击杀占比", "value": _fmt(0, 1, "%"), "pct": 0},
                {"label": "有狙击击杀回合占比", "value": _fmt(0, 1, "%"), "pct": 0},
                {"label": "狙击多杀回合", "value": _fmt(0, 3), "pct": 0},
                {"label": "每回合狙击首杀", "value": _fmt(0, 3), "pct": 0},
            ],
        },
        {
            "title": "道具",
            "score": _pct(overall["utility_damage_per_round"], 8),
            "items": [
                {
                    "label": "每回合道具伤害",
                    "value": _fmt(overall["utility_damage_per_round"]),
                    "pct": _pct(overall["utility_damage_per_round"], 10),
                },
                {
                    "label": "总道具伤害",
                    "value": str(int(utility_damage)),
                    "pct": _pct(utility_damage, max(rounds * 8, 1)),
                },
                {
                    "label": "每回合闪光投掷",
                    "value": _fmt(flash_count / rounds if rounds else 0),
                    "pct": _pct(flash_count / rounds if rounds else 0, 0.8),
                },
                {
                    "label": "每回合致盲敌人",
                    "value": _fmt(enemies_flashed / rounds if rounds else 0),
                    "pct": _pct(enemies_flashed / rounds if rounds else 0, 0.9),
                },
                {
                    "label": "闪光成功率",
                    "value": _fmt(enemies_flashed / flash_count if flash_count else 0),
                    "pct": _pct(enemies_flashed / flash_count if flash_count else 0, 1.5),
                },
            ],
        },
    ]
    player_statistics = [
        {"label": "总击杀", "value": str(int(kills))},
        {"label": "总回合", "value": str(int(rounds))},
        {"label": "HS%", "value": _fmt(overall["avg_hs"], 1, "%")},
        {"label": "每回合击杀", "value": _fmt(overall["avg_kpr"])},
        {"label": "总死亡", "value": str(int(deaths))},
        {"label": "每回合助攻", "value": _fmt(assists_per_round)},
        {"label": "K/D", "value": _fmt(kd_ratio)},
        {"label": "每回合死亡", "value": _fmt(overall["avg_dpr"])},
        {"label": "每回合伤害", "value": _fmt(overall["avg_adr"], 1)},
        {"label": "每回合被队友补枪", "value": _fmt(trade_deaths / rounds if rounds else 0)},
        {"label": "每回合道具伤害", "value": _fmt(overall["utility_damage_per_round"])},
        {"label": "每回合补枪队友", "value": _fmt(trade_kills / rounds if rounds else 0)},
        {"label": "比赛数", "value": str(maps)},
        {"label": "影响力 RATING", "value": _fmt(overall["avg_impact"])},
    ]

    conn.close()

    return render_template(
        "player_detail.html",
        player=player,
        overall=overall,
        recent_matches=recent_matches,
        medals=medals,
        championships=championships,
        chart_data=chart_data,
        period=period,
        overall_alltime=overall_alltime,
        nickname_history=nickname_history,
        event_filter=event_filter,
        filter_events=filter_events,
        teammates=teammates,
        player_summary=player_summary,
        player_category_cards=player_category_cards,
        player_statistics=player_statistics,
    )


@app.route("/stats/players/<int:player_id>")
def player_stats_detail(player_id):
    """选手详细数据页。"""
    filters = _player_current_filters()
    conn = get_db()
    player = conn.execute(
        """
        SELECT p.*, t.name AS team_name, t.short_name AS team_short
        FROM players p
        LEFT JOIN teams t ON p.team_id=t.id
        WHERE p.id=?
    """,
        (player_id,),
    ).fetchone()
    if not player:
        conn.close()
        return "选手不存在", 404

    expr = _player_side_expr(filters["side"])
    where_sql, params = _player_stat_where(player_id, filters)
    overall = conn.execute(
        f"""
        SELECT COUNT(*) AS matches,
               {expr["kills"]} AS total_kills,
               {expr["deaths"]} AS total_deaths,
               SUM(ms.assists) AS total_assists,
               {expr["rating"]} AS avg_rating,
               {expr["adr"]} AS avg_adr,
               AVG(ms.kast) AS avg_kast,
               AVG(ms.headshot_percentage) AS avg_hs,
               ({expr["kills"]} * 1.0 / NULLIF(SUM(ms.rounds_played), 0)) AS avg_kpr,
               ({expr["deaths"]} * 1.0 / NULLIF(SUM(ms.rounds_played), 0)) AS avg_dpr,
               AVG(ms.impact) AS avg_impact,
               AVG(CASE WHEN ms.t_rating > 0 THEN ms.t_rating END) AS avg_t_rating,
               AVG(CASE WHEN ms.ct_rating > 0 THEN ms.ct_rating END) AS avg_ct_rating,
               SUM(ms.rounds_played) AS rounds_played,
               SUM(ms.multi1k) AS multi1k, SUM(ms.multi2k) AS multi2k,
               SUM(ms.multi3k) AS multi3k, SUM(ms.multi4k) AS multi4k,
               SUM(ms.multi5k) AS multi5k,
               SUM(ms.first_kills) AS first_kills,
               SUM(ms.first_deaths) AS first_deaths,
               SUM(ms.trade_kills) AS trade_kills,
               SUM(ms.trade_deaths) AS trade_deaths,
               SUM(ms.clutches_won) AS clutches_won,
               SUM(ms.utility_damage) AS utility_damage,
               AVG(ms.utility_damage_per_round) AS utility_damage_per_round,
               SUM(ms.enemies_flashed) AS enemies_flashed,
               SUM(ms.flash_count) AS flash_count,
               SUM(ms.bomb_plants) AS bomb_plants,
               SUM(ms.bomb_defuses) AS bomb_defuses,
               AVG(ms.damage_delta_per_round) AS damage_delta_per_round,
               AVG(ms.rws_basic) AS rws_basic
        FROM match_stats ms
        JOIN matches m ON ms.match_id=m.id
        {where_sql}
    """,
        params,
    ).fetchone()
    if not overall:
        conn.close()
        return "暂无选手数据", 404

    recent_matches = conn.execute(
        f"""
        SELECT m.*, ms.team_id AS stat_team_id,
               ms.kills, ms.deaths, ms.assists,
               {expr["row_rating"]} AS rating,
               {expr["row_adr"]} AS adr,
               t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s,
               e.name AS event_name
        FROM match_stats ms
        JOIN matches m ON ms.match_id=m.id
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id
        {where_sql}
        ORDER BY m.match_time DESC LIMIT 10
    """,
        params,
    ).fetchall()
    recent_matches = [supplement_temp_teams(m, conn) for m in recent_matches]

    chart_rows = conn.execute(
        f"""
        SELECT m.match_time, {expr["row_rating"]} AS rating, {expr["row_adr"]} AS adr
        FROM match_stats ms
        JOIN matches m ON ms.match_id=m.id
        {where_sql}
        ORDER BY m.match_time ASC LIMIT 30
    """,
        params,
    ).fetchall()
    chart_data = json.dumps(
        {
            "labels": [date_display_filter(r["match_time"]) for r in chart_rows],
            "rating": [round(r["rating"], 2) if r["rating"] else None for r in chart_rows],
            "adr": [round(r["adr"], 1) if r["adr"] else None for r in chart_rows],
        },
        ensure_ascii=False,
    )

    medals = conn.execute(
        """
        SELECT pm.*, e.name AS event_name, e.id AS event_id, e.start_date AS event_date
        FROM player_medals pm
        LEFT JOIN events e ON pm.event_id = e.id
        WHERE pm.player_id = ?
        ORDER BY e.start_date DESC
    """,
        (player_id,),
    ).fetchall()
    championships = conn.execute(
        """
        SELECT ec.*, e.name AS event_name, e.id AS event_id, e.start_date AS event_date
        FROM event_champions ec
        JOIN events e ON ec.event_id = e.id
        JOIN players p ON p.team_id = ec.team_id
        WHERE p.id = ?
        ORDER BY e.start_date DESC
    """,
        (player_id,),
    ).fetchall()

    player_summary, player_category_cards, player_statistics = _build_player_blocks(overall)
    map_options = _player_available_maps(conn)
    conn.close()

    return render_template(
        "player_stats.html",
        player=player,
        overall=overall,
        recent_matches=recent_matches,
        medals=medals,
        championships=championships,
        chart_data=chart_data,
        filters=filters,
        time_options=PLAYER_TIME_FILTERS,
        map_options=map_options,
        side_options=PLAYER_SIDE_OPTIONS,
        player_summary=player_summary,
        player_category_cards=player_category_cards,
        player_statistics=player_statistics,
    )
