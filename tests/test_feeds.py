"""Live feeds turn each source's own format into the records the replay uses. Saved samples,
no network."""

from __future__ import annotations

import json
import urllib.error
from datetime import UTC, datetime, timedelta

import pytest

from backend import feeds

NOW = datetime(2026, 10, 14, 20, 30, tzinfo=UTC)
BOX = {"south": 34.15, "west": -118.19, "north": 34.23, "east": -118.08}

FIRMS_CSV = (
    "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,"
    "confidence,version,bright_ti5,frp,daynight\n"
) + """34.2001,-118.1302,330.1,0.4,0.4,2026-10-14,2012,N20,VIIRS,h,2.0NRT,290.2,12.5,D
34.1950,-118.1210,-999,815,1117,2026-10-14,5,G18,,30.0000,1.1NRT,-999,83.96,D
"""

OPEN_METEO = json.dumps([
    {"latitude": 34.17, "longitude": -118.17,
     "hourly": {"time": ["2026-10-14T20:00", "2026-10-14T21:00"],
                "wind_speed_10m": [12.0, None], "wind_direction_10m": [45, 50],
                "wind_gusts_10m": [20.0, 21.0]}},
])
META = json.dumps({"last_run_initialisation_time": 1791997200,
                   "last_run_availability_time": 1792004214})

IPAWS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ns1:alerts xmlns:ns1="http://gov.fema.ipaws.services/feed">
<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
  <identifier>urn:oid:2.49.0.1.840.0.abc123</identifier>
  <sent>2026-10-14T13:05:00-07:00</sent>
  <info><event>Evacuation Immediate</event>
    <eventCode><valueName>SAME</valueName><value>EVI</value></eventCode>
    <headline>EVACUATION ORDER for zone ALD-1</headline>
    <description>Leave now.</description>
    <area><areaDesc>Altadena zone ALD-1</areaDesc>
      <polygon>34.19,-118.15 34.21,-118.15 34.21,-118.12 34.19,-118.12 34.19,-118.15</polygon>
    </area>
  </info>
</alert>
<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
  <identifier>urn:oid:2.49.0.1.840.0.def456</identifier>
  <sent>2026-10-14T15:09:00-05:00</sent>
  <info><event>Flash Flood Warning</event>
    <eventCode><valueName>SAME</valueName><value>FFW</value></eventCode>
    <headline>Flash Flood Warning</headline>
    <area><areaDesc>Pecos, TX</areaDesc>
      <polygon>31.0,-103.0 31.1,-103.0 31.1,-102.9 31.0,-103.0</polygon></area>
  </info>
</alert>
</ns1:alerts>"""


def test_firms_rows_become_detections_with_the_right_pixel_and_publish_time():
    viirs, goes = feeds.parse_firms_csv(FIRMS_CSV, NOW)
    assert viirs.source == "VIIRS_NOAA20" and viirs.pixel_m == 375 and viirs.confidence == "high"
    assert viirs.observed_at == datetime(2026, 10, 14, 20, 12, tzinfo=UTC)
    # Fetched 18 min after the pass: published by then, sooner than the assumed 30 min.
    assert viirs.available_at == NOW and viirs.visible_from() == NOW
    assert goes.source == "GOES18" and goes.pixel_m == 2000 and goes.confidence is None
    assert goes.observed_at == datetime(2026, 10, 14, 0, 5, tzinfo=UTC)
    assert goes.available_at == goes.observed_at + timedelta(minutes=15)  # assumed delay
    assert goes.frp_mw == 83.96


def test_a_bad_firms_key_is_an_error_not_an_empty_sky():
    import pytest

    with pytest.raises(RuntimeError, match="Invalid MAP_KEY"):
        feeds.fires(BOX, "nope", NOW, get=lambda url: "Invalid MAP_KEY.")


def test_open_meteo_wind_keeps_the_model_run_times():
    rows = feeds.parse_open_meteo(OPEN_METEO, META)
    assert len(rows) == 1, "an hour with no value is skipped"
    w = rows[0]
    assert w.run_at == datetime.fromtimestamp(1791997200, UTC)
    assert w.visible_from() == datetime.fromtimestamp(1792004214, UTC)
    assert (w.speed_ms, w.dir_from_deg, w.gust_ms) == (12.0, 45.0, 20.0)


def test_only_evacuation_alerts_become_orders_with_their_outline():
    orders = feeds.parse_ipaws(IPAWS_XML)
    assert len(orders) == 1, "a flash flood warning is not an evacuation"
    o = orders[0]
    assert o.kind == "order" and o.area == "Altadena zone ALD-1"
    assert o.polygon[0] == [-118.15, 34.19], "CAP lat,lon becomes GeoJSON lon,lat"
    assert o.issued_at == datetime(2026, 10, 14, 20, 5, tzinfo=UTC)


def test_alert_kinds_use_the_same_words_as_the_eaton_alerts():
    assert feeds.alert_kind("Civil Emergency", "EVACUATION WARNING for ...", set()) == "warning"
    assert feeds.alert_kind("Evacuation Immediate", "", {"EVI"}) == "order"
    assert feeds.alert_kind("Red Flag Warning", "critical fire weather", {"FWW"}) is None


def test_alerts_keep_orders_touching_the_area_and_list_fire_weather():
    nws = json.dumps({"features": [
        {"properties": {"event": "Red Flag Warning", "headline": "Red Flag Warning until Fri",
                        "areaDesc": "LA County"}},
        {"properties": {"event": "Heat Advisory", "headline": "hot", "areaDesc": "LA"}},
    ]})

    def get(url: str) -> str:
        return IPAWS_XML if "ipaws" in url.lower() else nws

    orders, weather = feeds.alerts(BOX, NOW, get=get)
    assert [o.area for o in orders] == ["Altadena zone ALD-1"]
    assert weather == ["Red Flag Warning: Red Flag Warning until Fri"]


NWS_GRID = json.dumps({"properties": {
    "updateTime": "2026-10-14T19:45:00+00:00",
    "windSpeed": {"uom": "wmoUnit:km_h-1", "values": [
        {"validTime": "2026-10-14T19:00:00+00:00/PT3H", "value": 36.0},
        {"validTime": "2026-10-14T22:00:00+00:00/PT1H", "value": 18.0}]},
    "windDirection": {"values": [{"validTime": "2026-10-14T19:00:00+00:00/PT4H", "value": 45}]},
    "windGust": {"values": [{"validTime": "2026-10-14T19:00:00+00:00/PT2H", "value": 54.0}]},
}})


def _busy(url):
    raise urllib.error.HTTPError(url, 429, "Too Many Requests", None, None)


def _nws(url):
    if "/points/" in url:
        return json.dumps({"properties": {"forecastGridData": "https://api.weather.gov/grid",
                                          "timeZone": "America/Denver"}})
    if url == "https://api.weather.gov/grid":
        return NWS_GRID
    return _busy(url)


def test_nws_wind_is_hourly_in_metres_per_second_from_its_update_time():
    rows = feeds.parse_nws_grid(NWS_GRID, 34.2, -118.1, NOW)
    assert [(r.valid_at.hour, r.speed_ms, r.gust_ms) for r in rows] == [
        (20, 10.0, 15.0), (21, 10.0, None), (22, 5.0, None)]
    assert {r.issued_at for r in rows} == {datetime(2026, 10, 14, 19, 45, tzinfo=UTC)}
    assert {r.dir_from_deg for r in rows} == {45.0}


def test_wind_comes_from_the_nws_and_never_needs_open_meteo():
    rows = feeds.wind(BOX, NOW, get=_nws)  # Open-Meteo refuses us (429)
    assert len(rows) == 3 * len(feeds._sample_points(BOX))


def test_wind_falls_back_to_open_meteo_then_says_it_is_unavailable():
    def open_meteo(url):
        if "open-meteo" not in url:
            return _busy(url)
        return META if "meta.json" in url else OPEN_METEO

    assert feeds.wind(BOX, NOW, get=open_meteo) == feeds.parse_open_meteo(OPEN_METEO, META)
    with pytest.raises(feeds.FeedError):
        feeds.wind(BOX, NOW, get=_busy)


def test_an_area_reads_its_own_time_zone():
    assert feeds.time_zone(39.7, -105.0, get=_nws) == "America/Denver"
    assert feeds.time_zone(34.6, -91.4, get=lambda url: _busy(url) if "weather.gov" in url
                           else json.dumps({"timezone": "America/Chicago"})) == "America/Chicago"
    assert feeds.time_zone(34.6, -91.4, get=_busy) == "UTC", "never a reason to fail setup"
