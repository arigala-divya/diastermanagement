"""Ingestion pipeline: fetch -> land raw -> correlate -> events.

Order matters. Raw documents are written before anything is parsed, so a
parser bug can be fixed and the whole normalisation replayed from storage
without re-hitting the sources (see replay()).
"""

import json
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from backend.db import connect, init_db, load_districts, utcnow
from ingestion import gdacs, sachet, usgs
from ingestion.base import Signal, content_hash, log, new_client
from processing.correlate import (
    confidence_for,
    correlation_key,
    max_severity,
    resolve_status,
)

# Sources are declared here so adding one is a single-line change.
# IMD and MOSDAC adapters are intentionally absent until credentials exist.
BACKFILL_FROM = "2026-08-01"


def _record_health(conn, source, ok, count, error=""):
    conn.execute(
        """
        INSERT INTO source_health (source, last_attempt, last_success, last_error, items_last_run)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(source) DO UPDATE SET
            last_attempt   = excluded.last_attempt,
            last_success   = COALESCE(excluded.last_success, source_health.last_success),
            last_error     = excluded.last_error,
            items_last_run = excluded.items_last_run
        """,
        (source, utcnow(), utcnow() if ok else None, error, count),
    )


def _land_raw(conn, signal: Signal):
    """Insert into the immutable landing table; return its id.

    Look up before inserting: many signals (one per district) share a single
    CAP document, and INSERT OR IGNORE leaves lastrowid stale when it ignores.
    """
    payload = signal.raw or signal.headline
    digest = content_hash(payload)
    uid = signal.raw_uid or signal.source_uid

    row = conn.execute(
        "SELECT id FROM raw_documents WHERE source=? AND source_uid=? AND content_hash=?",
        (signal.source, uid, digest),
    ).fetchone()
    if row:
        return row["id"]

    cur = conn.execute(
        """INSERT INTO raw_documents
           (source, source_uid, url, payload, content_hash, retrieved_at)
           VALUES (?,?,?,?,?,?)""",
        (signal.source, uid, signal.url, payload, digest, utcnow()),
    )
    return cur.lastrowid


def _upsert_event(conn, signal: Signal, raw_id):
    key = correlation_key(signal)
    row = conn.execute("SELECT * FROM events WHERE correlation_key=?", (key,)).fetchone()
    stamp = signal.published_at or utcnow()

    if row is None:
        cur = conn.execute(
            """INSERT INTO events
               (correlation_key, hazard_type, headline, severity, status, confidence,
                state, district, lgd_district, lat, lon,
                first_detected, last_updated, starts_at, expires_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (key, signal.hazard_type, signal.headline, signal.severity, "ACTIVE",
             "OFFICIAL", signal.state, signal.district, signal.lgd_district,
             signal.lat, signal.lon, stamp, stamp, signal.starts_at, signal.expires_at),
        )
        event_id = cur.lastrowid
    else:
        event_id = row["id"]
        conn.execute(
            """UPDATE events SET
                 severity     = ?,
                 last_updated = MAX(last_updated, ?),
                 expires_at   = COALESCE(NULLIF(?, ''), expires_at),
                 headline     = COALESCE(NULLIF(headline, ''), ?)
               WHERE id = ?""",
            (max_severity([row["severity"], signal.severity]), stamp,
             signal.expires_at, signal.headline, event_id),
        )

    conn.execute(
        """INSERT OR IGNORE INTO event_sources
           (event_id, raw_id, source, agency, tier, url, headline, published_at, licence)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (event_id, raw_id, signal.source, signal.agency, signal.tier,
         signal.url, signal.headline, signal.published_at, signal.licence),
    )
    return event_id


def _refresh_derived(conn):
    """Recompute confidence and lifecycle status for every event."""
    for ev in conn.execute("SELECT * FROM events").fetchall():
        srcs = conn.execute(
            "SELECT tier, agency FROM event_sources WHERE event_id=?", (ev["id"],)
        ).fetchall()
        conf = confidence_for({s["tier"] for s in srcs}, {s["agency"] for s in srcs})
        status, rule = resolve_status(
            ev["hazard_type"], ev["last_updated"], ev["expires_at"] or ""
        )
        conn.execute(
            """UPDATE events SET confidence=?, status=?, resolution_rule=?,
                                 resolved_at = CASE WHEN ?='RESOLVED'
                                     THEN COALESCE(resolved_at, ?) ELSE NULL END
               WHERE id=?""",
            (conf, status, rule, status, utcnow(), ev["id"]),
        )


def ingest_signals(conn, signals):
    for s in signals:
        raw_id = _land_raw(conn, s)
        _upsert_event(conn, s, raw_id)


def run(sachet_limit=None, backfill_from=BACKFILL_FROM):
    """Fetch every enabled source, land it, correlate it. Returns a report."""
    init_db()
    districts = load_districts()
    report = {}

    with new_client() as client, connect() as conn:
        jobs = [
            ("SACHET", lambda: sachet.fetch(client, districts, limit=sachet_limit)),
            ("GDACS", lambda: gdacs.fetch(client, districts, backfill_from)),
            ("USGS", lambda: usgs.fetch(client, districts, backfill_from)),
        ]
        for name, job in jobs:
            try:
                signals = job()
                ingest_signals(conn, signals)
                _record_health(conn, name, True, len(signals))
                report[name] = {"ok": True, "signals": len(signals)}
                log(f"  {name}: {len(signals)} signals")
            except Exception as exc:  # noqa: BLE001 - one dead feed must not stop the rest
                _record_health(conn, name, False, 0, f"{type(exc).__name__}: {exc}")
                report[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
                log(f"  {name}: FAILED {type(exc).__name__}: {exc}")

        _refresh_derived(conn)
        conn.commit()
        report["events"] = conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]
        report["raw_documents"] = conn.execute(
            "SELECT COUNT(*) c FROM raw_documents"
        ).fetchone()["c"]
    return report


def replay():
    """Rebuild every event from raw_documents alone.

    This is the proof that the landing table works: drop all derived state and
    reconstruct it without touching the network.
    """
    districts = load_districts()
    with connect() as conn:
        conn.execute("DELETE FROM event_sources")
        conn.execute("DELETE FROM events")
        rows = conn.execute("SELECT * FROM raw_documents ORDER BY id").fetchall()
        for row in rows:
            signals = _signals_from_raw(row, districts)
            ingest_signals(conn, signals)
        _refresh_derived(conn)
        conn.commit()
        return conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]


def _signals_from_raw(row, districts):
    """Re-derive signals from one stored raw document, for every source."""
    source, payload = row["source"], row["payload"]
    if source == "SACHET":
        return sachet.signals_from_cap(payload, row["url"] or "", districts)
    try:
        feat = json.loads(payload)
    except (ValueError, TypeError):
        return []
    builder = {"USGS": usgs.signal_from_feature, "GDACS": gdacs.signal_from_feature}.get(source)
    if not builder:
        return []
    sig = builder(feat, districts)
    return [sig] if sig else []


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    print(run(sachet_limit=limit))
