"""Detector and alert-rule tests on synthetic SAR backscatter.

Synthetic scenes use gamma-distributed speckle (the physical model for
multilooked SAR intensity) around a land level of -8 dB and a water level of
-20 dB, matching the histogram of real NISAR S-SAR GCOV over Assam.
"""

import numpy as np
import pytest

from nisar_flood.alerts.rules import evaluate
from nisar_flood.detection.classical import ClassicalDetector, water_threshold
from nisar_flood.processing.preprocess import Crop, _multilook

RES = 20.0
PX_KM2 = (RES / 1000) ** 2
SHAPE = (1000, 1000)          # 20 x 20 km
THRESHOLDS = {"watch_km2": 5, "alert_km2": 20, "watch_increase_pct": 25,
              "alert_increase_pct": 75, "min_pct_km2": 1, "min_patch_km2": 2}


def scene(water: np.ndarray, seed: int, looks: int = 8, water_db: float = -20.0) -> Crop:
    rng = np.random.default_rng(seed)
    mean_db = np.where(water, water_db, -8.0) + rng.normal(0, 1.0, SHAPE)
    lin = 10 ** (mean_db / 10) * rng.gamma(looks, 1 / looks, SHAPE)
    return Crop(lin.astype(np.float32), None, 32646, 0.0, 0.0, RES, [])


def river() -> np.ndarray:
    w = np.zeros(SHAPE, bool)
    w[:, 450:520] = True      # 1.4 km wide channel, 28 km2
    return w


def test_recovers_injected_flood_area():
    ref_w = river()
    new_w = ref_w.copy()
    new_w[200:500, 520:820] = True          # 300 x 300 px = 36 km2 flood
    res = ClassicalDetector().detect(scene(ref_w, 1), scene(new_w, 2))
    s = res.summary()
    assert s["new_water_km2"] == pytest.approx(36.0, rel=0.10)
    assert -20 < res.threshold_db < -10
    assert evaluate(s, THRESHOLDS)[0] == "ALERT"


def test_speckle_only_does_not_alert():
    w = river()
    s = ClassicalDetector().detect(scene(w, 3), scene(w, 4)).summary()
    assert s["new_water_km2"] < 1.0
    assert evaluate(s, THRESHOLDS)[0] == "NORMAL"


def test_receding_water_is_not_flooding():
    ref_w = river()
    ref_w[200:500, 520:820] = True
    res = ClassicalDetector().detect(scene(ref_w, 5), scene(river(), 6))
    s = res.summary()
    assert s["new_water_km2"] < 1.0
    assert s["receded_km2"] == pytest.approx(36.0, rel=0.10)


def test_moderate_flood_is_watch():
    new_w = river()
    new_w[100:250, 520:620] = True          # 150 x 100 px = 6 km2
    s = ClassicalDetector().detect(scene(river(), 7), scene(new_w, 8)).summary()
    level, reasons = evaluate(s, THRESHOLDS)
    assert level == "WATCH", (s, reasons)


def test_scattered_change_downgraded_to_watch():
    s = {"new_water_km2": 25.0, "increase_pct": 90.0, "largest_patch_km2": 0.5}
    level, reasons = evaluate(s, THRESHOLDS)
    assert level == "WATCH" and "fragmented" in reasons[0]


def test_threshold_finds_valley_not_land_mode():
    d = 10 * np.log10(scene(river(), 9).hh)
    thr, n = water_threshold([d])
    assert n >= 3 and -18 < thr < -11


def test_high_noise_floor_track():
    # Seen on real NISAR track 112 over Assam: water near -15.5 dB, not -20.
    ref_w = river()
    new_w = ref_w.copy()
    new_w[200:500, 520:820] = True
    res = ClassicalDetector().detect(scene(ref_w, 11, water_db=-15.5),
                                     scene(new_w, 12, water_db=-15.5))
    assert res.summary()["water_ref_km2"] == pytest.approx(28.0, rel=0.15)
    assert res.summary()["new_water_km2"] == pytest.approx(36.0, rel=0.15)


def test_multilook_propagates_nan():
    a = np.ones((4, 4), np.float32)
    a[0, 0] = np.nan
    m = _multilook(a, 2)
    assert np.isnan(m[0, 0]) and np.all(m.ravel()[1:] == 1)


def test_misaligned_crops_rejected():
    a = scene(river(), 1)
    b = Crop(a.hh[:-1], None, 32646, 0, 0, RES, [])
    with pytest.raises(ValueError):
        ClassicalDetector().detect(a, b)


def test_calibration_offset_is_not_a_flood():
    # Whole-scene 2 dB darkening (calibration shift), no new water.
    a = scene(river(), 21)
    b = scene(river(), 22)
    b.hh *= 10 ** (-2.0 / 10)
    res = ClassicalDetector().detect(a, b)
    assert res.offset_db == pytest.approx(-2.0, abs=0.3)
    assert res.summary()["new_water_km2"] < 1.0


def test_offset_correction_keeps_real_flood():
    ref_w = river()
    new_w = ref_w.copy()
    new_w[200:500, 520:820] = True
    b = scene(new_w, 24)
    b.hh *= 10 ** (-1.5 / 10)
    s = ClassicalDetector().detect(scene(ref_w, 23), b).summary()
    assert s["new_water_km2"] == pytest.approx(36.0, rel=0.10)
