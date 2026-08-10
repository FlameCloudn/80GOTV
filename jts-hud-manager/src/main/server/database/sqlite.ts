import sqlite3 from 'sqlite3'
import path from 'path'
import { app } from 'electron'
import fs from 'fs'

// Store database in user app data folder so it persists across app updates
const userDataPath = app.getPath('userData')
const dbDir = path.join(userDataPath, 'database')

// Ensure the directory exists
if (!fs.existsSync(dbDir)) {
  fs.mkdirSync(dbDir, { recursive: true })
}

const dbPath = path.join(dbDir, 'jts-hud-manager.sqlite')

// Initialize SQLite Database
export const db = new sqlite3.Database(dbPath, (err) => {
  if (err) {
    console.error('Error opening SQLite database:', err.message)
  } else {
    console.log('Connected to the SQLite database at:', dbPath)
    initializeTables()
  }
})

// Helper function to run queries with Promises
export const dbRun = (query: string, params: any[] = []): Promise<void> => {
  return new Promise((resolve, reject) => {
    db.run(query, params, function (err) {
      if (err) reject(err)
      else resolve()
    })
  })
}

// Helper function to get multiple rows
export const dbAll = (query: string, params: any[] = []): Promise<any[]> => {
  return new Promise((resolve, reject) => {
    db.all(query, params, (err, rows) => {
      if (err) reject(err)
      else resolve(rows)
    })
  })
}

// Helper function to get a single row
export const dbGet = (query: string, params: any[] = []): Promise<any> => {
  return new Promise((resolve, reject) => {
    db.get(query, params, (err, row) => {
      if (err) reject(err)
      else resolve(row)
    })
  })
}

// --- Table Initialization ---
async function initializeTables() {
  try {
    // Enable foreign keys
    await dbRun('PRAGMA foreign_keys = ON;')

    // Teams table (needs to be created first for FKs)
    await dbRun(`
      CREATE TABLE IF NOT EXISTS teams (
        _id TEXT PRIMARY KEY,
        name TEXT,
        country TEXT,
        shortName TEXT,
        logo TEXT,
        extra TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        created_by TEXT,
        updated_by TEXT,
        deleted_at TEXT,
        version INTEGER DEFAULT 1
      )
    `)

    // Matches table
    await dbRun(`
      CREATE TABLE IF NOT EXISTS matches (
        id TEXT PRIMARY KEY,
        current INTEGER DEFAULT 0,
        left_id TEXT,
        left_wins INTEGER DEFAULT 0,
        right_id TEXT,
        right_wins INTEGER DEFAULT 0,
        matchType TEXT CHECK (matchType IN ('bo1', 'bo2', 'bo3', 'bo5')),
        vetos TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        created_by TEXT,
        updated_by TEXT,
        deleted_at TEXT,
        version INTEGER DEFAULT 1,
        FOREIGN KEY (left_id) REFERENCES teams(_id) ON DELETE SET NULL,
        FOREIGN KEY (right_id) REFERENCES teams(_id) ON DELETE SET NULL
      )
    `)

    // Ensure only one match can be marked as current at a time
    await dbRun(`
      CREATE UNIQUE INDEX IF NOT EXISTS idx_one_current_match 
      ON matches (current) 
      WHERE current = 1
    `)

    // Players table
    await dbRun(`
      CREATE TABLE IF NOT EXISTS players (
        _id TEXT PRIMARY KEY,
        firstName TEXT,
        lastName TEXT,
        username TEXT,
        avatar TEXT,
        country TEXT,
        steamid TEXT,
        team TEXT,
        isCoach INTEGER DEFAULT 0,
        extra TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        created_by TEXT,
        updated_by TEXT,
        deleted_at TEXT,
        version INTEGER DEFAULT 1,
        FOREIGN KEY (team) REFERENCES teams(_id) ON DELETE SET NULL
      )
    `)

    // Ensure steamid uniqueness but allow nulls
    await dbRun(
      `CREATE UNIQUE INDEX IF NOT EXISTS idx_players_steamid ON players(steamid) WHERE steamid IS NOT NULL AND steamid != ''`
    )

    // Triggers: keep updated_at current on every UPDATE
    const updateTriggers: { table: string; pk: string }[] = [
      { table: 'teams', pk: '_id' },
      { table: 'players', pk: '_id' },
      { table: 'matches', pk: 'id' }
    ]
    for (const { table, pk } of updateTriggers) {
      await dbRun(`
        CREATE TRIGGER IF NOT EXISTS trg_${table}_updated_at
        AFTER UPDATE ON ${table}
        FOR EACH ROW
        WHEN NEW.version = OLD.version
        BEGIN
          UPDATE ${table} SET updated_at = CURRENT_TIMESTAMP, version = OLD.version + 1 WHERE ${pk} = NEW.${pk};
        END
      `)
    }

    // Settings table
    await dbRun(`
      CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
      )
    `)

    // Default settings
    await dbRun(`INSERT OR IGNORE INTO settings (key, value) VALUES ('autoSwitchSides', 'true')`)

    // Hud configs table: stores panel config per hud id
    await dbRun(`
      CREATE TABLE IF NOT EXISTS hud_configs (
        hud_id TEXT PRIMARY KEY,
        config_data TEXT NOT NULL DEFAULT '{}'
      )
    `)

    // Map results are an outbox: a network failure or app restart must not
    // erase a finished map before the website acknowledges it.
    await dbRun(`
      CREATE TABLE IF NOT EXISTS broadcast_outbox (
        result_id TEXT PRIMARY KEY,
        match_id INTEGER NOT NULL,
        payload TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
      )
    `)

    console.log('SQLite tables initialized successfully.')
  } catch (error) {
    console.error('Failed to initialize SQLite tables:', error)
  }
}
