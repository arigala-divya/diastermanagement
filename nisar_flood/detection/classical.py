"""Unsupervised SAR flood change detection.

Calm open water is a specular reflector: it bounces the radar pulse away from
the sensor and appears dark (low gamma0). Flooding therefore shows up as land
pixels that drop sharply in backscatter between two passes on the same track.

Method (no training data, sensor-agnostic, so it works on S- and L-band):

  1. Speckle: 3x3 median on dB backscatter.
  2. Water threshold: global Otsu fails when water is a few percent of the
     scene (it splits the land mode instead), so only tiles holding a real
     mix of water and land are used, and the threshold is the valley between
     the water and land peaks of their histogram (Otsu as fallback). One
     threshold is shared by both dates so the two water masks are comparable.
  3. Change: log-ratio d = dB_new - dB_ref. A pixel counts as newly flooded
     only if it is water now, was not water before, and darkened by more than
     `drop_db`. The ratio test rejects pixels that are merely near the
     threshold on both dates.
  4. Clean-up: morphological opening and a minimum patch size, so isolated
     speckle never adds area.
"""

import numpy as np
from scipy import ndimage
from skimage.filters import threshold_otsu

from nisar_flood.detection.base import ChangeResult, Detector
from nisar_flood.processing.preprocess import to_db

THRESHOLD_RANGE = (-24.0, -9.5)
FALLBACK_DB = -16.0
MAX_OFFSET_DB = 3.0          # larger scene-wide shifts are not trusted


def provisional_split(images: list[np.ndarray]) -> float:
    """Rough water/land split used only to pick mixed tiles.

    Midway between the dark tail (1st percentile) and the land mode (median).
    A fixed value does not work: water sits near -20 dB on some tracks but
    near -15 dB on others where the instrument noise floor is higher.
    """
    v = np.concatenate([i[np.isfinite(i)] for i in images])
    if v.size == 0:
        return FALLBACK_DB
    p1, med = np.percentile(v, [1, 50])
    return float((p1 + med) / 2)


def _smooth_db(lin: np.ndarray) -> np.ndarray:
    d = to_db(lin)
    valid = np.isfinite(d)
    filled = np.where(valid, d, np.nanmedian(d) if valid.any() else 0.0)
    out = ndimage.median_filter(filled, size=3)
    out[~valid] = np.nan
    return out


def water_threshold(images: list[np.ndarray], tile: int = 100) -> tuple[float, int]:
    """Water/land threshold from tiles holding both. Returns (dB, n_tiles)."""
    split = provisional_split(images)
    picked = []
    for img in images:
        h, w = img.shape
        for r in range(0, h - tile + 1, tile):
            for c in range(0, w - tile + 1, tile):
                t = img[r:r + tile, c:c + tile]
                v = t[np.isfinite(t)]
                if v.size < 0.9 * tile * tile:
                    continue
                frac = np.mean(v < split)
                if 0.1 <= frac <= 0.9:
                    picked.append(v)
    if len(picked) < 3:
        return FALLBACK_DB, len(picked)
    v = np.concatenate(picked).clip(-30, 5)
    thr = histogram_valley(v)
    if thr is None:
        thr = threshold_otsu(v)
    return float(np.clip(thr, *THRESHOLD_RANGE)), len(picked)


def histogram_valley(v: np.ndarray, bin_db: float = 0.25, min_sep_db: float = 3.0) -> float | None:
    """Minimum of the smoothed histogram between the water and land peaks.

    Otsu minimises within-class variance, which drifts toward the bigger
    class when land dominates even the mixed tiles. The valley between the
    two modes is the physically meaningful split. None if there is no
    distinct water peak (then the caller falls back to Otsu).
    """
    edges = np.arange(-30, 5 + bin_db, bin_db)
    h, _ = np.histogram(v, bins=edges)
    h = ndimage.gaussian_filter1d(h.astype(float), 3)
    centres = (edges[:-1] + edges[1:]) / 2
    # Local maxima, tallest first. Either mode may be the taller one: in
    # mixed tiles over a wide river, water can outnumber land.
    peaks = [i for i in range(1, len(h) - 1) if h[i] >= h[i - 1] and h[i] > h[i + 1]]
    peaks.sort(key=lambda i: -h[i])
    if not peaks:
        return None
    p1 = peaks[0]
    p2 = next((i for i in peaks[1:] if abs(centres[i] - centres[p1]) >= min_sep_db), None)
    if p2 is None or h[p2] < 0.05 * h[p1]:
        return None
    water, land = sorted((p1, p2))
    valley = water + int(np.argmin(h[water:land + 1]))
    # A real valley is clearly lower than the smaller peak.
    if h[valley] > 0.8 * min(h[water], h[land]):
        return None
    return float(centres[valley])


class ClassicalDetector(Detector):
    name = "classical-v2"

    def __init__(self, drop_db: float = 3.0, min_patch_km2: float = 0.05):
        self.drop_db = drop_db
        self.min_patch_km2 = min_patch_km2

    def detect(self, ref, new, threshold_db: float | None = None) -> ChangeResult:
        """`threshold_db`, when given, is the group-wide water threshold (see
        group_threshold); otherwise one is derived from this pair alone."""
        if ref.hh.shape != new.hh.shape:
            raise ValueError(f"crops not aligned: {ref.hh.shape} vs {new.hh.shape}")
        a, b = _smooth_db(ref.hh), _smooth_db(new.hh)
        valid = np.isfinite(a) & np.isfinite(b)
        if threshold_db is None:
            thr, n_tiles = water_threshold([a, b])
            notes = [] if n_tiles >= 3 else ["too few mixed water/land tiles; fallback threshold used"]
        else:
            thr, notes = threshold_db, []

        # Relative radiometric normalisation. Products of one track can differ
        # by a scene-wide calibration offset; uncorrected, that reads as the
        # whole AOI darkening, i.e. a false flood (seen on Ghaghra, 5 Oct 2026).
        # Land that is clearly dry in the baseline is a stable reference: a
        # real flood darkens part of it, an offset shifts all of it, so the
        # median change over it estimates the offset.
        land = valid & (a > thr + 3.0)
        offset = float(np.median((b - a)[land])) if np.count_nonzero(land) > 1000 else 0.0
        unreliable = abs(offset) > MAX_OFFSET_DB
        if abs(offset) > 0.5:
            b = b - offset
            notes.append(f"radiometric offset {offset:+.1f} dB between passes corrected")
        if unreliable:
            notes.append(f"offset exceeds {MAX_OFFSET_DB:.0f} dB: comparison unreliable")

        water_ref = valid & (a < thr)
        water_new = valid & (b < thr)
        drop = valid & ((b - a) < -self.drop_db)

        min_px = max(1, int(round(self.min_patch_km2 / new.pixel_km2)))
        st = ndimage.generate_binary_structure(2, 1)

        def clean(m: np.ndarray) -> np.ndarray:
            m = ndimage.binary_opening(m, structure=st)
            lab, n = ndimage.label(m)
            if n == 0:
                return m
            sizes = np.bincount(lab.ravel())
            keep = sizes >= min_px
            keep[0] = False
            return keep[lab]

        new_water = clean(water_new & ~water_ref & drop)
        receded = clean(water_ref & ~water_new & valid & ((b - a) > self.drop_db))

        lab, n = ndimage.label(new_water)
        largest = int(np.bincount(lab.ravel())[1:].max()) if n else 0

        return ChangeResult(
            detector=self.name, water_ref=water_ref, water_new=water_new,
            new_water=new_water, receded=receded, valid=valid,
            pixel_km2=new.pixel_km2, threshold_db=thr,
            largest_patch_km2=largest * new.pixel_km2, notes=notes,
            offset_db=offset, unreliable=unreliable,
        )


def group_threshold(crops: list) -> float:
    """One water threshold for every pass in a comparison group.

    Per-pair thresholds drift with the pair, so the "same" baseline would show
    a different water extent in each comparison, a real problem where much
    wet land sits near the boundary (e.g. Kosi). Pooling all passes of one
    track+variant gives every pass the same ruler.
    """
    return water_threshold([_smooth_db(c.hh) for c in crops])[0]


def water_fraction(crop, threshold_db: float | None = None) -> float:
    """Share of valid pixels that are water; used to rank candidate baselines."""
    d = _smooth_db(crop.hh)
    if threshold_db is None:
        threshold_db, _ = water_threshold([d])
    v = np.isfinite(d)
    return float(np.mean(d[v] < threshold_db)) if v.any() else float("nan")
