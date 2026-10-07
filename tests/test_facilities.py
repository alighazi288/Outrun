"""Care facilities: counted if licensed ON THE FIRE NIGHT, not today."""

from __future__ import annotations

import importlib.util
from datetime import date

from backend.store import REPO_ROOT

_spec = importlib.util.spec_from_file_location(
    "build_facilities", REPO_ROOT / "scripts" / "build_facilities.py")
build_facilities = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_facilities)

FIRE = date(2025, 1, 7)


def _row(first: str, closed: str = "") -> dict:
    return {"license_first_date": first, "closed_date": closed}


def test_a_home_that_closed_after_the_fire_still_counts():
    assert build_facilities.licensed_on(_row("3/2/2021", "3/4/2025"), FIRE)


def test_a_home_licensed_after_the_fire_does_not_count():
    assert not build_facilities.licensed_on(_row("5/13/2025"), FIRE)


def test_a_home_closed_before_the_fire_does_not_count():
    assert not build_facilities.licensed_on(_row("12/16/2015", "7/31/2023"), FIRE)


def test_a_home_closed_on_the_fire_day_does_not_count():
    assert not build_facilities.licensed_on(_row("1/1/2020", "1/7/2025"), FIRE)
