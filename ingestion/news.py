"""Indian news RSS - the 'reported' tier.

News never creates an official disaster. Articles enter at tier 3 and surface
as REPORTED confidence unless an official agency independently describes the
same hazard in the same place, in which case correlation merges them and the
event is upgraded. That separation is the point: staff must be able to tell
"IMD issued a warning" from "a newspaper says something is happening".

Only link, headline, publisher and a short snippet are stored. Full article
text is never retained - it is copyrighted, and this is a government system.
"""

import html
import re

import feedparser

from ingestion.base import Signal, log, to_utc
from processing.geo import locate_free_text
from processing.taxonomy import classify

LICENCE = "Headline and link only; copyright remains with the publisher"

# Google News search feeds give far better signal-to-noise than general
# national feeds, because the hazard term is in the query itself.
GOOGLE = "https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
QUERIES = [
    "flood+India", "cyclone+India", "earthquake+India", "landslide+India",
    "forest+fire+India", "heavy+rainfall+India", "cloudburst+India",
    "heatwave+India", "drought+India", "lightning+deaths+India",
]

# General national feeds, keyword-filtered below.
OUTLETS = [
    ("The Hindu", "https://www.thehindu.com/news/national/feeder/default.rss"),
    ("NDTV", "https://feeds.feedburner.com/ndtvnews-india-news"),
    ("Times of India", "https://timesofindia.indiatimes.com/rssfeeds/-2128936835.cms"),
]

# Neighbouring-country coverage dominates these feeds during a regional
# disaster (Nepal's floods produced most of the first run's results). Such a
# story is dropped unless an Indian state or district is also named, so the
# dashboard stays about India.
FOREIGN = re.compile(
    r"nepal|pakistan|bangladesh|china|afghan|sri\s*lanka|myanmar|bhutan|"
    r"maldives|indonesia|philippines|japan|vietnam",
    re.IGNORECASE,
)

# A headline must look hazard-related before we consider it at all.
RELEVANT = re.compile(
    r"flood|cyclone|earthquake|landslide|cloudburst|heat\s*wave|cold\s*wave|"
    r"drought|lightning|thunderstorm|heavy\s+rain|downpour|deluge|inundat|"
    r"forest\s*fire|wildfire|avalanche|tsunami|storm|rainfall|waterlogg",
    re.IGNORECASE,
)


def _clean(text: str) -> str:
    return re.sub(r"<[^>]+>", "", html.unescape(text or "")).strip()


def _publisher(entry, fallback: str = "") -> str:
    src = entry.get("source")
    if isinstance(src, dict) and src.get("title"):
        return src["title"]
    # Google News appends " - Publisher" to the headline.
    title = entry.get("title", "")
    if " - " in title:
        return title.rsplit(" - ", 1)[1].strip()
    return fallback


def _headline(entry) -> str:
    title = _clean(entry.get("title", ""))
    return title.rsplit(" - ", 1)[0].strip() if " - " in title else title


def fetch(client, districts: dict, limit_per_feed: int = 25) -> list[Signal]:
    seen: set[str] = set()
    signals: list[Signal] = []

    feeds = [(GOOGLE.format(q=q), "") for q in QUERIES]
    feeds += [(url, name) for name, url in OUTLETS]

    for url, outlet in feeds:
        try:
            resp = client.get(url)
            resp.raise_for_status()
            parsed = feedparser.parse(resp.content)
        except Exception as exc:  # noqa: BLE001 - one dead feed must not stop the rest
            log(f"  NEWS: {outlet or url[:48]} failed: {type(exc).__name__}")
            continue

        for entry in parsed.entries[:limit_per_feed]:
            link = entry.get("link", "")
            headline = _headline(entry)
            if not link or not headline or link in seen:
                continue
            if not RELEVANT.search(headline):
                continue
            seen.add(link)

            hazard = classify(headline)
            if hazard == "OTHER":
                continue

            state, district, lat, lon = locate_free_text(headline, districts)

            # Must be placeable in India. An unplaceable headline cannot be
            # correlated with an official alert or shown on the map, and a
            # foreign story is not this dashboard's subject.
            if not state:
                continue
            if FOREIGN.search(headline) and not district:
                continue

            snippet = _clean(entry.get("summary", ""))[:280]

            signals.append(
                Signal(
                    source="NEWS",
                    source_uid=link,
                    hazard_type=hazard,
                    headline=headline,
                    severity="INFO",          # news carries no calibrated severity
                    agency=_publisher(entry, outlet),
                    tier=3,
                    url=link,
                    published_at=to_utc(entry.get("published", "")),
                    state=state,
                    district=district,
                    lat=lat,
                    lon=lon,
                    licence=LICENCE,
                    raw=snippet,
                )
            )
    return signals
