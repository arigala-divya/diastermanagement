"""Scene provider contract.

    search(bbox, start, end) -> list[SceneRef]
    open(scene)              -> h5py.File   (NISAR L2 GCOV layout)

Providers differ only in where the HDF5 bytes come from (Bhoonidhi over HTTP
range requests, or a local file dropped into the inbox). Everything after
open() is shared.
"""

from dataclasses import dataclass, field


@dataclass
class SceneRef:
    provider: str            # BHOONIDHI | MANUAL
    scene_id: str
    datetime: str            # acquisition start, UTC ISO-8601
    track: int
    frame: int
    node: str = ""           # Ascending | Descending
    footprint: list = field(default_factory=list)   # [[lon, lat], ...] closed ring
    location: str = ""       # local path for MANUAL
    meta: dict = field(default_factory=dict)


def point_in_ring(lon: float, lat: float, ring: list) -> bool:
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if (y1 > lat) != (y2 > lat):
            if lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
                inside = not inside
    return inside


def covers(footprint: list, bbox: tuple) -> bool:
    """True when all four AOI corners fall inside the scene footprint."""
    if not footprint:
        return True
    w, s, e, n = bbox
    return all(point_in_ring(x, y, footprint) for x, y in ((w, s), (w, n), (e, s), (e, n)))
