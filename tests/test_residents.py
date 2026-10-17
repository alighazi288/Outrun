"""Residents: synthetic people from real counts (Census ACS) in real homes and care homes."""

from __future__ import annotations

import importlib.util
import json

import pytest

from backend import census
from backend.assumptions import FACILITY_OCCUPANCY
from backend.schemas import Facility, Resident
from backend.store import DATASETS, REPO_ROOT, read_jsonl

_spec = importlib.util.spec_from_file_location(
    "build_residents", REPO_ROOT / "scripts" / "build_residents.py")
build_residents = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_residents)

FOLDER = DATASETS["eaton"]


def _residents() -> list[Resident]:
    return read_jsonl(FOLDER / "residents.jsonl", Resident)


def test_allocate_always_adds_up():
    shares = {"bedbound": 0.35, "wheelchair": 0.45, "oxygen": 0.10, "no_car": 0.10}
    for n in (0, 1, 7, 85, 199):
        got = build_residents.allocate(n, shares)
        assert len(got) == n
    assert build_residents.allocate(20, shares).count("wheelchair") == 9


def test_tract_needs_from_census_counts():
    acs = {v: 0 for v in census.AMBULATORY + census.AGE_65}
    acs |= {v: 0 for v in census.NO_CAR_BY_SIZE.values()}
    acs[census.AMBULATORY[0]] = 100
    acs[census.AGE_65[0]] = 1000
    acs[census.NO_CAR_BY_SIZE[2]] = 7
    needs = census.tract_needs(acs)
    assert needs[("wheelchair", 1)] == pytest.approx(12)
    assert needs[("bedbound", 1)] == pytest.approx(10)
    assert needs[("no_car", 2)] == 7


def test_every_care_home_is_filled_to_the_occupancy_assumption():
    facilities = read_jsonl(FOLDER / "facilities.jsonl", Facility)
    by_home: dict[str, int] = {}
    for r in _residents():
        if r.source == "facility":
            by_home[r.facility_id] = by_home.get(r.facility_id, 0) + 1
    for f in facilities:
        assert by_home.get(f.id, 0) == round(f.licensed_capacity * FACILITY_OCCUPANCY), f.id


def test_residents_are_synthetic_and_inside_the_study_area():
    box = json.loads((FOLDER / "meta.json").read_text())["bbox"]
    residents = _residents()
    assert len({r.id for r in residents}) == len(residents)
    assert {r.source for r in residents} == {"facility", "estimated"}
    for r in residents:
        assert box["south"] <= r.lat <= box["north"] and box["west"] <= r.lon <= box["east"]
        assert r.address is None and r.known_at is None
    assert all(r.id.startswith("est_") for r in residents if r.source == "estimated")


def test_committed_file_matches_the_builder():
    if not (build_residents.BUILDINGS_RAW.exists() and build_residents.ACS_RAW.exists()):
        pytest.skip("Census and building downloads not cached (uv run python "
                    "scripts/build_residents.py)")
    assert [r.model_dump(mode="json") for r in _residents()] == [
        r.model_dump(mode="json") for r in build_residents.build()]
