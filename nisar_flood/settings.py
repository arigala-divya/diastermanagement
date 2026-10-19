"""Paths, credentials and tunables.

Credentials come from nisar_flood/.env (git-ignored) or the process
environment. Nothing secret is ever written to the database or logs.
"""

import os
import pathlib

from dotenv import load_dotenv

PKG = pathlib.Path(__file__).resolve().parent
load_dotenv(PKG / ".env")

DATA = PKG / "data"
CROPS = DATA / "crops"          # per-hotspot AOI crops, one .npz per scene
RENDERS = DATA / "renders"      # PNG quicklooks served to the UI
INBOX = DATA / "inbox"          # manual provider: drop NISAR GCOV .h5 here
DB_PATH = DATA / "nisar_flood.db"
TOKEN_CACHE = DATA / "bhoonidhi_token.json"
HOTSPOTS_YAML = PKG / "config" / "hotspots.yaml"
FRONTEND = PKG / "frontend"

BHOONIDHI_USER = os.getenv("BHOONIDHI_USER", "")
BHOONIDHI_PASS = os.getenv("BHOONIDHI_PASS", "")
BHOONIDHI_API = "https://bhoonidhi-api.nrsc.gov.in"
BHOONIDHI_COLLECTION = "NISAR_SSAR_GCOV"

# Every crop is brought to one 20 m grid. GCOV comes at 10 m (averaged 2x2,
# which also suppresses speckle) or already at 20 m - a track can alternate
# between the two - and only same-grid crops can be differenced.
TARGET_RES = 20.0

# A crop with less valid (non-NaN) data than this is not analysed: an AOI
# clipped by a swath edge would read as a spurious change in water extent.
MIN_VALID_FRACTION = 0.8

for _d in (DATA, CROPS, RENDERS, INBOX):
    _d.mkdir(parents=True, exist_ok=True)
