from pathlib import Path

from src.website.runtime.database import database_path, get_db, using_turso
from src.website.runtime.initial_schema import execute_sql_script as _execute_sql_script
from src.website.runtime.initial_schema import install_base_schema
from src.website.runtime.legacy_upgrade import (
    _ensure_default_admin,
    _ensure_event_champion_snapshot_tables,
    _ensure_individual_registration_playtime_columns,
    _ensure_match_decider_columns,
    _ensure_match_roster_snapshot_columns,
    _ensure_match_stats_data_version_columns,
    _ensure_match_stats_flash_recorded_column,
    _ensure_match_stats_team_side_column,
    _ensure_match_stats_unique_result_index,
    _ensure_match_test_mode_column,
    _ensure_news_article_link_columns,
    _ensure_non_negative_impact,
    _ensure_placeholder_accounts_pending,
    _ensure_player_playtime_columns,
    _ensure_player_private_remarks_table,
    _ensure_school_profile_columns,
    _ensure_security_state_tables,
    _ensure_yearly_top10_table,
)
from src.website.runtime.storage import SOURCE_ROOT

CURRENT_SCHEMA_VERSION = 6


def supported_schema_version(*, remote: bool) -> int:
    return 3 if remote else CURRENT_SCHEMA_VERSION


def _add_prematch_schema(conn):
    root = SOURCE_ROOT / "migrations/v4"
    for relative in (
        "structure.sql",
        "participant_schema.sql",
        "map_schema.sql",
        "compatibility_views.sql",
        "legacy_writer_guards.sql",
    ):
        _execute_sql_script(conn, (root / relative).read_text(encoding="utf-8"))


def _add_operations_schema(conn):
    root = SOURCE_ROOT / "migrations/v5"
    for filename in (
        "operation_schema.sql",
        "result_schema.sql",
        "stats_schema.sql",
        "demo_schema.sql",
        "live_schema.sql",
    ):
        _execute_sql_script(conn, (root / filename).read_text(encoding="utf-8"))


def _add_championship_schema(conn):
    schema = SOURCE_ROOT / "migrations/v6/championship_schema.sql"
    _execute_sql_script(conn, schema.read_text(encoding="utf-8"))


def init_tables():
    if not using_turso():
        Path(database_path()).parent.mkdir(parents=True, exist_ok=True)
    conn = get_db()
    try:
        if _init_tables(conn) == "prematch_upgrade":
            return
        champions_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='event_champions'"
        ).fetchone()
        if champions_table:
            from src.website.domains.awards.champion_service import backfill_champion_members

            backfill_champion_members(conn)
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _init_tables(conn):
    c = conn.cursor()
    # 本次迁移只验证了本机 SQLite；可选远端驱动仍走网站原有版本。
    remote = using_turso()
    supported_version = supported_schema_version(remote=remote)

    # WAL lets readers continue while another request saves a small update.
    # The PRAGMA is SQLite-specific, so hosted libSQL connections may skip it.
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass

    c.execute("BEGIN" if remote else "BEGIN IMMEDIATE")
    c.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    applied_versions = {
        int(row[0]) for row in c.execute("SELECT version FROM schema_migrations").fetchall()
    }
    future_versions = [version for version in applied_versions if version > supported_version]
    if future_versions:
        raise RuntimeError(
            f"数据库版本高于当前代码：数据库 {max(future_versions)}，当前驱动支持 {supported_version}"
        )
    previous = max(applied_versions, default=0)
    # 同为 v3 的历史站点也可能缺少晚加的列；在安装引用它们的新结构之前补齐。
    if previous >= 3:
        _ensure_individual_registration_playtime_columns(c)
        _ensure_player_playtime_columns(c)
        _ensure_match_test_mode_column(c)
        _ensure_match_decider_columns(c)
        _ensure_match_roster_snapshot_columns(c)
        _ensure_event_champion_snapshot_tables(c)
        _ensure_match_stats_team_side_column(c)
        _ensure_match_stats_data_version_columns(c)
        _ensure_match_stats_flash_recorded_column(c)
        _ensure_news_article_link_columns(c)
        _ensure_school_profile_columns(c)
        _ensure_yearly_top10_table(c)
        _ensure_player_private_remarks_table(c)
        _ensure_security_state_tables(c)
    if not remote and 3 <= previous < supported_version:
        # 新建库只记录其安装时的版本；从实际最高版本起补，绝不重建旧表。
        if previous < 4 <= supported_version:
            _add_prematch_schema(conn)
            c.execute("INSERT INTO schema_migrations(version,name) VALUES(4,'host_prematch')")
        if previous < 5 <= supported_version:
            # 部分早期库尚未记录闪光弹覆盖；新版统计视图从第一次升级就要能读它。
            _ensure_match_stats_flash_recorded_column(c)
            _add_operations_schema(conn)
            c.execute(
                "INSERT INTO schema_migrations(version,name) VALUES(5,'host_match_operations')"
            )
        if previous < 6 <= supported_version:
            _add_championship_schema(conn)
            c.execute(
                "INSERT INTO schema_migrations(version,name) VALUES(6,'event_entrant_champions')"
            )
        conn.commit()
        return "prematch_upgrade"
    if supported_version in applied_versions:
        affected_players = set(_ensure_match_stats_unique_result_index(c))
        affected_players.update(_ensure_non_negative_impact(c))
        summary_exists = c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='player_performance_summary'"
        ).fetchone()
        if affected_players and summary_exists:
            from src.website.domains.statistics.performance_service import (
                refresh_player_performance,
            )

            refresh_player_performance(conn, affected_players)
        _ensure_placeholder_accounts_pending(c)
        _ensure_default_admin(c)
        conn.commit()
        return

    install_base_schema(conn)

    if not remote and supported_version >= 4:
        _add_prematch_schema(conn)
        if supported_version >= 5:
            _add_operations_schema(conn)
        if supported_version >= 6:
            _add_championship_schema(conn)
    c.execute(
        "INSERT INTO schema_migrations(version, name) VALUES(?, ?)",
        (
            supported_version,
            {
                3: "admin_yearly_top10_v3",
                4: "host_prematch",
                5: "host_match_operations",
                6: "event_entrant_champions",
            }[supported_version],
        ),
    )

    conn.commit()
    try:
        c.execute("PRAGMA optimize")
    except Exception:
        pass
