"""Build the LGD-keyed district gazetteer + state boundaries.

Run once (or when districts change). Produces two committed assets:

  data/districts.json  - LGD district code -> name, state, centroid
  data/states.geojson  - state/UT polygons keyed on LGD state code

Source: datta07/INDIAN-SHAPEFILES, which carries Survey of India derived
boundaries including J&K, Ladakh and Arunachal Pradesh per the official
Indian position. The per-state "District Hq" point files are used rather
than the 77MB district polygon file because they already carry Dist_LGD,
which is the exact geocode SACHET CAP alerts use.
"""

import json
import pathlib
import urllib.parse

import httpx

REPO = "https://raw.githubusercontent.com/datta07/INDIAN-SHAPEFILES/master"
TREE = "https://api.github.com/repos/datta07/INDIAN-SHAPEFILES/git/trees/master?recursive=1"
DATA = pathlib.Path(__file__).resolve().parent.parent / "data"

# The upstream shapefiles carry historic state names. SACHET and the state
# boundary file use current ones, so normalise or the state filter silently
# fails to join.
STATE_ALIASES = {
    "Orissa": "Odisha",
    "Pondicherry": "Puducherry",
    "Uttaranchal": "Uttarakhand",
    "Dadra & Nagar Have": "Dadra & Nagar Haveli",
    "Nct Of Delhi": "Delhi",
}

# Sikkim and Ladakh have null properties in the upstream District Hq files, so
# they are supplied here from district headquarters coordinates. Their LGD
# codes are deliberately left null rather than guessed: a wrong LGD code would
# silently place an alert in the wrong district, which is worse than not
# resolving it. Coordinate-based sources (USGS, GDACS) still snap to these
# correctly. To complete SACHET coverage for these two UTs, look the codes up
# at lgdirectory.gov.in and add them keyed by code.
SUPPLEMENT = [
    ("Gangtok", "Sikkim", 27.3314, 88.6138),
    ("Mangan", "Sikkim", 27.5089, 88.5222),
    ("Namchi", "Sikkim", 27.1667, 88.3667),
    ("Gyalshing", "Sikkim", 27.2833, 88.2667),
    ("Pakyong", "Sikkim", 27.2333, 88.5833),
    ("Soreng", "Sikkim", 27.1833, 88.2333),
    ("Leh", "Ladakh", 34.1526, 77.5771),
    ("Kargil", "Ladakh", 34.5539, 76.1349),
]


def district_hq_paths(client):
    """Every 'District Hq.geojson' path in the repo, one per state/UT."""
    tree = client.get(TREE, timeout=60).json()["tree"]
    return sorted(n["path"] for n in tree if n["path"].endswith("District Hq.geojson"))


def build_districts(client):
    districts = {}
    skipped = []
    for path in district_hq_paths(client):
        url = f"{REPO}/{urllib.parse.quote(path)}"
        try:
            fc = client.get(url, timeout=90).json()
        except Exception as exc:  # noqa: BLE001 - report and continue
            skipped.append(f"{path}: {type(exc).__name__}")
            continue
        for feat in fc.get("features", []):
            props = feat.get("properties") or {}
            lgd = props.get("Dist_LGD")
            geom = feat.get("geometry") or {}
            if not lgd or geom.get("type") != "Point":
                continue
            lon, lat = geom["coordinates"][:2]
            state = (props.get("STNAME") or "").strip().title()
            districts[str(int(lgd))] = {
                "lgd": int(lgd),
                "district": (props.get("DTNAME") or "").strip(),
                "state": STATE_ALIASES.get(state, state),
                "lat": round(float(lat), 5),
                "lon": round(float(lon), 5),
            }
    for name, state, lat, lon in SUPPLEMENT:
        districts[f"{state[:2].upper()}-{name.upper()}"] = {
            "lgd": None,
            "district": name,
            "state": state,
            "lat": lat,
            "lon": lon,
        }
    return districts, skipped


def build_states(client):
    fc = client.get(f"{REPO}/INDIA/INDIA_STATES.geojson", timeout=180).json()
    for feat in fc.get("features", []):
        props = feat.get("properties") or {}
        raw_name = (props.get("STNAME_SH") or props.get("STNAME") or "").strip().title()
        feat["properties"] = {
            "state": STATE_ALIASES.get(raw_name, raw_name),
            "state_lgd": props.get("State_LGD"),
        }
    return fc


def main():
    DATA.mkdir(exist_ok=True)
    with httpx.Client(follow_redirects=True, verify=False) as client:
        districts, skipped = build_districts(client)
        (DATA / "districts.json").write_text(
            json.dumps(districts, indent=1, ensure_ascii=False), encoding="utf-8"
        )
        print(f"districts.json  {len(districts)} districts")
        for s in skipped:
            print(f"  skipped {s}")

        states = build_states(client)
        (DATA / "states.geojson").write_text(
            json.dumps(states, ensure_ascii=False), encoding="utf-8"
        )
        names = sorted(f["properties"]["state"] for f in states["features"])
        print(f"states.geojson  {len(names)} states/UTs")
        print("  " + ", ".join(names))


if __name__ == "__main__":
    main()
