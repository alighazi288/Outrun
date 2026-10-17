"""Build a dataset's dins.geojson: which buildings the fire damaged (scoring only).

CAL FIRE's Damage Inspection (DINS) public view: every inspected structure with its damage
level. It says which buildings burned, never when, and it is after-the-fact data, so the
replay never loads it: only evaluation/arrival_window.py reads it, to decide which hexes the
fire reached. Points outside the study area box are left out. No parcel numbers are kept.

    uv run python scripts/build_dins.py                    # eaton
    uv run python scripts/build_dins.py --fire palisades
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fires import FIRES, fire_arg  # noqa: E402

LAYERS = "https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/arcgis/rest/services"


def download(bbox: dict, layer: str) -> dict:
    url = f"{LAYERS}/{layer}/FeatureServer/0/query"
    features, offset = [], 0
    while True:
        query = urllib.parse.urlencode({
            "where": "1=1", "outFields": "DAMAGE,STRUCTURETYPE", "returnGeometry": "true",
            "geometry": f"{bbox['west']},{bbox['south']},{bbox['east']},{bbox['north']}",
            "geometryType": "esriGeometryEnvelope", "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects", "outSR": 4326,
            "orderByFields": "OBJECTID", "resultOffset": offset, "resultRecordCount": 5000,
            "f": "geojson",
        })
        with urllib.request.urlopen(f"{url}?{query}", timeout=120) as r:
            page = json.load(r)
        batch = page.get("features", [])
        features += batch
        if len(batch) < 5000:
            break
        offset += len(batch)
    for f in features:
        f.pop("id", None)
        f["geometry"]["coordinates"] = [round(c, 6) for c in f["geometry"]["coordinates"]]
    return {"type": "FeatureCollection", "features": features}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    fire_arg(parser)
    fire = FIRES[parser.parse_args().fire]
    folder = fire.folder
    bbox = json.loads((folder / "meta.json").read_text())["bbox"]
    data = download(bbox, fire.dins_layer)
    out = folder / "dins.geojson"
    out.write_text(json.dumps(data, separators=(",", ":")) + "\n")
    damage: dict[str, int] = {}
    for f in data["features"]:
        d = f["properties"]["DAMAGE"]
        damage[d] = damage.get(d, 0) + 1
    print(f"Wrote {len(data['features'])} inspected structures -> {out}")
    for d, n in sorted(damage.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>6}  {d}")


if __name__ == "__main__":
    main()
