"""NISAR flood monitoring pipeline.

    python -m nisar_flood.pipeline [--hotspot ID ...] [--max-per-track N]
                                   [--workers N] [--provider bhoonidhi|manual]

Stages, all idempotent:
  1. search    find online GCOV scenes over each hotspot AOI
  2. register  one `scenes` row per acquisition (a pass on one track; frames
               from the same pass are mosaicked), written before any work
  3. crop      open each remote product once, cut out every hotspot it
               covers; runs in worker processes
  4. analyse   per hotspot and track: pick the driest scene as baseline,
               run change detection on every other scene, render PNGs
  5. alert     replay analyses in time order: WATCH/ALERT raise an alert,
               a later below-threshold pass resolves it
"""

import argparse
import os
import hashlib
import json
import shutil
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime, timezone

import numpy as np

from ingestion.base import log
from nisar_flood import settings
from nisar_flood.acquisition.base import SceneRef, point_in_ring
from nisar_flood.alerts.rules import evaluate
from nisar_flood.db import connect, init_db
from nisar_flood.detection.classical import ClassicalDetector, group_threshold, water_fraction
from nisar_flood.hotspots import Hotspot, load_hotspots
from nisar_flood.processing.preprocess import Crop, crop_aoi
from nisar_flood.render import backscatter_png, change_png

PASS_GAP_S = 300   # frames of one pass are acquired seconds apart


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RunLock:
    """Exclusive, cross-process pipeline lock (CLI vs the UI's refresh button).

    An OS-level file lock, so it is released automatically if the holder
    crashes; no stale lock files to clean up.
    """

    def __init__(self):
        self.path = settings.DATA / "pipeline.lock"
        self.fh = None

    def __enter__(self):
        self.fh = open(self.path, "a+")
        try:
            if os.name == "nt":
                import msvcrt
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.fh.close()
            raise RunInProgress("another pipeline run is already in progress")
        return self

    def __exit__(self, *exc):
        try:
            if os.name == "nt":
                import msvcrt
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self.fh.close()


class RunInProgress(RuntimeError):
    pass


def get_provider(name: str):
    if name == "manual":
        from nisar_flood.acquisition.manual import ManualProvider
        return ManualProvider()
    from nisar_flood.acquisition.bhoonidhi import BhoonidhiProvider
    return BhoonidhiProvider()


def intersects(footprint: list, bbox: tuple) -> bool:
    if not footprint:
        return True
    w, s, e, n = bbox
    pts = ((w, s), (w, n), (e, s), (e, n), ((w + e) / 2, (s + n) / 2))
    if any(point_in_ring(x, y, footprint) for x, y in pts):
        return True
    return any(w <= x <= e and s <= y <= n for x, y in footprint)


# --------------------------------------------------------------------------
# 1-2. search and register
# --------------------------------------------------------------------------

def acquisitions(scenes: list[SceneRef]) -> list[dict]:
    """Group frames of the same pass into one acquisition.

    The comparison group is track + direction + product variant. The variant
    (e.g. 3700 vs 2500 in Bhoonidhi ids) can alternate pass to pass on one
    track, and variants differ radiometrically by several dB: mixing them
    reads as the whole scene darkening, i.e. a false flood.
    """
    by_track = defaultdict(list)
    for s in scenes:
        by_track[(s.track, s.node, s.meta.get("variant", ""))].append(s)
    out = []
    for (track, node, variant), items in by_track.items():
        items.sort(key=lambda s: s.datetime)
        cur: list[SceneRef] = []
        for s in items:
            if cur and (datetime.fromisoformat(s.datetime) -
                        datetime.fromisoformat(cur[0].datetime)).total_seconds() > PASS_GAP_S:
                out.append(cur)
                cur = []
            cur.append(s)
        if cur:
            out.append(cur)
    result = []
    for frames in out:
        f0 = frames[0]
        grp = f"T{f0.track:03d}{(f0.node or '?')[0]}"
        if f0.meta.get("variant"):
            grp += f"-{f0.meta['variant']}"
        t = datetime.fromisoformat(f0.datetime).strftime("%Y%m%dT%H%M")
        result.append({
            "scene_id": f"{grp}_{t}", "grp": grp, "acquired_at": f0.datetime,
            "node": f0.node, "provider": f0.provider, "frames": frames,
        })
    return sorted(result, key=lambda a: a["acquired_at"])


def register(conn, hs: Hotspot, acqs: list[dict]) -> None:
    for a in acqs:
        meta = {"frames": [{"id": f.scene_id, "frame": f.frame, "location": f.location,
                            **f.meta} for f in a["frames"]]}
        conn.execute(
            """INSERT OR IGNORE INTO scenes (hotspot_id, scene_id, provider, acquired_at,
               grp, node, meta, status, found_at) VALUES (?,?,?,?,?,?,?, 'PENDING', ?)""",
            (hs.id, a["scene_id"], a["provider"], a["acquired_at"], a["grp"], a["node"],
             json.dumps(meta), utcnow()),
        )


# --------------------------------------------------------------------------
# 3. crop (worker processes)
# --------------------------------------------------------------------------

def frame_crop_path(hotspot_id: str, frame_id: str):
    d = settings.CROPS / hotspot_id / "frames"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{hashlib.sha1(frame_id.encode()).hexdigest()[:16]}.npz"


def crop_worker(provider_name: str, frame: dict, targets: list[tuple[str, tuple]]) -> dict:
    """Open one product and crop it for each (hotspot_id, bbox). Runs in a subprocess."""
    t0 = time.time()
    provider = get_provider(provider_name)
    ref = SceneRef(provider=provider_name, scene_id=frame["id"], datetime="",
                   track=0, frame=frame.get("frame", 0), location=frame.get("location", ""))
    done, errors = [], {}
    try:
        with provider.open(ref) as f:
            remote = getattr(provider, "last_remote", None)
            for hid, bbox in targets:
                try:
                    c = crop_aoi(f, tuple(bbox), prefetch=remote.prefetch if remote else None)
                    c.save(frame_crop_path(hid, frame["id"]))
                    done.append(hid)
                except Exception as e:  # noqa: BLE001 - one bad AOI must not sink the rest
                    errors[hid] = f"{type(e).__name__}: {e}"
    except Exception as e:  # noqa: BLE001
        for hid, _ in targets:
            errors[hid] = f"{type(e).__name__}: {e}"
    remote = getattr(provider, "last_remote", None)
    return {"frame": frame["id"], "done": done, "errors": errors,
            "secs": round(time.time() - t0, 1),
            "mb": round(remote.bytes / 1e6, 1) if remote else 0}


def merge_frames(paths: list) -> Crop | None:
    crops = [Crop.load(p) for p in paths if p.exists()]
    if not crops:
        return None
    crops.sort(key=lambda c: -c.valid_fraction)
    base = crops[0]
    for c in crops[1:]:
        if c.epsg != base.epsg or c.hh.shape != base.hh.shape:
            continue
        fill = ~np.isfinite(base.hh)
        base.hh[fill] = c.hh[fill]
        if base.hv is not None and c.hv is not None:
            base.hv[fill] = c.hv[fill]
    return base


def assemble(conn, hs: Hotspot, rows: list, errors: dict) -> None:
    """Mosaic frame crops into one crop per acquisition and grade its coverage."""
    for r in rows:
        frames = json.loads(r["meta"])["frames"]
        errs = [errors[(hs.id, fr["id"])] for fr in frames if (hs.id, fr["id"]) in errors]
        paths = [frame_crop_path(hs.id, fr["id"]) for fr in frames]
        if errs and not any(p.exists() for p in paths):
            conn.execute("UPDATE scenes SET status='FAILED', error=?, processed_at=? WHERE id=?",
                         (errs[0][:500], utcnow(), r["id"]))
            continue
        if not all(p.exists() for p in paths) and not errs:
            continue
        crop = merge_frames(paths)
        out = settings.CROPS / hs.id / f"{r['scene_id']}.npz"
        crop.save(out)
        vf = crop.valid_fraction
        status = "CROPPED" if vf >= settings.MIN_VALID_FRACTION else "INSUFFICIENT"
        wf = water_fraction(crop) if status == "CROPPED" else None
        conn.execute(
            """UPDATE scenes SET status=?, crop_path=?, valid_frac=?, water_frac=?,
               error=NULL, processed_at=? WHERE id=?""",
            (status, str(out.relative_to(settings.DATA)), vf, wf, utcnow(), r["id"]),
        )
    conn.commit()


def run_crops(conn, hotspots: dict[str, Hotspot], provider_name: str, workers: int,
              on_ready) -> dict:
    """Crop all pending scenes. `on_ready(hs)` fires as soon as every product a
    hotspot needs is done, so results appear hotspot by hotspot rather than
    only at the end of a multi-hour backfill. Jobs are submitted in hotspot
    order to make that early finish real."""
    rows = conn.execute("SELECT * FROM scenes WHERE status = 'PENDING'").fetchall()
    rows_by_hs: dict[str, list] = defaultdict(list)
    for r in rows:
        if r["hotspot_id"] in hotspots:
            rows_by_hs[r["hotspot_id"]].append(r)

    jobs: dict[str, dict] = {}
    needs: dict[str, set] = {hid: set() for hid in hotspots}
    for hid in hotspots:                       # hotspot order = submit order
        hs = hotspots[hid]
        for r in rows_by_hs[hid]:
            for fr in json.loads(r["meta"])["frames"]:
                if frame_crop_path(hid, fr["id"]).exists():
                    continue
                job = jobs.setdefault(fr["id"], {"frame": fr, "targets": []})
                if hid not in [t[0] for t in job["targets"]]:
                    job["targets"].append((hid, hs.bbox))
                needs[hid].add(fr["id"])

    stats = {"frames": len(jobs), "ok": 0, "failed": 0, "mb": 0.0}
    errors: dict[tuple[str, str], str] = {}
    done_hs: set[str] = set()

    def finish(hid):
        assemble(conn, hotspots[hid], rows_by_hs[hid], errors)
        on_ready(hotspots[hid])
        done_hs.add(hid)

    for hid in hotspots:                       # nothing left to fetch
        if not needs[hid]:
            finish(hid)

    if jobs:
        if provider_name == "bhoonidhi":
            get_provider("bhoonidhi").session.token()   # one login before workers fan out
        log(f"crop: {len(jobs)} product(s) with {workers} worker(s)")
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(crop_worker, provider_name, j["frame"], j["targets"]) for j in jobs.values()]
            for i, fut in enumerate(as_completed(futs), 1):
                res = fut.result()
                stats["mb"] += res["mb"]
                for hid, err in res["errors"].items():
                    errors[(hid, res["frame"])] = err
                stats["ok" if not res["errors"] else "failed"] += 1
                log(f"  [{i}/{len(futs)}] {res['frame'][:60]} {res['secs']}s {res['mb']}MB"
                    + (f" ERR {list(res['errors'].values())[0][:120]}" if res["errors"] else ""))
                for hid in hotspots:
                    needs[hid].discard(res["frame"])
                    if not needs[hid] and hid not in done_hs:
                        finish(hid)
                        log(f"  -> {hid} analysed")
    return stats


# --------------------------------------------------------------------------
# 4. analyse
# --------------------------------------------------------------------------

def choose_baseline(rows: list, months: list[int], wet: dict):
    """Driest scene (by `wet`: scene_id -> water fraction under the group
    threshold), preferring dry-season months when any exist."""
    dry = [r for r in rows if int(r["acquired_at"][5:7]) in months]
    pool = dry or rows
    return min(pool, key=lambda r: (wet[r["scene_id"]], r["acquired_at"]))


def analyse_hotspot(conn, hs: Hotspot, detector) -> int:
    rows = conn.execute(
        """SELECT * FROM scenes WHERE hotspot_id=? AND status='CROPPED'
           ORDER BY acquired_at""", (hs.id,)).fetchall()
    by_grp = defaultdict(list)
    for r in rows:
        by_grp[r["grp"]].append(r)

    rdir = settings.RENDERS / hs.id
    rdir.mkdir(parents=True, exist_ok=True)
    n_new = 0
    for grp, scenes in by_grp.items():
        if len(scenes) < 2:
            continue
        crops = {s["scene_id"]: Crop.load(settings.DATA / s["crop_path"]) for s in scenes}
        shape = max({(c.hh.shape, c.res) for c in crops.values()},
                    key=lambda k: sum((c.hh.shape, c.res) == k for c in crops.values()))
        scenes = [s for s in scenes if (crops[s["scene_id"]].hh.shape, crops[s["scene_id"]].res) == shape]
        if len(scenes) < 2:
            continue
        thr = round(group_threshold([crops[s["scene_id"]] for s in scenes]), 2)
        wet = {s["scene_id"]: water_fraction(crops[s["scene_id"]], thr) for s in scenes}
        base = choose_baseline(scenes, hs.baseline_months, wet)
        ref = crops[base["scene_id"]]
        # A new baseline or a new pass shifting the group threshold makes
        # older analyses stale; drop them so they are recomputed below.
        conn.execute(
            """DELETE FROM analyses WHERE hotspot_id=? AND grp=? AND
               (baseline_scene_id != ? OR detector != ? OR ABS(threshold_db - ?) > 0.001)""",
            (hs.id, grp, base["scene_id"], detector.name, thr))
        before_png = rdir / f"{base['scene_id']}_sar.png"
        if not before_png.exists():
            backscatter_png(ref.hh, before_png)

        prev_water = None
        prev_id = None
        for s in scenes:
            is_base = s["scene_id"] == base["scene_id"]
            existing = conn.execute(
                """SELECT water_new_km2 FROM analyses WHERE hotspot_id=? AND scene_id=?
                   AND baseline_scene_id=? AND detector=?""",
                (hs.id, s["scene_id"], base["scene_id"], detector.name)).fetchone()
            if existing:
                prev_water, prev_id = existing["water_new_km2"], s["scene_id"]
                continue
            new = crops[s["scene_id"]]
            if new.hh.shape != ref.hh.shape or new.res != ref.res:
                log(f"{hs.id}: {s['scene_id']} grid {new.hh.shape}@{new.res}m does not match "
                    f"baseline {ref.hh.shape}@{ref.res}m; skipped")
                continue
            res = detector.detect(ref, new, threshold_db=thr)
            summ = res.summary()
            if is_base:
                # The baseline pass is, by construction, the least flooded on
                # record for this track: it is a valid NORMAL observation.
                level, reasons = "NORMAL", ["Baseline pass: the driest on this track, "
                                            "used as the reference for the others"]
            elif res.unreliable:
                level, reasons = "NORMAL", [f"Not assessed: {res.offset_db:+.1f} dB scene-wide "
                                            "radiometric offset between passes"]
            else:
                level, reasons = evaluate(summ, hs.thresholds)
            if prev_water is None:
                prev_water = summ["water_ref_km2"]
            after_png = rdir / f"{s['scene_id']}_sar.png"
            chg_png = rdir / f"{s['scene_id']}_vs_{base['scene_id']}_change.png"
            if not after_png.exists():
                backscatter_png(new.hh, after_png)
            change_png(res, chg_png)
            conn.execute(
                """INSERT OR REPLACE INTO analyses (hotspot_id, scene_id, baseline_scene_id,
                   prev_scene_id, grp, acquired_at, baseline_at, detector, threshold_db,
                   valid_km2, water_ref_km2, water_new_km2, new_water_km2, receded_km2,
                   increase_pct, largest_patch_km2, delta_prev_km2, level, reasons, notes,
                   render_before, render_after, render_change, corners_ll, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (hs.id, s["scene_id"], base["scene_id"], prev_id, grp, s["acquired_at"],
                 base["acquired_at"], detector.name, summ["threshold_db"], summ["valid_km2"],
                 summ["water_ref_km2"], summ["water_new_km2"], summ["new_water_km2"],
                 summ["receded_km2"], summ["increase_pct"], summ["largest_patch_km2"],
                 round(summ["water_new_km2"] - prev_water, 2), level,
                 json.dumps(reasons, ensure_ascii=False), json.dumps(res.notes),
                 str(before_png.relative_to(settings.RENDERS)),
                 str(after_png.relative_to(settings.RENDERS)),
                 str(chg_png.relative_to(settings.RENDERS)),
                 json.dumps(new.corners_ll), utcnow()))
            prev_water, prev_id = summ["water_new_km2"], s["scene_id"]
            n_new += 1
    conn.commit()
    return n_new


# --------------------------------------------------------------------------
# 5. alerts
# --------------------------------------------------------------------------

def flood_episodes(analyses: list) -> list[dict]:
    """Split a hotspot's passes (all tracks, time order) into flood episodes."""
    episodes, cur = [], None
    for a in analyses:
        if a["level"] in ("WATCH", "ALERT"):
            if cur is None:
                cur = {"first": a, "passes": [], "peak": "WATCH", "peak_km2": 0.0, "closed_by": None}
            cur["passes"].append(a)
            if a["level"] == "ALERT":
                cur["peak"] = "ALERT"
            cur["peak_km2"] = max(cur["peak_km2"], a["new_water_km2"])
        elif cur is not None:
            cur["closed_by"] = a
            episodes.append(cur)
            cur = None
    if cur is not None:
        episodes.append(cur)
    return episodes


def update_alerts(conn, hs: Hotspot) -> None:
    """Rebuild this hotspot's alerts from its analyses.

    Derived deterministically, so re-runs and re-baselining converge; an
    existing row keeps its original raised_at / resolved_at timestamps.
    """
    rows = conn.execute(
        "SELECT * FROM analyses WHERE hotspot_id=? ORDER BY acquired_at, grp", (hs.id,)).fetchall()
    keep = []
    for ep in flood_episodes(rows):
        first, last, closer = ep["first"], ep["passes"][-1], ep["closed_by"]
        label = "FLOOD ALERT" if ep["peak"] == "ALERT" else "Flood watch"
        span = first["acquired_at"][:10]
        if len(ep["passes"]) > 1:
            span += f" to {last['acquired_at'][:10]}"
        headline = (f"{label}: {hs.river}, {hs.name} ({hs.state}): up to "
                    f"{ep['peak_km2']:.1f} km² new water ({span})")
        status = "RESOLVED" if closer else "ACTIVE"
        reason = (f"Pass {closer['scene_id']} ({closer['acquired_at'][:10]}): "
                  f"{closer['new_water_km2']:.1f} km² new water, below thresholds") if closer else None
        old = conn.execute("SELECT * FROM alerts WHERE hotspot_id=? AND scene_id=?",
                           (hs.id, first["scene_id"])).fetchone()
        resolved_at = (old["resolved_at"] if old and old["resolved_at"] else utcnow()) if closer else None
        vals = (last["scene_id"], ep["peak"], last["level"], status, headline,
                last["new_water_km2"], ep["peak_km2"], len(ep["passes"]),
                last["acquired_at"], resolved_at, reason)
        if old:
            conn.execute(
                """UPDATE alerts SET last_scene_id=?, level=?, current_level=?, status=?,
                   headline=?, new_water_km2=?, peak_new_water_km2=?, passes=?,
                   last_acquired_at=?, resolved_at=?, resolution_reason=? WHERE id=?""",
                (*vals, old["id"]))
        else:
            conn.execute(
                """INSERT INTO alerts (last_scene_id, level, current_level, status, headline,
                   new_water_km2, peak_new_water_km2, passes, last_acquired_at, resolved_at,
                   resolution_reason, hotspot_id, scene_id, acquired_at, raised_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (*vals, hs.id, first["scene_id"], first["acquired_at"], utcnow()))
        keep.append(first["scene_id"])
    # Episodes that no longer exist (e.g. after a drier baseline arrived).
    conn.execute(
        f"DELETE FROM alerts WHERE hotspot_id=? AND scene_id NOT IN ({','.join('?' * len(keep))})",
        (hs.id, *keep))
    conn.commit()


# --------------------------------------------------------------------------

def run(hotspot_ids: list[str] | None = None, provider_name: str = "bhoonidhi",
        max_per_track: int = 6, workers: int = 3, since: str | None = None,
        retry_failed: bool = False) -> dict:
    with RunLock():
        return _run(hotspot_ids, provider_name, max_per_track, workers, since, retry_failed)


def _run(hotspot_ids, provider_name, max_per_track, workers, since, retry_failed) -> dict:
    init_db()
    hotspots = {h.id: h for h in load_hotspots() if not hotspot_ids or h.id in hotspot_ids}
    provider = get_provider(provider_name)
    detector = ClassicalDetector()
    summary = {"started_at": utcnow(), "hotspots": len(hotspots), "found": 0, "errors": []}
    today = date.today().isoformat()

    with connect() as conn:
        run_id = conn.execute("INSERT INTO runs (started_at) VALUES (?)",
                              (summary["started_at"],)).lastrowid
        if retry_failed:
            conn.executemany("UPDATE scenes SET status='PENDING' WHERE status='FAILED' AND hotspot_id=?",
                             [(h,) for h in hotspots])
        for hs in hotspots.values():
            try:
                scenes = [s for s in provider.search(hs.bbox, since or hs.history_start, today)
                          if intersects(s.footprint, hs.bbox)]
            except Exception as e:  # noqa: BLE001
                summary["errors"].append(f"{hs.id}: search {e}")
                log(f"{hs.id}: search failed: {e}")
                continue
            acqs = acquisitions(scenes)
            by_grp = defaultdict(list)
            for a in acqs:
                by_grp[a["grp"]].append(a)
            keep = [a for g in by_grp.values() for a in g[-max_per_track:]]
            register(conn, hs, keep)
            summary["found"] += len(keep)
            log(f"{hs.id}: {len(acqs)} acquisition(s) on {len(by_grp)} track(s), "
                f"keeping {len(keep)}")
        conn.commit()

        summary["analyses"] = 0

        def on_ready(hs):
            # One hotspot's failure must never stop the other nineteen.
            try:
                summary["analyses"] += analyse_hotspot(conn, hs, detector)
                update_alerts(conn, hs)
            except Exception as e:  # noqa: BLE001
                conn.rollback()
                summary["errors"].append(f"{hs.id}: analyse {type(e).__name__}: {e}")
                log(f"{hs.id}: analyse failed: {type(e).__name__}: {e}")

        summary["crop"] = run_crops(conn, hotspots, provider_name, workers, on_ready)

        summary["active_alerts"] = conn.execute(
            "SELECT COUNT(*) FROM alerts WHERE status='ACTIVE'").fetchone()[0]
        summary["finished_at"] = utcnow()
        conn.execute("UPDATE runs SET finished_at=?, summary=? WHERE id=?",
                     (summary["finished_at"], json.dumps(summary), run_id))
    return summary


def reset_analyses() -> None:
    init_db()
    with connect() as conn:
        conn.execute("DELETE FROM analyses")
    shutil.rmtree(settings.RENDERS, ignore_errors=True)
    settings.RENDERS.mkdir(parents=True, exist_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hotspot", action="append", help="hotspot id (repeatable); default all")
    ap.add_argument("--provider", default="bhoonidhi", choices=["bhoonidhi", "manual"])
    ap.add_argument("--max-per-track", type=int, default=6,
                    help="most recent acquisitions kept per track (default 6)")
    ap.add_argument("--workers", type=int, default=3,
                    help="parallel product reads; Bhoonidhi allows 5 (default 3)")
    ap.add_argument("--since", help="earliest acquisition date, YYYY-MM-DD")
    ap.add_argument("--retry-failed", action="store_true",
                    help="re-attempt scenes whose crop failed on an earlier run")
    ap.add_argument("--reset-analyses", action="store_true",
                    help="recompute everything derived from crops (after a detector change); "
                         "crops are kept, nothing is re-downloaded")
    args = ap.parse_args()
    if args.reset_analyses:
        reset_analyses()
    print(json.dumps(run(args.hotspot, args.provider, args.max_per_track, args.workers,
                         args.since, args.retry_failed), indent=2))


if __name__ == "__main__":
    main()
