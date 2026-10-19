"""FastAPI app for the NISAR flood monitor.

    uvicorn nisar_flood.api:app --port 8001
"""

import json
import threading

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from nisar_flood import settings
from nisar_flood.db import connect, init_db
from nisar_flood.hotspots import load_hotspots
from nisar_flood.pipeline import RunInProgress, run as run_pipeline, utcnow

app = FastAPI(title="NISAR Flood Monitor", version="0.1")
_run_lock = threading.Lock()
_run_state: dict = {"running": False, "last": None, "error": None, "error_at": None}


@app.on_event("startup")
def _startup():
    init_db()


def _analysis(row) -> dict:
    d = dict(row)
    for k in ("reasons", "notes", "corners_ll"):
        d[k] = json.loads(d[k]) if d.get(k) else []
    return d


@app.get("/")
def index():
    return FileResponse(settings.FRONTEND / "index.html")


@app.get("/api/hotspots")
def hotspots():
    out = []
    with connect() as conn:
        for h in load_hotspots():
            latest = conn.execute(
                """SELECT * FROM analyses WHERE hotspot_id=?
                   ORDER BY acquired_at DESC LIMIT 1""", (h.id,)).fetchone()
            counts = conn.execute(
                """SELECT COUNT(*) n, SUM(status='CROPPED') ok, MAX(acquired_at) last
                   FROM scenes WHERE hotspot_id=?""", (h.id,)).fetchone()
            active = conn.execute(
                """SELECT level, headline, acquired_at FROM alerts
                   WHERE hotspot_id=? AND status='ACTIVE'
                   ORDER BY acquired_at DESC LIMIT 1""", (h.id,)).fetchone()
            out.append({
                **h.as_dict(),
                "status": latest["level"] if latest else ("NO_DATA" if not counts["ok"] else "BASELINE"),
                "latest": _analysis(latest) if latest else None,
                "scenes": counts["n"], "scenes_ok": counts["ok"] or 0,
                "last_scene_at": counts["last"],
                "active_alert": dict(active) if active else None,
            })
    return out


@app.get("/api/hotspots/{hid}")
def hotspot(hid: str):
    h = next((h for h in load_hotspots() if h.id == hid), None)
    if not h:
        raise HTTPException(404, "unknown hotspot")
    with connect() as conn:
        scenes = [dict(r) for r in conn.execute(
            """SELECT scene_id, provider, acquired_at, grp, node, status, error,
               valid_frac, water_frac FROM scenes WHERE hotspot_id=?
               ORDER BY acquired_at""", (hid,))]
        analyses = [_analysis(r) for r in conn.execute(
            "SELECT * FROM analyses WHERE hotspot_id=? ORDER BY acquired_at", (hid,))]
        alerts = [dict(r) for r in conn.execute(
            "SELECT * FROM alerts WHERE hotspot_id=? ORDER BY acquired_at DESC", (hid,))]
    return {"hotspot": h.as_dict(), "scenes": scenes, "analyses": analyses, "alerts": alerts}


@app.get("/api/alerts")
def alerts(status: str | None = None, limit: int = 200):
    q = "SELECT * FROM alerts"
    args: list = []
    if status:
        q += " WHERE status=?"
        args.append(status.upper())
    q += " ORDER BY status='ACTIVE' DESC, acquired_at DESC LIMIT ?"
    args.append(limit)
    with connect() as conn:
        return [dict(r) for r in conn.execute(q, args)]


@app.get("/api/status")
def status():
    with connect() as conn:
        last = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    last_done = last["finished_at"] if last else None
    error = _run_state["error"]
    # An error from the UI's run is stale once any later run (e.g. the CLI) succeeded.
    if error and last_done and _run_state["error_at"] and last_done > _run_state["error_at"]:
        error = None
    return {
        "running": _run_state["running"],
        "error": error,
        "last_run": {**dict(last), "summary": json.loads(last["summary"] or "{}")} if last else None,
        "server_time": utcnow(),
        "credentials_configured": bool(settings.BHOONIDHI_USER and settings.BHOONIDHI_PASS),
    }


def _bg_run(hotspot_ids):
    try:
        _run_state["last"] = run_pipeline(hotspot_ids)
        _run_state["error"] = None
    except RunInProgress as e:
        _run_state["error"], _run_state["error_at"] = f"Not started: {e}", utcnow()
    except Exception as e:  # noqa: BLE001 - surfaced through /api/status
        _run_state["error"], _run_state["error_at"] = f"{type(e).__name__}: {e}", utcnow()
    finally:
        _run_state["running"] = False
        _run_lock.release()


@app.post("/api/refresh")
def refresh(hotspot: str | None = None):
    """Start a pipeline run in the background (a full run takes many minutes)."""
    if not _run_lock.acquire(blocking=False):
        return {"started": False, "reason": "a run is already in progress"}
    _run_state["running"] = True
    threading.Thread(target=_bg_run, args=([hotspot] if hotspot else None,), daemon=True).start()
    return {"started": True}


app.mount("/renders", StaticFiles(directory=settings.RENDERS), name="renders")
app.mount("/static", StaticFiles(directory=settings.FRONTEND), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8001)
