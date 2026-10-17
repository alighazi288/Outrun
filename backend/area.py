"""Set up any US area on demand, in about a minute, from free national sources.

    uv run python -m backend.area --fires                       # current US wildfires
    uv run python -m backend.area --lat 39.76 --lon -121.62 --name paradise-ca

Writes a dataset folder (data/live/<name>/) in the same format as data/processed/eaton/, so
the same engines, API and dashboard run on it:

    map             every map cell within RADIUS_KM of the point
    care homes      Medicare-certified nursing homes (CMS), with each home's own average
                    number of residents per day; needs mix from assumptions.py
    people at home  Census ACS tract counts (same rule as Altadena, backend/census.py), spread
                    over the tract's Census 2020 blocks by each block's real population, so
                    nobody is placed in empty hills.
    shelters        FEMA shelters open right now within SHELTER_SEARCH_KM; if none, an
                    EXAMPLE shelter (a public high school, NCES school locations), labeled
    fleet           an EXAMPLE fleet (FLEET_BASELINE) staged at the first shelter, labeled
    fire, wind,     today's live feeds (backend/feeds.py)
    alerts
    roads           none: travel uses the straight-line estimate (x DETOUR_FACTOR)

What a county adds when it adopts Outrun (and Altadena shows): its own list of people who
need help, its paratransit fleet and depots, the shelters it opens, all licensed care homes,
and real road travel times. The approximations are written into meta.json so the dashboard
and agents can say so.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import urllib.parse
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import h3

from backend import feeds
from backend.assumptions import (
    FACILITY_NEEDS,
    FACILITY_OCCUPANCY,
    FLEET_BASELINE,
    NEED_PROFILES,
    VEHICLE_SPECS,
)
from backend.census import TOTAL_POPULATION, VARIABLES, allocate, api_name, tract_needs
from backend.schemas import H3_RES, Facility, FireReport, Resident, Shelter, Vehicle
from backend.store import DATA_DIR, read_jsonl, write_jsonl
from engines.travel import haversine_m

AREA_ROOT = DATA_DIR / "live"
RADIUS_KM = 4.0
SHELTER_SEARCH_KM = 80.0
SEED = 20261014
INCIDENT_REPORT_HOURS = 2  # = the nowcast's ACTIVE_WINDOW: after this, satellites only
WINDOW_PAST_H, WINDOW_H = 2, 12  # a live area's clock: from 2 h before setup, 12 h long

BLOCKS = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/"
          "tigerWMS_Census2020/MapServer/10/query")
ACS_API = "https://api.census.gov/data/2023/acs/acs5"
CMS_NURSING_HOMES = "https://data.cms.gov/provider-data/api/1/datastore/query/4pq5-n9py/0"
FEMA_OPEN_SHELTERS = "https://gis.fema.gov/arcgis/rest/services/NSS/OpenShelters/MapServer/0/query"
NCES_SCHOOLS = ("https://nces.ed.gov/opengis/rest/services/K12_School_Locations/"
                "EDGE_GEOCODE_PUBLICSCH_2223/MapServer/0/query")
NIFC_CURRENT = ("https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/"
                "WFIGS_Incident_Locations_Current/FeatureServer/0/query")

STATE_POSTAL = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT",
    "10": "DE", "11": "DC", "12": "FL", "13": "GA", "15": "HI", "16": "ID", "17": "IL",
    "18": "IN", "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME", "24": "MD",
    "25": "MA", "26": "MI", "27": "MN", "28": "MS", "29": "MO", "30": "MT", "31": "NE",
    "32": "NV", "33": "NH", "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND",
    "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD",
    "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA", "54": "WV",
    "55": "WI", "56": "WY", "72": "PR",
}


@dataclass(frozen=True)
class Block:
    geoid: str  # 15 digits; the first 11 are its tract
    population: int  # Census 2020
    lat: float
    lon: float


# --------------------------------------------------------------------------------------
# The area
# --------------------------------------------------------------------------------------


def box_around(lat: float, lon: float, radius_km: float) -> dict:
    dlat = radius_km / 110.574
    dlon = radius_km / (111.320 * math.cos(math.radians(lat)))
    return {"south": round(lat - dlat, 4), "west": round(lon - dlon, 4),
            "north": round(lat + dlat, 4), "east": round(lon + dlon, 4)}


def us_fires(days: int = 3, get: feeds.Get = feeds.http_get, limit: int = 50) -> list[dict]:
    """Real US wildfires from the national incident system (NIFC WFIGS, fed by IRWIN): every
    one found in the last `days` days plus any still not contained, none declared out,
    newest first. Most are small and put out fast; that is what a normal day looks like."""
    since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    query = urllib.parse.urlencode({
        "where": (f"IncidentTypeCategory='WF' AND FireOutDateTime IS NULL AND "
                  f"(FireDiscoveryDateTime > TIMESTAMP '{since}' OR PercentContained < 100)"),
        "outFields": ",".join(INCIDENT_FIELDS), "orderByFields": "FireDiscoveryDateTime DESC",
        "resultRecordCount": limit, "returnGeometry": "true", "outSR": 4326, "f": "json",
    })
    return [incident(f) for f in json.loads(get(f"{NIFC_CURRENT}?{query}")).get("features", [])
            if (f.get("geometry") or {}).get("y") is not None]


INCIDENT_FIELDS = ("IrwinID", "IncidentName", "IncidentSize", "PercentContained", "POOCity",
                   "POOCounty", "POOState", "FireDiscoveryDateTime", "ContainmentDateTime",
                   "ControlDateTime", "FireOutDateTime", "FireBehaviorGeneral")


def _when(ms: float | None) -> str | None:
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat() if ms else None


def incident(feature: dict) -> dict:
    """One NIFC incident as plain fields (times as ISO strings, UTC)."""
    a, g = feature["attributes"], feature["geometry"]
    place = ", ".join(p for p in (a.get("POOCity") or a.get("POOCounty"),
                                  (a.get("POOState") or "").removeprefix("US-")) if p)
    status = ("out" if a.get("FireOutDateTime") else "controlled" if a.get("ControlDateTime")
              else "contained" if a.get("ContainmentDateTime") else "active")
    return {
        "id": a.get("IrwinID") or a["IncidentName"], "name": a["IncidentName"], "place": place,
        "lat": round(g["y"], 5), "lon": round(g["x"], 5),
        "acres": a.get("IncidentSize"), "contained_pct": a.get("PercentContained"),
        "status": status, "behavior": a.get("FireBehaviorGeneral"),
        "discovered_at": _when(a.get("FireDiscoveryDateTime")),
        "contained_at": _when(a.get("ContainmentDateTime")),
        "out_at": _when(a.get("FireOutDateTime")),
    }


def incident_report(fire: dict, now: datetime) -> FireReport | None:
    """The incident's own first report as a real FireReport: where and when the fire was
    found. Only while the fire is under INCIDENT_REPORT_HOURS old and not contained. After
    that the satellites say where it is: a small fire nobody sees for that long is most
    likely out, and an old report would make the forecast assume hours of unseen spread."""
    found = datetime.fromisoformat(fire["discovered_at"]) if fire["discovered_at"] else None
    if (found is None or now - found > timedelta(hours=INCIDENT_REPORT_HOURS)
            or fire["status"] != "active"):
        return None
    return FireReport(
        id=f"nifc_{fire['id']}", lat=fire["lat"], lon=fire["lon"],
        h3=h3.latlng_to_cell(fire["lat"], fire["lon"], H3_RES), reported_at=found,
        description=f"{fire['name']}: wildfire reported ({fire['place']})",
        location_precision_m=500.0,
        source=f"NIFC WFIGS incident {fire['id']} (point of origin, discovery time)",
    )


# --------------------------------------------------------------------------------------
# People
# --------------------------------------------------------------------------------------


def census_blocks(box: dict, get: feeds.Get = feeds.http_get) -> list[Block]:
    """Inhabited Census 2020 blocks whose inside point is in the box."""
    out, offset = [], 0
    while True:
        query = urllib.parse.urlencode({
            "geometry": f"{box['west']},{box['south']},{box['east']},{box['north']}",
            "geometryType": "esriGeometryEnvelope", "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects", "where": "POP100 > 0",
            "outFields": "GEOID,POP100,INTPTLAT,INTPTLON", "returnGeometry": "false",
            "orderByFields": "GEOID", "resultOffset": offset, "resultRecordCount": 2000,
            "f": "json",
        })
        page = json.loads(get(f"{BLOCKS}?{query}"))
        rows = page.get("features", [])
        for f in rows:
            a = f["attributes"]
            lat, lon = float(a["INTPTLAT"]), float(a["INTPTLON"])
            if box["south"] <= lat <= box["north"] and box["west"] <= lon <= box["east"]:
                out.append(Block(a["GEOID"], int(a["POP100"]), lat, lon))
        if len(rows) < 2000 and not page.get("exceededTransferLimit"):
            return out
        offset += len(rows)


def acs_by_tract(tracts: set[str], key: str,
                 get: feeds.Get = feeds.http_get) -> dict[str, dict[str, int]]:
    """Tract GEOID -> ACS 2019-23 estimates (summary-file names), one call per county."""
    by_county: dict[tuple[str, str], list[str]] = {}
    for t in sorted(tracts):
        by_county.setdefault((t[:2], t[2:5]), []).append(t[5:])
    names = [api_name(v) for v in VARIABLES]
    out: dict[str, dict[str, int]] = {}
    for (state, county), codes in by_county.items():
        query = urllib.parse.urlencode({
            "get": ",".join(names), "for": f"tract:{','.join(codes)}",
            "in": f"state:{state} county:{county}", "key": key,
        })
        rows = json.loads(get(f"{ACS_API}?{query}"))
        header = rows[0]
        for row in rows[1:]:
            values = dict(zip(header, row, strict=True))
            geoid = values["state"] + values["county"] + values["tract"]
            out[geoid] = {v: max(int(float(values[api_name(v)] or 0)), 0) for v in VARIABLES}
    return out


def _resident(rid: str, lat: float, lon: float, need: str, people: int, **kw) -> Resident:
    vehicle_types, load = NEED_PROFILES[need]
    return Resident(id=rid, lat=round(lat, 6), lon=round(lon, 6),
                    h3=h3.latlng_to_cell(lat, lon, H3_RES), needs=need,
                    vehicle_types=vehicle_types, load_minutes=load, people=people, **kw)


def estimated_residents(blocks: list[Block], acs: dict[str, dict[str, int]],
                        rng: random.Random) -> list[Resident]:
    """Each tract's expected people, times the share of its population living in the area,
    placed at its blocks in proportion to each block's population."""
    by_tract: dict[str, list[Block]] = {}
    for b in blocks:
        by_tract.setdefault(b.geoid[:11], []).append(b)
    out = []
    for tract in sorted(by_tract):
        if tract not in acs or not acs[tract][TOTAL_POPULATION]:
            continue
        inside = by_tract[tract]
        share = min(sum(b.population for b in inside) / acs[tract][TOTAL_POPULATION], 1.0)
        weights = [b.population for b in inside]
        for (need, size), expected in tract_needs(acs[tract]).items():
            kept = expected * share
            for _ in range(math.floor(kept) + (rng.random() < kept - math.floor(kept))):
                b = rng.choices(inside, weights)[0]
                out.append(_resident("", b.lat, b.lon, need, size, source="estimated"))
    return [r.model_copy(update={"id": f"est_{i:05d}"}) for i, r in enumerate(out, 1)]


def nursing_homes(box: dict, states: set[str],
                  get: feeds.Get = feeds.http_get) -> list[tuple[Facility, float | None]]:
    """(facility, average residents per day) for Medicare nursing homes in the box."""
    out = []
    for state in sorted(states):
        offset = 0
        while True:
            query = urllib.parse.urlencode({
                "limit": 1000, "offset": offset,
                "conditions[0][property]": "state", "conditions[0][value]": state,
            })
            page = json.loads(get(f"{CMS_NURSING_HOMES}?{query}"))
            rows = page.get("results", [])
            for r in rows:
                try:
                    lat, lon = float(r["latitude"]), float(r["longitude"])
                except (KeyError, TypeError, ValueError):
                    continue
                if not (box["south"] <= lat <= box["north"] and box["west"] <= lon <= box["east"]):
                    continue
                ccn = r["cms_certification_number_ccn"]
                avg = r.get("average_number_of_residents_per_day")
                out.append((Facility(
                    id=f"cms_{ccn}", name=r["provider_name"].title(),
                    kind="skilled nursing facility (Medicare-certified)",
                    lat=lat, lon=lon, h3=h3.latlng_to_cell(lat, lon, H3_RES),
                    licensed_capacity=int(float(r.get("number_of_certified_beds") or 0)),
                    source=f"CMS Nursing Home Provider Information, CCN {ccn}",
                ), float(avg) if avg not in (None, "") else None))
            offset += len(rows)
            if len(rows) < 1000:
                break
    return out


def facility_residents(homes: list[tuple[Facility, float | None]]) -> list[Resident]:
    """Each home's own average residents per day (else beds x FACILITY_OCCUPANCY)."""
    out = []
    for f, average in homes:
        n = round(average) if average is not None else round(f.licensed_capacity *
                                                              FACILITY_OCCUPANCY)
        for i, need in enumerate(allocate(n, FACILITY_NEEDS["nursing"]), 1):
            out.append(_resident(f"{f.id}_r{i:03d}", f.lat, f.lon, need, 1,
                                 source="facility", facility_id=f.id))
    return out


# --------------------------------------------------------------------------------------
# Shelters and fleet
# --------------------------------------------------------------------------------------


def open_shelters(lat: float, lon: float, get: feeds.Get = feeds.http_get) -> list[Shelter]:
    """FEMA National Shelter System: shelters open right now, nearest first."""
    d = SHELTER_SEARCH_KM / 111.0
    query = urllib.parse.urlencode({
        "geometry": f"{lon - d * 1.4},{lat - d},{lon + d * 1.4},{lat + d}",
        "geometryType": "esriGeometryEnvelope", "inSR": 4326, "outSR": 4326,
        "spatialRel": "esriSpatialRelIntersects", "where": "1=1", "outFields": "*",
        "returnGeometry": "true", "f": "json",
    })
    out = []
    for f in json.loads(get(f"{FEMA_OPEN_SHELTERS}?{query}")).get("features", []):
        a, g = f["attributes"], f.get("geometry") or {}
        if "x" not in g:
            continue
        name = a.get("shelter_name") or a.get("SHELTER_NAME") or "Open shelter"
        out.append(Shelter(
            id=f"fema_{a.get('shelter_id') or a.get('SHELTER_ID') or len(out)}", name=name,
            lat=g["y"], lon=g["x"], capacity=a.get("evacuation_capacity"),
            source="FEMA National Shelter System, open shelters (live)",
        ))
    return sorted(out, key=lambda s: haversine_m((lat, lon), (s.lat, s.lon)))


def example_shelter(lat: float, lon: float, radius_km: float,
                    get: feeds.Get = feeds.http_get) -> Shelter | None:
    """No shelter open: an EXAMPLE drop-off at a public high school (NCES public school
    locations), the nearest one outside the area if there is one."""
    d = radius_km * 4 / 111.0
    query = urllib.parse.urlencode({
        "geometry": f"{lon - d * 1.3},{lat - d},{lon + d * 1.3},{lat + d}",
        "geometryType": "esriGeometryEnvelope", "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "where": "NAME LIKE '%High%' OR NAME LIKE '%HIGH%'",
        "outFields": "NCESSCH,NAME,CITY,LAT,LON", "returnGeometry": "false",
        "resultRecordCount": 2000, "f": "json",
    })
    schools = []
    for f in json.loads(get(f"{NCES_SCHOOLS}?{query}")).get("features", []):
        a = f["attributes"]
        if re.search(r"\bhigh\b", a["NAME"], re.I) and not re.search(
                r"\b(junior|middle|jr)\b", a["NAME"], re.I):
            schools.append((haversine_m((lat, lon), (a["LAT"], a["LON"])), a["NAME"].title(),
                            a["LAT"], a["LON"], a["NCESSCH"]))
    if not schools:
        return None
    outside = [s for s in schools if s[0] > radius_km * 1000]
    _, name, s_lat, s_lon, school_id = min(outside or schools)
    return Shelter(id="example_shelter", name=f"{name} (example shelter)", lat=s_lat, lon=s_lon,
                   source=f"EXAMPLE, not a real opening: public high school, NCES {school_id}. "
                          "The county names its real shelters.")


def example_fleet(at: Shelter) -> list[Vehicle]:
    """FLEET_BASELINE, staged at the first shelter. An EXAMPLE: the county loads its own."""
    out = []
    for kind, count in FLEET_BASELINE.items():
        prefix, seats, wheelchair, stretcher = VEHICLE_SPECS[kind]
        out += [Vehicle(id=f"{prefix}_{n:02d}", type=kind, seats=seats,
                        wheelchair_spaces=wheelchair, stretcher_spaces=stretcher,
                        lat=at.lat, lon=at.lon, depot="example_staging")
                for n in range(1, count + 1)]
    return out


# --------------------------------------------------------------------------------------
# Live fire data
# --------------------------------------------------------------------------------------


def refresh_fire(folder: Path, now: datetime, get: feeds.Get = feeds.http_get) -> dict:
    """Pull today's detections, wind and alerts into the area's folder. Returns a summary."""
    meta = json.loads((folder / "meta.json").read_text())
    box = meta["bbox"]
    if meta.get("incident"):
        _follow_incident(folder, meta, now, get)
    key = os.environ.get("FIRMS_MAP_KEY")
    detections = feeds.fires(box, key, now, get=get) if key else []
    wind = feeds.wind(box, get=get)
    orders, weather = feeds.alerts(box, now, get=get)
    write_jsonl(folder / "detections.jsonl", detections)
    write_jsonl(folder / "wind.jsonl", wind)
    write_jsonl(folder / "evac_orders.jsonl", orders)
    if "replay" not in meta:  # set once, at setup: refreshing never moves the clock
        start = (now - timedelta(hours=WINDOW_PAST_H)).replace(
            minute=now.minute // 10 * 10, second=0, microsecond=0)
        meta["replay"] = {"start": start.isoformat(),
                          "end": (start + timedelta(hours=WINDOW_H)).isoformat(),
                          "step_minutes": 10}
    meta.update({
        "fire_weather": weather,
        "feeds_pulled_at": now.isoformat(),
        "feeds": {"satellite": "NASA FIRMS (VIIRS, GOES)" if key else "none: no FIRMS_MAP_KEY",
                  "wind": "NOAA HRRR via Open-Meteo",
                  "alerts": "FEMA IPAWS public feed; NWS"},
    })
    (folder / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    return {"detections": len(detections), "wind": len(wind), "orders": len(orders),
            "fire_weather": weather}


# --------------------------------------------------------------------------------------
# Set up
# --------------------------------------------------------------------------------------


def _follow_incident(folder: Path, meta: dict, now: datetime, get: feeds.Get) -> None:
    """Update the incident's status from NIFC, and keep its report only while it may still
    drive the forecast (incident_report). Other reports (drills) are kept."""
    fire = next((f for f in us_fires(days=14, get=get) if f["id"] == meta["incident"]["id"]),
                None)
    if fire is None:  # gone from the current list: declared out
        fire = {**meta["incident"], "status": "out"}
    meta["incident"] = fire
    path = folder / "fire_reports.jsonl"
    others = [r for r in (read_jsonl(path, FireReport) if path.exists() else [])
              if not r.id.startswith("nifc_")]
    report = incident_report(fire, now)
    write_jsonl(path, [report, *others] if report else others)


def drill_report(folder: Path, lat: float, lon: float, minutes_after_start: float = 20,
                 text: str = "brush fire reported") -> FireReport:
    """Add a DRILL fire report (a typed example, never presented as real) to an area."""
    meta = json.loads((folder / "meta.json").read_text())
    at = datetime.fromisoformat(meta["replay"]["start"]) + timedelta(minutes=minutes_after_start)
    path = folder / "fire_reports.jsonl"
    reports = read_jsonl(path, FireReport) if path.exists() else []
    report = FireReport(
        id=f"drill_{len(reports) + 1}", lat=lat, lon=lon, h3=h3.latlng_to_cell(lat, lon, H3_RES),
        reported_at=at, description=f"DRILL: {text}", location_precision_m=250,
        source="DRILL: a typed example report, not a real one")
    write_jsonl(path, [*reports, report])
    return report


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "area"


def setup(lat: float, lon: float, name: str, radius_km: float = RADIUS_KM,
          now: datetime | None = None, get: feeds.Get = feeds.http_get,
          fire: dict | None = None) -> Path:
    """Set up an area around (lat, lon). With `fire` (from us_fires), the fire's own report
    is added as a real fire report while it is new and not contained."""
    now = now or datetime.now(UTC)
    folder = AREA_ROOT / slug(name)
    folder.mkdir(parents=True, exist_ok=True)
    box = box_around(lat, lon, radius_km)
    notes = ["Road travel times are a straight-line estimate (no road network set up).",
             "Care homes: Medicare-certified nursing homes only (CMS); a county adds every "
             "licensed care home."]

    blocks = census_blocks(box, get)
    states = {STATE_POSTAL[b.geoid[:2]] for b in blocks if b.geoid[:2] in STATE_POSTAL}
    homes = nursing_homes(box, states, get) if states else []
    people = facility_residents(homes)
    census_key = os.environ.get("CENSUS_API_KEY")
    if census_key and blocks:
        acs = acs_by_tract({b.geoid[:11] for b in blocks}, census_key, get)
        people += estimated_residents(blocks, acs, random.Random(SEED))
        notes.append("People at home: estimated from Census ACS tract counts, placed at "
                     "Census 2020 blocks by population; real addresses are never used.")
    else:
        notes.append("People at home: NOT included; care homes only.")

    shelters = open_shelters(lat, lon, get)
    if not shelters:
        example = example_shelter(lat, lon, radius_km, get)
        shelters = [example] if example else []
        notes.append("No FEMA shelter is open nearby: the shelter is an EXAMPLE, labeled.")
    vehicles = example_fleet(shelters[0]) if shelters else []
    notes.append("Fleet: an EXAMPLE fleet (4 wheelchair vans, 4 ambulances, 11 buses); the "
                 "county loads its own.")

    meta = {
        "name": slug(name), "synthetic": False, "live": True,
        "description": f"Live area around {name}, set up automatically from national data",
        "bbox": box, "center": [lat, lon], "radius_km": radius_km, "h3_res": H3_RES,
        "set_up_at": now.isoformat(), "time_zone": feeds.time_zone(lat, lon, get),
        "approximations": notes,
        "study_area": {"source": f"{radius_km:g} km around ({lat:.4f}, {lon:.4f})"},
    }
    (folder / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    write_jsonl(folder / "facilities.jsonl", [f for f, _ in homes])
    write_jsonl(folder / "residents.jsonl", people)
    write_jsonl(folder / "shelters.jsonl", shelters)
    write_jsonl(folder / "vehicles.jsonl", vehicles)
    report = incident_report(fire, now) if fire else None
    if fire:
        meta["incident"] = fire
        (folder / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    write_jsonl(folder / "fire_reports.jsonl", [report] if report else [])
    refresh_fire(folder, now, get)
    return folder


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fires", action="store_true",
                        help="list real US wildfires: new in the last 3 days, or not contained")
    parser.add_argument("--fire", help="set up around this fire (an id from --fires)")
    parser.add_argument("--lat", type=float)
    parser.add_argument("--lon", type=float)
    parser.add_argument("--name", help="a short name for the area, e.g. paradise-ca")
    parser.add_argument("--radius-km", type=float, default=RADIUS_KM)
    parser.add_argument("--drill", nargs=2, type=float, metavar=("LAT", "LON"),
                        help="add a DRILL fire report to an area already set up (--name)")
    args = parser.parse_args()
    if args.drill:
        if not args.name:
            parser.error("--drill needs --name")
        r = drill_report(AREA_ROOT / slug(args.name), *args.drill)
        print(f"Added {r.id} at ({r.lat}, {r.lon}), {r.reported_at:%H:%M} UTC: {r.description}")
        return
    if args.fires:
        for f in us_fires():
            print(f"  {f['discovered_at'][5:16]}Z  {f['name'][:24]:<24} {f['place'][:24]:<24} "
                  f"{f['acres'] or 0:>9,.1f} ac  {f['status']:<10}  {f['id']}")
        return
    fire = None
    if args.fire:
        fire = next((f for f in us_fires() if f["id"] == args.fire), None)
        if fire is None:
            parser.error(f"no current fire with id {args.fire}")
        args.lat, args.lon = fire["lat"], fire["lon"]
        args.name = args.name or f"{fire['name']} {fire['place']}"
    if args.lat is None or args.lon is None or not args.name:
        parser.error("give --lat, --lon and --name, or --fire ID (or --fires)")
    folder = setup(args.lat, args.lon, args.name, args.radius_km, fire=fire)
    meta = json.loads((folder / "meta.json").read_text())
    count = {n: sum(1 for _ in open(folder / f"{n}.jsonl")) for n in
             ("residents", "facilities", "shelters", "vehicles", "detections", "wind")}
    print(f"Set up {folder}: {count['residents']} people who may need a ride "
          f"({count['facilities']} nursing homes), {count['shelters']} shelter(s), "
          f"{count['vehicles']} vehicles, {count['detections']} fire detections, "
          f"{count['wind']} wind values")
    for note in meta["approximations"]:
        print(f"  - {note}")
    for w in meta.get("fire_weather", []):
        print(f"  ! {w}")


if __name__ == "__main__":
    main()
