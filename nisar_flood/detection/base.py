"""Detector contract.

    detect(ref, new) -> ChangeResult

`ref` and `new` are pixel-aligned Crops of the same AOI from the same orbit
track. Any detector (classical thresholding today, a U-Net later) returns the
same ChangeResult, so alert rules, storage and the UI never change.
"""

from dataclasses import dataclass, field

import numpy as np


@dataclass
class ChangeResult:
    detector: str
    water_ref: np.ndarray        # bool masks, same shape as the crops
    water_new: np.ndarray
    new_water: np.ndarray        # flooded: water now, dry in reference
    receded: np.ndarray          # water in reference, dry now
    valid: np.ndarray
    pixel_km2: float
    threshold_db: float | None = None
    largest_patch_km2: float = 0.0
    notes: list[str] = field(default_factory=list)
    offset_db: float = 0.0       # scene-wide radiometric offset removed (new - ref)
    unreliable: bool = False     # pair too inconsistent to raise alerts on

    def km2(self, mask: np.ndarray) -> float:
        return float(np.count_nonzero(mask & self.valid)) * self.pixel_km2

    def summary(self) -> dict:
        ref_km2 = self.km2(self.water_ref)
        new_km2 = self.km2(self.water_new)
        return {
            "detector": self.detector,
            "threshold_db": None if self.threshold_db is None else round(self.threshold_db, 2),
            "valid_km2": round(self.km2(self.valid), 2),
            "water_ref_km2": round(ref_km2, 2),
            "water_new_km2": round(new_km2, 2),
            "new_water_km2": round(self.km2(self.new_water), 2),
            "receded_km2": round(self.km2(self.receded), 2),
            "increase_pct": round(100.0 * (new_km2 - ref_km2) / max(ref_km2, 0.5), 1),
            "largest_patch_km2": round(self.largest_patch_km2, 2),
        }


class Detector:
    name = "base"

    def detect(self, ref, new) -> ChangeResult:
        raise NotImplementedError
