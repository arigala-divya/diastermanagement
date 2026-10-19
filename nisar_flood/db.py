"""SQLite storage, following the conventions of backend/db.py.

  * scenes is written when a scene is found, BEFORE any processing, so a
    failed crop is visible (status FAILED + error) rather than silently lost.
  * every timestamp is UTC ISO-8601.
  * idempotent: UNIQUE keys mean re-running the pipeline never duplicates.
"""

import sqlite3

from nisar_flood.settings import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS scenes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    hotspot_id    TEXT NOT NULL,
    scene_id      TEXT NOT NULL,      -- acquisition key: provider ids joined by '+'
    provider      TEXT NOT NULL,
    acquired_at   TEXT NOT NULL,
    grp           TEXT NOT NULL,      -- track (+frame when single-frame), e.g. T040
    node          TEXT,
    meta          TEXT,               -- provider metadata, JSON
    status        TEXT NOT NULL,      -- PENDING | CROPPED | FAILED | INSUFFICIENT
    error         TEXT,
    crop_path     TEXT,
    valid_frac    REAL,
    water_frac    REAL,
    found_at      TEXT NOT NULL,
    processed_at  TEXT,
    UNIQUE (hotspot_id, scene_id)
);
CREATE INDEX IF NOT EXISTS idx_scenes_hs ON scenes (hotspot_id, grp, acquired_at);

CREATE TABLE IF NOT EXISTS analyses (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    hotspot_id         TEXT NOT NULL,
    scene_id           TEXT NOT NULL,
    baseline_scene_id  TEXT NOT NULL,
    prev_scene_id      TEXT,
    grp                TEXT NOT NULL,
    acquired_at        TEXT NOT NULL,
    baseline_at        TEXT NOT NULL,
    detector           TEXT NOT NULL,
    threshold_db       REAL,
    valid_km2          REAL,
    water_ref_km2      REAL,
    water_new_km2      REAL,
    new_water_km2      REAL,
    receded_km2        REAL,
    increase_pct       REAL,
    largest_patch_km2  REAL,
    delta_prev_km2     REAL,          -- water extent change since previous pass
    level              TEXT NOT NULL, -- NORMAL | WATCH | ALERT
    reasons            TEXT,          -- JSON list
    notes              TEXT,          -- JSON list
    render_before      TEXT,
    render_after       TEXT,
    render_change      TEXT,
    corners_ll         TEXT,          -- JSON [[lat, lon] x4] for the map overlay
    created_at         TEXT NOT NULL,
    UNIQUE (hotspot_id, scene_id, baseline_scene_id, detector)
);
CREATE INDEX IF NOT EXISTS idx_analyses_hs ON analyses (hotspot_id, acquired_at);

-- One row per flood episode: opened by the first WATCH/ALERT pass, extended
-- by consecutive WATCH/ALERT passes, closed by the first pass below threshold.
CREATE TABLE IF NOT EXISTS alerts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    hotspot_id        TEXT NOT NULL,
    scene_id          TEXT NOT NULL,  -- pass that opened the episode
    last_scene_id     TEXT NOT NULL,  -- most recent pass in the episode
    level             TEXT NOT NULL,  -- peak level reached: WATCH | ALERT
    current_level     TEXT NOT NULL,  -- level on the most recent pass
    status            TEXT NOT NULL,  -- ACTIVE | RESOLVED
    headline          TEXT NOT NULL,
    new_water_km2     REAL,           -- on the most recent pass
    peak_new_water_km2 REAL,
    passes            INTEGER NOT NULL,
    acquired_at       TEXT NOT NULL,  -- first pass time
    last_acquired_at  TEXT NOT NULL,
    raised_at         TEXT NOT NULL,
    resolved_at       TEXT,
    resolution_reason TEXT,           -- why it closed; auditable
    UNIQUE (hotspot_id, scene_id)
);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts (status, raised_at);

CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    summary      TEXT
);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
