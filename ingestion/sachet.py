"""NDMA SACHET — the CAP backbone.

SACHET is the single most valuable V1 source: it carries alerts from IMD's
regional offices, CWC, INCOIS and the state SDMAs in one CAP 1.2 feed, with
no authentication. It therefore delivers IMD and CWC content even though
api.imd.gov.in itself returns HTTP 401 without a key.

Two properties make it unusually good to work with:
  * every alert carries <cap:geocode> LGD District Code, the same key our
    gazetteer is built on, so district resolution is exact rather than fuzzy.
  * <cap:event> is English even when the public headline is in a regional
    language, which is what we classify on.
"""

import xml.etree.ElementTree as ET

import feedparser

from ingestion.base import Signal, content_hash, log, to_utc
from processing.taxonomy import CAP_SEVERITY, classify

RSS_URL = "https://sachet.ndma.gov.in/cap_public_website/rss/rss_india.xml"
CAP_NS = {"cap": "urn:oasis:names:tc:emergency:cap:1.2"}
LICENCE = "NDMA SACHET - public CAP feed, attribution required"

# Agencies that appear as CAP senders, mapped to a friendlier display name.
_AGENCY_CLEAN = str.maketrans({"(": "", ")": ""})


def _text(node, path: str) -> str:
    found = node.find(path, CAP_NS)
    return (found.text or "").strip() if found is not None and found.text else ""


def _agency_from_author(author: str) -> str:
    """'controlroom@ndma.gov.in (IMD Ranchi)' -> 'IMD Ranchi'."""
    if "(" in author and ")" in author:
        return author[author.index("(") + 1 : author.rindex(")")].strip()
    return author.translate(_AGENCY_CLEAN).strip()


def _parse_cap(xml_text: str):
    """Extract the fields we need from one CAP alert document."""
    root = ET.fromstring(xml_text)
    info = root.find("cap:info", CAP_NS)
    if info is None:
        return None

    lgd_codes = []
    area_desc = ""
    area = info.find("cap:area", CAP_NS)
    if area is not None:
        area_desc = _text(area, "cap:areaDesc")
        for geocode in area.findall("cap:geocode", CAP_NS):
            name = _text(geocode, "cap:valueName")
            value = _text(geocode, "cap:value")
            if "LGD" in name.upper() and value.isdigit():
                lgd_codes.append(int(value))

    return {
        "identifier": _text(root, "cap:identifier"),
        "sender": _text(root, "cap:sender"),
        "sent": _text(root, "cap:sent"),
        "event": _text(info, "cap:event"),
        "headline": _text(info, "cap:headline"),
        "description": _text(info, "cap:description"),
        "severity": _text(info, "cap:severity"),
        "effective": _text(info, "cap:effective"),
        "expires": _text(info, "cap:expires"),
        "area_desc": area_desc,
        "lgd_codes": lgd_codes,
    }


def signals_from_cap(xml_text: str, url: str, districts: dict, author: str = "") -> list[Signal]:
    """Build signals from one CAP document.

    Kept separate from fetch() so replay() can rebuild events from stored raw
    documents without any network access.
    """
    cap = _parse_cap(xml_text)
    if not cap:
        return []

    agency = _agency_from_author(author) or cap["sender"]
    hazard = classify(cap["event"], cap["headline"])
    severity = CAP_SEVERITY.get(cap["severity"].lower(), "INFO")
    published = to_utc(cap["sent"])

    targets = [d for d in (districts.get(str(c)) for c in cap["lgd_codes"]) if d]
    unresolved = [c for c in cap["lgd_codes"] if str(c) not in districts]
    if unresolved:
        # Visible gap rather than a silent mis-placement. Sikkim and Ladakh
        # codes are the known offenders; see scripts/build_gazetteer.py.
        log(f"  SACHET: unresolved LGD codes {unresolved} in {cap['identifier']}")
    if not targets:
        targets = [None]

    out = []
    for target in targets:
        out.append(
            Signal(
                source="SACHET",
                source_uid=f"{cap['identifier']}::{target['lgd'] if target else 'na'}",
                raw_uid=cap["identifier"],
                hazard_type=hazard,
                headline=cap["headline"] or cap["event"],
                severity=severity,
                agency=agency,
                tier=1,
                url=url,
                published_at=published,
                starts_at=to_utc(cap["effective"]),
                expires_at=to_utc(cap["expires"]),
                state=target["state"] if target else "",
                district=target["district"] if target else "",
                lgd_district=target["lgd"] if target else None,
                lat=target["lat"] if target else None,
                lon=target["lon"] if target else None,
                licence=LICENCE,
                raw=xml_text,
            )
        )
    return out


def fetch(client, districts: dict, limit: int | None = None) -> list[Signal]:
    resp = client.get(RSS_URL)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)

    signals: list[Signal] = []
    entries = feed.entries[:limit] if limit else feed.entries

    for entry in entries:
        link = entry.get("link", "")
        if not link:
            continue
        try:
            cap_resp = client.get(link)
            cap_resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001 - one bad alert must not kill the run
            log(f"  SACHET: skipped {entry.get('guid','?')}: {type(exc).__name__}")
            continue
        signals.extend(
            signals_from_cap(cap_resp.text, link, districts, entry.get("author", ""))
        )
    return signals
