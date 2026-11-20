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
