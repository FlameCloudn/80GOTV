CREATE TABLE IF NOT EXISTS demo_originals (
    demo_id INTEGER PRIMARY KEY,
    map_run_id INTEGER NOT NULL REFERENCES map_runs(map_run_id),
    storage_key TEXT NOT NULL UNIQUE,
    fingerprint TEXT NOT NULL UNIQUE,
    byte_count INTEGER NOT NULL CHECK (byte_count > 0),
    uploaded_by INTEGER NOT NULL,
    uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_demo_originals_run ON demo_originals(map_run_id);

CREATE TABLE IF NOT EXISTS demo_analyses (
    analysis_id INTEGER PRIMARY KEY,
    demo_id INTEGER NOT NULL REFERENCES demo_originals(demo_id),
    status TEXT NOT NULL CHECK (status IN ('running', 'ready', 'failed')),
    requested_by INTEGER NOT NULL,
    requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    parser_source TEXT NOT NULL,
    parser_build TEXT,
    candidate_json TEXT,
    error TEXT,
    CHECK ((status = 'ready') = (candidate_json IS NOT NULL)),
    CHECK ((status = 'failed') = (error IS NOT NULL)),
    CHECK ((status = 'running') = (finished_at IS NULL))
);

CREATE INDEX IF NOT EXISTS idx_demo_analyses_demo ON demo_analyses(demo_id, analysis_id);

CREATE TABLE IF NOT EXISTS demo_adoptions (
    adoption_id INTEGER PRIMARY KEY,
    analysis_id INTEGER NOT NULL REFERENCES demo_analyses(analysis_id),
    approval_key TEXT NOT NULL,
    actor INTEGER NOT NULL,
    reason TEXT NOT NULL,
    adopted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    result_revision INTEGER,
    download_default INTEGER NOT NULL CHECK (download_default IN (0, 1)),
    decisions_json TEXT NOT NULL,
    UNIQUE (analysis_id, approval_key),
    CHECK (download_default = 0 OR result_revision IS NOT NULL)
);
