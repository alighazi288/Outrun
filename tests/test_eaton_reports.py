"""Real Eaton fire reports and evacuation orders: cited facts, honest precision."""

from __future__ import annotations

import importlib.util
from datetime import datetime

from backend.knowledge import _inside, first_trigger
from backend.schemas import EvacOrder, FireReport, Resident
from backend.store import REPO_ROOT

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
EAST_WARN = datetime.fromisoformat("2025-01-07T18:48:00-08:00")


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
    assert hours >= 4, f"west reports should precede 3:25 a.m. by hours, got {hours:.1f}"


def test_named_west_intersections_are_west_of_lake():
    reports = {r.id: r for r in build_fire_reports.build()}
    for rid in ("fr_calaveras", "fr_glenrose", "fr_las_flores", "fr_wapello", "fr_monterosa"):
        assert reports[rid].lon < LAKE, rid


def test_named_east_intersections_are_east_of_lake():
    reports = {r.id: r for r in build_fire_reports.build()}
    for rid in ("fr_midwick", "fr_mendocino", "fr_morslay"):
        assert reports[rid].lon > LAKE, rid


def test_street_precision_is_not_tighter_than_the_source():
    """An area report cannot name one hex (EVAL_SPEC: precision > 500 m)."""
    reports = {r.id: r for r in build_fire_reports.build()}
    assert reports["fr_origin"].location_precision_m == 1000.0
    assert reports["fr_west_flank"].location_precision_m == 1000.0
    assert reports["fr_glenrose"].location_precision_m == 250.0
    assert reports["fr_calaveras"].location_precision_m == 500.0


def test_no_personal_911_records():
    text = " ".join(r.description.lower() for r in build_fire_reports.build())
    assert "terrace" not in text
    assert "mitchell" not in text


def test_orders_validate_and_polygons_close():
    orders = build_evac_orders.build()
    assert orders
    for o in orders:
        EvacOrder.model_validate(o.model_dump())
        assert o.source
        assert o.polygon and o.polygon[0] == o.polygon[-1]
        assert all(len(p) == 2 for p in o.polygon)


def test_east_warning_then_order_then_west_order():
    orders = build_evac_orders.build()
    times = {(o.zone_id, o.kind): o.issued_at for o in orders}
    assert times["ALD-EASTLOMA", "warning"] == EAST_WARN
    assert times["ALD-EASTLOMA", "order"] == EAST_ORDER
    assert times["ALD-WAPELLO", "order"] == WEST_ORDER
    assert ("ALD-WAPELLO", "warning") not in times  # investigations: no west warning


def test_thirteen_west_orders_at_325():
    west = [
        o for o in build_evac_orders.build()
        if o.kind == "order" and o.issued_at == WEST_ORDER
    ]
    assert len(west) == 13
    assert {o.zone_id for o in west} >= {
        "ALD-WAPELLO", "ALD-FARNSWORTH", "ALD-CHANEY", "LCF-JPL",
    }


def test_lake_divide_on_order_polygons():
    orders = build_evac_orders.build()
    east = next(o for o in orders if o.zone_id == "ALD-EASTLOMA" and o.kind == "order")
    west = next(o for o in orders if o.zone_id == "ALD-WAPELLO" and o.kind == "order")
    midwick = (34.182888, -118.106120)  # east of Lake
    glenrose = (34.202771, -118.147337)  # west of Lake
    assert _inside(midwick[1], midwick[0], east.polygon)
    assert not _inside(midwick[1], midwick[0], west.polygon)
    assert _inside(glenrose[1], glenrose[0], west.polygon)
    assert not _inside(glenrose[1], glenrose[0], east.polygon)


def test_a_west_home_is_triggered_by_the_evening_report_not_the_3am_order():
    """Call trigger uses the earlier of covering order or nearby report (knowledge.py)."""
    reports = build_fire_reports.build()
    orders = build_evac_orders.build()
    glenrose = next(r for r in reports if r.id == "fr_glenrose")
    person = Resident(
        id="r_test", lat=glenrose.lat, lon=glenrose.lon, h3=glenrose.h3,
        needs="none", vehicle_types=["bus", "wheelchair_van", "ambulance"],
        load_minutes=3, source="estimated",
    )
    evidence = [(r.lat, r.lon, r.reported_at) for r in reports]
    trigger = first_trigger(person, orders, evidence, trigger_km=2.0)
    assert trigger is not None
    assert trigger < WEST_ORDER
    # Calaveras (22:50) is within 2 km of Glenrose, so it starts the call, not the 3:25 order.
    assert trigger == next(r for r in reports if r.id == "fr_calaveras").reported_at
