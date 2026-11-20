"""新库和早于 v3 的旧库：安装领域表、补齐旧字段和业务种子数据。"""

import sqlite3
from pathlib import Path

from config import BASE_DIR
from src.website.runtime.legacy_upgrade import (
    _ensure_default_admin,
    _ensure_event_champion_snapshot_tables,
    _ensure_individual_registration_playtime_columns,
    _ensure_match_decider_columns,
    _ensure_match_roster_snapshot_columns,
    _ensure_match_stats_data_version_columns,
    _ensure_match_stats_unique_result_index,
    _ensure_match_test_mode_column,
    _ensure_placeholder_accounts_pending,
    _ensure_player_playtime_columns,
    _ensure_school_profile_columns,
    _ensure_security_state_tables,
    _ensure_yearly_top10_table,
)


def _statements(script):
    pending = []
    for line in script.splitlines():
        pending.append(line)
        statement = "\n".join(pending).strip()
        if statement and sqlite3.complete_statement(statement):
            yield statement
            pending.clear()
    if "\n".join(pending).strip():
        raise RuntimeError("数据库升级脚本包含不完整的 SQL")


def execute_sql_script(conn, script):
    """executescript 会隐式提交；逐条执行才能和版本号处于同一个事务。"""
    for statement in _statements(script):
        conn.execute(statement)


def _seed_forum(c):
    # 自动创建默认论坛版块
    default_forum_cats = [
        ("CS2 综合讨论", "cs2-general", "Counter-Strike 2 赛事、战队、选手讨论", 1),
        ("赛事讨论", "tournaments", "S/A/B 级赛事讨论与赛后分析", 2),
        ("转会与战队", "transfers", "战队阵容变动、转会新闻讨论", 3),
        ("游戏更新", "game-updates", "版本更新、地图变化、武器平衡讨论", 4),
        ("水友专区", "offtopic", "灌水闲聊，非 CS 话题", 5),
    ]
    for cat_name, cat_slug, cat_desc, cat_order in default_forum_cats:
        c.execute(
            "INSERT OR IGNORE INTO forum_categories(name, slug, description, sort_order) VALUES(?,?,?,?)",
            (cat_name, cat_slug, cat_desc, cat_order),
        )
    default_category = c.execute(
        "SELECT id FROM forum_categories ORDER BY sort_order, id LIMIT 1"
    ).fetchone()
    if default_category:
        c.execute(
            """
            UPDATE forum_threads
            SET category_id=?
            WHERE NOT EXISTS (
                SELECT 1 FROM forum_categories
                WHERE forum_categories.id=forum_threads.category_id
            )
        """,
            (default_category[0],),
        )


def _upgrade_references(conn, c):
    # 旧赛事没有简称时补一个稳定值，避免保存 Demo 时无法生成文件名。
    c.execute("""UPDATE events SET short_name='EVENT_' || id
                 WHERE short_name IS NULL OR TRIM(short_name)=''""")

    # 为旧赛事和旧比赛补齐新的可读网址名称；只更新 slug，不改业务内容。
    try:
        from src.website.domains.events.event_references import (
            ensure_unique_event_slug,
            make_event_slug,
        )
        from src.website.domains.matches.match_references import (
            ensure_unique_match_slug,
            make_match_slug,
        )

        event_rows = c.execute(
            "SELECT id, name, short_name, slug FROM events ORDER BY id"
        ).fetchall()
        for event in event_rows:
            base = event["slug"] or event["name"] or event["short_name"] or f"event-{event['id']}"
            event_slug = ensure_unique_event_slug(conn, event["id"], make_event_slug(base))
            if event["slug"] and event["slug"] != event_slug:
                c.execute(
                    "INSERT OR IGNORE INTO event_slug_aliases(slug,event_id) VALUES(?,?)",
                    (event["slug"], event["id"]),
                )
            c.execute("UPDATE events SET slug=? WHERE id=?", (event_slug, event["id"]))

        match_rows = c.execute(
            """SELECT m.id, m.slug, m.match_time,
                      COALESCE(t1.short_name, t1.name, 'team1') AS team1_name,
                      COALESCE(t2.short_name, t2.name, 'team2') AS team2_name,
                      COALESCE(e.slug, e.short_name, e.name, 'event') AS event_name
               FROM matches m
               LEFT JOIN teams t1 ON m.team1_id=t1.id
               LEFT JOIN teams t2 ON m.team2_id=t2.id
               LEFT JOIN events e ON m.event_id=e.id
               ORDER BY m.id"""
        ).fetchall()
        for match in match_rows:
            base = make_match_slug(
                match["team1_name"],
                match["team2_name"],
                match["match_time"],
                match["event_name"],
            )
            match_slug = ensure_unique_match_slug(conn, match["id"], base)
            if match["slug"] and match["slug"] != match_slug:
                c.execute(
                    "INSERT OR IGNORE INTO match_slug_aliases(slug,match_id) VALUES(?,?)",
                    (match["slug"], match["id"]),
                )
            c.execute("UPDATE matches SET slug=? WHERE id=?", (match_slug, match["id"]))
    except Exception as exc:
        raise RuntimeError("数据库升级失败：生成可读网址") from exc

    # 旧报名表使用 captain_user_id，新代码统一改用 creator_user_id。
    try:
        reg_columns = {
            row[1] for row in c.execute("PRAGMA table_info(event_registrations)").fetchall()
        }
        if "creator_user_id" not in reg_columns:
            c.execute("ALTER TABLE event_registrations ADD COLUMN creator_user_id INTEGER")
            reg_columns.add("creator_user_id")
        if "captain_user_id" in reg_columns:
            c.execute("""UPDATE event_registrations
                         SET creator_user_id=captain_user_id
                         WHERE creator_user_id IS NULL""")
        if "team_logo" not in reg_columns:
            c.execute("ALTER TABLE event_registrations ADD COLUMN team_logo TEXT")
    except Exception as exc:
        raise RuntimeError("数据库升级失败：报名表字段") from exc


def install_base_schema(conn):
    c = conn.cursor()
    bootstrap = Path(BASE_DIR) / "migrations" / "bootstrap"
    for owner in (
        "directory",
        "events",
        "matches",
        "statistics",
        "community",
        "identity",
        "awards",
        "predictions",
        "operations",
        "games",
    ):
        execute_sql_script(conn, (bootstrap / f"{owner}.sql").read_text(encoding="utf-8"))

    # Reaching this point means version 1 has not completed yet. Everything
    # below is part of that one transaction and must succeed before it is recorded.
    _ensure_default_admin(c)

    _seed_forum(c)

    for stmt in _statements((bootstrap / "legacy-columns.sql").read_text(encoding="utf-8")):
        try:
            c.execute(stmt)
        except Exception as exc:
            err = str(exc).lower()
            if any(kw in err for kw in ("duplicate column", "already exists")):
                continue
            raise RuntimeError(f"数据库升级失败：{stmt[:80]}") from exc

    # These columns were introduced after the original full-schema migration.
    # Add them before creating indexes or rebuilding derived data that reads them.
    _ensure_individual_registration_playtime_columns(c)
    _ensure_player_playtime_columns(c)
    _ensure_match_test_mode_column(c)
    _ensure_match_decider_columns(c)
    _ensure_match_roster_snapshot_columns(c)
    _ensure_event_champion_snapshot_tables(c)
    _ensure_school_profile_columns(c)
    _ensure_yearly_top10_table(c)
    _ensure_security_state_tables(c)

    _upgrade_references(conn, c)

    _ensure_placeholder_accounts_pending(c)
    _ensure_match_stats_data_version_columns(c)
    _ensure_match_stats_unique_result_index(c)

    # --- 数据库性能索引 ---
    execute_sql_script(conn, (bootstrap / "indexes.sql").read_text(encoding="utf-8"))

    # Player pages read this compact table instead of regrouping every map row
    # for every visitor. It is rebuilt from match_stats only, never from Demo files.
    try:
        from src.website.domains.statistics.performance_service import refresh_player_performance

        refresh_player_performance(conn)
    except Exception as exc:
        raise RuntimeError("数据库升级失败：选手表现汇总") from exc

    # The game uses a small local snapshot so page loads never depend on HLTV being online.
    try:
        from src.website.domains.games.guess_player_service import seed_guess_players

        seed_guess_players(conn)
        from src.website.domains.operations.live_service import remove_stored_gsi_auth

        remove_stored_gsi_auth(conn)
    except Exception as exc:
        raise RuntimeError("数据库升级失败：初始化派生数据") from exc

    # 将已有正式昵称放入历史表。以后昵称变化时继续追加，不覆盖旧记录。
    c.execute("""
        INSERT OR IGNORE INTO player_nickname_history(player_id, nickname, source)
        SELECT id, nickname, 'website' FROM players
        WHERE nickname IS NOT NULL AND TRIM(nickname) != ''
    """)
