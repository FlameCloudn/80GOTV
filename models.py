import logging
import os
import sys
from contextlib import contextmanager

from config import Config

logger = logging.getLogger("80gotv")

TURSO_URL = os.environ.get("TURSO_URL", "")
TURSO_TOKEN = os.environ.get("TURSO_TOKEN", "")

if TURSO_URL and TURSO_TOKEN:
    import libsql_experimental as libsql

    def get_db():
        conn = libsql.connect(database=TURSO_URL, auth_token=TURSO_TOKEN)
        conn.sync()
        return conn
else:
    import sqlite3

    def get_db():
        conn = sqlite3.connect(Config.DATABASE)
        conn.row_factory = sqlite3.Row
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


def init_tables():
    conn = get_db()
    c = conn.cursor()

    c.executescript("""
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
        team_id INTEGER,
        steam_id TEXT,
        avatar TEXT,
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
        stream_url TEXT,
        stream_info TEXT,
        map_halves TEXT,
        watch_urls TEXT,
        server_address TEXT,
        server_password TEXT,
        demo_file TEXT,
        slug TEXT,
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
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(match_id) REFERENCES matches(id),
        FOREIGN KEY(player_id) REFERENCES players(id),
        FOREIGN KEY(team_id) REFERENCES teams(id)
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
        steam_id64 TEXT,
        avatar TEXT,
        is_placeholder INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
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
    """)

    # 自动创建默认管理员
    try:
        admin = c.execute(
            "SELECT id FROM admins WHERE username=?", (Config.DEFAULT_ADMIN_USERNAME,)
        ).fetchone()
        if not admin and Config.DEFAULT_ADMIN_PASSWORD:
            from werkzeug.security import generate_password_hash

            c.execute(
                "INSERT INTO admins(username, password_hash) VALUES(?,?)",
                (
                    Config.DEFAULT_ADMIN_USERNAME,
                    generate_password_hash(Config.DEFAULT_ADMIN_PASSWORD),
                ),
            )
        elif not admin:
            logger.error(
                "尚未创建管理员。请设置 ADMIN_USERNAME 和 ADMIN_PASSWORD 后重新运行初始化。"
            )
    except Exception:
        pass

    # 自动创建默认论坛版块
    default_forum_cats = [
        ("CS2 综合讨论", "cs2-general", "Counter-Strike 2 赛事、战队、选手讨论", 1),
        ("赛事讨论", "tournaments", "S/A/B 级赛事讨论与赛后分析", 2),
        ("转会与战队", "transfers", "战队阵容变动、转会新闻讨论", 3),
        ("游戏更新", "game-updates", "版本更新、地图变化、武器平衡讨论", 4),
        ("水友专区", "offtopic", "灌水闲聊，非 CS 话题", 5),
    ]
    for cat_name, cat_slug, cat_desc, cat_order in default_forum_cats:
        try:
            c.execute(
                "INSERT OR IGNORE INTO forum_categories(name, slug, description, sort_order) VALUES(?,?,?,?)",
                (cat_name, cat_slug, cat_desc, cat_order),
            )
        except Exception:
            pass
    try:
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
    except Exception as exc:
        logger.warning("[MIGRATION] forum_threads category_id → %s", exc)

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
        "ALTER TABLE events ADD COLUMN registration_open INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN is_placeholder INTEGER DEFAULT 0",
    ]
    for stmt in migrations:
        try:
            c.execute(stmt)
        except Exception:
            err = str(sys.exc_info()[1] or "")
            if any(kw in err.lower() for kw in ("duplicate column", "already exists")):
                pass
            else:
                logger.warning("[MIGRATION] %s... → %s", stmt[:80], err)

    # 旧赛事没有简称时补一个稳定值，避免保存 Demo 时无法生成文件名。
    try:
        c.execute("""UPDATE events SET short_name='EVENT_' || id
                     WHERE short_name IS NULL OR TRIM(short_name)=''""")
    except Exception as exc:
        logger.warning("[MIGRATION] events short_name → %s", exc)

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
    except Exception as exc:
        logger.warning("[MIGRATION] event_registrations creator_user_id → %s", exc)

    # 旧版 Demo 自动创建账号时使用过固定密码，仅将这些账号标记为待本人接管。
    try:
        from werkzeug.security import check_password_hash

        placeholder_users = c.execute(
            "SELECT id, password_hash FROM users WHERE steam_id64 IS NOT NULL AND is_placeholder=0"
        ).fetchall()
        for user_id, password_hash in placeholder_users:
            if check_password_hash(password_hash, "123456"):
                c.execute("UPDATE users SET is_placeholder=1 WHERE id=?", (user_id,))
    except Exception as exc:
        logger.warning("[MIGRATION] users is_placeholder → %s", exc)

    # --- 数据库性能索引 ---
    c.executescript("""
        CREATE INDEX IF NOT EXISTS idx_matches_event ON matches(event_id);
        CREATE INDEX IF NOT EXISTS idx_matches_time ON matches(match_time);
        CREATE INDEX IF NOT EXISTS idx_stats_match ON match_stats(match_id);
        CREATE INDEX IF NOT EXISTS idx_stats_player ON match_stats(player_id);
        CREATE INDEX IF NOT EXISTS idx_players_team ON players(team_id);
        CREATE INDEX IF NOT EXISTS idx_players_steam ON players(steam_id);
        CREATE INDEX IF NOT EXISTS idx_player_nickname_history_player ON player_nickname_history(player_id);
        CREATE INDEX IF NOT EXISTS idx_player_nickname_history_name ON player_nickname_history(nickname);
        CREATE INDEX IF NOT EXISTS idx_comments_target ON comments(target_type, target_id);
        CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, is_read);
        CREATE INDEX IF NOT EXISTS idx_forum_threads_cat ON forum_threads(category_id);
        CREATE INDEX IF NOT EXISTS idx_votes_match ON match_votes(match_id);
        CREATE INDEX IF NOT EXISTS idx_news_publish ON news(publish_time);
        CREATE INDEX IF NOT EXISTS idx_registrations_event ON event_registrations(event_id, status);
        CREATE INDEX IF NOT EXISTS idx_registration_slots_user ON event_registration_slots(user_id);
        CREATE INDEX IF NOT EXISTS idx_live_match_events_match ON live_match_events(match_id, round_num, id);
        CREATE INDEX IF NOT EXISTS idx_match_stats_map ON match_stats(map_name);
    """)

    # 将已有正式昵称放入历史表。以后昵称变化时继续追加，不覆盖旧记录。
    c.execute("""
        INSERT OR IGNORE INTO player_nickname_history(player_id, nickname, source)
        SELECT id, nickname, 'website' FROM players
        WHERE nickname IS NOT NULL AND TRIM(nickname) != ''
    """)

    conn.commit()
    try:
        conn.close()
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
