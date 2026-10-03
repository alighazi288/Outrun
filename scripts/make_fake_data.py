"""Generate the FAKE fixture dataset in data/fixtures/eaton_fake/.

Scaffolding and test data only. It lets everyone build against the shared formats before
the real pipeline exists, and CI keeps using it because CI can't download satellite data.
Nothing judges see (demo, video, evaluation) uses it after build week 2.

Everything here is invented, including the fire shape, wind, fire reports, care facilities,
residents and shelters. The two evacuation order times come from the NBC News timeline cited
in the project brief.

    uv run python scripts/make_fake_data.py     # deterministic: same seed, same files
"""

from __future__ import annotations

import json
import math
import random
from datetime import datetime, timedelta

import h3

from backend.clock import PACIFIC
from backend.schemas import (
    H3_RES,
    NEED_PROFILES,
    EvacOrder,
    Facility,
    FireDetection,
    FireReport,
    Resident,
    Shelter,
    Vehicle,
    WindForecast,
)
from backend.store import DATASETS, write_jsonl

SEED = 7
OUT = DATASETS["fixtures"]

BBOX = {"south": 34.160, "west": -118.180, "north": 34.215, "east": -118.080}
LAKE_AVE_LON = -118.1317  # rough dividing line between east and west Altadena
IGNITION = datetime(2025, 1, 7, 18, 18, tzinfo=PACIFIC)
ORIGIN = (34.1905, -118.0985)  # approximate, near Eaton Canyon
SPREAD_BEARING = 245.0  # fire runs west-south-west under a north-east (Santa Ana) wind
HEAD_KM_PER_H = 0.9
REPLAY = {
    "start": "2025-01-07T18:00:00-08:00",
    "end": "2025-01-08T06:00:00-08:00",
    "step_minutes": 10,
}


def cell(lat: float, lon: float) -> str:
    return h3.latlng_to_cell(lat, lon, H3_RES)


def offset(lat: float, lon: float, bearing_deg: float, km: float) -> tuple[float, float]:
    """Move km along a compass bearing (flat-earth, fine at city scale)."""
    b = math.radians(bearing_deg)
    dlat = km * math.cos(b) / 110.54
    dlon = km * math.sin(b) / (111.32 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon


def make_residents(rng: random.Random) -> list[Resident]:
    needs = ["wheelchair", "oxygen", "bedbound", "no_car", "none"]
    weights = [0.22, 0.16, 0.10, 0.42, 0.10]
    out = []
    for i in range(1, 51):
        lat = round(rng.uniform(34.170, 34.200), 5)
        lon = round(rng.uniform(-118.170, -118.110), 5)
        need = rng.choices(needs, weights)[0]
        vehicle_types, load = NEED_PROFILES[need]
        out.append(Resident(
            id=f"r_{i:04d}", lat=lat, lon=lon, h3=cell(lat, lon), needs=need,
            vehicle_types=vehicle_types, load_minutes=load,
            people=rng.choices([1, 2, 3], [0.70, 0.25, 0.05])[0], source="estimated",
        ))
    return out


FACILITIES = [
    # id, name, lat, lon, capacity, needs mix (wheelchair, bedbound, oxygen, no_car)
    ("fac_01", "Care home A (fake, west of Lake)", 34.1880, -118.1550, 12, (3, 2, 2, 5)),
    ("fac_02", "Care home B (fake, east of Lake)", 34.1830, -118.1250, 8, (2, 1, 1, 4)),
]


def make_facilities() -> tuple[list[Facility], list[Resident]]:
    facilities, residents = [], []
    for fid, name, lat, lon, capacity, mix in FACILITIES:
        facilities.append(Facility(
            id=fid, name=name, kind="residential care for the elderly (fake)", lat=lat, lon=lon,
            h3=cell(lat, lon), licensed_capacity=capacity, source="FAKE",
        ))
        needs = [n for n, k in zip(("wheelchair", "bedbound", "oxygen", "no_car"), mix,
                                   strict=True) for _ in range(k)]
        for i, need in enumerate(needs, 1):
            vehicle_types, load = NEED_PROFILES[need]
            residents.append(Resident(
                id=f"{fid}_r{i:02d}", lat=lat, lon=lon, h3=cell(lat, lon), needs=need,
                vehicle_types=vehicle_types, load_minutes=load, people=1, source="facility",
                facility_id=fid,
            ))
    return facilities, residents


def make_fire_reports(rng: random.Random) -> list[FireReport]:
    """Fake 911/radio reports: the advancing front, plus spot fires ahead of it (embers)."""
    out = []
    t = IGNITION + timedelta(minutes=5)
    n = 0
    while t <= IGNITION + timedelta(hours=7):
        hours = (t - IGNITION).total_seconds() / 3600
        spot = n % 3 == 2  # every third report is an ember-driven spot fire ahead of the front
        km = HEAD_KM_PER_H * hours * (rng.uniform(1.3, 1.6) if spot else rng.uniform(0.8, 1.0))
        lat, lon = offset(*ORIGIN, SPREAD_BEARING + rng.uniform(-25, 25), km)
        n += 1
        out.append(FireReport(
            id=f"fr_{n:04d}", lat=round(lat, 5), lon=round(lon, 5), h3=cell(lat, lon),
            reported_at=t, location_precision_m=250.0, source="FAKE",
            description="Spot fire reported ahead of the main fire" if spot
            else "Fire reported at the advancing edge",
        ))
        t += timedelta(minutes=rng.choice([20, 30, 40]))
    return out


def make_vehicles() -> list[Vehicle]:
    depot = (34.1478, -118.1445)  # assumed depot, central Pasadena
    specs = [
        ("v_01", "wheelchair_van", 6, 2, 0),
        ("v_02", "wheelchair_van", 6, 2, 0),
        ("v_03", "ambulance", 2, 1, 1),
        ("v_04", "ambulance", 2, 1, 1),
        ("v_05", "bus", 40, 0, 0),
    ]
    return [
        Vehicle(id=i, type=t, seats=s, wheelchair_spaces=w, stretcher_spaces=x,
                lat=depot[0], lon=depot[1], status="idle", depot="depot_1")
        for i, t, s, w, x in specs
    ]


def make_shelters() -> list[Shelter]:
    return [
        Shelter(id="shelter_1", name="Shelter A (fake, central Pasadena)",
                lat=34.1443, lon=-118.1446, capacity=800),
        Shelter(id="shelter_2", name="Shelter B (fake, south-west)",
                lat=34.1360, lon=-118.1900, capacity=400),
    ]


def make_detections(rng: random.Random) -> list[FireDetection]:
    """Every 30 min, a handful of detections along the advancing fire front."""
    out, n = [], 0
    t = IGNITION + timedelta(minutes=12)
    while t <= IGNITION + timedelta(hours=11, minutes=42):
        hours = (t - IGNITION).total_seconds() / 3600
        head_km = HEAD_KM_PER_H * hours
        for _ in range(8):
            rel = rng.uniform(-100, 100)  # angle away from the head direction
            shape = 0.15 + 0.85 * max(math.cos(math.radians(rel)), 0) ** 1.5
            km = head_km * shape * rng.uniform(0.92, 1.08)
            lat, lon = offset(*ORIGIN, SPREAD_BEARING + rel, km)
            n += 1
            out.append(FireDetection(
                id=f"d_{n:04d}", lat=round(lat, 5), lon=round(lon, 5), h3=cell(lat, lon),
                observed_at=t, available_at=t + timedelta(minutes=15), source="FAKE",
                frp_mw=round(rng.uniform(5, 80), 1), confidence="nominal",
            ))
        t += timedelta(minutes=30)
    return out


def make_wind(rng: random.Random) -> list[WindForecast]:
    """Hourly forecast runs, each valid 0-3 hours ahead. Error grows with lead time."""
    center = ((BBOX["south"] + BBOX["north"]) / 2, (BBOX["west"] + BBOX["east"]) / 2)
    out = []
    issued = datetime(2025, 1, 7, 12, 0, tzinfo=PACIFIC)
    while issued <= datetime(2025, 1, 8, 6, 0, tzinfo=PACIFIC):
        for lead in range(4):
            valid = issued + timedelta(hours=lead)
            hours = (valid - issued.replace(hour=12)).total_seconds() / 3600
            true_speed = 17 + 4 * math.sin(hours / 4)
            out.append(WindForecast(
                issued_at=issued, valid_at=valid, lat=round(center[0], 4),
                lon=round(center[1], 4),
                speed_ms=round(max(true_speed + rng.gauss(0, 0.8 * (1 + lead)), 0), 1),
                dir_from_deg=round((45 + rng.gauss(0, 4 * (1 + lead))) % 360, 1),
                gust_ms=round(true_speed * 1.6, 1),
            ))
        issued += timedelta(hours=1)
    return out


def make_orders() -> list[EvacOrder]:
    src = "FAKE fixture; real times come from the NBC News timeline (see DATA_SOURCES.md)"
    s, n, w, e = BBOX["south"], BBOX["north"], BBOX["west"], BBOX["east"]
    lake = LAKE_AVE_LON
    return [
        EvacOrder(zone_id="east_altadena", kind="order", area="East Altadena (east of Lake Ave)",
                  issued_at=datetime(2025, 1, 7, 18, 50, tzinfo=PACIFIC), source=src,
                  polygon=[[lake, s], [e, s], [e, n], [lake, n], [lake, s]]),
        EvacOrder(zone_id="west_altadena", kind="order", area="West Altadena (west of Lake Ave)",
                  issued_at=datetime(2025, 1, 8, 3, 25, tzinfo=PACIFIC), source=src,
                  polygon=[[w, s], [lake, s], [lake, n], [w, n], [w, s]]),
    ]


def main() -> None:
    rng = random.Random(SEED)
    OUT.mkdir(parents=True, exist_ok=True)
    meta = {
        "name": "eaton_fake",
        "synthetic": True,
        "description": "FAKE fixture data for development and tests. Not the real fire.",
        "bbox": BBOX,
        "h3_res": H3_RES,
        "replay": REPLAY,
    }
    (OUT / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    facilities, facility_residents = make_facilities()
    write_jsonl(OUT / "residents.jsonl", make_residents(rng) + facility_residents)
    write_jsonl(OUT / "facilities.jsonl", facilities)
    write_jsonl(OUT / "vehicles.jsonl", make_vehicles())
    write_jsonl(OUT / "shelters.jsonl", make_shelters())
    write_jsonl(OUT / "detections.jsonl", make_detections(rng))
    write_jsonl(OUT / "fire_reports.jsonl", make_fire_reports(rng))
    write_jsonl(OUT / "wind.jsonl", make_wind(rng))
    write_jsonl(OUT / "evac_orders.jsonl", make_orders())
    print(f"Wrote fake fixtures to {OUT}")


if __name__ == "__main__":
    main()
