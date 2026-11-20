"""升级旧 SQLite 结构与既有业务字段；不更改已发布 SQL 版本。"""

import logging

from src.website.runtime.config import Config

logger = logging.getLogger("80gotv")


def _ensure_default_admin(cursor):
    admin = cursor.execute(
        "SELECT id FROM admins WHERE username=?", (Config.DEFAULT_ADMIN_USERNAME,)
    ).fetchone()
    if admin or not Config.DEFAULT_ADMIN_PASSWORD:
        if not admin:
            logger.error(
                "尚未创建管理员。请设置 ADMIN_USERNAME 和 ADMIN_PASSWORD 后重新运行初始化。"
            )
        return

    from werkzeug.security import generate_password_hash

    cursor.execute(
        "INSERT INTO admins(username, password_hash) VALUES(?,?)",
        (
            Config.DEFAULT_ADMIN_USERNAME,
            generate_password_hash(Config.DEFAULT_ADMIN_PASSWORD),
        ),
    )


def _ensure_placeholder_accounts_pending(cursor):
    """Fill a missing placeholder status without overwriting an admin decision."""
    table = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()
    if not table:
        return
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(users)").fetchall()}
    if {"is_placeholder", "approval_status"}.issubset(columns):
        cursor.execute(
            """UPDATE users
               SET approval_status='pending'
               WHERE is_placeholder=1
                 AND COALESCE(TRIM(approval_status), '')=''"""
        )


def _ensure_individual_registration_playtime_columns(cursor):
    table = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='event_individual_registrations'"
    ).fetchone()
    if not table:
        return
    columns = {
        row[1]
        for row in cursor.execute("PRAGMA table_info(event_individual_registrations)").fetchall()
    }
    additions = {
        "cs2_playtime_minutes": "INTEGER",
        "playtime_status": "TEXT NOT NULL DEFAULT 'unknown'",
        "playtime_checked_at": "TEXT",
        "preferred_registration_id": "INTEGER",
    }
    for name, definition in additions.items():
        if name not in columns:
            cursor.execute(
                f"ALTER TABLE event_individual_registrations ADD COLUMN {name} {definition}"
            )


def _ensure_player_playtime_columns(cursor):
    table = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='players'"
    ).fetchone()
    if not table:
        return
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(players)").fetchall()}
    additions = {
        "group_username_override": "TEXT",
        "cs2_playtime_minutes": "INTEGER",
        "playtime_status": "TEXT NOT NULL DEFAULT 'unknown'",
        "playtime_checked_at": "TEXT",
    }
    for name, definition in additions.items():
        if name not in columns:
            cursor.execute(f"ALTER TABLE players ADD COLUMN {name} {definition}")


def _ensure_match_test_mode_column(cursor):
    table = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='matches'"
    ).fetchone()
    if not table:
        return
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(matches)").fetchall()}
    if "is_test_mode" not in columns:
        cursor.execute("ALTER TABLE matches ADD COLUMN is_test_mode INTEGER NOT NULL DEFAULT 0")


def _ensure_match_decider_columns(cursor):
    table = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='matches'"
    ).fetchone()
    if not table:
        return
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(matches)").fetchall()}
    additions = {
        "decider_knife_winner": "TEXT",
        "decider_start_side": "TEXT",
    }
    for name, definition in additions.items():
        if name not in columns:
            cursor.execute(f"ALTER TABLE matches ADD COLUMN {name} {definition}")


def _ensure_match_roster_snapshot_columns(cursor):
    table = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='matches'"
    ).fetchone()
    if not table:
        return
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(matches)").fetchall()}
    additions = {
        "roster_snapshot": "TEXT",
        "team1_registration_id": ("INTEGER REFERENCES event_registrations(id) ON DELETE SET NULL"),
        "team2_registration_id": ("INTEGER REFERENCES event_registrations(id) ON DELETE SET NULL"),
    }
    for name, definition in additions.items():
        if name not in columns:
            cursor.execute(f"ALTER TABLE matches ADD COLUMN {name} {definition}")


def _ensure_event_champion_snapshot_tables(cursor):
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS event_champions (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               event_id INTEGER NOT NULL,
               team_id INTEGER NOT NULL,
               players_snapshot_at TEXT,
               created_at TEXT DEFAULT CURRENT_TIMESTAMP,
               FOREIGN KEY(event_id) REFERENCES events(id),
               FOREIGN KEY(team_id) REFERENCES teams(id)
           )"""
    )
    champion_columns = {
        row[1] for row in cursor.execute("PRAGMA table_info(event_champions)").fetchall()
    }
    if "players_snapshot_at" not in champion_columns:
        cursor.execute("ALTER TABLE event_champions ADD COLUMN players_snapshot_at TEXT")
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS event_champion_players (
               champion_id INTEGER NOT NULL,
               player_id INTEGER NOT NULL,
               PRIMARY KEY(champion_id, player_id),
               FOREIGN KEY(champion_id) REFERENCES event_champions(id) ON DELETE CASCADE,
               FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
           )"""
    )


def _ensure_match_stats_team_side_column(cursor):
    table = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='match_stats'"
    ).fetchone()
    if not table:
        return
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(match_stats)").fetchall()}
    if "match_team_side" not in columns:
        cursor.execute("ALTER TABLE match_stats ADD COLUMN match_team_side TEXT")


def _ensure_match_stats_data_version_columns(cursor):
    """Backfill live-data metadata for databases already on the current version."""
    table = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='match_stats'"
    ).fetchone()
    if not table:
        return
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(match_stats)").fetchall()}
    additions = {
        "data_source": "TEXT NOT NULL DEFAULT 'legacy'",
        "data_status": "TEXT NOT NULL DEFAULT 'final'",
        "data_version": "INTEGER NOT NULL DEFAULT 1",
        "impact_method": "TEXT",
        "rating_impact": "REAL",
        "side_stats_json": "TEXT",
    }
    for name, definition in additions.items():
        if name not in columns:
            cursor.execute(f"ALTER TABLE match_stats ADD COLUMN {name} {definition}")


def _ensure_match_stats_flash_recorded_column(cursor):
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(match_stats)").fetchall()}
    if columns and "flash_count_recorded" not in columns:
        cursor.execute(
            "ALTER TABLE match_stats ADD COLUMN flash_count_recorded INTEGER NOT NULL DEFAULT 0"
        )


def _ensure_news_article_link_columns(cursor):
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(news)").fetchall()}
    for name in ("internal_link_url", "internal_link_text"):
        if columns and name not in columns:
            cursor.execute(f"ALTER TABLE news ADD COLUMN {name} TEXT")


def _ensure_match_stats_unique_result_index(cursor):
    """Prevent duplicate player/map rows while retaining older rows as history."""
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(match_stats)").fetchall()}
    if not {"data_status", "match_id", "map_name", "player_id"}.issubset(columns):
        return []
    duplicates = cursor.execute(
        """
        SELECT id, player_id FROM (
            SELECT id, player_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY match_id, map_name, player_id ORDER BY id DESC
                   ) AS row_number
            FROM match_stats
            WHERE player_id IS NOT NULL AND map_name IS NOT NULL
              AND COALESCE(data_status, 'final') <> 'superseded'
        )
        WHERE row_number > 1
        """
    ).fetchall()
    if duplicates:
        cursor.executemany(
            "UPDATE match_stats SET data_status='superseded' WHERE id=?",
            [(row[0],) for row in duplicates],
        )
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_match_stats_match_map_player_current
        ON match_stats(match_id, map_name, player_id)
        WHERE player_id IS NOT NULL AND map_name IS NOT NULL
          AND COALESCE(data_status, 'final') <> 'superseded'
        """
    )
    return sorted({row[1] for row in duplicates})


def _ensure_non_negative_impact(cursor):
    """Impact 最低记 0：以前按回归公式存下的负数（击杀很少时会出现）改成 0，只改 impact 这一列。

    返回受影响的选手，用来刷新他们的汇总数据。重复执行不会再改到任何记录。
    """
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(match_stats)").fetchall()}
    if not {"impact", "player_id"}.issubset(columns):
        return []
    players = cursor.execute(
        "SELECT DISTINCT player_id FROM match_stats WHERE impact < 0 AND player_id IS NOT NULL"
    ).fetchall()
    cursor.execute("UPDATE match_stats SET impact = 0 WHERE impact < 0")
    return sorted({row[0] for row in players})


def _ensure_school_profile_columns(cursor):
    additions = {
        "users": {"is_bashizhong_student": "INTEGER"},
        "players": {"is_bashizhong_student": "INTEGER"},
    }
    for table, columns_to_add in additions.items():
        table_exists = cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        if not table_exists:
            continue
        existing_columns = {
            row[1] for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for name, definition in columns_to_add.items():
            if name not in existing_columns:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _ensure_yearly_top10_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS yearly_top_players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year INTEGER NOT NULL,
            rank INTEGER NOT NULL CHECK(rank BETWEEN 1 AND 10),
            player_id INTEGER NOT NULL,
            decided_by INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(year, rank),
            UNIQUE(year, player_id),
            FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE,
            FOREIGN KEY(decided_by) REFERENCES admins(id) ON DELETE SET NULL
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_yearly_top_players_year "
        "ON yearly_top_players(year DESC, rank ASC)"
    )


def _ensure_player_private_remarks_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS player_private_remarks (
            owner_user_id INTEGER NOT NULL,
            target_user_id INTEGER NOT NULL,
            remark TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(owner_user_id, target_user_id),
            CHECK(owner_user_id <> target_user_id),
            FOREIGN KEY(owner_user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(target_user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_player_private_remarks_target "
        "ON player_private_remarks(target_user_id)"
    )


def _ensure_security_state_tables(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS request_rate_limits (
            bucket TEXT NOT NULL,
            attempted_at REAL NOT NULL,
            expires_at REAL NOT NULL
        )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_rate_limits_bucket_time "
        "ON request_rate_limits(bucket, attempted_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_rate_limits_expiry ON request_rate_limits(expires_at)"
    )
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS email_verification_challenges (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            digest TEXT NOT NULL,
            expires_at REAL NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            verified_at REAL,
            consumed_at REAL
        )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_email_challenges_email "
        "ON email_verification_challenges(email)"
    )
