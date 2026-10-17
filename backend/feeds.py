"""Live feeds: today's fire, wind and alerts over an area, as the same records the replay uses.

    uv run python -m backend.feeds              # what is live over Altadena right now
    uv run python -m backend.feeds --dataset palisades

Standard library only, so it runs on the free API host. Every record keeps the time its
source made it (observed_at, run_at, issued_at), so the no-hindsight rules still hold.

- fires():  NASA FIRMS area API, near-real-time. VIIRS on three satellites (375 m pixels) and
  GOES (2 km pixels, every few minutes).
- wind():   Open-Meteo's copy of NOAA's HRRR model, a small grid of points over the area,
  stamped with the model run's start and availability times.
- alerts(): the FEMA IPAWS public feed (county evacuation orders and warnings go out on it, as
  they did for Eaton) and the National Weather Service (fire weather). Only evacuation alerts
  become EvacOrders; a Red Flag Warning is context for the manager, not an order.

Each function takes `get` so tests can feed it saved responses instead of the network.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import h3

from backend.schemas import H3_RES, EvacOrder, FireDetection, WindForecast, publish_delay_min

Get = Callable[[str], str]
USER_AGENT = "Outrun wildfire evacuation prototype (github.com/alighazi288/Outrun)"

FIRMS_AREA = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{source}/{box}/{days}"
FIRMS_SOURCES = ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT", "GOES_NRT")
SATELLITE = {
    "N": "VIIRS_SNPP", "N20": "VIIRS_NOAA20", "N21": "VIIRS_NOAA21",
    "G16": "GOES16", "G17": "GOES17", "G18": "GOES18", "G19": "GOES19",
}
VIIRS_CONFIDENCE = {"l": "low", "n": "nominal", "h": "high"}

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_HRRR_META = "https://api.open-meteo.com/data/ncep_hrrr_conus/static/meta.json"
WIND_GRID = 3  # points per side over the area (HRRR cells are 3 km)
WIND_HOURS = 4

NWS_POINT = "https://api.weather.gov/alerts/active?point={lat:.4f},{lon:.4f}"
IPAWS_RECENT = "https://apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/public/recent/{since}"
CAP = "{urn:oasis:names:tc:emergency:cap:1.2}"
FIRE_WEATHER = {"Red Flag Warning", "Fire Weather Watch", "Fire Warning", "Extreme Fire Danger"}


def http_get(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8")


# --------------------------------------------------------------------------------------
# Fire detections (NASA FIRMS)
# --------------------------------------------------------------------------------------


def fires(box: dict, key: str, now: datetime, days: int = 1,
          get: Get = http_get) -> list[FireDetection]:
    """Every VIIRS and GOES detection in the box over the last `days` (1-10)."""
    where = f"{box['west']},{box['south']},{box['east']},{box['north']}"
    out: list[FireDetection] = []
    for source in FIRMS_SOURCES:
        text = get(FIRMS_AREA.format(key=key, source=source, box=where, days=days))
        if not text.startswith("latitude"):
            raise RuntimeError(f"FIRMS {source}: {text[:200]}")  # e.g. an invalid key
        out += parse_firms_csv(text, now)
    return sorted(out, key=lambda d: (d.observed_at, d.id))


def parse_firms_csv(text: str, fetched_at: datetime) -> list[FireDetection]:
    """FIRMS CSV rows -> FireDetection. acq_date + acq_time are UTC. A row we hold was
    published by the time we fetched it, so it is usable from the earlier of that and the
    assumed publish delay."""
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        lat, lon = float(row["latitude"]), float(row["longitude"])
        hhmm = row["acq_time"].zfill(4)
        observed = datetime.strptime(f"{row['acq_date']} {hhmm}", "%Y-%m-%d %H%M").replace(
            tzinfo=UTC)
        source = SATELLITE.get(row["satellite"], row["satellite"])
        goes = source.startswith("GOES")
        delay = timedelta(minutes=publish_delay_min(source))
        frp = float(row["frp"]) if row.get("frp") not in (None, "", "-999") else None
        out.append(FireDetection(
            id=f"{source}_{row['acq_date']}_{hhmm}_{lat:.4f}_{lon:.4f}",
            lat=lat, lon=lon, h3=h3.latlng_to_cell(lat, lon, H3_RES),
            observed_at=observed,
            available_at=min(fetched_at, observed + delay),
            source=source,
            pixel_m=2000.0 if goes else 375.0,
            frp_mw=frp,
            confidence=None if goes else VIIRS_CONFIDENCE.get(row["confidence"].strip().lower()),
        ))
    return out


# --------------------------------------------------------------------------------------
# Wind (NOAA HRRR via Open-Meteo)
# --------------------------------------------------------------------------------------


def wind(box: dict, get: Get = http_get) -> list[WindForecast]:
    """The next WIND_HOURS of 10 m wind and gusts on a WIND_GRID x WIND_GRID grid."""
    lats = [box["south"] + (box["north"] - box["south"]) * (i + 0.5) / WIND_GRID
            for i in range(WIND_GRID)]
    lons = [box["west"] + (box["east"] - box["west"]) * (j + 0.5) / WIND_GRID
            for j in range(WIND_GRID)]
    points = [(la, lo) for la in lats for lo in lons]
    query = (
        f"latitude={','.join(f'{p[0]:.4f}' for p in points)}"
        f"&longitude={','.join(f'{p[1]:.4f}' for p in points)}"
        "&hourly=wind_speed_10m,wind_direction_10m,wind_gusts_10m&models=gfs_hrrr"
        f"&wind_speed_unit=ms&forecast_hours={WIND_HOURS}&past_hours=1&timezone=UTC"
    )
    return parse_open_meteo(get(f"{OPEN_METEO}?{query}"), get(OPEN_METEO_HRRR_META))


def parse_open_meteo(forecast: str, meta: str) -> list[WindForecast]:
    """One WindForecast per point per hour. run_at = the HRRR run Open-Meteo is serving;
    issued_at = when that run became available there."""
    m = json.loads(meta)
    run_at = datetime.fromtimestamp(m["last_run_initialisation_time"], UTC)
    issued_at = datetime.fromtimestamp(m["last_run_availability_time"], UTC)
    data = json.loads(forecast)
    out = []
    for point in data if isinstance(data, list) else [data]:
        hourly = point["hourly"]
        for i, when in enumerate(hourly["time"]):
            speed, direction = hourly["wind_speed_10m"][i], hourly["wind_direction_10m"][i]
            if speed is None or direction is None:
                continue
            out.append(WindForecast(
                run_at=run_at, issued_at=issued_at,
                valid_at=datetime.fromisoformat(when).replace(tzinfo=UTC),
                lat=point["latitude"], lon=point["longitude"],
                speed_ms=speed, dir_from_deg=float(direction) % 360,
                gust_ms=hourly["wind_gusts_10m"][i],
            ))
    return out


def time_zone(lat: float, lon: float, get: Get = http_get) -> str:
    """The IANA time zone at a point (Open-Meteo), e.g. "America/Chicago", for showing an
    area's times the way people there read their clocks."""
    query = f"latitude={lat:.4f}&longitude={lon:.4f}&timezone=auto&current=temperature_2m"
    return json.loads(get(f"{OPEN_METEO}?{query}"))["timezone"]


# --------------------------------------------------------------------------------------
# Alerts (FEMA IPAWS public feed, National Weather Service)
# --------------------------------------------------------------------------------------


def alert_kind(event: str, text: str, codes: set[str]) -> str | None:
    """Order, warning or advisory from the alert's own words (same rule as the Eaton
    alerts, scripts/build_evac_orders.py) or its event code. None: not an evacuation."""
    words = f"{event} {text}".upper()
    if "EVACUATION ORDER" in words or "EVACUATE NOW" in words:
        return "order"
    if "EVACUATION WARNING" in words:
        return "warning"
    if "EVI" in codes:  # Evacuation Immediate
        return "order"
    if "EVACUATION" in words and "BE AWARE" in words:
        return "advisory"
    return None


def alerts(box: dict, now: datetime, hours: int = 24,
           get: Get = http_get) -> tuple[list[EvacOrder], list[str]]:
    """(evacuation alerts touching the box, fire-weather alerts in effect there)."""
    since = (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    orders = [o for o in parse_ipaws(get(IPAWS_RECENT.format(since=since)))
              if o.polygon and _touches(o.polygon, box)]
    weather: set[str] = set()
    for lat, lon in _sample_points(box):
        for feature in json.loads(get(NWS_POINT.format(lat=lat, lon=lon)))["features"]:
            p = feature["properties"]
            if p["event"] in FIRE_WEATHER:
                weather.add(f"{p['event']}: {p.get('headline') or p['areaDesc']}")
    return orders, sorted(weather)


def parse_ipaws(xml_text: str) -> list[EvacOrder]:
    """CAP 1.2 alerts from the IPAWS public feed -> EvacOrder (evacuation alerts only)."""
    out = []
    for alert in ET.fromstring(xml_text).iter(f"{CAP}alert"):
        sent = datetime.fromisoformat(alert.findtext(f"{CAP}sent"))
        ident = alert.findtext(f"{CAP}identifier", "")
        for info in alert.iter(f"{CAP}info"):
            event = info.findtext(f"{CAP}event", "")
            text = " ".join(info.findtext(f"{CAP}{t}", "") for t in
                            ("headline", "description", "instruction"))
            codes = {v.text or "" for v in info.iter(f"{CAP}value")}
            kind = alert_kind(event, text, codes)
            if kind is None:
                continue
            for n, area in enumerate(info.iter(f"{CAP}area")):
                polygon = _cap_polygon(area.findtext(f"{CAP}polygon"))
                out.append(EvacOrder(
                    zone_id=f"ipaws-{ident[-12:]}-{n}", kind=kind, issued_at=sent,
                    area=area.findtext(f"{CAP}areaDesc", "") or event, polygon=polygon,
                    source=f"FEMA IPAWS public feed, CAP alert {ident}",
                ))
    return out


def _cap_polygon(text: str | None) -> list[list[float]] | None:
    """CAP "lat,lon lat,lon ..." -> [[lon, lat], ...] (GeoJSON order)."""
    if not text:
        return None
    pairs = [p.split(",") for p in text.split()]
    return [[float(lon), float(lat)] for lat, lon in pairs]


def _touches(polygon: list[list[float]], box: dict) -> bool:
    """Do the polygon's bounds overlap the box? (Cheap; the knowledge rule then tests each
    home against the polygon itself.)"""
    lons, lats = [p[0] for p in polygon], [p[1] for p in polygon]
    return (min(lons) <= box["east"] and max(lons) >= box["west"]
            and min(lats) <= box["north"] and max(lats) >= box["south"])


def _sample_points(box: dict) -> list[tuple[float, float]]:
    """The centre and four inner corners: NWS alerts are by forecast zone, so a few points
    cover a town-sized area."""
    s, w, n, e = box["south"], box["west"], box["north"], box["east"]
    dy, dx = (n - s) / 4, (e - w) / 4
    return [((s + n) / 2, (w + e) / 2), (s + dy, w + dx), (s + dy, e - dx),
            (n - dy, w + dx), (n - dy, e - dx)]


# --------------------------------------------------------------------------------------
# Command line: what is live over an area right now
# --------------------------------------------------------------------------------------


def main() -> None:
    from backend.store import DATASETS

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", default="eaton", help="whose area to pull (default eaton)")
    parser.add_argument("--days", type=int, default=1, help="days of fire detections (1-10)")
    args = parser.parse_args()
    box = json.loads((DATASETS[args.dataset] / "meta.json").read_text())["bbox"]
    now = datetime.now(UTC)
    print(f"Live over '{args.dataset}' {box} at {now:%Y-%m-%d %H:%M} UTC")

    key = os.environ.get("FIRMS_MAP_KEY")
    if key:
        found = fires(box, key, now, args.days)
        viirs = [d for d in found if not d.source.startswith("GOES")]
        print(f"  fire detections, last {args.days} day(s): {len(viirs)} VIIRS, "
              f"{len(found) - len(viirs)} GOES"
              + (f"; latest {found[-1].observed_at:%H:%M} UTC ({found[-1].source})"
                 if found else ""))
    else:
        print("  fire detections: skipped, FIRMS_MAP_KEY is not set")
    w = wind(box)
    if w:
        latest = max(w, key=lambda r: r.valid_at)
        print(f"  wind: HRRR run {w[0].run_at:%H:%M} UTC, available {w[0].issued_at:%H:%M}; "
              f"{len(w)} values; at {latest.valid_at:%H:%M} UTC {latest.speed_ms:.1f} m/s "
              f"from {latest.dir_from_deg:.0f}°")
    orders, weather = alerts(box, now)
    print(f"  evacuation alerts in the last 24 h: {len(orders)}")
    for o in orders:
        print(f"    {o.issued_at:%H:%M} {o.kind}: {o.area[:70]}")
    print(f"  fire weather: {'; '.join(weather) if weather else 'none in effect'}")


if __name__ == "__main__":
    main()
