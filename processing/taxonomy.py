"""Hazard taxonomy and classification.

Every source speaks its own vocabulary. This module is the single place where
those vocabularies collapse into one controlled hazard list.

Classification prefers the CAP <event> field (English even when the public
headline is in a regional language), then falls back to multilingual keyword
matching, because live SACHET headlines arrive in Hindi, Telugu, Odia and
others. Never assume English.
"""

import re

# Controlled hazard vocabulary. Order matters: first match wins, so more
# specific hazards must precede the general ones they would otherwise match.
HAZARDS = [
    "TSUNAMI",
    "CYCLONE",
    "EARTHQUAKE",
    "FOREST_FIRE",
    "LANDSLIDE",
    "AVALANCHE",
    "CLOUD_BURST",
    "FLOOD",
    "STORM_SURGE",
    "HIGH_WAVE",
    "DUST_STORM",
    "THUNDERSTORM",
    "LIGHTNING",
    "HEAVY_RAIN",
    "HEATWAVE",
    "COLDWAVE",
    "DROUGHT",
    "FOG",
    "GALE_WIND",
    "OTHER",
]

HAZARD_LABELS = {
    "TSUNAMI": "Tsunami",
    "CYCLONE": "Cyclone",
    "EARTHQUAKE": "Earthquake",
    "FOREST_FIRE": "Forest Fire",
    "LANDSLIDE": "Landslide",
    "AVALANCHE": "Avalanche",
    "CLOUD_BURST": "Cloudburst",
    "FLOOD": "Flood",
    "STORM_SURGE": "Storm Surge",
    "HIGH_WAVE": "High Wave / Swell",
    "DUST_STORM": "Dust Storm",
    "THUNDERSTORM": "Thunderstorm",
    "LIGHTNING": "Lightning",
    "HEAVY_RAIN": "Heavy Rain",
    "HEATWAVE": "Heatwave",
    "COLDWAVE": "Cold Wave",
    "DROUGHT": "Drought",
    "FOG": "Fog",
    "GALE_WIND": "Gale / Squall",
    "OTHER": "Other",
}

# Keyword patterns per hazard, in HAZARDS order. Includes Devanagari, Telugu,
# Odia, Bengali and Tamil terms seen in live SACHET traffic.
_RULES = {
    "TSUNAMI": [r"tsunami", r"सुनामी"],
    "CYCLONE": [r"cyclon", r"depression", r"चक्रवात", r"তুফান"],
    "EARTHQUAKE": [r"earthquake", r"seismic", r"भूकंप"],
    "FOREST_FIRE": [r"forest\s*fire", r"wild\s*fire", r"वनाग्नि", r"आग"],
    "LANDSLIDE": [r"landslide", r"landslip", r"mudslide", r"भूस्खलन"],
    "AVALANCHE": [r"avalanche", r"हिमस्खलन"],
    "CLOUD_BURST": [r"cloud\s*burst", r"बादल\s*फटना"],
    # River level / inundation wording used by CWC bulletins.
    "FLOOD": [
        r"flood", r"inundat", r"water\s*level", r"river.*(rise|rising|increase)",
        r"बाढ़", r"जल\s*स्तर", r"वरद", r"বন্যা",
    ],
    "STORM_SURGE": [r"storm\s*surge", r"tidal\s*wave"],
    "HIGH_WAVE": [r"high\s*wave", r"swell", r"kallakadal"],
    "DUST_STORM": [r"dust\s*storm", r"sand\s*storm", r"आंधी"],
    "THUNDERSTORM": [
        r"thunder", r"squall", r"मेघगर्जन", r"गरज", r"आंधी-तूफ़ान", r"तूफ़ान",
        r"ఉరుము", r"ଘଡ଼ଘଡ଼",
    ],
    "LIGHTNING": [r"lightning", r"बिजली", r"वज्रपात", r"आकाशीय", r"పిడుగు"],
    "HEAVY_RAIN": [
        r"rain", r"rainfall", r"precipitation", r"वर्षा", r"बारिश",
        r"వర్ష", r"ବର୍ଷା", r"বৃষ্টি",
    ],
    "HEATWAVE": [r"heat\s*wave", r"heatwave", r"लू", r"गर्मी"],
    "COLDWAVE": [r"cold\s*wave", r"coldwave", r"cold\s*day", r"शीत"],
    "DROUGHT": [r"drought", r"सूखा"],
    "FOG": [r"\bfog\b", r"visibility", r"कोहरा"],
    "GALE_WIND": [r"gale", r"gusty\s*wind", r"surface\s*wind", r"तेज़?\s*हवा"],
}

_COMPILED = {
    hazard: [re.compile(p, re.IGNORECASE | re.UNICODE) for p in pats]
    for hazard, pats in _RULES.items()
}

# GDACS uses single-letter event type codes.
GDACS_TYPES = {
    "EQ": "EARTHQUAKE",
    "TC": "CYCLONE",
    "FL": "FLOOD",
    "VO": "OTHER",
    "WF": "FOREST_FIRE",
    "DR": "DROUGHT",
    "TS": "TSUNAMI",
}

# CAP severity -> our scale. CAP's own vocabulary is already close.
CAP_SEVERITY = {
    "extreme": "EXTREME",
    "severe": "SEVERE",
    "moderate": "MODERATE",
    "minor": "MINOR",
    "unknown": "INFO",
}


def classify(*texts: str) -> str:
    """Return the best hazard match across the given texts, first match wins."""
    blob = " ".join(t for t in texts if t)
    if not blob.strip():
        return "OTHER"
    for hazard in HAZARDS:
        for pattern in _COMPILED.get(hazard, []):
            if pattern.search(blob):
                return hazard
    return "OTHER"


def severity_from_magnitude(mag: float) -> str:
    """USGS earthquake magnitude -> our severity scale."""
    if mag >= 7.0:
        return "EXTREME"
    if mag >= 6.0:
        return "SEVERE"
    if mag >= 5.0:
        return "MODERATE"
    if mag >= 4.0:
        return "MINOR"
    return "INFO"


def severity_from_gdacs(alert_level: str) -> str:
    return {"Red": "EXTREME", "Orange": "SEVERE", "Green": "MINOR"}.get(
        (alert_level or "").title(), "INFO"
    )
