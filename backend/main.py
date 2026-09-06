"""FastAPI application serving the dashboard and its data."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.db import connect, init_db, load_states_geojson, utcnow
from backend.pipeline import run as run_pipeline
from processing.taxonomy import HAZARD_LABELS

ROOT = pathlib.Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

app = FastAPI(title="IIRS-ISRO Disaster Intelligence", version="0.1")


@app.on_event("startup")
def _startup():
    init_db()


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


@app.get("/api/events")
def events(
    date_from: str = Query("", alias="from"),
    date_to: str = Query("", alias="to"),
    hazards: str = "",
    state: str = "",
    status: str = "",
):
    """Events as GeoJSON, filtered by date range, hazard type, state and status."""
    sql = ["SELECT * FROM events WHERE 1=1"]
    params: list = []

    # Overlap semantics: an event counts if it was active at any point in the
    # window, not only if it started inside it. A 3-week flood must show up in
    # a query for last Tuesday.
    if date_from:
        sql.append(
            "AND COALESCE(NULLIF(expires_at,''), NULLIF(last_updated,''), first_detected) >= ?"
        )
        params.append(date_from)
    if date_to:
        sql.append("AND first_detected <= ?")
        params.append(date_to + "T23:59:59+00:00")
    if hazards:
        picks = [h for h in hazards.split(",") if h]
        if picks:
            sql.append(f"AND hazard_type IN ({','.join('?' * len(picks))})")
            params.extend(picks)
    if state:
        sql.append("AND state = ?")
        params.append(state)
    if status:
        sql.append("AND status = ?")
        params.append(status)
    sql.append("ORDER BY first_detected DESC LIMIT 3000")

    with connect() as conn:
        rows = conn.execute(" ".join(sql), params).fetchall()
        ids = [r["id"] for r in rows]
        agencies: dict[int, list] = {i: [] for i in ids}
        if ids:
            marks = ",".join("?" * len(ids))
            for s in conn.execute(
                f"""SELECT event_id, source, agency, tier, url, published_at
                    FROM event_sources WHERE event_id IN ({marks})""",
                ids,
            ):
                agencies[s["event_id"]].append(dict(s))

    features = []
    for r in rows:
        if r["lat"] is None or r["lon"] is None:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
                "properties": {**dict(r), "sources": agencies.get(r["id"], [])},
            }
        )
    return {"type": "FeatureCollection", "features": features}


@app.get("/api/meta")
def meta():
    """Filter vocabulary, counts and feed health for the dashboard chrome."""
    with connect() as conn:
        hazards = conn.execute(
            "SELECT hazard_type h, COUNT(*) n FROM events GROUP BY h ORDER BY n DESC"
        ).fetchall()
        states = conn.execute(
            "SELECT state s, COUNT(*) n FROM events WHERE state<>'' GROUP BY s ORDER BY s"
        ).fetchall()
        # Every state/UT is offered in the filter, not only those with events,
        # so selecting a quiet state gives an explicit "nothing here" rather
        # than an empty dropdown.
        counts = {r["s"]: r["n"] for r in states}
        all_states = sorted(
            {f["properties"]["state"] for f in load_states_geojson()["features"]}
        )
        statuses = conn.execute(
            "SELECT status s, COUNT(*) n FROM events GROUP BY s"
        ).fetchall()
        health = conn.execute("SELECT * FROM source_health").fetchall()
        span = conn.execute(
            "SELECT MIN(first_detected) a, MAX(first_detected) b FROM events"
        ).fetchone()
        # Events whose LGD district code is not in the gazetteer (usually a
        # newly created district). Surfaced in the UI so the gap is visible
        # rather than silently dropping alerts off the map.
        unlocated = conn.execute(
            "SELECT COUNT(*) n FROM events WHERE lat IS NULL"
        ).fetchone()["n"]
        daily = conn.execute(
            """SELECT substr(first_detected,1,10) d, COUNT(*) n
               FROM events GROUP BY d ORDER BY d"""
        ).fetchall()

    return {
        "hazards": [
            {"key": h["h"], "label": HAZARD_LABELS.get(h["h"], h["h"]), "count": h["n"]}
            for h in hazards
        ],
        "states": [{"s": n, "n": counts.get(n, 0)} for n in all_states],
        "statuses": {s["s"]: s["n"] for s in statuses},
        "health": [dict(h) for h in health],
        "span": {"from": span["a"], "to": span["b"]},
        "daily": [dict(d) for d in daily],
        "unlocated": unlocated,
        "server_time": utcnow(),
    }


@app.get("/api/states.geojson")
def states_geojson():
    return JSONResponse(load_states_geojson())


@app.post("/api/refresh")
def refresh(sachet_limit: int | None = None):
    return run_pipeline(sachet_limit=sachet_limit)


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
