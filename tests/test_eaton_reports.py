"""Real Eaton fire reports and evacuation alerts: cited facts, honest precision."""

from __future__ import annotations

import importlib.util
from datetime import datetime

import pytest

from backend.knowledge import _inside, first_trigger
from backend.schemas import EvacOrder, FireReport, Resident
from backend.store import DATASETS, REPO_ROOT, read_jsonl

_SCRIPTS = REPO_ROOT / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


timeline = _load("eaton_timeline")
build_fire_reports = _load("build_fire_reports")
build_evac_orders = _load("build_evac_orders")

LAKE = timeline.LAKE_LON
ORIGIN = datetime.fromisoformat("2025-01-07T18:18:00-08:00")
WEST_ORDER = datetime.fromisoformat("2025-01-08T03:25:00-08:00")
EAST_ORDER = datetime.fromisoformat("2025-01-07T19:26:00-08:00")
EAST_ADVISORY = datetime.fromisoformat("2025-01-07T18:49:00-08:00")  # Citygate: ~6:48


def test_reports_validate_and_are_unique():
    reports = build_fire_reports.build()
    assert reports
    assert len({r.id for r in reports}) == len(reports)
    for r in reports:
        FireReport.model_validate(r.model_dump())
        assert r.source
        assert r.reported_at.utcoffset() is not None
        assert r.location_precision_m in {250.0, 500.0, 1000.0}


def test_first_report_is_the_locked_ignition_time():
    reports = build_fire_reports.build()
    assert reports[0].id == "fr_origin"
    assert reports[0].reported_at == ORIGIN
    assert reports[0].location_precision_m == 1000.0


def test_west_of_lake_is_reported_hours_before_the_west_order():
    reports = build_fire_reports.build()
    west = [r for r in reports if r.lon < LAKE]
    assert west, "need published fire west of Lake Avenue"
    first = min(west, key=lambda r: r.reported_at)
    assert first.reported_at < WEST_ORDER
    hours = (WEST_ORDER - first.reported_at).total_seconds() / 3600
    assert hours >= 3, f"west reports should precede 3:25 a.m. by hours, got {hours:.1f}"
    assert first.id == "fr_glenrose"


def test_named_west_intersections_are_west_of_lake():
    reports = {r.id: r for r in build_fire_reports.build()}
    for rid in ("fr_glenrose", "fr_las_flores", "fr_wapello", "fr_monterosa"):
        assert reports[rid].lon < LAKE, rid
    assert "fr_calaveras" not in reports


def test_a_direction_is_not_a_place():
    """'Spreading west toward Lake' says where the fire was heading, not where it was.
    Placing it ourselves put fire west of every named location an hour later."""
    reports = {r.id: r for r in build_fire_reports.build()}
    for rid in ("fr_west_of_origin", "fr_toward_lake", "fr_west_flank"):
        assert rid not in reports
    assert "toward_lake" not in timeline.PLACES and "west_of_origin" not in timeline.PLACES


def test_named_east_intersections_are_east_of_lake():
    reports = {r.id: r for r in build_fire_reports.build()}
    for rid in ("fr_midwick", "fr_mendocino", "fr_morslay"):
        assert reports[rid].lon > LAKE, rid


def test_street_precision_is_not_tighter_than_the_source():
    """An area report cannot name one hex (EVAL_SPEC: precision > 500 m)."""
    reports = {r.id: r for r in build_fire_reports.build()}
    assert reports["fr_origin"].location_precision_m == 1000.0
    assert reports["fr_glenrose"].location_precision_m == 250.0
    assert reports["fr_upper_lake"].location_precision_m == 500.0


def test_no_personal_911_records():
    text = " ".join(r.description.lower() for r in build_fire_reports.build())
    assert "terrace" not in text
    assert "mitchell" not in text


def _orders() -> list[EvacOrder]:
    """The committed file: built from the real alerts, which CI can't download."""
    return read_jsonl(DATASETS["eaton"] / "evac_orders.jsonl", EvacOrder)


def _alerts_at(lat: float, lon: float) -> list[tuple[datetime, str]]:
    return sorted((o.issued_at, o.kind) for o in _orders() if _inside(lon, lat, o.polygon))


def test_orders_validate_and_polygons_close():
    orders = _orders()
    assert orders
    for o in orders:
        assert o.source.startswith("LA County, IPAWS")
        assert o.polygon and o.polygon[0] == o.polygon[-1]


def test_alert_times_and_kinds_match_citygate():
    """The layer's send times, read as Pacific clock time, land on Citygate's minutes."""
    got = {(o.issued_at.strftime("%m-%d %H:%M"), o.kind) for o in _orders()}
    assert got >= {
        ("01-07 18:49", "advisory"), ("01-07 19:26", "order"), ("01-07 19:55", "warning"),
        ("01-07 21:00", "order"), ("01-08 03:25", "order"),
    }
    assert not [o for o in _orders() if o.kind == "warning" and o.issued_at < EAST_ORDER]


def test_east_of_lake_advised_then_ordered():
    midwick = (34.182888, -118.106120)
    assert _alerts_at(*midwick)[:2] == [(EAST_ADVISORY, "advisory"), (EAST_ORDER, "order")]


def test_mount_lowe_warned_at_755_and_ordered_at_9():
    """The strip just east of Lake was left out of the 6:48 and 7:26 alerts."""
    assert _alerts_at(34.194, LAKE + 0.004) == [
        (datetime.fromisoformat("2025-01-07T19:55:00-08:00"), "warning"),
        (datetime.fromisoformat("2025-01-07T21:00:00-08:00"), "order"),
    ]


def test_west_of_lake_ordered_at_325_without_a_warning():
    glenrose = (34.202771, -118.147337)
    assert _alerts_at(*glenrose) == [(WEST_ORDER, "order")]


def test_south_west_altadena_was_ordered_after_5am_not_at_325():
    """What the drawn boxes got wrong: the 3:25 a.m. order stopped north of here."""
    alerts = _alerts_at(34.175, -118.145)
    assert alerts and alerts[0][1] == "order"
    assert alerts[0][0] > datetime.fromisoformat("2025-01-08T05:00:00-08:00")


def test_committed_files_match_the_builders():
    """The replay loads the JSONL files, not build() in memory."""
    reports = build_fire_reports.build()
    on_disk_r = read_jsonl(DATASETS["eaton"] / "fire_reports.jsonl", FireReport)
    assert [r.model_dump(mode="json") for r in on_disk_r] == [
        r.model_dump(mode="json") for r in reports
    ]
    if not build_evac_orders.RAW.exists():
        pytest.skip("alerts not downloaded (make evac-orders)")
    assert [o.model_dump(mode="json") for o in _orders()] == [
        o.model_dump(mode="json") for o in build_evac_orders.build()
    ]


def test_alert_kind_comes_from_the_words():
    kind = build_evac_orders.kind_of
    assert kind("Fast moving wildfire. BE AWARE and MONITOR.") == "advisory"
    assert kind("AN EVACUATION WARNING HAS BEEN ISSUED.") == "warning"
    assert kind("EVACUATION ORDER. LEAVE NOW.") == "order"
    with pytest.raises(ValueError):
        kind("Shelter in place.")


def test_a_west_home_is_triggered_by_the_evening_report_not_the_3am_order():
    """Call trigger uses the earlier of covering alert or nearby report (knowledge.py)."""
    reports = build_fire_reports.build()
    glenrose = next(r for r in reports if r.id == "fr_glenrose")
    person = Resident(
        id="r_test", lat=glenrose.lat, lon=glenrose.lon, h3=glenrose.h3,
        needs="none", vehicle_types=["bus", "wheelchair_van", "ambulance"],
        load_minutes=3, source="estimated",
    )
    evidence = [(r.lat, r.lon, r.reported_at) for r in reports]
    trigger = first_trigger(person, _orders(), evidence, trigger_km=2.0)
    assert trigger is not None
    assert trigger < WEST_ORDER
    assert trigger == glenrose.reported_at
