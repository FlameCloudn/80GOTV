import os
import libsql_experimental as libsql
from config import Config

# 优先用 Turso 云数据库，否则回退本地 SQLite
TURSO_URL = os.environ.get("TURSO_URL", "")
TURSO_TOKEN = os.environ.get("TURSO_TOKEN", "")

if TURSO_URL and TURSO_TOKEN:
    _db = libsql.connect(database=TURSO_URL, auth_token=TURSO_TOKEN)
    def get_db():
        _db.sync()
        return _db
else:
    import sqlite3
    def get_db():
        conn = sqlite3.connect(Config.DATABASE)
        conn.row_factory = sqlite3.Row
        return conn

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

    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        start_date TEXT,
        end_date TEXT,
        format TEXT,
        status TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER,
        team1_id INTEGER,
        team2_id INTEGER,
        team1_score INTEGER DEFAULT 0,
        team2_score INTEGER DEFAULT 0,
        match_time TEXT,
        bo_format TEXT,
        status TEXT,
        map_pool TEXT,
        map1 TEXT,
        map1_t1 INTEGER DEFAULT 0,
        map1_t2 INTEGER DEFAULT 0,
        map2 TEXT,
        map2_t1 INTEGER DEFAULT 0,
        map2_t2 INTEGER DEFAULT 0,
        map3 TEXT,
        map3_t1 INTEGER DEFAULT 0,
        map3_t2 INTEGER DEFAULT 0,
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
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS admins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL
    );
    """)

    # 自动创建默认管理员
    try:
        admin = c.execute("SELECT id FROM admins WHERE username='admin'").fetchone()
        if not admin:
            from werkzeug.security import generate_password_hash
            c.execute("INSERT INTO admins(username, password_hash) VALUES(?,?)",
                      ('admin', generate_password_hash('admin123')))
    except:
        pass

    conn.commit()

def query_db(query, args=(), one=False):
    conn = get_db()
    cur = conn.execute(query, args)
    rv = cur.fetchall()
    try: conn.close()
    except: pass
    return (rv[0] if rv else None) if one else rv

def execute_db(query, args=()):
    conn = get_db()
    conn.execute(query, args)
    conn.commit()
    try: conn.close()
    except: pass