"""AOI extraction from NISAR L2 GCOV HDF5.

GCOV is radiometrically terrain-corrected backscatter (gamma0) on a map grid,
so no SAR processing is needed here, only:

  1. project the AOI into the product's UTM grid and snap it to that grid,
  2. read just the AOI window of the HH (and HV) covariance terms,
  3. average to a common 20 m grid (multilooking: cuts speckle; products
     come at 10 m or 20 m, even on one track).

Every scene in the same track+frame shares one UTM zone and a 10 m grid
snapped to whole metres, so cropping each by the same snapped UTM bounds
yields pixel-aligned arrays that can be differenced directly.
"""

import math
from dataclasses import dataclass

import h5py
import numpy as np
from pyproj import Transformer

from nisar_flood import settings


@dataclass
class Crop:
    hh: np.ndarray            # gamma0 linear power, NaN = no data
    hv: np.ndarray | None
    epsg: int
    x0: float                 # UTM easting of the upper-left pixel's outer corner
    y0: float                 # UTM northing of the upper-left pixel's outer corner
    res: float                # metres per pixel after multilooking
    corners_ll: list          # [[lat, lon] x4] UL, UR, LR, LL - for map overlays

    @property
    def valid_fraction(self) -> float:
        return float(np.mean(np.isfinite(self.hh) & (self.hh > 0)))

    @property
    def pixel_km2(self) -> float:
        return (self.res / 1000.0) ** 2

    def save(self, path) -> None:
        np.savez_compressed(
            path, hh=self.hh.astype(np.float32),
            hv=self.hv.astype(np.float32) if self.hv is not None else np.empty(0, np.float32),
            meta=np.array([self.epsg, self.x0, self.y0, self.res], dtype=np.float64),
            corners_ll=np.array(self.corners_ll, dtype=np.float64),
        )

    @classmethod
    def load(cls, path) -> "Crop":
        z = np.load(path)
        epsg, x0, y0, res = z["meta"]
        hv = z["hv"] if z["hv"].size else None
        return cls(z["hh"], hv, int(epsg), float(x0), float(y0), float(res), z["corners_ll"].tolist())


def _grid(f: h5py.File) -> tuple[str, h5py.Group]:
    for band in ("SSAR", "LSAR"):
        path = f"science/{band}/GCOV/grids/frequencyA"
        if path in f:
            return band, f[path]
    raise ValueError("not a NISAR GCOV product (no science/*/GCOV/grids/frequencyA)")


def scene_identification(f: h5py.File) -> dict:
    """Track/frame/time from the product itself (used by the manual provider)."""
    band, _ = _grid(f)
    ident = f[f"science/{band}/identification"]

    def val(k):
        if k not in ident:
            return None
        v = ident[k][()]
        return v.decode() if isinstance(v, bytes) else v.item() if hasattr(v, "item") else v

    return {
        "track": int(val("trackNumber") or 0),
        "frame": int(val("frameNumber") or 0),
        "datetime": str(val("zeroDopplerStartTime") or ""),
        "node": str(val("orbitPassDirection") or ""),
        "granule": str(val("granuleId") or ""),
    }


def _multilook(a: np.ndarray, k: int) -> np.ndarray:
    if k <= 1:
        return a
    h, w = (a.shape[0] // k) * k, (a.shape[1] // k) * k
    a = a[:h, :w].reshape(h // k, k, w // k, k)
    with np.errstate(invalid="ignore"):
        # Mean of linear power; a block with any NaN becomes NaN so swath
        # edges are never half-averaged into a misleadingly dark pixel.
        return a.mean(axis=(1, 3))


def utm_window(epsg: int, bbox: tuple, step: float) -> tuple[float, float, float, float]:
    """AOI bounds in the product CRS, snapped outward to multiples of `step`."""
    w, s, e, n = bbox
    t = Transformer.from_crs(4326, epsg, always_xy=True)
    xs, ys = t.transform([w, w, e, e], [s, n, s, n])
    return (math.floor(min(xs) / step) * step, math.floor(min(ys) / step) * step,
            math.ceil(max(xs) / step) * step, math.ceil(max(ys) / step) * step)


def chunk_ranges(ds: h5py.Dataset, r0: int, r1: int, c0: int, c1: int) -> list[tuple[int, int]]:
    """File byte ranges of the chunks covering rows r0:r1, cols c0:c1."""
    if ds.chunks is None:
        return []
    ch, cw = ds.chunks
    out = []
    for r in range((r0 // ch) * ch, r1, ch):
        for c in range((c0 // cw) * cw, c1, cw):
            info = ds.id.get_chunk_info_by_coord((r, c))
            if info.byte_offset is not None and info.size:
                out.append((info.byte_offset, info.size))
    return out


def crop_aoi(f: h5py.File, bbox: tuple, target_res: float = settings.TARGET_RES,
             prefetch=None, with_cross_pol: bool = False) -> Crop:
    """Cut the AOI out of a GCOV product.

    `prefetch(ranges)`, when given (remote files), is called with the byte
    ranges of exactly the chunks needed so they can be fetched in a few large
    requests. The cross-pol channel is skipped by default: the detector uses
    only the co-pol (or RV) channel, and skipping it halves the transfer.
    """
    _, g = _grid(f)
    epsg = int(g["projection"][()])
    dx = float(g["xCoordinateSpacing"][()])
    dy = float(g["yCoordinateSpacing"][()])          # negative: north-up
    xc = g["xCoordinates"][()]                       # pixel centres
    yc = g["yCoordinates"][()]
    multilook = max(1, int(round(target_res / abs(dx))))
    res = abs(dx) * multilook

    xmin, ymin, xmax, ymax = utm_window(epsg, bbox, res)
    # Pixel edges are centre +/- half a pixel.
    c0 = int(round((xmin - (xc[0] - dx / 2)) / dx))
    r0 = int(round((ymax - (yc[0] - dy / 2)) / dy))
    ncol = int(round((xmax - xmin) / abs(dx)))
    nrow = int(round((ymax - ymin) / abs(dy)))

    def read(name: str) -> np.ndarray | None:
        if name not in g:
            return None
        out = np.full((nrow, ncol), np.nan, dtype=np.float32)
        rr0, cc0 = max(r0, 0), max(c0, 0)
        rr1, cc1 = min(r0 + nrow, len(yc)), min(c0 + ncol, len(xc))
        if rr1 > rr0 and cc1 > cc0:
            if prefetch is not None:
                prefetch(chunk_ranges(g[name], rr0, rr1, cc0, cc1))
            out[rr0 - r0:rr1 - r0, cc0 - c0:cc1 - c0] = g[name][rr0:rr1, cc0:cc1]
        out[~(out > 0)] = np.nan
        return _multilook(out, multilook)

    # Primary channel: a co-pol term for dual/quad-pol products, or for
    # compact-pol (circular transmit, CRNA products) the RV term. Calm water
    # is dark in all of them; only same-track scenes are ever compared, and a
    # track keeps one polarisation mode.
    primary = next((n for n in ("HHHH", "VVVV", "RVRV", "RHRH") if n in g), None)
    if primary is None:
        raise ValueError(f"no usable backscatter term in {sorted(g.keys())}")
    secondary = next((n for n in ("HVHV", "VHVH", "RHRH") if n in g and n != primary), None)
    hh = read(primary)
    hv = read(secondary) if secondary and with_cross_pol else None

    inv = Transformer.from_crs(epsg, 4326, always_xy=True)
    xe = xmin + hh.shape[1] * res
    ye = ymax - hh.shape[0] * res
    lons, lats = inv.transform([xmin, xe, xe, xmin], [ymax, ymax, ye, ye])
    corners = [[la, lo] for lo, la in zip(lons, lats)]
    return Crop(hh, hv, epsg, xmin, ymax, res, corners)


def to_db(a: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return 10.0 * np.log10(a)
