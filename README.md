# India Disaster Intelligence — IIRS-ISRO

An internal multi-hazard situational-awareness dashboard for the IIRS-ISRO
Disaster Management Department. It aggregates official Indian disaster alerts,
correlates reports of the same event across agencies, and presents them on a
map with full provenance and a browsable history.

> **Not an official warning system.** This aggregates third-party feeds for
> situational awareness. Every event links back to its issuing agency. Refer to
> IMD, NDMA and CWC for authoritative alerts.

---

## Quick start

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt

# One-time: build the district gazetteer and state boundaries
.venv/Scripts/python.exe scripts/build_gazetteer.py

# Fetch live data (also backfills history from 1 Aug 2026)
.venv/Scripts/python.exe -m backend.pipeline

# Serve
.venv/Scripts/python.exe -m uvicorn backend.main:app --port 8000
```

Then open <http://127.0.0.1:8000>.

On Windows, set `PYTHONIOENCODING=utf-8` before running anything that prints
alert text — the console's default cp1252 codec cannot render the Hindi,
Telugu, Odia and Marathi alerts these feeds carry.

---

## Data sources

All V1 sources are **open and require no credentials**.

| Source | Tier | Provides | Status |
| --- | --- | --- | --- |
| **NDMA SACHET** | Official | CAP 1.2 alerts from IMD regional offices, CWC, INCOIS and state SDMAs | Live |
| **USGS FDSN** | Official | Earthquakes across the subcontinent, full history | Live |
| **GDACS** | Modelled | Global multi-hazard cross-check (GLOFAS floods, cyclones) | Live |
| **News RSS** | Reported | Google News hazard queries + The Hindu, NDTV, TOI | Live |
| *IMD API* | Official | 28 endpoints incl. cyclone GeoJSON | **Needs key** — adapter stubbed |
| *MOSDAC* | Official | Satellite products | **Needs privileged access** — deferred |

**SACHET is the backbone.** It carries IMD and CWC content inside its CAP feed,
so `api.imd.gov.in` returning HTTP 401 without a key does not block V1.

Two access items are worth starting now, since both are paperwork rather than
engineering:

1. **Register at `api.imd.gov.in`** — self-service, unlocks cyclone tracks,
   wind-threat polygons and district warnings. `ingestion/imd.py` is stubbed
   and disabled until a key exists.
2. **Request MOSDAC privileged/NRT access** via an IIRS supervisor. General
   registered users receive data at **3-day latency**, which can never drive a
   daily dashboard. Only the privileged tier gets near-real-time.

---

## How it works

```
  SACHET / USGS / GDACS
            │
            ▼
    raw_documents            immutable landing table, written BEFORE parsing
            │
            ▼
     normalisation           source vocabulary -> one hazard taxonomy
            │
            ▼
      correlation            same hazard + district + time window = one event
            │
            ▼
   events + event_sources    one event, many corroborating agencies
            │
            ▼
      FastAPI  ->  dashboard
```

### Design decisions that matter

**Events, not API responses.** The unit of storage is a real-world occurrence.
When IMD, CWC and GDACS all describe one flood, staff see a single event with
three sources — not three rows.

**Raw documents are immutable and replayable.** Everything is landed before it
is parsed, so a parser bug can be fixed and history rebuilt with no network
access:

```bash
python -c "from backend.pipeline import replay; print(replay())"
```

**LGD district codes as the join key.** SACHET tags most alerts with
`<cap:geocode>LGD District Code`, and the gazetteer is built on the same codes,
so district resolution is exact rather than fuzzy string matching.

**...with a name-matching fallback, because not every office populates it.**
IMD Dehradun sends no geocodes at all — only free text such as
`"Chamoli, Bageshwar, Pithoragarh, Almora"` or `"Isolated places over Kumaun
region"`. Those alerts were being dropped entirely. District names are now
matched against the gazetteer, constrained to the issuing office's own state
(`IMD Dehradun` → Uttarakhand), because India has too many duplicate district
names — Hamirpur in UP and HP, Aurangabad in Bihar and Maharashtra — for an
unconstrained match to be safe. Region-level alerts that name no district are
pinned to the state centroid and flagged as state-level rather than being given
false district precision.

**News is a separate tier, never an official confirmation.** Articles enter at
tier 3 and display as `REPORTED` in their own "Related coverage" section, kept
visually distinct from confirming agencies. A headline is only kept if it can
be placed in India: unplaceable stories and neighbouring-country coverage
(Nepal's floods dominated the first run) are dropped. Only link, headline,
publisher and snippet are stored — never article text.

**Confidence is explainable, never a fabricated percentage.** A number like
"96%" implies a calibration that does not exist, and in a disaster tool someone
will eventually act on it. Instead:

| Tier | Meaning |
| --- | --- |
| `CORROBORATED` | Two or more independent official agencies agree |
| `OFFICIAL` | One Tier-1 agency (NDMA, IMD, CWC, NCS, INCOIS) |
| `MODELLED` | Global model output, not ground-confirmed |
| `REPORTED` | News only, no official confirmation |

**Events must be able to close.** Each hazard has an explicit TTL and CAP
expiry handling, and the reason an event closed is stored in
`resolution_rule`. Without this the dashboard fills with zombie floods.

**Silent failure is treated as a safety defect.** If a parser breaks, an empty
map is indistinguishable from a quiet day — and far more dangerous. The
`source_health` table drives per-feed freshness indicators in the header, and
alerts whose district code cannot be resolved are counted as "unmapped" rather
than being dropped.

**Boundaries are LGD / Survey of India derived, and the map uses no tile
layer.** Default OSM and Natural Earth tiles depict Jammu & Kashmir, Aksai
Chin and Arunachal Pradesh in ways that do not match the official Indian
position — unacceptable in an ISRO deliverable. Rendering vectors from our own
boundary file removes that risk entirely, and has the side benefit of working
on a network with no outbound internet access.

**All timestamps are UTC in storage, IST only at the UI edge.** Indian feeds
publish IST, USGS and GDACS publish UTC.

---

## Dashboard

- **Date range** with presets and a draggable per-day timeline histogram
- **Hazard filters** with live counts and a custom SVG icon per hazard,
  distinguishable by shape as well as colour
- **State selection** by dropdown or map click, which zooms to that state's
  bounds and filters every panel
- **Event detail** showing which agencies confirm an event, with deep links to
  each original record
- **Feed health** indicators, and a count of alerts that could not be mapped
- **Shareable URLs** — the current filter state is reflected in the query
  string

---

## Layout

```
backend/      FastAPI app, SQLite schema, ingestion pipeline
ingestion/    One module per source; all implement fetch() -> [Signal]
processing/   Hazard taxonomy, geo resolution, correlation and lifecycle
scripts/      build_gazetteer.py — regenerates data/ assets
data/         districts.json (709 LGD-keyed districts), states.geojson (37)
frontend/     Single-page dashboard: index.html, app.js, icons.js
database/     MIGRATION.md — porting notes for PostgreSQL + PostGIS
```

Adding a source means writing one `ingestion/<name>.py` that returns `Signal`
objects and adding a line to `jobs` in `backend/pipeline.py`.

---

## Known gaps

- **Sikkim and Ladakh districts have no LGD codes** in the gazetteer. The
  upstream boundary files have null properties for both, and guessing codes
  would silently place alerts in the wrong district — worse than not placing
  them. They are included by name and coordinates, so USGS and GDACS events
  still resolve there; SACHET alerts for those districts appear in the
  "unmapped" count. To close this, look the codes up at `lgdirectory.gov.in`
  and add them to `SUPPLEMENT` in `scripts/build_gazetteer.py`.
- **Newly created districts** (post-2011 reorganisations) are likewise absent
  and show in the unmapped count.
- **Historical depth is limited by the sources, not the code.** SACHET's RSS
  carries only current alerts with no archive, so history before first
  collection comes from USGS and GDACS alone and is sparse. It fills in densely
  going forward.
- **News geolocation is headline-only** and therefore conservative. A district
  name is accepted only when unique nationally or when a state is named in the
  same headline; Delhi's compass-named districts (North, South, Central) are
  ignored unless Delhi itself appears, since they match constantly in phrases
  like "South Korea".
- **News rarely correlates with official alerts.** Press reports and CAP
  warnings seldom share a district and time window, so most news forms its own
  `REPORTED` events. This is honest rather than forced.

## Roadmap

1. IMD API adapter once a key is issued
2. CWC flood forecasts and INCOIS ocean bulletins as first-class sources
3. NCS as the authoritative Indian earthquake source alongside USGS
4. NASA FIRMS active fire; FSI direct feed if a relationship can be arranged
5. PostgreSQL + PostGIS (see `database/MIGRATION.md`)
6. MOSDAC and Sentinel-1 SAR for flood-extent mapping, once access allows
