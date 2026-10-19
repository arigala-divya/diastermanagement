"""Bhoonidhi (NRSC) provider for NISAR S-SAR L2 GCOV.

Uses the official Bhoonidhi API (https://bhoonidhi.nrsc.gov.in/bhoonidhi-api/):
JWT auth, STAC search, and a download endpoint that honours HTTP Range.

A full GCOV frame is ~12 GB, so scenes are never downloaded whole. The HDF5
file is opened remotely through RemoteFile, a seekable file object that turns
h5py's reads into ranged GETs. Datasets are stored as 512x512 gzip chunks, so
reading one 30 km AOI touches only a few dozen chunks plus the file metadata
(~70 MB per scene instead of 12 GB).

API limits honoured here: 20 token requests/hour/IP (tokens are cached on
disk and refreshed rather than re-issued), 3 search requests/second, and 5
concurrent downloads (all reads are sequential).
"""

import io
import json
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

import h5py
import httpx

from ingestion.base import log
from nisar_flood import settings
from nisar_flood.acquisition.base import SceneRef

TIMEOUT = 120


class BhoonidhiError(RuntimeError):
    pass


class Session:
    """Token lifecycle: reuse cached access token, else refresh, else log in."""

    def __init__(self, client: httpx.Client):
        self.client = client
        self.tok: dict = {}
        try:
            self.tok = json.loads(settings.TOKEN_CACHE.read_text())
        except (OSError, ValueError):
            pass

    def _store(self, tok: dict) -> None:
        tok["obtained_at"] = time.time()
        self.tok = tok
        settings.TOKEN_CACHE.write_text(json.dumps(tok))

    def _valid(self) -> bool:
        if not self.tok.get("access_token"):
            return False
        if self.tok.get("userId") != settings.BHOONIDHI_USER:
            return False
        age = time.time() - self.tok.get("obtained_at", 0)
        return age < float(self.tok.get("expires_in", 0)) - 60

    def _auth(self, body: dict) -> httpx.Response:
        return self.client.post(f"{settings.BHOONIDHI_API}/auth/token", json=body)

    def token(self, force: bool = False) -> str:
        if not force and self._valid():
            return self.tok["access_token"]
        if self.tok.get("refresh_token") and self.tok.get("userId") == settings.BHOONIDHI_USER:
            r = self._auth({"userId": settings.BHOONIDHI_USER,
                            "refresh_token": self.tok["refresh_token"],
                            "grant_type": "refresh_token"})
            if r.status_code == 200:
                self._store(r.json())
                return self.tok["access_token"]
        if not (settings.BHOONIDHI_USER and settings.BHOONIDHI_PASS):
            raise BhoonidhiError("BHOONIDHI_USER / BHOONIDHI_PASS not set in nisar_flood/.env")
        r = self._auth({"userId": settings.BHOONIDHI_USER,
                        "password": settings.BHOONIDHI_PASS,
                        "grant_type": "password"})
        if r.status_code != 200:
            raise BhoonidhiError(f"Bhoonidhi login failed: HTTP {r.status_code} {r.text[:200]}")
        self._store(r.json())
        return self.tok["access_token"]

    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token()}"}

    def request(self, method: str, url: str, headers: dict | None = None, **kw) -> httpx.Response:
        """Authenticated request with re-auth on 401 and backoff on 5xx/429."""
        for attempt in range(5):
            try:
                r = self.client.request(method, url, headers={**(headers or {}), **self.headers()}, **kw)
            except httpx.TransportError as e:
                log(f"bhoonidhi: {type(e).__name__}, retrying")
                time.sleep(min(60, 5 * 2 ** attempt))
                continue
            if r.status_code == 401:
                self.token(force=True)
                continue
            if r.status_code in (412, 429, 500, 502, 503, 504):
                time.sleep(min(60, 5 * 2 ** attempt))
                continue
            return r
        raise BhoonidhiError(f"{method} {url}: gave up after retries")


class RemoteFile(io.RawIOBase):
    """Read-only, seekable view of a Bhoonidhi product over HTTP Range."""

    BLOCK = 1 << 20          # 1 MiB per ranged GET for metadata reads
    MAX_BLOCKS = 768         # LRU cap: 768 MiB

    def __init__(self, session: Session, item_id: str):
        self.s = session
        self.params = {"id": item_id, "collection": settings.BHOONIDHI_COLLECTION}
        self.url = f"{settings.BHOONIDHI_API}/download"
        self.pos = 0
        self.cache: OrderedDict[int, bytes] = OrderedDict()
        self.requests = 0
        self.bytes = 0
        r = self.s.request("GET", self.url, params=self.params, headers={"Range": "bytes=0-0"})
        if r.status_code != 206:
            raise BhoonidhiError(f"{item_id}: range read refused (HTTP {r.status_code}) {r.text[:200]}")
        self.size = int(r.headers["content-range"].split("/")[-1])

    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.pos

    def seek(self, off, whence=io.SEEK_SET):
        if whence == io.SEEK_SET:
            self.pos = off
        elif whence == io.SEEK_CUR:
            self.pos += off
        else:
            self.pos = self.size + off
        return self.pos

    def _block(self, b: int) -> bytes:
        if b in self.cache:
            self.cache.move_to_end(b)
            return self.cache[b]
        lo = b * self.BLOCK
        hi = min(lo + self.BLOCK, self.size) - 1
        r = self.s.request("GET", self.url, params=self.params, headers={"Range": f"bytes={lo}-{hi}"})
        if r.status_code != 206 or len(r.content) != hi - lo + 1:
            raise BhoonidhiError(f"range {lo}-{hi}: HTTP {r.status_code}, {len(r.content)} bytes")
        self.requests += 1
        self.bytes += len(r.content)
        self.cache[b] = r.content
        if len(self.cache) > self.MAX_BLOCKS:
            self.cache.popitem(last=False)
        return r.content

    def prefetch(self, ranges: list[tuple[int, int]], gap: int = 1 << 20, max_span: int = 48 << 20) -> None:
        """Warm the cache for known (offset, size) byte ranges in few requests.

        Each request pays ~1.2 s of latency, so h5py's natural pattern (one
        small read per chunk) runs at ~0.6 MB/s; merged spans of tens of MB
        reach the link's bandwidth. Spans are block-aligned so the bytes land
        in the same cache h5py reads from.
        """
        blocks = sorted({b for off, size in ranges
                         for b in range(off // self.BLOCK, (off + size - 1) // self.BLOCK + 1)
                         if b not in self.cache})
        spans: list[list[int]] = []
        for b in blocks:
            if spans and (b - spans[-1][1]) * self.BLOCK <= gap and \
                    (b - spans[-1][0] + 1) * self.BLOCK <= max_span:
                spans[-1][1] = b
            else:
                spans.append([b, b])
        for b0, b1 in spans:
            lo = b0 * self.BLOCK
            hi = min((b1 + 1) * self.BLOCK, self.size) - 1
            r = self.s.request("GET", self.url, params=self.params, headers={"Range": f"bytes={lo}-{hi}"})
            if r.status_code != 206 or len(r.content) != hi - lo + 1:
                raise BhoonidhiError(f"range {lo}-{hi}: HTTP {r.status_code}, {len(r.content)} bytes")
            self.requests += 1
            self.bytes += len(r.content)
            data = r.content
            for b in range(b0, b1 + 1):
                self.cache[b] = data[(b - b0) * self.BLOCK:(b - b0 + 1) * self.BLOCK]
            while len(self.cache) > self.MAX_BLOCKS:
                self.cache.popitem(last=False)

    def readinto(self, buf) -> int:
        want = max(0, min(len(buf), self.size - self.pos))
        done = 0
        while done < want:
            b, off = divmod(self.pos, self.BLOCK)
            piece = self._block(b)[off:off + want - done]
            buf[done:done + len(piece)] = piece
            done += len(piece)
            self.pos += len(piece)
        return done


def _windows(start: str, end: str, days: int = 360):
    """The search API rejects ranges over 366 days; split longer ones."""
    a = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    b = datetime.fromisoformat(end).replace(tzinfo=timezone.utc)
    while a < b:
        c = min(a + timedelta(days=days), b)
        yield a.strftime("%Y-%m-%dT%H:%M:%SZ"), c.strftime("%Y-%m-%dT%H:%M:%SZ")
        a = c


class BhoonidhiProvider:
    name = "BHOONIDHI"

    def __init__(self):
        self.client = httpx.Client(timeout=TIMEOUT, verify=False, follow_redirects=True)
        self.session = Session(self.client)

    def search(self, bbox: tuple, start: str, end: str) -> list[SceneRef]:
        out: dict[str, SceneRef] = {}
        for a, b in _windows(start, end):
            body = {
                "collections": [settings.BHOONIDHI_COLLECTION],
                "bbox": list(bbox),
                "datetime": f"{a}/{b}",
                "filter": {"op": "eq", "args": [{"property": "Online"}, "Y"]},
                "filter-lang": "cql2-json",
                "limit": 500,
            }
            url = f"{settings.BHOONIDHI_API}/data/search"
            while url:
                r = self.session.request("POST", url, json=body)
                if r.status_code != 200:
                    raise BhoonidhiError(f"search HTTP {r.status_code}: {r.text[:300]}")
                d = r.json()
                for f in d.get("features", []):
                    p = f["properties"]
                    ring = f.get("geometry", {}).get("coordinates", [[]])[0]
                    parts = f["id"].split("_")
                    out[f["id"]] = SceneRef(
                        provider=self.name, scene_id=f["id"],
                        datetime=p["datetime"].replace("Z", "+00:00"),
                        track=int(p.get("Track", 0)), frame=int(p.get("Frame", 0)),
                        node=p.get("Node", ""), footprint=ring,
                        meta={**{k: p.get(k) for k in ("Polarization", "Mode", "IncidenceAngle",
                                                       "Look_dir", "CycleNumber", "Coverage")},
                              # product variant field of the id, e.g. 3700 / 2500
                              "variant": parts[8] if len(parts) > 8 else ""},
                    )
                nxt = next((l for l in d.get("links", []) if l.get("rel") == "next"), None)
                url = nxt["href"] if nxt else None
                body = nxt.get("body", body) if nxt else body
                time.sleep(0.4)
        return sorted(out.values(), key=lambda s: s.datetime)

    def open(self, scene: SceneRef) -> h5py.File:
        rf = RemoteFile(self.session, scene.scene_id)
        f = h5py.File(rf, "r")
        self.last_remote = rf  # transfer statistics for logging
        return f
