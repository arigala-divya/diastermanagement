"""GDACS - global multi-hazard, model-driven.

Valuable for two reasons: it is an independent cross-check on Indian agency
reporting, and its SEARCH endpoint accepts a date range, so it can backfill
history. It only reports large-scale events, so expect low volume - it is a
corroborating source, not a primary one. Its output is modelled rather than
ground-observed, so signals are tier 2 and surface as MODELLED confidence.
"""

import json
from datetime import datetime, timezone

from ingestion.base import Signal, log, to_utc
from processing.geo import nearest_district
from processing.taxonomy import GDACS_TYPES, severity_from_gdacs

URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
# GDACS is intermittently degraded - the same SEARCH URL returns 200, then 400,
# then times out within a few hours. EVENTS4APP serves recent events without a
# date range and stays up when SEARCH does not, so it is tried as a fallback.
FALLBACK_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/EVENTS4APP"
LICENCE = "GDACS (JRC/UN) - open, attribution required"


def fetch(client, districts: dict, start: str, end: str = "", country: str = "India"):
    # GDACS rejects fromDate without toDate with a bare HTTP 400, so the end
    # of the window is always sent, defaulting to today.
    params = {
        "country": country,
        "fromDate": start,
        "toDate": end or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    try:
        resp = client.get(URL, params=params)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001 - fall back rather than lose the source
        log(f"  GDACS: SEARCH unavailable ({type(exc).__name__}), trying EVENTS4APP")
        resp = client.get(FALLBACK_URL, params={"country": country})
        resp.raise_for_status()
        payload = resp.json()
        # EVENTS4APP ignores the date range, so filter to the window ourselves.
        payload["features"] = [
            f for f in payload.get("features", [])
            if str((f.get("properties") or {}).get("fromdate", ""))[:10] >= start
            or not (f.get("properties") or {}).get("fromdate")
        ]

    return [s for s in (signal_from_feature(f, districts) for f in payload.get("features", [])) if s]


def signal_from_feature(feat: dict, districts: dict):
    """Build one signal from a GDACS GeoJSON feature. Reused by replay()."""
    if True:
        props = feat.get("properties") or {}
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            return None
        lon, lat = float(coords[0]), float(coords[1])

        hazard = GDACS_TYPES.get((props.get("eventtype") or "").upper(), "OTHER")
        district, _ = nearest_district(lat, lon, districts)
        name = props.get("eventname") or props.get("name") or f"{hazard.title()} event"
        event_id = props.get("eventid")

        return Signal(
            source="GDACS",
            source_uid=f"gdacs-{event_id}",
            hazard_type=hazard,
            headline=str(name),
            severity=severity_from_gdacs(props.get("alertlevel", "")),
            agency="GDACS",
            tier=2,
            url=props.get("url", {}).get("report", "")
            if isinstance(props.get("url"), dict)
            else f"https://www.gdacs.org/report.aspx?eventid={event_id}",
            published_at=to_utc(props.get("fromdate")),
            starts_at=to_utc(props.get("fromdate")),
            expires_at=to_utc(props.get("todate")),
            state=district["state"] if district else "",
            district=district["district"] if district else "",
            lgd_district=district["lgd"] if district else None,
            lat=lat,
            lon=lon,
            licence=LICENCE,
            raw=json.dumps(feat, ensure_ascii=False),
        )
