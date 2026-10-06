"""Build data/processed/eaton/meta.json and study_area.geojson from Altadena's real boundary.

The study area is the Census 2020 boundary of Altadena (Census Designated Place, GEOID
0601290) plus a 1 km margin (data/BUILD.md). The boundary comes from the US Census Bureau's
TIGERweb service (public domain), so the area is sourced, not drawn by hand.

    uv run python scripts/build_study_area.py
"""

from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request

from backend.store import DATA_DIR, DATASETS

GEOID = "0601290"  # Altadena CDP, California
MARGIN_KM = 1.0  # data/BUILD.md: "study area = Altadena boundary + 1 km"
TIGERWEB = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/"
            "Places_CouSub_ConCity_SubMCD/MapServer/26/query")  # layer 26: Census 2020 CDPs
RAW = DATA_DIR / "raw" / "census" / f"cdp_{GEOID}_2020.geojson"


def download_boundary() -> dict:
    """The CDP outline as GeoJSON (cached in data/raw/, which git ignores)."""
    if not RAW.exists():
        query = urllib.parse.urlencode({
            "where": f"GEOID='{GEOID}'", "outFields": "NAME,GEOID,POP100,AREALAND",
            "returnGeometry": "true", "outSR": "4326", "f": "geojson",
        })
        with urllib.request.urlopen(f"{TIGERWEB}?{query}", timeout=60) as response:
            data = json.load(response)
        if len(data.get("features", [])) != 1:
            raise RuntimeError(f"Expected one boundary for GEOID {GEOID}, got {data}")
        RAW.parent.mkdir(parents=True, exist_ok=True)
        RAW.write_text(json.dumps(data))
    return json.loads(RAW.read_text())


def bbox_with_margin(geometry: dict, margin_km: float) -> dict:
    polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" \
        else [geometry["coordinates"]]
    points = [p for polygon in polygons for ring in polygon for p in ring]
    lons, lats = [p[0] for p in points], [p[1] for p in points]
    mid_lat = (min(lats) + max(lats)) / 2
    dlat = margin_km * 1000 / 110_540
    dlon = margin_km * 1000 / (111_320 * math.cos(math.radians(mid_lat)))
    return {"south": round(min(lats) - dlat, 4), "west": round(min(lons) - dlon, 4),
            "north": round(max(lats) + dlat, 4), "east": round(max(lons) + dlon, 4)}


def main() -> None:
    feature = download_boundary()["features"][0]
    props = feature["properties"]
    out = DATASETS["eaton"]
    out.mkdir(parents=True, exist_ok=True)
    meta = {
        "name": "eaton",
        "synthetic": False,
        "description": "Eaton Fire: real reports, satellites, wind, roads, facilities, orders; "
                       "residents estimated from Census",
        "bbox": bbox_with_margin(feature["geometry"], MARGIN_KM),
        "h3_res": 9,
        "replay": {"start": "2025-01-07T18:00:00-08:00", "end": "2025-01-08T06:00:00-08:00",
                   "step_minutes": 10},
        "study_area": {
            "source": f"US Census Bureau TIGERweb, Census 2020: {props['NAME']} "
                      f"(GEOID {props['GEOID']})",
            "margin_km": MARGIN_KM,
            "population_2020": props["POP100"],
            "outline": "study_area.geojson",
        },
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    (out / "study_area.geojson").write_text(json.dumps(
        {"type": "FeatureCollection", "features": [feature]}) + "\n")
    print(f"Wrote {out / 'meta.json'}: {props['NAME']}, population {props['POP100']:,}, "
          f"bbox {meta['bbox']}")


if __name__ == "__main__":
    main()
