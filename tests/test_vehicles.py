"""The real fleet: Pasadena Transit's 11 buses that night, starting at their yard."""

from __future__ import annotations

import importlib.util

from backend.assumptions import FLEET_BASELINE
from backend.schemas import Vehicle
from backend.store import DATASETS, REPO_ROOT, read_jsonl

_spec = importlib.util.spec_from_file_location(
    "build_vehicles", REPO_ROOT / "scripts" / "build_vehicles.py")
build_vehicles = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_vehicles)


def test_eleven_buses_with_the_new_flyer_capacity():
    buses = [v for v in build_vehicles.build() if v.type == "bus"]
    assert len(buses) == 11
    assert all(v.seats == 32 and v.wheelchair_spaces == 2 for v in buses)


def test_dial_a_ride_vans_carry_four_wheelchairs():
    vans = [v for v in build_vehicles.build() if v.type == "wheelchair_van"]
    assert vans and all(v.wheelchair_spaces == 4 and v.seats == 6 for v in vans)


def test_fleet_matches_the_baseline_and_starts_at_the_yard():
    fleet = build_vehicles.build()
    for kind, count in FLEET_BASELINE.items():
        assert sum(v.type == kind for v in fleet) == count
    assert {v.depot for v in fleet} == {"pasadena_transit_yard"}
    assert len({v.id for v in fleet}) == len(fleet)


def test_committed_file_matches_the_builder():
    on_disk = read_jsonl(DATASETS["eaton"] / "vehicles.jsonl", Vehicle)
    assert [v.model_dump(mode="json") for v in on_disk] == [
        v.model_dump(mode="json") for v in build_vehicles.build()]
