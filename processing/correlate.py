"""Event correlation and lifecycle.

Turns many source signals into one event per real-world occurrence. This is
the part that makes the platform more than a feed reader: when IMD, CWC and
GDACS all describe the same flood, staff should see one event with three
corroborating sources, not three events.

Correlation is deliberately deterministic - no ML, no similarity thresholds.
Every merge decision is explainable and auditable, which matters for a
government tool where someone will eventually ask "why did it say that?".
"""

from datetime import datetime, timedelta, timezone

# How long signals about the same hazard in the same place are considered the
# same event. Slow-onset hazards get longer windows than convective ones.
WINDOW_HOURS = {
    "FLOOD": 72,
    "DROUGHT": 720,
    "CYCLONE": 120,
    "HEATWAVE": 96,
    "COLDWAVE": 96,
    "FOREST_FIRE": 48,
    "EARTHQUAKE": 2,
    "THUNDERSTORM": 6,
    "LIGHTNING": 6,
    "HEAVY_RAIN": 12,
}
DEFAULT_WINDOW = 24

# How long after its last update an event stays ACTIVE when the source gave no
# explicit expiry. Without this the dashboard accumulates zombie events.
TTL_HOURS = {
    "EARTHQUAKE": 24,
    "THUNDERSTORM": 6,
    "LIGHTNING": 6,
    "HEAVY_RAIN": 24,
    "FLOOD": 120,
    "CYCLONE": 168,
    "DROUGHT": 1440,
}
DEFAULT_TTL = 48

SEVERITY_ORDER = ["INFO", "MINOR", "MODERATE", "SEVERE", "EXTREME"]


def _parse(ts: str):
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def correlation_key(signal) -> str:
    """Signals sharing this key describe the same event.

    Place component prefers the LGD district code; point sources without one
    fall back to a coarse spatial cell so nearby reports still merge.
    """
    when = _parse(signal.starts_at or signal.published_at) or datetime.now(timezone.utc)
    window = WINDOW_HOURS.get(signal.hazard_type, DEFAULT_WINDOW)
    bucket = int(when.timestamp() // (window * 3600))

    if signal.lgd_district:
        place = f"lgd{signal.lgd_district}"
    elif signal.lat is not None and signal.lon is not None:
        place = f"cell{round(signal.lat, 1)},{round(signal.lon, 1)}"
    else:
        place = "unknown"

    return f"{signal.hazard_type}|{place}|{bucket}"


def confidence_for(tiers: set[int], agencies: set[str]) -> str:
    """Explainable confidence. Never a fabricated percentage.

    Two or more independent official agencies agreeing is the strongest signal
    available without ground truth, so it is named as such rather than being
    converted into a number that implies calibration we do not have.
    """
    official_agencies = {a for a in agencies if a}
    if 1 in tiers:
        return "CORROBORATED" if len(official_agencies) >= 2 else "OFFICIAL"
    if 2 in tiers:
        return "MODELLED"
    return "REPORTED"


def max_severity(values) -> str:
    best = "INFO"
    for v in values:
        if v in SEVERITY_ORDER and SEVERITY_ORDER.index(v) > SEVERITY_ORDER.index(best):
            best = v
    return best


def resolve_status(hazard: str, last_updated: str, expires_at: str):
    """Return (status, resolution_rule). Rule is stored so closure is auditable."""
    now = datetime.now(timezone.utc)

    expiry = _parse(expires_at)
    if expiry:
        if expiry < now:
            return "RESOLVED", f"CAP expiry passed ({expires_at})"
        return "ACTIVE", ""

    updated = _parse(last_updated)
    if not updated:
        return "WATCH", "no usable timestamp"

    ttl = TTL_HOURS.get(hazard, DEFAULT_TTL)
    age_h = (now - updated).total_seconds() / 3600
    if age_h > ttl:
        return "RESOLVED", f"no update in {age_h:.0f}h (TTL {ttl}h)"
    if age_h > ttl / 2:
        return "WATCH", f"stale {age_h:.0f}h of {ttl}h TTL"
    return "ACTIVE", ""
