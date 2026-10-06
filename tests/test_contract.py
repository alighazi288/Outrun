"""The locked data formats (2026-10-05): files hold facts, assumed publish delays are applied
when a record is read, and nothing becomes usable before it existed."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from backend.assumptions import FIRMS_LATENCY_MIN, GOES_LATENCY_MIN, HRRR_PUBLISH_LAG_MIN
from backend.schemas import FireDetection, Shelter, WindForecast

from .conftest import pt


def _detection(**kw) -> FireDetection:
    base = dict(id="d1", lat=34.19, lon=-118.13, h3="8929a1c052fffff", observed_at=pt("01:02", 8))
    return FireDetection(**{**base, **kw})


def test_detection_without_publish_time_waits_for_the_assumed_delay():
    viirs = _detection(source="VIIRS_NOAA21")
    goes = _detection(source="GOES18", pixel_m=2000)
    assert viirs.visible_from() == viirs.observed_at + timedelta(minutes=FIRMS_LATENCY_MIN)
    assert goes.visible_from() == goes.observed_at + timedelta(minutes=GOES_LATENCY_MIN)


def test_a_recorded_publish_time_wins():
    d = _detection(available_at=pt("01:10", 8))
    assert d.visible_from() == pt("01:10", 8)


def test_one_confidence_vocabulary():
    assert _detection(confidence="nominal").confidence == "nominal"
    with pytest.raises(ValidationError):
        _detection(confidence="n")  # FIRMS letters must be mapped to low/nominal/high


def test_wind_from_run_time_waits_for_the_publish_delay():
    w = WindForecast(run_at=pt("21:00"), valid_at=pt("22:00"), lat=34.19, lon=-118.13,
                     speed_ms=15, dir_from_deg=45)
    assert w.visible_from() == pt("21:00") + timedelta(minutes=HRRR_PUBLISH_LAG_MIN)


def test_wind_needs_a_run_or_issue_time():
    with pytest.raises(ValidationError):
        WindForecast(valid_at=pt("22:00"), lat=34.19, lon=-118.13, speed_ms=15, dir_from_deg=45)


def test_a_shelter_is_unusable_before_it_opened(store):
    store.shelters.append(Shelter(id="shelter_late", name="Opens at 22:00", lat=34.15,
                                  lon=-118.14, opened_at=pt("22:00"), source="test"))
    assert "shelter_late" not in {s.id for s in store.at(pt("21:50")).shelters}
    assert "shelter_late" in {s.id for s in store.at(pt("22:00")).shelters}


def test_a_real_dataset_borrows_people_and_fleet_but_never_a_fake_fire(tmp_path):
    from backend.store import DATASETS, DataStore

    folder = tmp_path / "real"
    folder.mkdir()
    (folder / "meta.json").write_text((DATASETS["eaton"] / "meta.json").read_text())
    store = DataStore(folder)
    assert set(store.fake_inputs) == {"residents.jsonl", "facilities.jsonl", "vehicles.jsonl",
                                      "shelters.jsonl"}
    assert store.detections == [] and store.reports == [] and store.wind == []
    assert not store.complete, "the judged export refuses until every input is real"
