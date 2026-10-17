"""Build a dataset's meta.json and study area from real boundaries.

eaton: the Census 2020 boundary of Altadena (Census Designated Place, GEOID 0601290) plus a
1 km margin (data/BUILD.md).
palisades (the forecast development set): the extent of CAL FIRE's damage inspections plus
2 km (scripts/fires.py), land only: cells whose centre falls in the Census cartographic
boundary of Los Angeles County, which is cut at the shoreline. Sea cells would count as places
the fire "never reached" and flatter the forecast.

Boundaries come from the US Census Bureau's TIGERweb service (public domain), so the areas are
sourced, not drawn by hand.

    uv run python scripts/build_study_area.py                    # eaton
    uv run python scripts/build_study_area.py --fire palisades
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import h3

from backend.knowledge import _inside
from backend.store import DATA_DIR, DATASETS, grid_cells

sys.path.insert(0, str(Path(__file__).parent))
from fires import FIRES, fire_arg  # noqa: E402

GEOID = "0601290"  # Altadena CDP, California
MARGIN_KM = 1.0  # data/BUILD.md: "study area = Altadena boundary + 1 km"
# Ignition, the lower bound of every arrival window (evaluation/arrival_window.py). Not the
# replay start, which is a clock setting.
FIRE_START = "2025-01-07T18:18:00-08:00"
FIRE_START_SOURCE = ("Eaton Fire reported at 6:18 p.m. Jan 7, 2025: McChrystal after-action "
                     "review timeline (DATA_SOURCES.md). Used only as the lower bound of the "
                     "arrival window.")
TIGERWEB = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/"
            "Places_CouSub_ConCity_SubMCD/MapServer/26/query")  # layer 26: Census 2020 CDPs
RAW = DATA_DIR / "raw" / "census" / f"cdp_{GEOID}_2020.geojson"
# Census cartographic (500k) county boundaries, cut at the shoreline.
COUNTIES_500K = ("https://tigerweb.geo.census.gov/arcgis/rest/services/Generalized_ACS2023/"
                 "State_County/MapServer/11/query")
LA_COUNTY = "06037"
RAW_LA = DATA_DIR / "raw" / "census" / f"county_{LA_COUNTY}_500k.geojson"


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


def download_county() -> dict:
    """LA County's shoreline-cut outline as GeoJSON (cached in data/raw/)."""
    if not RAW_LA.exists():
        query = urllib.parse.urlencode({
            "where": f"GEOID='{LA_COUNTY}'", "outFields": "NAME,GEOID",
            "returnGeometry": "true", "outSR": "4326", "f": "geojson",
        })
        with urllib.request.urlopen(f"{COUNTIES_500K}?{query}", timeout=90) as response:
            data = json.load(response)
        if len(data.get("features", [])) != 1:
            raise RuntimeError(f"Expected one county for GEOID {LA_COUNTY}, got {data}")
        RAW_LA.parent.mkdir(parents=True, exist_ok=True)
        RAW_LA.write_text(json.dumps(data))
    return json.loads(RAW_LA.read_text())


def build_palisades() -> None:
    fire = FIRES["palisades"]
    county = download_county()["features"][0]
    geometry = county["geometry"]
    polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" \
        else [geometry["coordinates"]]

    def on_land(cell: str) -> bool:
        lat, lon = h3.cell_to_latlng(cell)
        return any(_inside(lon, lat, p[0]) for p in polygons)  # outer rings; no holes

    box = fire.box
    every = grid_cells(box)
    cells = [c for c in every if on_land(c)]
    out = fire.folder
    out.mkdir(parents=True, exist_ok=True)
    meta = {
        "name": "palisades",
        "synthetic": False,
        "description": "Palisades Fire, forecast development set: real satellites, wind and "
                       "damage. People and fleet are borrowed fakes; not for dispatch claims.",
        "bbox": box,
        "cells": "cells.json",
        "h3_res": 9,
        "replay": {"start": "2025-01-07T10:30:00-08:00", "end": "2025-01-08T16:00:00-08:00",
                   "step_minutes": 10},
        "fire_start": fire.ignition.isoformat(),
        "fire_start_source": fire.ignition_source,
        "study_area": {
            "source": "CAL FIRE DINS (DINS_2025_Palisades_Public_View) inspection extent + 2 km; "
                      "land = US Census Bureau TIGERweb cartographic boundary, Los Angeles "
                      "County (GEOID 06037, 1:500k)",
            "margin_km": 2.0,
        },
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    (out / "cells.json").write_text(json.dumps(cells) + "\n")
    print(f"Wrote {out / 'meta.json'}: {len(cells)} land cells of {len(every)} in the box")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    fire_arg(parser)
    if parser.parse_args().fire == "palisades":
        build_palisades()
        return
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
        "fire_start": FIRE_START,
        "fire_start_source": FIRE_START_SOURCE,
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
