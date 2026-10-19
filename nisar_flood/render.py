"""PNG quicklooks for the UI.

before/after: greyscale HH backscatter, -25..0 dB (water black, land grey).
change: transparent overlay; red = new water, blue = water on both dates,
yellow = receded water.
"""

import numpy as np
from PIL import Image

from nisar_flood.detection.base import ChangeResult
from nisar_flood.processing.preprocess import to_db

MAX_PX = 1000


def _save(img: Image.Image, path) -> None:
    if max(img.size) > MAX_PX:
        s = MAX_PX / max(img.size)
        img = img.resize((round(img.width * s), round(img.height * s)), Image.NEAREST)
    img.save(path, optimize=True)


def backscatter_png(lin: np.ndarray, path) -> None:
    d = to_db(lin)
    g = ((np.nan_to_num(d, nan=-25).clip(-25, 0) + 25) / 25 * 255).astype(np.uint8)
    a = np.where(np.isfinite(d), 255, 0).astype(np.uint8)
    _save(Image.fromarray(np.dstack([g, g, g, a]), "RGBA"), path)


def change_png(res: ChangeResult, path) -> None:
    h, w = res.new_water.shape
    rgba = np.zeros((h, w, 4), np.uint8)
    rgba[res.water_ref & res.water_new] = (37, 99, 235, 170)
    rgba[res.receded] = (234, 179, 8, 200)
    rgba[res.new_water] = (220, 38, 38, 230)
    _save(Image.fromarray(rgba, "RGBA"), path)
