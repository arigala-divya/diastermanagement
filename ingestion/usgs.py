"""USGS FDSN earthquake catalogue.

Open, no authentication, and supports arbitrary historical windows - which is
what makes the dashboard's date range usable back to 1 August. NCS is India's
authoritative seismic agency and should be added when its feed is available;
USGS is used here because it is openly queryable today.
"""

import json

from ingestion.base import Signal, log, to_utc
from processing.geo import nearest_district
from processing.taxonomy import severity_from_magnitude

URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
LICENCE = "USGS - public domain"

# Indian subcontinent window. Deliberately wider than India's borders:
# Hindu Kush and Nepal earthquakes are felt across northern India.
BBOX = {"minlatitude": 6, "maxlatitude": 38, "minlongitude": 68, "maxlongitude": 98}


def fetch(client, districts: dict, start: str, end: str = "", min_mag: float = 3.0):
    params = {
        "format": "geojson",
        "starttime": start,
        "minmagnitude": min_mag,
        "orderby": "time",
        **BBOX,
    }
    if end:
        params["endtime"] = end

    resp = client.get(URL, params=params)
    resp.raise_for_status()
    payload = resp.json()

    return [s for s in (signal_from_feature(f, districts) for f in payload.get("features", [])) if s]


def signal_from_feature(feat: dict, districts: dict):
    """Build one signal from a USGS GeoJSON feature. Reused by replay()."""
    if True:
        props = feat.get("properties") or {}
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            return None
        lon, lat = float(coords[0]), float(coords[1])
        mag = props.get("mag")
        if mag is None:
            return None

        district, _ = nearest_district(lat, lon, districts)
        place = props.get("place") or "Unknown location"

        return Signal(
            source="USGS",
            source_uid=str(feat.get("id") or props.get("code") or f"{lat},{lon}"),
            hazard_type="EARTHQUAKE",
            headline=f"M{mag:.1f} earthquake - {place}",
            severity=severity_from_magnitude(float(mag)),
            agency="USGS",
            tier=1,
            url=props.get("url", ""),
            published_at=to_utc(props.get("time")),
            starts_at=to_utc(props.get("time")),
            state=district["state"] if district else "",
            district=district["district"] if district else "",
            lgd_district=district["lgd"] if district else None,
            lat=lat,
            lon=lon,
            licence=LICENCE,
            raw=json.dumps(feat, ensure_ascii=False),
        )
