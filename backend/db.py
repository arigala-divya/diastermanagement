"""SQLite storage layer.

Schema is written to be portable to PostgreSQL + PostGIS: no SQLite-specific
types, geometry held as plain lat/lon columns, and JSON kept in TEXT columns.
See database/MIGRATION.md for the porting notes.

Design rules that matter:
  * raw_documents is an immutable landing table written BEFORE any parsing,
    so the whole normalisation pipeline can be replayed after a parser fix.
  * every timestamp is UTC ISO-8601. IST is applied only at the UI edge.
  * ingestion is idempotent via UNIQUE(source, source_uid) and content hash.
"""

import json
import pathlib
import sqlite3
from datetime import datetime, timezone

DB_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "disasters.db"

SCHEMA = """
-- Immutable landing zone. Never updated, only inserted. Enables full replay.
CREATE TABLE IF NOT EXISTS raw_documents (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,
    source_uid   TEXT NOT NULL,
    url          TEXT,
    payload      TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    UNIQUE (source, source_uid, content_hash)
);
CREATE INDEX IF NOT EXISTS idx_raw_source ON raw_documents (source, retrieved_at);

-- One row per real-world hazard occurrence, correlated across sources.
CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    correlation_key TEXT NOT NULL UNIQUE,
    hazard_type     TEXT NOT NULL,
    headline        TEXT,
    severity        TEXT,            -- INFO | MINOR | MODERATE | SEVERE | EXTREME
    status          TEXT NOT NULL,   -- ACTIVE | WATCH | RESOLVED
    confidence      TEXT NOT NULL,   -- OFFICIAL | CORROBORATED | REPORTED | MODELLED
    state           TEXT,
    district        TEXT,
    lgd_district    INTEGER,
    lat             REAL,
    lon             REAL,
    first_detected  TEXT NOT NULL,
    last_updated    TEXT NOT NULL,
    starts_at       TEXT,
    expires_at      TEXT,
    resolved_at     TEXT,
    resolution_rule TEXT             -- why it closed; auditable
);
CREATE INDEX IF NOT EXISTS idx_events_time   ON events (first_detected);
CREATE INDEX IF NOT EXISTS idx_events_state  ON events (state);
CREATE INDEX IF NOT EXISTS idx_events_hazard ON events (hazard_type);

-- Provenance: which agency, via which raw document, said what about an event.
CREATE TABLE IF NOT EXISTS event_sources (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     INTEGER NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    raw_id       INTEGER REFERENCES raw_documents (id),
    source       TEXT NOT NULL,      -- SACHET | GDACS | USGS | NEWS
    agency       TEXT,               -- e.g. "IMD Ranchi", "CWC"
    tier         INTEGER NOT NULL,   -- 1 official, 2 modelled, 3 reported
    url          TEXT,
    headline     TEXT,
    published_at TEXT,
    licence      TEXT,
    UNIQUE (event_id, source, url)
);
CREATE INDEX IF NOT EXISTS idx_evsrc_event ON event_sources (event_id);

-- Link + headline + snippet only. Never full article text (copyright).
CREATE TABLE IF NOT EXISTS news_articles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    url          TEXT NOT NULL UNIQUE,
    headline     TEXT NOT NULL,
    snippet      TEXT,
    publisher    TEXT,
    published_at TEXT,
    hazard_type  TEXT,
    state        TEXT,
    district     TEXT,
    event_id     INTEGER REFERENCES events (id)
);

-- Feed liveness. A broken parser must look different from a quiet day.
CREATE TABLE IF NOT EXISTS source_health (
    source            TEXT PRIMARY KEY,
    last_attempt      TEXT,
    last_success      TEXT,
    last_error        TEXT,
    items_last_run    INTEGER DEFAULT 0,
    stale_after_mins  INTEGER DEFAULT 180
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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


def load_districts() -> dict:
    path = DB_PATH.parent / "districts.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_states_geojson() -> dict:
    path = DB_PATH.parent / "states.geojson"
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    init_db()
    print(f"initialised {DB_PATH}")
