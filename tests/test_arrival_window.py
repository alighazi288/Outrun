"""The arrival window: a hex is reached by DINS, a VIIRS detection or a precise report;
earliest is the last clear look, latest is the first evidence; strict scoring uses earliest."""

from __future__ import annotations

import h3

from backend.schemas import H3_RES, EvacOrder, FireDetection, FireReport, Resident
from evaluation.arrival_window import (
    ArrivalWindow,
    build_windows,
    dins_hexes,
    read_windows,
    score,
    warning_lead_min,
    warning_precision,
    write_windows,
)

from .conftest import pt

START, END = pt("18:18"), pt("06:00", day=8)
HOME = (34.19, -118.13)
HOME_H3 = h3.latlng_to_cell(*HOME, H3_RES)
FAR = (34.21, -118.09)
FAR_H3 = h3.latlng_to_cell(*FAR, H3_RES)
CELLS = sorted({HOME_H3, FAR_H3} | set(h3.grid_disk(HOME_H3, 1)))


def _det(when, lat, lon, pixel=375.0, i=0) -> FireDetection:
    return FireDetection(
        id=f"d{i}", lat=lat, lon=lon, h3=h3.latlng_to_cell(lat, lon, H3_RES),
        observed_at=when, source="VIIRS_SNPP", pixel_m=pixel,
    )


def _report(when, lat, lon, precision=250.0) -> FireReport:
    return FireReport(
        id="fr", lat=lat, lon=lon, h3=h3.latlng_to_cell(lat, lon, H3_RES), reported_at=when,
        description="fire", location_precision_m=precision, source="test",
    )


def _person(rid="r", h3_cell=HOME_H3, needs="wheelchair") -> Resident:
    lat, lon = h3.cell_to_latlng(h3_cell)
    return Resident(
        id=rid, lat=lat, lon=lon, h3=h3_cell, needs=needs,
        vehicle_types=["wheelchair_van"], load_minutes=12,
    )


def _build(detections=(), reports=(), dins=frozenset()):
    return build_windows(CELLS, list(detections), list(reports), set(dins), START, END)


def test_detection_sets_latest_and_fire_start_sets_earliest():
    w = _build([_det(pt("23:00"), *HOME)])[HOME_H3]
    assert w.latest == pt("23:00")
    assert w.earliest == START
    assert w.reached_by == ["detection"] and w.clear_from == "fire_start"


def test_a_clear_satellite_pass_raises_earliest():
    passes = [_det(pt("21:00"), *FAR, i=1), _det(pt("23:00"), *HOME, i=2)]
    w = _build(passes)[HOME_H3]
    assert w.earliest == pt("21:00"), "the 21:00 pass saw FAR burn and HOME clear"
    assert w.latest == pt("23:00") and w.clear_from == "satellite_pass"


def test_goes_pixels_are_not_truth():
    assert _build([_det(pt("22:00"), *HOME, pixel=2000.0)]) == {}


def test_a_coarse_report_cannot_name_one_hex():
    assert _build(reports=[_report(pt("22:00"), *HOME, precision=1000.0)]) == {}
    w = _build(reports=[_report(pt("22:00"), *HOME)])[HOME_H3]
    assert w.latest == pt("22:00") and w.reached_by == ["report"]


def test_dins_says_where_not_when():
    geojson = {"features": [
        {"geometry": {"type": "Point", "coordinates": [HOME[1], HOME[0]]},
         "properties": {"DAMAGE": "Destroyed (>50%)"}},
        {"geometry": {"type": "Point", "coordinates": [FAR[1], FAR[0]]},
         "properties": {"DAMAGE": "No Damage"}},
    ]}
    burned = dins_hexes(geojson)
    assert burned == {HOME_H3}
    w = _build(dins=burned)[HOME_H3]
    assert w.dins_only and w.latest == END and w.earliest == START
    both = _build([_det(pt("23:00"), *HOME)], dins=burned)[HOME_H3]
    assert not both.dins_only and both.reached_by == ["detection", "dins"]


def test_window_is_ordered_for_every_fixture_hex(store):
    windows = build_windows(
        store.cells, store.detections, store.reports, set(), pt("18:00"), pt("06:00", day=8),
    )
    assert windows
    for w in windows.values():
        assert pt("18:00") <= w.earliest <= w.latest
    for d in store.detections:
        if d.h3 in windows:
            assert windows[d.h3].latest <= d.observed_at


def test_strict_counts_before_earliest_lenient_before_latest():
    windows = {HOME_H3: ArrivalWindow(
        h3=HOME_H3, earliest=pt("21:00"), latest=pt("23:00"), reached_by=["detection"],
        clear_from="satellite_pass",
    )}
    person = _person()
    between = {person.id: pt("22:00")}
    assert score([person], between, windows, strict=True).saved == 0
    assert score([person], between, windows, strict=False).saved == 1
    assert score([person], {person.id: pt("20:50")}, windows).saved == 1
    assert score([person], {}, windows).reached == 1
    assert score([_person(needs="none")], {}, windows).reached == 0
    assert score([_person(h3_cell=FAR_H3)], {}, windows).reached == 0


def test_warning_lead_and_precision():
    lat, lon = h3.cell_to_latlng(HOME_H3)
    box = [[lon - 0.01, lat - 0.01], [lon + 0.01, lat - 0.01], [lon + 0.01, lat + 0.01],
           [lon - 0.01, lat + 0.01], [lon - 0.01, lat - 0.01]]
    orders = [EvacOrder(zone_id="z", kind="order", issued_at=pt("20:00"), area="home",
                        polygon=box, source="test")]
    windows = _build([_det(pt("21:00"), *FAR, i=1), _det(pt("23:00"), *HOME, i=2)])
    lead = warning_lead_min(windows, orders)
    assert lead[HOME_H3] == 60, "ordered at 20:00, earliest plausible arrival 21:00"
    assert lead[FAR_H3] is None, "never ordered"
    precision = warning_precision(CELLS, windows, orders)
    assert precision is not None and 0 < precision < 1


def test_round_trip(tmp_path):
    windows = _build([_det(pt("23:00"), *HOME)])
    path = tmp_path / "arrival_window.jsonl"
    write_windows(path, windows)
    assert read_windows(path) == windows
