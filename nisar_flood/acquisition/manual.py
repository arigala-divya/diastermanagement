"""Manual provider: NISAR GCOV .h5 files dropped into nisar_flood/data/inbox/.

A fallback for when the API is down or a scene must be ordered offline via
Bhoonidhi Browse & Order. The product's own identification group supplies
track, frame and time; coverage is judged after cropping (valid fraction).
"""

import h5py

from nisar_flood.acquisition.base import SceneRef
from nisar_flood.processing.preprocess import scene_identification
from nisar_flood.settings import INBOX


class ManualProvider:
    name = "MANUAL"

    def search(self, bbox: tuple, start: str, end: str) -> list[SceneRef]:
        out = []
        for path in sorted(INBOX.glob("*.h5")):
            try:
                with h5py.File(path, "r") as f:
                    ident = scene_identification(f)
            except (OSError, ValueError, KeyError):
                continue
            dt = ident["datetime"][:19] + "+00:00"
            if not (start <= dt[:10] <= end):
                continue
            out.append(SceneRef(
                provider=self.name, scene_id=path.stem, datetime=dt,
                track=ident["track"], frame=ident["frame"], node=ident["node"],
                location=str(path),
            ))
        return sorted(out, key=lambda s: s.datetime)

    def open(self, scene: SceneRef) -> h5py.File:
        return h5py.File(scene.location, "r")
