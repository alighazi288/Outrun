"""Build data/processed/eaton/residents.jsonl: the people who may need a ride out.

Synthetic people only: no real person or address is ever used. Two kinds:

- Care-home residents: the real licensed facilities in facilities.jsonl, filled to
  FACILITY_OCCUPANCY, with a needs mix by facility group. Known from the start.
- Everyone else ("estimated"): counted per Census tract from the American Community Survey
  2019-2023 5-year estimates (published Dec 2024, before the fire), then placed in real
  homes: LA County's 2020 building outlines (pre-fire; Microsoft's current footprints are from
  2026 and may miss the homes that burned).
    wheelchair  people with an ambulatory difficulty (B18105) x WHEELCHAIR_SHARE_OF_AMBULATORY
    bedbound    people 65+ (B01001) x BEDBOUND_SHARE_65
    oxygen      people 65+ x OXYGEN_SHARE_65
    no_car      households with no vehicle, by household size (B08201): one row per household
  backend/knowledge.py later decides who is on a list and who calls, and when.

Counts are per tract. A tract partly outside the study area keeps the share of its homes that
are inside (tracts reach far into the forest), and each person goes to a random one of them.

Known overlaps (stated, not corrected): one person can be counted twice (e.g. a wheelchair
user in a car-free home), and ACS counts people in assisted living, who are also care-home
residents here. Nursing homes are not in ACS's numbers.

    uv run python scripts/build_residents.py
"""

from __future__ import annotations

import json
import math
import random
import urllib.parse
import urllib.request

import h3

from backend.assumptions import (
    BEDBOUND_SHARE_65,
    FACILITY_NEEDS,
    FACILITY_OCCUPANCY,
    MIN_HOME_SQFT,
    NEED_PROFILES,
    OXYGEN_SHARE_65,
    WHEELCHAIR_SHARE_OF_AMBULATORY,
)
from backend.knowledge import _inside
from backend.schemas import H3_RES, Facility, Resident
from backend.store import DATA_DIR, DATASETS, grid_cells, read_jsonl, write_jsonl

SEED = 20250107
RAW = DATA_DIR / "raw"
TRACTS_RAW = RAW / "census" / "tracts_acs2023.geojson"
ACS_RAW = RAW / "census" / "acs2023_5yr_study_tracts.json"
BUILDINGS_RAW = RAW / "buildings" / "lariac2020_study_area.json"
TRACT_HOMES_RAW = RAW / "buildings" / f"lariac2020_homes_per_tract_{MIN_HOME_SQFT:.0f}sqft.json"

TIGERWEB_TRACTS = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/"
                   "tigerWMS_ACS2023/MapServer/8/query")
# ACS table-based summary files: every geography.
ACS_FILES = ("https://www2.census.gov/programs-surveys/acs/summary_file/2023/table-based-SF/"
             "data/5YRData/acsdt5y2023-{table}.dat")
LARIAC_2020 = ("https://services.arcgis.com/RmCCgQtiZLDCtblq/arcgis/rest/services/"
               "Countywide_Building_Outlines_(2020)/FeatureServer/0/query")

# People with an ambulatory difficulty, all ages 5+ (male, then female).
AMBULATORY = [f"B18105_E{n:03d}" for n in (4, 7, 10, 13, 16, 20, 23, 26, 29, 32)]
AGE_65 = [f"B01001_E{n:03d}" for n in (*range(20, 26), *range(44, 50))]  # 65+, male and female
# Households with no vehicle, by size (4 = four or more).
NO_CAR_BY_SIZE = {1: "B08201_E008", 2: "B08201_E014", 3: "B08201_E020", 4: "B08201_E026"}
NURSING = ("skilled nursing", "congregate living", "intermediate care", "hospice")


# --- Downloads (cached in data/raw/, which git ignores) ---------------------------------------

def _get(url: str, params: dict) -> dict:
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=120) as r:
        return json.load(r)


def download_tracts(bbox: dict) -> dict:
    if not TRACTS_RAW.exists():
        envelope = f"{bbox['west']},{bbox['south']},{bbox['east']},{bbox['north']}"
        data = _get(TIGERWEB_TRACTS, {
            "geometry": envelope, "geometryType": "esriGeometryEnvelope", "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects", "outFields": "GEOID,NAME",
            "returnGeometry": "true", "outSR": 4326, "f": "geojson",
        })
        TRACTS_RAW.parent.mkdir(parents=True, exist_ok=True)
        TRACTS_RAW.write_text(json.dumps(data))
    return json.loads(TRACTS_RAW.read_text())


def download_acs(geoids: set[str]) -> dict[str, dict[str, int]]:
    """GEOID -> variable -> estimate, for the given tracts (streams three national files)."""
    if not ACS_RAW.exists():
        wanted = {f"1400000US{g}": g for g in geoids}
        out: dict[str, dict[str, int]] = {g: {} for g in geoids}
        for table in ("b18105", "b01001", "b08201"):
            with urllib.request.urlopen(ACS_FILES.format(table=table), timeout=600) as r:
                header = r.readline().decode().strip().split("|")
                for line in r:
                    geo = line[:20].decode()
                    if geo.split("|")[0] not in wanted:
                        continue
                    row = dict(zip(header, line.decode().strip().split("|"), strict=True))
                    out[wanted[row["GEO_ID"]]].update({
                        k: int(float(v)) for k, v in row.items()
                        if "_E" in k and v not in ("", "null")})
        ACS_RAW.parent.mkdir(parents=True, exist_ok=True)
        ACS_RAW.write_text(json.dumps(out))
    return {g: {k: max(v, 0) for k, v in vs.items()}
            for g, vs in json.loads(ACS_RAW.read_text()).items()}


def download_buildings(box: tuple[float, float, float, float]) -> list[tuple[float, float]]:
    """(lat, lon) of county building outlines (2020) at least MIN_HOME_SQFT, inside box."""
    if not BUILDINGS_RAW.exists():
        west, south, east, north = box
        rows, offset = [], 0
        while True:
            page = _get(LARIAC_2020, {
                "geometry": f"{west},{south},{east},{north}",
                "geometryType": "esriGeometryEnvelope", "inSR": 4326,
                "spatialRel": "esriSpatialRelIntersects", "where": "CODE='Building'",
                "outFields": "AREA", "returnGeometry": "false", "returnCentroid": "true",
                "outSR": 4326, "orderByFields": "OBJECTID", "resultOffset": offset,
                "resultRecordCount": 2000, "f": "json",
            })
            feats = page.get("features", [])
            rows += [[round(f["centroid"]["x"], 6), round(f["centroid"]["y"], 6),
                      round(f["attributes"]["AREA"] or 0)] for f in feats]
            if not page.get("exceededTransferLimit") or not feats:
                break
            offset += len(feats)
        BUILDINGS_RAW.parent.mkdir(parents=True, exist_ok=True)
        BUILDINGS_RAW.write_text(json.dumps(rows))
    return [(y, x) for x, y, area in json.loads(BUILDINGS_RAW.read_text())
            if area >= MIN_HOME_SQFT]


# --- Counting --------------------------------------------------------------------------------

def download_tract_home_counts(tracts: dict) -> dict[str, int]:
    """GEOID -> number of homes (outlines >= MIN_HOME_SQFT) in the whole tract."""
    if not TRACT_HOMES_RAW.exists():
        counts = {}
        for feat in tracts["features"]:
            rings = _rings(feat["geometry"])
            page = _get(LARIAC_2020, {
                "geometry": json.dumps({"rings": rings, "spatialReference": {"wkid": 4326}}),
                "geometryType": "esriGeometryPolygon", "inSR": 4326,
                "spatialRel": "esriSpatialRelIntersects",
                "where": f"CODE='Building' AND AREA >= {MIN_HOME_SQFT}",
                "returnCountOnly": "true", "f": "json",
            })
            counts[feat["properties"]["GEOID"]] = page["count"]
        TRACT_HOMES_RAW.parent.mkdir(parents=True, exist_ok=True)
        TRACT_HOMES_RAW.write_text(json.dumps(counts))
    return json.loads(TRACT_HOMES_RAW.read_text())


def tract_needs(acs: dict[str, int]) -> dict[tuple[str, int], float]:
    """Expected number of people (need, household size) in one tract."""
    ambulatory = sum(acs[v] for v in AMBULATORY)
    age_65 = sum(acs[v] for v in AGE_65)
    out = {
        ("wheelchair", 1): ambulatory * WHEELCHAIR_SHARE_OF_AMBULATORY,
        ("bedbound", 1): age_65 * BEDBOUND_SHARE_65,
        ("oxygen", 1): age_65 * OXYGEN_SHARE_65,
    }
    for size, var in NO_CAR_BY_SIZE.items():
        out[("no_car", size)] = acs[var]
    return out


def allocate(n: int, shares: dict[str, float]) -> list[str]:
    """n items split by shares, largest remainder first: the counts always add up to n."""
    exact = {k: n * v / sum(shares.values()) for k, v in shares.items()}
    counts = {k: math.floor(v) for k, v in exact.items()}
    short = n - sum(counts.values())
    for k in sorted(exact, key=lambda k: exact[k] - counts[k], reverse=True)[:short]:
        counts[k] += 1
    return [k for k in shares for _ in range(counts[k])]


def _rings(geometry: dict) -> list[list[list[float]]]:
    polys = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [
        geometry["coordinates"]]
    return [poly[0] for poly in polys]  # outer rings (tracts here have no holes that matter)


def _in_tract(lat: float, lon: float, rings, bounds) -> bool:
    west, south, east, north = bounds
    if not (west <= lon <= east and south <= lat <= north):
        return False
    return any(_inside(lon, lat, ring) for ring in rings)


def _resident(rid: str, lat: float, lon: float, need: str, people: int, **kw) -> Resident:
    vehicle_types, load = NEED_PROFILES[need]
    return Resident(id=rid, lat=round(lat, 6), lon=round(lon, 6),
                    h3=h3.latlng_to_cell(lat, lon, H3_RES), needs=need,
                    vehicle_types=vehicle_types, load_minutes=load, people=people, **kw)


def facility_residents(facilities: list[Facility]) -> list[Resident]:
    out = []
    for f in facilities:
        group = "nursing" if f.kind.startswith(NURSING) else "residential"
        n = round(f.licensed_capacity * FACILITY_OCCUPANCY)
        for i, need in enumerate(allocate(n, FACILITY_NEEDS[group]), 1):
            out.append(_resident(f"{f.id}_r{i:03d}", f.lat, f.lon, need, 1,
                                 source="facility", facility_id=f.id))
    return out


def homes_by_tract(tracts: dict, homes: list[tuple[float, float]],
                   cells: set[str]) -> dict[str, list[tuple[float, float]]]:
    """Each home inside the study area, under the tract that contains it."""
    shapes = []
    for feat in tracts["features"]:
        rings = _rings(feat["geometry"])
        xs = [x for ring in rings for x, _ in ring]
        ys = [y for ring in rings for _, y in ring]
        shapes.append((feat["properties"]["GEOID"], rings, (min(xs), min(ys), max(xs), max(ys))))
    out: dict[str, list[tuple[float, float]]] = {}
    for lat, lon in homes:
        if h3.latlng_to_cell(lat, lon, H3_RES) not in cells:
            continue
        for geoid, rings, bounds in shapes:
            if _in_tract(lat, lon, rings, bounds):
                out.setdefault(geoid, []).append((lat, lon))
                break
    return out


def estimated_residents(acs: dict, inside: dict[str, list[tuple[float, float]]],
                        total_homes: dict[str, int], rng: random.Random) -> list[Resident]:
    out = []
    for geoid in sorted(inside):
        homes = inside[geoid]
        if geoid not in acs or not total_homes.get(geoid):
            continue
        share = min(len(homes) / total_homes[geoid], 1.0)  # of the tract's homes, inside
        for (need, size), expected in tract_needs(acs[geoid]).items():
            kept = expected * share
            n = math.floor(kept) + (rng.random() < kept - math.floor(kept))
            for _ in range(n):
                lat, lon = rng.choice(homes)
                out.append(_resident("", lat, lon, need, size, source="estimated"))
    return [r.model_copy(update={"id": f"est_{i:05d}"}) for i, r in enumerate(out, 1)]


def build() -> list[Resident]:
    folder = DATASETS["eaton"]
    meta = json.loads((folder / "meta.json").read_text())
    cells = set(grid_cells(meta["bbox"]))
    box = meta["bbox"]
    tracts = download_tracts(box)
    homes = [(lat, lon) for lat, lon in download_buildings(
        (box["west"], box["south"], box["east"], box["north"]))
        if box["south"] <= lat <= box["north"] and box["west"] <= lon <= box["east"]]
    inside = homes_by_tract(tracts, homes, cells)
    facilities = read_jsonl(folder / "facilities.jsonl", Facility)
    rng = random.Random(SEED)
    return (facility_residents(facilities) + estimated_residents(
        download_acs(set(inside)), inside, download_tract_home_counts(tracts), rng))


def main() -> None:
    residents = build()
    out = DATASETS["eaton"] / "residents.jsonl"
    write_jsonl(out, residents)
    print(f"Wrote {len(residents)} residents -> {out}")
    by: dict[tuple[str, str], int] = {}
    for r in residents:
        by[(r.source, r.needs)] = by.get((r.source, r.needs), 0) + 1
    for (source, need), n in sorted(by.items()):
        print(f"  {source:9s} {need:10s} {n:>5}")


if __name__ == "__main__":
    main()
