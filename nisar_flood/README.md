# NISAR Flood Monitor

Detects river flooding at 20 Indian flood hotspots by comparing successive
NISAR S-band SAR passes, and raises a WATCH or FLOOD ALERT when new surface
water appears. It sits alongside the India Disaster Intelligence dashboard in
this repo but runs independently, on port 8001.

> **Detection, not forecasting.** NISAR revisits each orbit track every 12
> days, and most hotspots are seen from one or two tracks. An alert means
> flooding was visible on the latest pass. Radar sees through cloud, which
> is what makes this usable in the monsoon.

## Quick start

```bash
.venv/Scripts/python.exe -m pip install -r nisar_flood/requirements.txt

# Credentials (git-ignored). Use your Bhoonidhi login.
printf 'BHOONIDHI_USER=...\nBHOONIDHI_PASS=...\n' > nisar_flood/.env

# Fetch, analyse, alert. Safe to re-run; only new passes are processed.
.venv/Scripts/python.exe -m nisar_flood.pipeline

# Serve the UI
.venv/Scripts/python.exe -m uvicorn nisar_flood.api:app --port 8001
```

Open <http://127.0.0.1:8001>. The **Check for new scenes** button runs the
pipeline in the background.

Useful flags: `--hotspot ID` (repeatable), `--max-per-track N` (history depth,
default 6), `--workers N` (parallel reads, default 3; Bhoonidhi allows 5),
`--provider manual`, `--reset-analyses`.

## Data access

Scenes come from the **official Bhoonidhi API** (`bhoonidhi-api.nrsc.gov.in`),
collection `NISAR_SSAR_GCOV`: S-band, Level-2 geocoded, terrain-corrected
backscatter, on a 10 m UTM grid, delivered as HDF5.

A GCOV frame is **~12.6 GB**, so nothing is downloaded whole. The download
endpoint honours HTTP Range, and `acquisition/bhoonidhi.py` opens the HDF5
file *remotely*: h5py reads go through a seekable file object that issues
ranged GETs. Data is stored in 512×512 gzip chunks, so one 30 km AOI costs
about 110 MB of transfer and 2–3 minutes per pass. One product covering
several hotspots is opened once and cropped for all of them.

API limits are respected: tokens are cached in `data/` and refreshed (logins
are capped at 20/hour), searches are paced, and parallel reads stay under the
5-concurrent-download cap.

**Fallback:** if the API is unavailable, order scenes through Bhoonidhi
Browse & Order, drop the `.h5` files into `nisar_flood/data/inbox/`, and run
with `--provider manual`.

## How detection works

```
search ─► register pass ─► remote AOI crop ─► baseline pick ─► change detection ─► alert rules
          (scenes table)    10 m → 20 m          driest pass     water masks +        NORMAL /
                            mosaic frames        per track       log-ratio            WATCH / ALERT
```

1. **Like-for-like comparison.** Passes are grouped by orbit track,
   direction and product variant (the `3700`/`2500` field of Bhoonidhi
   ids). Viewing geometry changes brightness, and the two variants, which
   alternate on some tracks, differ by about 4 dB. Every crop is resampled to
   one 20 m grid (products come at 10 m or 20 m). Frames from the same pass
   are mosaicked when an AOI straddles a frame boundary.
2. **Baseline** is the driest processed pass on the track, preferring
   dry-season months. When a drier pass arrives, analyses are recomputed
   against it.
3. **Water mask:** calm water reflects radar away and appears dark. The
   threshold is the valley between the water and land peaks of the
   histogram, taken only over tiles that mix water and land (global Otsu fails
   when water is a few percent of the scene). It adapts per track: water sits
   near −19 dB on track 40 over Assam but near −14 dB on track 112, where the
   noise floor is higher. One threshold is pooled over every pass in the
   comparison group, so all passes on a track are measured with the same
   ruler (per-pair thresholds made the same baseline read 44 km² in one
   comparison and 156 km² in another over the Kosi floodplain).
4. **Radiometric normalisation:** the median change over land that is
   clearly dry in the baseline estimates any scene-wide calibration offset
   between the two products, and that offset is removed. (A real flood
   darkens part of the land, while an offset shifts all of it.) A pair with
   an offset above 3 dB is marked "not assessed" rather than alerted on.
   This removed a false 289 km² alert on the Ghaghra.
5. **New water** = water now, not water in the baseline, *and* darkened by
   more than 3 dB (log-ratio). Morphological opening and a 0.05 km² minimum
   patch size remove speckle.
6. **Alert rules** (`config/hotspots.yaml`, overridable per hotspot):
   WATCH at ≥ 5 km² new water or +25% extent; FLOOD ALERT at ≥ 20 km² or +75%,
   which also needs one contiguous patch ≥ 2 km². Every level records the rule
   that fired it.
7. **Alert episodes:** one alert per flood. The first WATCH or ALERT pass
   opens it, consecutive WATCH/ALERT passes (on any track) extend it and
   record the peak, and the first pass below the thresholds resolves it, with
   the reason recorded. The baseline pass counts as NORMAL. Episodes are
   rebuilt from the analyses on every run, so re-runs converge.

The detector sits behind a `Detector` interface (`detection/base.py`), so a
deep-learning model can replace it without touching storage, rules or UI.

## Validation so far

Detections were cross-checked against CWC flood bulletins already in the
India Disaster Intelligence database (`data/disasters.db`, via SACHET). On
7 Sep 2026 CWC reported *"River Ganga at Bhagalpur … severe flood
situation"*, and NISAR raised a FLOOD ALERT at Bhagalpur peaking at 313 km²
new water on 5 Sep. Systematic validation against all CWC station bulletins
is a natural next step.

## Known limitations

- **The archive starts in July 2026**, mid-monsoon. Until dry-season passes
  exist, the "driest pass" baseline may itself contain flood water, which
  under-reports flooding. Expect better baselines from November onward.
- **Permanent water is not masked.** Braided channels (Brahmaputra, Kosi)
  migrate and can register as change. A JRC Global Surface Water mask is the
  planned fix.
- **Dark non-water surfaces** (dry sand bars, smooth tarmac, radar shadow)
  look like water. The change test suppresses most of them because they are
  dark on *both* dates.
- **Urban and mountain AOIs** (Chennai, Srinagar) are poorly served by
  backscatter thresholds. Buildings brighten floodwater by double-bounce
  rather than darkening it, and terrain gives no clean water/land histogram
  split: on some tracks there the threshold sits at the −9.5 dB limit.
  Treat these hotspots as indicative only.
- **Some product variants show almost no water contrast** (e.g. Rapti track
  T149D `2500`: about 0 km² water at a −22.8 dB threshold). They cannot
  raise false alerts, but they also add little detection power.
- Hotspot centres are approximate; check each AOI on the map and adjust
  `config/hotspots.yaml`.

## Tests

```bash
.venv/Scripts/python.exe -m pytest nisar_flood/tests -q
```

These are synthetic-scene tests with gamma-distributed speckle. They check
that an injected flood is recovered within 10%, that speckle alone or
receding water never alerts, and that the threshold lands in the water/land
valley.

## Layout

| Path | Role |
| --- | --- |
| `config/hotspots.yaml` | 20 AOIs and alert thresholds |
| `acquisition/` | `bhoonidhi.py` (API + remote HDF5), `manual.py` (inbox) |
| `processing/preprocess.py` | AOI crop, UTM grid snapping, multilook |
| `detection/` | `Detector` interface and the classical detector |
| `alerts/rules.py` | NORMAL / WATCH / ALERT with reasons |
| `pipeline.py` | CLI orchestration, idempotent |
| `api.py`, `frontend/` | FastAPI + Leaflet UI |
| `data/` | git-ignored: SQLite DB, crops, renders, token cache |
