"""Geographic resolution against the LGD district gazetteer.

SACHET gives us LGD codes directly, so it needs no geocoding. Point sources
(USGS, GDACS) give coordinates only, so they are snapped to the nearest
district headquarters. Anything beyond MAX_SNAP_KM is treated as outside
India and left unattributed rather than being forced into a wrong district -
a misplaced disaster marker is worse than an unplaced one.
"""

import math

# Regional earthquakes (Nepal, Hindu Kush) genuinely matter to India, so they
# are kept on the map, but only attributed to a state when they are plausibly
# within it.
MAX_SNAP_KM = 150.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_district(lat: float, lon: float, districts: dict):
    """Return (district_record, distance_km) or (None, None) if too far."""
    if lat is None or lon is None:
        return None, None
    best, best_km = None, float("inf")
    for rec in districts.values():
        km = haversine_km(lat, lon, rec["lat"], rec["lon"])
        if km < best_km:
            best, best_km = rec, km
    if best is None or best_km > MAX_SNAP_KM:
        return None, best_km
    return best, best_km
