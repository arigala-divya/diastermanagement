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


# ── Name-based resolution ──────────────────────────────────────────────
#
# Not every agency populates <cap:geocode>. IMD Dehradun, for example, sends
# only free-text areaDesc ("Chamoli, Bageshwar, Pithoragarh, Almora", or
# "Isolated places over Kumaun region"). Without a fallback those alerts land
# unmapped, which is how eight live Uttarakhand alerts went missing.
#
# Matching is constrained by a state hint derived from the issuing office,
# which is what makes it safe: India has many duplicate district names
# (Hamirpur in UP and HP, Aurangabad in Bihar and Maharashtra, Bilaspur in HP
# and Chhattisgarh), so an unconstrained name match would misplace events.

import re

# IMD meteorological centres and state SDMAs -> the state they cover.
AGENCY_STATE = {
    "dehradun": "Uttarakhand", "jaipur": "Rajasthan", "lucknow": "Uttar Pradesh",
    "ranchi": "Jharkhand", "kolkata": "West Bengal", "chennai": "Tamil Nadu",
    "mumbai": "Maharashtra", "nagpur": "Maharashtra", "pune": "Maharashtra",
    "bhopal": "Madhya Pradesh", "bhubaneswar": "Odisha", "guwahati": "Assam",
    "raipur": "Chhattisgarh", "patna": "Bihar", "ahmedabad": "Gujarat",
    "hyderabad": "Telangana", "bengaluru": "Karnataka", "bangalore": "Karnataka",
    "thiruvananthapuram": "Kerala", "shimla": "Himachal Pradesh",
    "srinagar": "Jammu & Kashmir", "jammu": "Jammu & Kashmir", "leh": "Ladakh",
    "chandigarh": "Chandigarh", "delhi": "Delhi", "goa": "Goa", "panaji": "Goa",
    "agartala": "Tripura", "imphal": "Manipur", "shillong": "Meghalaya",
    "aizawl": "Mizoram", "kohima": "Nagaland", "itanagar": "Arunachal Pradesh",
    "gangtok": "Sikkim", "port blair": "Andaman & Nicobar",
    "amaravati": "Andhra Pradesh", "visakhapatnam": "Andhra Pradesh",
}

_STATE_NAMES: dict[str, str] = {}
_NAME_INDEX: dict[str, list] = {}
_STATE_CENTROIDS: dict[str, tuple] = {}


def _build_indexes(districts: dict):
    if _NAME_INDEX:
        return
    acc: dict[str, list] = {}
    for rec in districts.values():
        key = rec["district"].strip().lower()
        _NAME_INDEX.setdefault(key, []).append(rec)
        acc.setdefault(rec["state"], []).append((rec["lat"], rec["lon"]))
        _STATE_NAMES[rec["state"].lower()] = rec["state"]
    for st, pts in acc.items():
        _STATE_CENTROIDS[st] = (
            sum(p[0] for p in pts) / len(pts),
            sum(p[1] for p in pts) / len(pts),
        )


def state_from_agency(agency: str, districts: dict):
    """Infer the covered state from the issuing office, e.g. 'IMD Dehradun'."""
    _build_indexes(districts)
    low = (agency or "").lower()
    for token, st in AGENCY_STATE.items():
        if token in low:
            return st
    # "<State> SDMA" / "<State> State Disaster Management Authority"
    for st_low, st in _STATE_NAMES.items():
        if st_low in low:
            return st
    return ""


def state_centroid(state: str, districts: dict):
    _build_indexes(districts)
    return _STATE_CENTROIDS.get(state)


def districts_from_text(area_desc: str, districts: dict, hint_state: str = ""):
    """Match district names inside a free-text CAP areaDesc.

    Restricted to hint_state when one is known, so duplicate district names
    across states cannot cause a mis-placement.
    """
    _build_indexes(districts)
    if not area_desc:
        return []

    # areaDesc is comma/'and'/slash separated, often with trailing qualifiers
    # such as "districts of Jharkhand" or "Isolated places over Kumaun region".
    parts = re.split(r"[,;/&]|\band\b", area_desc, flags=re.IGNORECASE)
    out, seen = [], set()
    for part in parts:
        token = re.sub(
            r"\b(districts?|of|isolated|places|over|at|rest|region|and)\b",
            " ", part, flags=re.IGNORECASE,
        )
        token = re.sub(r"\s+", " ", token).strip().lower()
        if len(token) < 3:
            continue
        for rec in _NAME_INDEX.get(token, []):
            if hint_state and rec["state"] != hint_state:
                continue
            key = rec.get("lgd") or f"{rec['state']}-{rec['district']}"
            if key not in seen:
                seen.add(key)
                out.append(rec)
    return out


# Delhi's districts are named after compass directions, which match constantly
# in free text ("South Korea", "central Peru", "west coast"). They are only
# accepted when Delhi itself is named.
AMBIGUOUS_NAMES = {
    "north", "south", "east", "west", "central", "new delhi",
    "north east", "north west", "south east", "south west", "shahdara",
}


def locate_free_text(text: str, districts: dict):
    """Find a place in unconstrained text (news headlines).

    Returns (state, district, lat, lon). Deliberately conservative: a district
    name is only accepted when it is unique across India, or when a state is
    also named in the same text. India has too many duplicate district names
    to guess, and a misplaced disaster marker is worse than an unplaced one.
    """
    _build_indexes(districts)
    low = f" {(text or '').lower()} "

    found_state = ""
    for st_low, st in _STATE_NAMES.items():
        if f" {st_low} " in low:
            found_state = st
            break

    for name, recs in _NAME_INDEX.items():
        if len(name) < 4 or f" {name} " not in low:
            continue
        if name in AMBIGUOUS_NAMES and not found_state:
            continue
        if found_state:
            for rec in recs:
                if rec["state"] == found_state:
                    return rec["state"], rec["district"], rec["lat"], rec["lon"]
        elif len(recs) == 1:  # unambiguous nationally
            rec = recs[0]
            return rec["state"], rec["district"], rec["lat"], rec["lon"]

    if found_state:
        centre = _STATE_CENTROIDS.get(found_state)
        if centre:
            return found_state, "", centre[0], centre[1]
    return "", "", None, None
