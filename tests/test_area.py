"""Setting up any area: national sources become the same dataset files as Altadena. Saved
samples, no network."""

from __future__ import annotations

import json
import random
import urllib.error
import urllib.parse
from datetime import UTC, datetime

import pytest

from backend import area
from backend.census import TOTAL_POPULATION, VARIABLES, api_name

BOX = area.box_around(34.19, -118.13, 4.0)


def _blocks_page(rows, more=False):
    return json.dumps({"features": [{"attributes": r} for r in rows],
                       "exceededTransferLimit": more})


def test_the_box_is_radius_km_each_way():
    box = area.box_around(34.0, -118.0, 4.0)
    assert abs((box["north"] - box["south"]) * 110.574 - 8.0) < 0.01
    assert box["west"] < -118.0 < box["east"]


def test_blocks_keep_inhabited_points_inside_the_box_across_pages():
    pages = [
        _blocks_page([{"GEOID": "060374602002004", "POP100": 185,
                       "INTPTLAT": "+34.2002830", "INTPTLON": "-118.1401793"}], more=True),
        _blocks_page([{"GEOID": "060374602002005", "POP100": 10,
                       "INTPTLAT": "+35.0000000", "INTPTLON": "-118.1401793"}]),  # outside
    ]
    blocks = area.census_blocks(BOX, get=lambda url: pages.pop(0))
    assert [b.geoid for b in blocks] == ["060374602002004"]
    assert blocks[0].population == 185 and blocks[0].geoid[:11] == "06037460200"


def test_acs_is_asked_per_county_and_read_back_by_tract():
    asked = []

    def get(url):
        asked.append(urllib.parse.parse_qs(urllib.parse.urlparse(url).query))
        header = [api_name(v) for v in VARIABLES] + ["state", "county", "tract"]
        return json.dumps([header, ["10"] * len(VARIABLES) + ["06", "037", "460200"]])

    acs = area.acs_by_tract({"06037460200"}, "KEY", get)
    assert asked[0]["in"] == ["state:06 county:037"] and asked[0]["for"] == ["tract:460200"]
    assert acs["06037460200"][TOTAL_POPULATION] == 10


def test_people_go_where_people_live():
    """A tract's people are placed at its blocks by population: an empty-ish block in the
    hills gets far fewer than a dense one."""
    town = area.Block("060374602002004", 990, 34.20, -118.14)
    hills = area.Block("060374602002099", 10, 34.22, -118.10)
    acs = {"06037460200": dict.fromkeys(VARIABLES, 0)}
    acs["06037460200"][TOTAL_POPULATION] = 1000
    acs["06037460200"]["B08201_E008"] = 400  # one-person households with no car
    people = area.estimated_residents([town, hills], acs, random.Random(1))
    assert len(people) == 400 and all(p.needs == "no_car" for p in people)
    in_town = sum((p.lat, p.lon) == (town.lat, town.lon) for p in people)
    assert in_town > 380


def test_nursing_homes_use_their_own_average_residents():
    rows = {"results": [
        {"cms_certification_number_ccn": "555001", "provider_name": "ALTADENA CARE CENTER",
         "latitude": "34.19", "longitude": "-118.13", "number_of_certified_beds": "99",
         "average_number_of_residents_per_day": "73.4"},
        {"cms_certification_number_ccn": "555002", "provider_name": "FAR AWAY",
         "latitude": "36.0", "longitude": "-119.0", "number_of_certified_beds": "50",
         "average_number_of_residents_per_day": "40"},
    ]}
    homes = area.nursing_homes(BOX, {"CA"}, get=lambda url: json.dumps(rows))
    assert [f.name for f, _ in homes] == ["Altadena Care Center"]
    people = area.facility_residents(homes)
    assert len(people) == 73 and {p.source for p in people} == {"facility"}


def test_the_example_shelter_is_a_high_school_outside_the_area_and_says_so():
    schools = {"features": [
        {"attributes": {"NCESSCH": "1", "NAME": "Altadena High", "CITY": "Altadena",
                        "LAT": 34.19, "LON": -118.13}},  # inside the area
        {"attributes": {"NCESSCH": "2", "NAME": "Highland Elementary", "CITY": "X",
                        "LAT": 34.30, "LON": -118.13}},  # not a high school
        {"attributes": {"NCESSCH": "3", "NAME": "La Canada High", "CITY": "La Canada",
                        "LAT": 34.193, "LON": -118.179}},
        {"attributes": {"NCESSCH": "4", "NAME": "Marsh Junior High", "CITY": "Chico",
                        "LAT": 34.191, "LON": -118.170}},  # closer, but not a high school
    ]}
    s = area.example_shelter(34.19, -118.13, 4.0, get=lambda url: json.dumps(schools))
    assert s.name == "La Canada High (example shelter)"
    assert s.source.startswith("EXAMPLE")


def test_a_rural_area_searches_further_for_a_high_school():
    far = {"features": [{"attributes": {"NCESSCH": "9", "NAME": "County High", "CITY": "Far",
                                        "LAT": 34.50, "LON": -118.13}}]}
    calls = []

    def get(url):
        calls.append(url)
        return json.dumps(far if len(calls) == 2 else {"features": []})

    assert area.example_shelter(34.19, -118.13, 4.0, get=get).name.startswith("County High")
    assert len(calls) == 2
    assert area.example_shelter(34.19, -118.13, 4.0,
                                get=lambda url: json.dumps({"features": []})) is None


def _busy(url):
    raise urllib.error.HTTPError(url, 429, "Too Many Requests", None, None)


def test_a_feed_that_fails_keeps_its_last_good_data(tmp_path, monkeypatch):
    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)
    meta = {"bbox": BOX, "feeds_pulled_at": "2026-10-14T20:00:00+00:00",
            "fire_weather": ["Red Flag Warning: test"]}
    (tmp_path / "meta.json").write_text(json.dumps(meta))
    (tmp_path / "wind.jsonl").write_text("last good wind\n")
    now = datetime(2026, 10, 14, 20, 30, tzinfo=UTC)
    summary = area.refresh_fire(tmp_path, now, get=_busy)
    assert [p.split(":")[0] for p in summary["problems"]] == ["wind", "alerts"]
    assert (tmp_path / "wind.jsonl").read_text() == "last good wind\n"
    after = json.loads((tmp_path / "meta.json").read_text())
    assert after["fire_weather"] == ["Red Flag Warning: test"] and after["feed_problems"]


def test_setting_up_without_any_wind_is_an_error_not_a_still_day(tmp_path, monkeypatch):
    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)
    (tmp_path / "meta.json").write_text(json.dumps({"bbox": BOX}))
    with pytest.raises(area.feeds.FeedError):
        area.refresh_fire(tmp_path, datetime(2026, 10, 14, 20, 30, tzinfo=UTC), get=_busy)


def test_the_example_fleet_is_the_baseline_at_the_shelter():
    shelter = area.Shelter(id="s", name="S", lat=34.0, lon=-118.0)
    fleet = area.example_fleet(shelter)
    assert len(fleet) == sum(area.FLEET_BASELINE.values())
    assert {(v.lat, v.lon) for v in fleet} == {(34.0, -118.0)}


def test_a_fire_report_drives_the_forecast_only_while_new_and_active():
    from datetime import UTC, datetime, timedelta

    now = datetime(2026, 10, 15, 17, 0, tzinfo=UTC)
    fire = {"id": "F", "name": "PICO", "place": "Los Angeles, CA", "lat": 34.03, "lon": -118.04,
            "status": "active", "discovered_at": (now - timedelta(minutes=90)).isoformat()}
    report = area.incident_report(fire, now)
    assert report.id == "nifc_F" and report.reported_at == now - timedelta(minutes=90)
    assert "NIFC" in report.source and not report.description.startswith("DRILL")
    assert area.incident_report(fire, now + timedelta(hours=1)) is None, "old: satellites only"
    assert area.incident_report({**fire, "status": "contained"}, now) is None
