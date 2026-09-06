# Migrating SQLite -> PostgreSQL + PostGIS

The V1 schema in `backend/db.py` is written to port cleanly. Nothing in it is
SQLite-specific by accident; the choices below were made so this migration is
mechanical rather than a rewrite.

## Why SQLite first

PostGIS on Windows can consume an hour of setup before a single row is
ingested. V1's geographic needs are point markers plus a district lookup,
which SQLite serves fine. Postgres becomes worth it when we add polygon
storage (CAP alert areas, flood inundation footprints) and spatial joins.

## What changes

| SQLite | PostgreSQL |
| --- | --- |
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `BIGSERIAL PRIMARY KEY` |
| `TEXT` timestamps (UTC ISO-8601) | `TIMESTAMPTZ` |
| `lat REAL, lon REAL` | add `geom GEOGRAPHY(Point, 4326)` |
| `payload TEXT` (raw JSON/XML) | `JSONB` for JSON sources, `TEXT` for CAP XML |
| `INSERT OR IGNORE` | `INSERT ... ON CONFLICT DO NOTHING` |
| `ON CONFLICT DO UPDATE` (already used) | identical syntax |

## Steps

1. Create the database with PostGIS enabled:
   `CREATE EXTENSION postgis;`
2. Translate `SCHEMA` in `backend/db.py` using the table above, and add:
   ```sql
   ALTER TABLE events ADD COLUMN geom GEOGRAPHY(Point, 4326);
   CREATE INDEX idx_events_geom ON events USING GIST (geom);
   UPDATE events SET geom = ST_MakePoint(lon, lat)::geography
     WHERE lat IS NOT NULL;
   ```
3. Replace `connect()` with a psycopg connection pool. Every query in
   `backend/main.py` and `backend/pipeline.py` uses plain SQL with `?`
   placeholders - switch these to `%s`.
4. Re-run ingestion. **Do not migrate the `events` table itself**: run
   `python -c "from backend.pipeline import replay; replay()"` to rebuild
   every event from `raw_documents`. Only `raw_documents` needs copying,
   which is precisely why the landing table exists.

## Job queue

If ingestion outgrows a single process, Postgres can act as its own queue via
`SELECT ... FOR UPDATE SKIP LOCKED`. Redis and Celery are not required at this
scale and were deliberately left out.
