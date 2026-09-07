"""Shared ingestion plumbing.

Every source follows the same contract:

    fetch(client) -> list[Signal]

A Signal is one normalised observation from one source about one hazard in one
place. Signals are later correlated into events; a Signal is never itself an
event, because two agencies reporting the same flood must collapse into one.
"""

import hashlib
import json
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

import httpx

# Government TLS chains are occasionally misconfigured; several of these hosts
# fail verification from some networks. Data is public and read-only, so we
# proceed unverified rather than losing the feed entirely.
VERIFY_TLS = False
TIMEOUT = 60

USER_AGENT = "IIRS-ISRO-DisasterIntelligence/0.1 (internal research dashboard)"


@dataclass
class Signal:
    source: str                 # SACHET | GDACS | USGS | NEWS
    source_uid: str
    hazard_type: str
    headline: str
    severity: str = "INFO"
    agency: str = ""
    tier: int = 1               # 1 official, 2 modelled, 3 reported
    url: str = ""
    published_at: str = ""
    starts_at: str = ""
    expires_at: str = ""
    state: str = ""
    district: str = ""
    lgd_district: int | None = None
    lat: float | None = None
    lon: float | None = None
    licence: str = ""
    raw: str = ""
    raw_uid: str = ""   # parent document key; many signals may share one

    def as_dict(self) -> dict:
        return asdict(self)


def new_client() -> httpx.Client:
    # Government and aggregator endpoints time out intermittently under load;
    # GDACS in particular. Connection-level retries stop a transient blip from
    # marking a healthy feed as failed.
    return httpx.Client(
        timeout=TIMEOUT,
        follow_redirects=True,
        verify=VERIFY_TLS,
        headers={"User-Agent": USER_AGENT},
        transport=httpx.HTTPTransport(retries=2),
    )


def content_hash(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8", "replace")).hexdigest()[:32]


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def to_utc(value) -> str:
    """Best-effort conversion of assorted timestamp formats to UTC ISO-8601."""
    if not value:
        return ""
    if isinstance(value, (int, float)):  # USGS epoch milliseconds
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat(
            timespec="seconds"
        )
    text = str(value).strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(text, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
        except ValueError:
            continue
    try:  # ISO with 'Z' or offset
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
    except ValueError:
        return ""


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)
