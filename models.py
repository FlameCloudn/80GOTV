import logging
import os
import sqlite3
from contextlib import contextmanager

from config import Config

logger = logging.getLogger("80gotv")
CURRENT_SCHEMA_VERSION = 3

TURSO_URL = os.environ.get("TURSO_URL", "")
TURSO_TOKEN = os.environ.get("TURSO_TOKEN", "")
_CONFIGURED_DATABASE = Config.DATABASE


def _using_turso():
    """Use Turso only while the configured production database is unchanged."""
    return bool(
        TURSO_URL
        and TURSO_TOKEN
        and Config.DATABASE == _CONFIGURED_DATABASE
        and os.environ.get("FLASK_ENV", "").strip().lower() != "testing"
    )


def get_db():
    if _using_turso():
        import libsql_experimental as libsql

        conn = libsql.connect(database=TURSO_URL, auth_token=TURSO_TOKEN)
        conn.sync()
        return conn
    conn = sqlite3.connect(Config.DATABASE, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    # Keep hot indexes and temporary sort data in memory. These values are
    # deliberately modest so the 1 GB production host stays comfortable.
    conn.execute("PRAGMA cache_size=-16384")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA mmap_size=67108864")
    return conn


@contextmanager
def db():
    """数据库连接上下文管理器"""
    conn = get_db()
    try:
        yield conn
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    else:
        try:
            conn.commit()
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _execute_sql_script(conn, script):
    """Execute complete SQL statements without sqlite3.executescript's implicit commit."""
    pending = []
    for line in script.splitlines():
        pending.append(line)
        statement = "\n".join(pending).strip()
        if statement and sqlite3.complete_statement(statement):
            conn.execute(statement)
            pending.clear()
    if "\n".join(pending).strip():
        raise RuntimeError("数据库升级脚本包含不完整的 SQL")


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


def _ensure_match_stats_team_side_column(cursor):
    table = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='match_stats'"
    ).fetchone()
    if not table:
        return
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(match_stats)").fetchall()}
    if "match_team_side" not in columns:
        cursor.execute("ALTER TABLE match_stats ADD COLUMN match_team_side TEXT")


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


def init_tables():
    conn = get_db()
    try:
        _init_tables(conn)
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

    # WAL lets readers continue while another request saves a small update.
    # The PRAGMA is SQLite-specific, so hosted libSQL connections may skip it.
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass

    c.execute("BEGIN" if _using_turso() else "BEGIN IMMEDIATE")
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
    future_versions = [version for version in applied_versions if version > CURRENT_SCHEMA_VERSION]
    if future_versions:
        raise RuntimeError(
            f"数据库版本高于当前代码：数据库 {max(future_versions)}，代码 {CURRENT_SCHEMA_VERSION}"
        )
    if CURRENT_SCHEMA_VERSION in applied_versions:
        _ensure_individual_registration_playtime_columns(c)
        _ensure_player_playtime_columns(c)
        _ensure_match_test_mode_column(c)
        _ensure_match_decider_columns(c)
        _ensure_match_stats_team_side_column(c)
        _ensure_school_profile_columns(c)
        _ensure_yearly_top10_table(c)
        _ensure_player_private_remarks_table(c)
        _ensure_placeholder_accounts_pending(c)
        _ensure_default_admin(c)
        conn.commit()
        return

    _execute_sql_script(
        conn,
        """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS teams (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        short_name TEXT,
        logo TEXT,
        description TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS players (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nickname TEXT NOT NULL,
        real_name TEXT,
        group_username_override TEXT,
        is_bashizhong_student INTEGER,
        team_id INTEGER,
        steam_id TEXT,
        avatar TEXT,
        cs2_playtime_minutes INTEGER,
        playtime_status TEXT NOT NULL DEFAULT 'unknown',
        playtime_checked_at TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(team_id) REFERENCES teams(id)
    );

    CREATE TABLE IF NOT EXISTS player_nickname_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id INTEGER NOT NULL,
        nickname TEXT NOT NULL COLLATE NOCASE,
        source TEXT DEFAULT 'website',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(player_id) REFERENCES players(id),
        UNIQUE(player_id, nickname)
    );

    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        short_name TEXT,
        slug TEXT,
        description TEXT,
        start_date TEXT,
        end_date TEXT,
        format TEXT,
        status TEXT,
        stream_url TEXT,
        bracket_data TEXT,
        registration_open INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER,
        team1_id INTEGER,
        team2_id INTEGER,
        team1_score INTEGER DEFAULT 0,
        team2_score INTEGER DEFAULT 0,
        team1_players TEXT,
        team2_players TEXT,
        match_time TEXT,
        bo_format TEXT,
        stage TEXT,
        status TEXT,
        map_pool TEXT,
        map1 TEXT,
        map1_t1 INTEGER DEFAULT 0,
        map1_t2 INTEGER DEFAULT 0,
        map1_picked_by TEXT,
        map2 TEXT,
        map2_t1 INTEGER DEFAULT 0,
        map2_t2 INTEGER DEFAULT 0,
        map2_picked_by TEXT,
        map3 TEXT,
        map3_t1 INTEGER DEFAULT 0,
        map3_t2 INTEGER DEFAULT 0,
        map3_picked_by TEXT,
        has_map3 INTEGER DEFAULT 1,
        map4 TEXT,
        map4_t1 INTEGER DEFAULT 0,
        map4_t2 INTEGER DEFAULT 0,
        map4_picked_by TEXT,
        has_map4 INTEGER DEFAULT 1,
        map5 TEXT,
        map5_t1 INTEGER DEFAULT 0,
        map5_t2 INTEGER DEFAULT 0,
        map5_picked_by TEXT,
        has_map5 INTEGER DEFAULT 1,
        bp_process TEXT,
        bp_password TEXT DEFAULT NULL,
        bp_state TEXT DEFAULT NULL,
        decider_knife_winner TEXT,
        decider_start_side TEXT,
        stream_url TEXT,
        stream_info TEXT,
        map_halves TEXT,
        watch_urls TEXT,
        server_address TEXT,
        server_password TEXT,
        demo_file TEXT,
        slug TEXT,
        is_test_mode INTEGER NOT NULL DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(event_id) REFERENCES events(id),
        FOREIGN KEY(team1_id) REFERENCES teams(id),
        FOREIGN KEY(team2_id) REFERENCES teams(id)
    );

    CREATE TABLE IF NOT EXISTS match_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER,
        player_id INTEGER,
        team_id INTEGER,
        match_team_side TEXT,
        kills INTEGER DEFAULT 0,
        deaths INTEGER DEFAULT 0,
        assists INTEGER DEFAULT 0,
        adr REAL DEFAULT 0,
        kpr REAL DEFAULT 0,
        dpr REAL DEFAULT 0,
        rating REAL DEFAULT 0,
        impact REAL DEFAULT 0,
        kast REAL DEFAULT 0,
        headshot_percentage REAL DEFAULT 0,
        clutches_won INTEGER DEFAULT 0,
        map_name TEXT,
        side TEXT,
        t_rating REAL DEFAULT 0,
        ct_rating REAL DEFAULT 0,
        t_kills INTEGER DEFAULT 0,
        ct_kills INTEGER DEFAULT 0,
        t_deaths INTEGER DEFAULT 0,
        ct_deaths INTEGER DEFAULT 0,
        t_adr REAL DEFAULT 0,
        ct_adr REAL DEFAULT 0,
        multi1k INTEGER DEFAULT 0,
        multi2k INTEGER DEFAULT 0,
        multi3k INTEGER DEFAULT 0,
        multi4k INTEGER DEFAULT 0,
        multi5k INTEGER DEFAULT 0,
        first_kills INTEGER DEFAULT 0,
        first_deaths INTEGER DEFAULT 0,
        mvp_count INTEGER DEFAULT 0,
        utility_damage REAL DEFAULT 0,
        enemies_flashed INTEGER DEFAULT 0,
        flash_count INTEGER DEFAULT 0,
        he_count INTEGER DEFAULT 0,
        smoke_count INTEGER DEFAULT 0,
        molotov_count INTEGER DEFAULT 0,
        trade_kills INTEGER DEFAULT 0,
        trade_deaths INTEGER DEFAULT 0,
        bomb_plants INTEGER DEFAULT 0,
        bomb_defuses INTEGER DEFAULT 0,
        utility_damage_per_round REAL DEFAULT 0,
        rounds_played INTEGER DEFAULT 0,
        damage_delta_per_round REAL DEFAULT 0,
        rws_basic REAL DEFAULT 0,
        clutch_1v1 INTEGER DEFAULT 0,
        clutch_1v2 INTEGER DEFAULT 0,
        clutch_1v3 INTEGER DEFAULT 0,
        clutch_1v4 INTEGER DEFAULT 0,
        clutch_1v5 INTEGER DEFAULT 0,
        flash_blinded_seconds REAL DEFAULT 0,
        flash_enemy_seconds REAL DEFAULT 0,
        flash_assists INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(match_id) REFERENCES matches(id),
        FOREIGN KEY(player_id) REFERENCES players(id),
        FOREIGN KEY(team_id) REFERENCES teams(id)
    );

    CREATE TABLE IF NOT EXISTS player_performance_summary (
        player_id INTEGER PRIMARY KEY,
        matches INTEGER NOT NULL DEFAULT 0,
        maps INTEGER NOT NULL DEFAULT 0,
        total_kills INTEGER NOT NULL DEFAULT 0,
        total_deaths INTEGER NOT NULL DEFAULT 0,
        total_assists INTEGER NOT NULL DEFAULT 0,
        avg_kills REAL NOT NULL DEFAULT 0,
        avg_deaths REAL NOT NULL DEFAULT 0,
        avg_assists REAL NOT NULL DEFAULT 0,
        avg_rating REAL NOT NULL DEFAULT 0,
        avg_adr REAL NOT NULL DEFAULT 0,
        avg_kast REAL NOT NULL DEFAULT 0,
        avg_hs REAL NOT NULL DEFAULT 0,
        avg_kpr REAL NOT NULL DEFAULT 0,
        avg_dpr REAL NOT NULL DEFAULT 0,
        avg_impact REAL NOT NULL DEFAULT 0,
        avg_t_rating REAL NOT NULL DEFAULT 0,
        avg_ct_rating REAL NOT NULL DEFAULT 0,
        avg_t_adr REAL NOT NULL DEFAULT 0,
        avg_ct_adr REAL NOT NULL DEFAULT 0,
        rounds_played INTEGER NOT NULL DEFAULT 0,
        multi1k INTEGER NOT NULL DEFAULT 0,
        multi2k INTEGER NOT NULL DEFAULT 0,
        multi3k INTEGER NOT NULL DEFAULT 0,
        multi4k INTEGER NOT NULL DEFAULT 0,
        multi5k INTEGER NOT NULL DEFAULT 0,
        first_kills INTEGER NOT NULL DEFAULT 0,
        first_deaths INTEGER NOT NULL DEFAULT 0,
        mvp_count INTEGER NOT NULL DEFAULT 0,
        clutches_won INTEGER NOT NULL DEFAULT 0,
        clutch_1v1 INTEGER NOT NULL DEFAULT 0,
        clutch_1v2 INTEGER NOT NULL DEFAULT 0,
        clutch_1v3 INTEGER NOT NULL DEFAULT 0,
        clutch_1v4 INTEGER NOT NULL DEFAULT 0,
        clutch_1v5 INTEGER NOT NULL DEFAULT 0,
        utility_damage REAL NOT NULL DEFAULT 0,
        enemies_flashed INTEGER NOT NULL DEFAULT 0,
        flash_count INTEGER NOT NULL DEFAULT 0,
        he_count INTEGER NOT NULL DEFAULT 0,
        smoke_count INTEGER NOT NULL DEFAULT 0,
        molotov_count INTEGER NOT NULL DEFAULT 0,
        flash_blinded_seconds REAL NOT NULL DEFAULT 0,
        flash_enemy_seconds REAL NOT NULL DEFAULT 0,
        flash_assists INTEGER NOT NULL DEFAULT 0,
        flash_maps INTEGER NOT NULL DEFAULT 0,
        opponent_flash_maps INTEGER NOT NULL DEFAULT 0,
        trade_kills INTEGER NOT NULL DEFAULT 0,
        trade_deaths INTEGER NOT NULL DEFAULT 0,
        bomb_plants INTEGER NOT NULL DEFAULT 0,
        bomb_defuses INTEGER NOT NULL DEFAULT 0,
        avg_utility_damage_per_round REAL NOT NULL DEFAULT 0,
        avg_damage_delta_per_round REAL NOT NULL DEFAULT 0,
        avg_rws_basic REAL NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS match_kill_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER NOT NULL,
        map_name TEXT NOT NULL DEFAULT '',
        round_number INTEGER NOT NULL DEFAULT 0,
        tick INTEGER NOT NULL DEFAULT 0,
        killer_player_id INTEGER,
        victim_player_id INTEGER,
        assister_player_id INTEGER,
        killer_steam_id TEXT,
        victim_steam_id TEXT,
        assister_steam_id TEXT,
        killer_name TEXT,
        victim_name TEXT,
        assister_name TEXT,
        killer_side TEXT,
        victim_side TEXT,
        assister_side TEXT,
        weapon TEXT,
        headshot INTEGER NOT NULL DEFAULT 0,
        assisted_flash INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(match_id) REFERENCES matches(id) ON DELETE CASCADE,
        FOREIGN KEY(killer_player_id) REFERENCES players(id) ON DELETE SET NULL,
        FOREIGN KEY(victim_player_id) REFERENCES players(id) ON DELETE SET NULL,
        FOREIGN KEY(assister_player_id) REFERENCES players(id) ON DELETE SET NULL,
        UNIQUE(
            match_id, map_name, round_number, tick,
            killer_steam_id, victim_steam_id, killer_name, victim_name
        )
    );

    CREATE TABLE IF NOT EXISTS news (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        content TEXT,
        summary TEXT,
        author TEXT,
        publish_time TEXT,
        comment_count INTEGER DEFAULT 0,
        tags TEXT DEFAULT '',
        related_match_id INTEGER,
        redirect_url TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS admins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        email TEXT,
        email_verified_at TEXT,
        steam_id64 TEXT,
        avatar TEXT,
        group_username TEXT,
        is_bashizhong_student INTEGER,
        is_placeholder INTEGER DEFAULT 0,
        is_cheater INTEGER DEFAULT 0,
        approval_status TEXT NOT NULL DEFAULT 'approved',
        approval_note TEXT,
        approved_at TEXT,
        approved_by INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

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
    );

    CREATE INDEX IF NOT EXISTS idx_player_private_remarks_target
        ON player_private_remarks(target_user_id);

    CREATE TABLE IF NOT EXISTS event_slug_aliases (
        slug TEXT PRIMARY KEY,
        event_id INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS match_slug_aliases (
        slug TEXT PRIMARY KEY,
        match_id INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        target_type TEXT NOT NULL,
        target_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        parent_id INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS comment_likes (
        user_id INTEGER NOT NULL,
        comment_id INTEGER NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(user_id, comment_id),
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(comment_id) REFERENCES comments(id)
    );

    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        type TEXT NOT NULL,
        message TEXT NOT NULL,
        link TEXT,
        is_read INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS player_medals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id INTEGER NOT NULL,
        type TEXT NOT NULL,
        event_id INTEGER,
        match_id INTEGER,
        reason TEXT,
        evp_rank INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(player_id) REFERENCES players(id),
        FOREIGN KEY(event_id) REFERENCES events(id),
        FOREIGN KEY(match_id) REFERENCES matches(id)
    );

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
    );

    CREATE TABLE IF NOT EXISTS event_champions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER NOT NULL,
        team_id INTEGER NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(event_id) REFERENCES events(id),
        FOREIGN KEY(team_id) REFERENCES teams(id)
    );

    CREATE TABLE IF NOT EXISTS match_votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        voted_for TEXT NOT NULL,
        score1_guess INTEGER,
        score2_guess INTEGER,
        points_earned INTEGER DEFAULT 0,
        scored INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(match_id, user_id),
        FOREIGN KEY(match_id) REFERENCES matches(id),
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS forum_categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        slug TEXT UNIQUE NOT NULL,
        description TEXT,
        sort_order INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS forum_threads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        is_pinned INTEGER DEFAULT 0,
        is_locked INTEGER DEFAULT 0,
        view_count INTEGER DEFAULT 0,
        reply_count INTEGER DEFAULT 0,
        last_reply_at TEXT,
        last_reply_user_id INTEGER,
        tags TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(category_id) REFERENCES forum_categories(id),
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(last_reply_user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS event_registrations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER NOT NULL,
        team_name TEXT NOT NULL,
        team_logo TEXT,
        creator_user_id INTEGER NOT NULL,
        status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(event_id) REFERENCES events(id),
        FOREIGN KEY(creator_user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS event_registration_slots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        registration_id INTEGER NOT NULL,
        slot_index INTEGER NOT NULL CHECK(slot_index BETWEEN 0 AND 4),
        user_id INTEGER,
        player_name TEXT NOT NULL,
        steam_id TEXT,
        filled_by_creator INTEGER DEFAULT 0,
        FOREIGN KEY(registration_id) REFERENCES event_registrations(id),
        FOREIGN KEY(user_id) REFERENCES users(id),
        UNIQUE(registration_id, slot_index)
    );

    CREATE TABLE IF NOT EXISTS event_individual_registrations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        player_name TEXT NOT NULL,
        steam_id TEXT NOT NULL,
        assignment_status TEXT NOT NULL DEFAULT 'pending'
            CHECK(assignment_status IN ('pending', 'assigned', 'reserve')),
        team_number INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        assigned_at TEXT,
        cs2_playtime_minutes INTEGER,
        playtime_status TEXT NOT NULL DEFAULT 'unknown',
        playtime_checked_at TEXT,
        preferred_registration_id INTEGER,
        FOREIGN KEY(event_id) REFERENCES events(id),
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(preferred_registration_id) REFERENCES event_registrations(id),
        UNIQUE(event_id, user_id)
    );

    CREATE TABLE IF NOT EXISTS live_match_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER UNIQUE NOT NULL,
        live_state TEXT,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(match_id) REFERENCES matches(id)
    );

    CREATE TABLE IF NOT EXISTS live_match_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER NOT NULL,
        event_key TEXT NOT NULL,
        event_type TEXT NOT NULL,
        round_num INTEGER DEFAULT 0,
        payload TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(match_id) REFERENCES matches(id),
        UNIQUE(match_id, event_key, event_type)
    );

    CREATE TABLE IF NOT EXISTS live_ingest_status (
        source TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        message TEXT,
        match_id INTEGER,
        map_name TEXT,
        received_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(match_id) REFERENCES matches(id)
    );

    CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL DEFAULT 'suggestion',
        content TEXT NOT NULL,
        contact TEXT,
        page_url TEXT,
        user_agent TEXT,
        user_id INTEGER,
        status TEXT DEFAULT 'open',
        admin_reply TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS guess_players (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nickname TEXT NOT NULL UNIQUE COLLATE NOCASE,
        full_name TEXT NOT NULL,
        team TEXT NOT NULL,
        country_code TEXT NOT NULL,
        country_name TEXT NOT NULL,
        birth_date TEXT NOT NULL,
        profile_age INTEGER,
        role TEXT NOT NULL,
        sniping_score INTEGER,
        player_status TEXT NOT NULL DEFAULT 'unknown',
        noob_eligible INTEGER NOT NULL DEFAULT 0,
        major_appearances INTEGER NOT NULL DEFAULT 0,
        active INTEGER NOT NULL DEFAULT 1,
        source_url TEXT,
        source_checked_at TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS guess_player_daily (
        game_date TEXT PRIMARY KEY,
        player_id INTEGER NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(player_id) REFERENCES guess_players(id)
    );

    CREATE TABLE IF NOT EXISTS guess_player_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        game_date TEXT NOT NULL,
        guessed_player_id INTEGER NOT NULL,
        attempt_number INTEGER NOT NULL CHECK(attempt_number BETWEEN 1 AND 8),
        is_correct INTEGER NOT NULL DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(guessed_player_id) REFERENCES guess_players(id),
        UNIQUE(user_id, game_date, guessed_player_id),
        UNIQUE(user_id, game_date, attempt_number)
    );

    CREATE TABLE IF NOT EXISTS guess_player_practice_games (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        player_id INTEGER NOT NULL,
        pool_mode TEXT NOT NULL DEFAULT 'noob',
        status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        completed_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(player_id) REFERENCES guess_players(id)
    );

    CREATE TABLE IF NOT EXISTS guess_player_practice_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id INTEGER NOT NULL,
        guessed_player_id INTEGER NOT NULL,
        attempt_number INTEGER NOT NULL CHECK(attempt_number BETWEEN 1 AND 8),
        is_correct INTEGER NOT NULL DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(game_id) REFERENCES guess_player_practice_games(id),
        FOREIGN KEY(guessed_player_id) REFERENCES guess_players(id),
        UNIQUE(game_id, guessed_player_id),
        UNIQUE(game_id, attempt_number)
    );

    CREATE TABLE IF NOT EXISTS guess_player_rooms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_code TEXT NOT NULL UNIQUE,
        host_user_id INTEGER NOT NULL,
        guest_user_id INTEGER,
        player_id INTEGER NOT NULL,
        pool_mode TEXT NOT NULL DEFAULT 'noob',
        status TEXT NOT NULL DEFAULT 'waiting',
        winner_user_id INTEGER,
        host_last_seen TEXT,
        guest_last_seen TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        started_at TEXT,
        finished_at TEXT,
        FOREIGN KEY(host_user_id) REFERENCES users(id),
        FOREIGN KEY(guest_user_id) REFERENCES users(id),
        FOREIGN KEY(player_id) REFERENCES guess_players(id),
        FOREIGN KEY(winner_user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS guess_player_room_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        guessed_player_id INTEGER NOT NULL,
        attempt_number INTEGER NOT NULL CHECK(attempt_number BETWEEN 1 AND 8),
        is_correct INTEGER NOT NULL DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(room_id) REFERENCES guess_player_rooms(id),
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(guessed_player_id) REFERENCES guess_players(id),
        UNIQUE(room_id, user_id, guessed_player_id),
        UNIQUE(room_id, user_id, attempt_number)
    );

    CREATE TABLE IF NOT EXISTS map_quiz_games (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        mode TEXT NOT NULL CHECK(mode IN ('daily', 'practice')),
        game_key TEXT NOT NULL,
        question_key TEXT NOT NULL,
        finished INTEGER NOT NULL DEFAULT 0,
        won INTEGER NOT NULL DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id),
        UNIQUE(user_id, mode, game_key)
    );

    CREATE TABLE IF NOT EXISTS map_quiz_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id INTEGER NOT NULL,
        attempt_number INTEGER NOT NULL CHECK(attempt_number BETWEEN 1 AND 3),
        guessed_map TEXT NOT NULL,
        guessed_spot TEXT NOT NULL,
        map_correct INTEGER NOT NULL DEFAULT 0,
        spot_correct INTEGER NOT NULL DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(game_id) REFERENCES map_quiz_games(id) ON DELETE CASCADE,
        UNIQUE(game_id, attempt_number)
    );

    CREATE TABLE IF NOT EXISTS player_bingo_games (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        mode TEXT NOT NULL CHECK(mode IN ('daily', 'practice')),
        game_key TEXT NOT NULL,
        board_json TEXT NOT NULL,
        mistakes INTEGER NOT NULL DEFAULT 0,
        lines INTEGER NOT NULL DEFAULT 0,
        finished INTEGER NOT NULL DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id),
        UNIQUE(user_id, mode, game_key)
    );

    CREATE TABLE IF NOT EXISTS player_bingo_cells (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id INTEGER NOT NULL,
        row_index INTEGER NOT NULL CHECK(row_index BETWEEN 0 AND 2),
        column_index INTEGER NOT NULL CHECK(column_index BETWEEN 0 AND 2),
        player_id INTEGER NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(game_id) REFERENCES player_bingo_games(id) ON DELETE CASCADE,
        FOREIGN KEY(player_id) REFERENCES guess_players(id),
        UNIQUE(game_id, row_index, column_index),
        UNIQUE(game_id, player_id)
    );
    """,
    )

    # Reaching this point means version 1 has not completed yet. Everything
    # below is part of that one transaction and must succeed before it is recorded.
    _ensure_default_admin(c)

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

    # --- 迁移：新 match_stats 列（EVP + 投掷物） ---
    migrations = [
        "ALTER TABLE match_stats ADD COLUMN multi1k INTEGER DEFAULT 0",
        "ALTER TABLE match_stats ADD COLUMN multi2k INTEGER DEFAULT 0",
        "ALTER TABLE match_stats ADD COLUMN multi3k INTEGER DEFAULT 0",
        "ALTER TABLE match_stats ADD COLUMN multi4k INTEGER DEFAULT 0",
        "ALTER TABLE match_stats ADD COLUMN multi5k INTEGER DEFAULT 0",
        "ALTER TABLE match_stats ADD COLUMN first_kills INTEGER DEFAULT 0",
        "ALTER TABLE match_stats ADD COLUMN first_deaths INTEGER DEFAULT 0",
        "ALTER TABLE match_stats ADD COLUMN mvp_count INTEGER DEFAULT 0",
        "ALTER TABLE match_stats ADD COLUMN utility_damage REAL DEFAULT 0",
        "ALTER TABLE match_stats ADD COLUMN enemies_flashed INTEGER DEFAULT 0",
        "ALTER TABLE match_stats ADD COLUMN flash_count INTEGER DEFAULT 0",
        "ALTER TABLE match_stats ADD COLUMN he_count INTEGER DEFAULT 0",
        "ALTER TABLE match_stats ADD COLUMN smoke_count INTEGER DEFAULT 0",
        "ALTER TABLE match_stats ADD COLUMN molotov_count INTEGER DEFAULT 0",
        "ALTER TABLE match_stats ADD COLUMN trade_kills INTEGER DEFAULT 0",
        "ALTER TABLE match_stats ADD COLUMN trade_deaths INTEGER DEFAULT 0",
        "ALTER TABLE match_stats ADD COLUMN bomb_plants INTEGER DEFAULT 0",
        "ALTER TABLE match_stats ADD COLUMN bomb_defuses INTEGER DEFAULT 0",
        "ALTER TABLE match_stats ADD COLUMN utility_damage_per_round REAL DEFAULT 0",
        "ALTER TABLE match_stats ADD COLUMN rounds_played INTEGER DEFAULT 0",
        "ALTER TABLE match_stats ADD COLUMN damage_delta_per_round REAL DEFAULT 0",
        "ALTER TABLE match_stats ADD COLUMN rws_basic REAL DEFAULT 0",
        "ALTER TABLE match_stats ADD COLUMN clutch_1v1 INTEGER DEFAULT 0",
        "ALTER TABLE match_stats ADD COLUMN clutch_1v2 INTEGER DEFAULT 0",
        "ALTER TABLE match_stats ADD COLUMN clutch_1v3 INTEGER DEFAULT 0",
        "ALTER TABLE match_stats ADD COLUMN clutch_1v4 INTEGER DEFAULT 0",
        "ALTER TABLE match_stats ADD COLUMN clutch_1v5 INTEGER DEFAULT 0",
        "ALTER TABLE match_stats ADD COLUMN flash_blinded_seconds REAL DEFAULT 0",
        "ALTER TABLE match_stats ADD COLUMN flash_enemy_seconds REAL DEFAULT 0",
        "ALTER TABLE match_stats ADD COLUMN flash_assists INTEGER DEFAULT 0",
        "ALTER TABLE player_performance_summary ADD COLUMN flash_maps INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE player_performance_summary ADD COLUMN opponent_flash_maps INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE matches ADD COLUMN stage TEXT",
        "ALTER TABLE matches ADD COLUMN slug TEXT",
        # 为现有比赛自动生成 slug
        """UPDATE matches SET slug=(
            LOWER(
                REPLACE(
                    COALESCE((SELECT short_name FROM teams WHERE teams.id=matches.team1_id), 't1'), ' ', '-'
                ) || '-vs-' ||
                REPLACE(
                    COALESCE((SELECT short_name FROM teams WHERE teams.id=matches.team2_id), 't2'), ' ', '-'
                ) || '-' ||
                COALESCE(SUBSTR(match_time, 1, 4), '0000') || '-' ||
                REPLACE(
                    COALESCE((SELECT short_name FROM events WHERE events.id=matches.event_id), 'event'), ' ', '-'
                )
            )
        ) WHERE slug IS NULL""",
        "ALTER TABLE events ADD COLUMN short_name TEXT",
        "ALTER TABLE events ADD COLUMN slug TEXT",
        "ALTER TABLE events ADD COLUMN registration_open INTEGER DEFAULT 0",
        "ALTER TABLE news ADD COLUMN redirect_url TEXT",
        "ALTER TABLE users ADD COLUMN is_placeholder INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN is_cheater INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN approval_status TEXT DEFAULT 'approved'",
        "ALTER TABLE users ADD COLUMN approval_note TEXT",
        "ALTER TABLE users ADD COLUMN approved_at TEXT",
        "ALTER TABLE users ADD COLUMN approved_by INTEGER",
        "ALTER TABLE users ADD COLUMN email TEXT",
        "ALTER TABLE users ADD COLUMN email_verified_at TEXT",
        "ALTER TABLE users ADD COLUMN group_username TEXT",
        "ALTER TABLE users ADD COLUMN is_bashizhong_student INTEGER",
        "ALTER TABLE players ADD COLUMN is_bashizhong_student INTEGER",
        "ALTER TABLE guess_players ADD COLUMN profile_age INTEGER",
        "ALTER TABLE guess_players ADD COLUMN sniping_score INTEGER",
        "ALTER TABLE guess_players ADD COLUMN player_status TEXT NOT NULL DEFAULT 'unknown'",
        "ALTER TABLE guess_players ADD COLUMN noob_eligible INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE guess_player_practice_games ADD COLUMN pool_mode TEXT NOT NULL DEFAULT 'noob'",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique ON users(LOWER(email)) WHERE email IS NOT NULL AND TRIM(email)<>''",
        "UPDATE users SET approval_status='approved' WHERE approval_status IS NULL OR TRIM(approval_status)=''",
    ]
    for stmt in migrations:
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
    _ensure_school_profile_columns(c)
    _ensure_yearly_top10_table(c)

    # 旧赛事没有简称时补一个稳定值，避免保存 Demo 时无法生成文件名。
    c.execute("""UPDATE events SET short_name='EVENT_' || id
                 WHERE short_name IS NULL OR TRIM(short_name)=''""")

    # 为旧赛事和旧比赛补齐新的可读网址名称；只更新 slug，不改业务内容。
    try:
        from utils.helpers import (
            ensure_unique_event_slug,
            ensure_unique_match_slug,
            make_event_slug,
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

    _ensure_placeholder_accounts_pending(c)

    # --- 数据库性能索引 ---
    _execute_sql_script(
        conn,
        """
        CREATE INDEX IF NOT EXISTS idx_matches_event ON matches(event_id);
        CREATE INDEX IF NOT EXISTS idx_matches_time ON matches(match_time);
        CREATE INDEX IF NOT EXISTS idx_matches_status_time ON matches(status, match_time);
        CREATE INDEX IF NOT EXISTS idx_matches_event_time ON matches(event_id, match_time);
        CREATE INDEX IF NOT EXISTS idx_stats_match ON match_stats(match_id);
        CREATE INDEX IF NOT EXISTS idx_stats_player ON match_stats(player_id);
        CREATE INDEX IF NOT EXISTS idx_stats_player_match_map ON match_stats(player_id, match_id, map_name);
        CREATE INDEX IF NOT EXISTS idx_stats_match_map_team ON match_stats(match_id, map_name, team_id);
        CREATE INDEX IF NOT EXISTS idx_players_team ON players(team_id);
        CREATE INDEX IF NOT EXISTS idx_players_steam ON players(steam_id);
        CREATE INDEX IF NOT EXISTS idx_players_group_username_override ON players(group_username_override);
        CREATE INDEX IF NOT EXISTS idx_users_steam_id64 ON users(steam_id64);
        CREATE INDEX IF NOT EXISTS idx_users_group_username ON users(group_username);
        CREATE INDEX IF NOT EXISTS idx_users_approval_status ON users(approval_status);
        CREATE INDEX IF NOT EXISTS idx_player_nickname_history_player ON player_nickname_history(player_id);
        CREATE INDEX IF NOT EXISTS idx_player_nickname_history_name ON player_nickname_history(nickname);
        CREATE INDEX IF NOT EXISTS idx_comments_target ON comments(target_type, target_id);
        CREATE INDEX IF NOT EXISTS idx_comments_target_created ON comments(target_type, target_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, is_read);
        CREATE INDEX IF NOT EXISTS idx_forum_threads_cat ON forum_threads(category_id);
        CREATE INDEX IF NOT EXISTS idx_votes_match ON match_votes(match_id);
        CREATE INDEX IF NOT EXISTS idx_news_publish ON news(publish_time);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_events_slug ON events(slug);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_matches_slug ON matches(slug);
        CREATE INDEX IF NOT EXISTS idx_registrations_event ON event_registrations(event_id, status);
        CREATE INDEX IF NOT EXISTS idx_registration_slots_registration ON event_registration_slots(registration_id, slot_index);
        CREATE INDEX IF NOT EXISTS idx_registration_slots_user ON event_registration_slots(user_id);
        CREATE INDEX IF NOT EXISTS idx_individual_registrations_event ON event_individual_registrations(event_id, assignment_status, team_number);
        CREATE INDEX IF NOT EXISTS idx_individual_registrations_user ON event_individual_registrations(user_id, event_id);
        CREATE INDEX IF NOT EXISTS idx_live_match_events_match ON live_match_events(match_id, round_num, id);
        CREATE INDEX IF NOT EXISTS idx_match_stats_map ON match_stats(map_name);
        CREATE INDEX IF NOT EXISTS idx_guess_attempts_user_date ON guess_player_attempts(user_id, game_date);
        CREATE INDEX IF NOT EXISTS idx_guess_daily_player ON guess_player_daily(player_id);
        CREATE INDEX IF NOT EXISTS idx_guess_practice_user ON guess_player_practice_games(user_id, id);
        CREATE INDEX IF NOT EXISTS idx_guess_practice_attempt_game ON guess_player_practice_attempts(game_id, attempt_number);
        CREATE INDEX IF NOT EXISTS idx_guess_players_pool ON guess_players(active, noob_eligible);
        CREATE INDEX IF NOT EXISTS idx_guess_rooms_code ON guess_player_rooms(room_code);
        CREATE INDEX IF NOT EXISTS idx_guess_rooms_users ON guess_player_rooms(host_user_id, guest_user_id, status);
        CREATE INDEX IF NOT EXISTS idx_guess_room_attempts ON guess_player_room_attempts(room_id, user_id, attempt_number);
        CREATE INDEX IF NOT EXISTS idx_map_quiz_games_user ON map_quiz_games(user_id, mode, id);
        CREATE INDEX IF NOT EXISTS idx_map_quiz_attempts_game ON map_quiz_attempts(game_id, attempt_number);
        CREATE INDEX IF NOT EXISTS idx_bingo_games_user ON player_bingo_games(user_id, mode, id);
        CREATE INDEX IF NOT EXISTS idx_bingo_cells_game ON player_bingo_cells(game_id, row_index, column_index);
        CREATE INDEX IF NOT EXISTS idx_player_performance_rating ON player_performance_summary(avg_rating DESC, maps DESC);
        CREATE INDEX IF NOT EXISTS idx_kill_events_match_map ON match_kill_events(match_id, map_name, round_number, tick);
        CREATE INDEX IF NOT EXISTS idx_kill_events_weapon ON match_kill_events(weapon);
        CREATE INDEX IF NOT EXISTS idx_kill_events_killer ON match_kill_events(killer_player_id, match_id);
    """,
    )

    # Player pages read this compact table instead of regrouping every map row
    # for every visitor. It is rebuilt from match_stats only, never from Demo files.
    try:
        from services.performance_service import refresh_player_performance

        refresh_player_performance(conn)
    except Exception as exc:
        raise RuntimeError("数据库升级失败：选手表现汇总") from exc

    # The game uses a small local snapshot so page loads never depend on HLTV being online.
    try:
        from services.guess_player_service import seed_guess_players

        seed_guess_players(conn)
        from services.live_service import remove_stored_gsi_auth

        remove_stored_gsi_auth(conn)
    except Exception as exc:
        raise RuntimeError("数据库升级失败：初始化派生数据") from exc

    # 将已有正式昵称放入历史表。以后昵称变化时继续追加，不覆盖旧记录。
    c.execute("""
        INSERT OR IGNORE INTO player_nickname_history(player_id, nickname, source)
        SELECT id, nickname, 'website' FROM players
        WHERE nickname IS NOT NULL AND TRIM(nickname) != ''
    """)

    c.execute(
        "INSERT INTO schema_migrations(version, name) VALUES(?, ?)",
        (CURRENT_SCHEMA_VERSION, "admin_yearly_top10_v3"),
    )

    conn.commit()
    try:
        c.execute("PRAGMA optimize")
    except Exception:
        pass


def query_db(query, args=(), one=False):
    with db() as conn:
        cur = conn.execute(query, args)
        rv = cur.fetchall()
        return (rv[0] if rv else None) if one else rv


def execute_db(query, args=()):
    with db() as conn:
        conn.execute(query, args)
