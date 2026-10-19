"""Hotspot definitions loaded from config/hotspots.yaml."""

import math
from dataclasses import dataclass, field

import yaml

from nisar_flood.settings import HOTSPOTS_YAML


@dataclass
class Hotspot:
    id: str
    river: str
    name: str
    state: str
    lat: float
    lon: float
    half_km: float
    history_start: str
    baseline_months: list[int]
    thresholds: dict = field(default_factory=dict)

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """(west, south, east, north) in degrees."""
        dlat = self.half_km / 111.32
        dlon = self.half_km / (111.32 * math.cos(math.radians(self.lat)))
        return (self.lon - dlon, self.lat - dlat, self.lon + dlon, self.lat + dlat)

    def as_dict(self) -> dict:
        return {
            "id": self.id, "river": self.river, "name": self.name,
            "state": self.state, "lat": self.lat, "lon": self.lon,
            "half_km": self.half_km, "bbox": self.bbox,
            "thresholds": self.thresholds,
        }


def load_hotspots() -> list[Hotspot]:
    cfg = yaml.safe_load(HOTSPOTS_YAML.read_text(encoding="utf-8"))
    d = cfg.get("defaults", {})
    out = []
    for h in cfg["hotspots"]:
        thresholds = {**d.get("thresholds", {}), **h.get("thresholds", {})}
        out.append(Hotspot(
            id=h["id"], river=str(h["river"]), name=str(h["name"]),
            state=str(h["state"]), lat=float(h["lat"]), lon=float(h["lon"]),
            half_km=float(h.get("half_km", d.get("half_km", 15))),
            history_start=str(h.get("history_start", d.get("history_start", "2026-01-01"))),
            baseline_months=list(h.get("baseline_months", d.get("baseline_months", []))),
            thresholds=thresholds,
        ))
    return out
