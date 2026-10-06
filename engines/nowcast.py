"""Fire nowcast: P(fire reaches each map cell within 1, 2 and 3 hours).

STUB. Good enough to drive the rest of the system, not good enough to evaluate. The real
version (see engines/README.md) fits the spread rate from past fires and runs 100+ Monte
Carlo runs with varied wind, including downwind ember spotting.

Fire evidence comes from two sources: satellite detections and fire reports (911/radio).
Reports matter: on the Eaton night the VIIRS satellite's first detection came at 1:30 a.m.,
hours after the first reports of fire west of Lake Avenue.

How the stub works:
1. Cells within a detection's pixel size (pixel_m), or within a report's stated location
   precision of a report, are burning (arrival = 0).
2. The active fire front is the evidence from the last ACTIVE_WINDOW.
3. Fire spreads fastest downwind and slowest upwind (an ellipse). The spread rate in any
   direction mixes the head rate and the backing rate by how aligned that direction is
   with the wind.
4. Median arrival at a cell = distance / rate, minus the time since the fire was seen there.
5. Uncertainty: the true rate varies around our guess by a log-normal factor (SIGMA).
   That gives P(arrival <= 1 h / 2 h / 3 h) and the pessimistic 10th-percentile arrival.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

import h3

from backend.assumptions import HORIZON_MIN
from backend.schemas import FireDetection, FireOutlook, FireReport, WindForecast
from engines.travel import haversine_m

BACKING_RATE_M_PER_MIN = 3.0  # spread against the wind
HEAD_RATE_M_PER_MIN_PER_MS = 0.7  # extra head-fire speed per m/s of wind
DETECTION_RADIUS_M = 375.0  # VIIRS pixel size: the smallest radius any fire evidence gets
ACTIVE_WINDOW = timedelta(hours=2)
SIGMA = 0.4  # log-normal spread of the rate (uncertainty)
MIN_P_TO_REPORT = 0.01
Z_P10 = -1.2816  # 10th percentile of the standard normal


@dataclass(frozen=True)
class _Evidence:
    """A place where fire was seen, when, and how precisely it is located."""

    lat: float
    lon: float
    seen_at: datetime
    radius_m: float


def nowcast(
    detections: list[FireDetection],
    wind: list[WindForecast],
    cells: list[str],
    t: datetime,
    reports: Sequence[FireReport] = (),
) -> list[FireOutlook]:
    """Forecast for every cell with a meaningful chance of fire within 3 hours.

    Inputs are already filtered to what existed at t (DataStore.at(t)).
    """
    evidence = [_Evidence(d.lat, d.lon, d.observed_at, d.pixel_m) for d in detections]
    evidence += [
        _Evidence(r.lat, r.lon, r.reported_at, max(r.location_precision_m, DETECTION_RADIUS_M))
        for r in reports
    ]
    if not evidence:
        return []
    active = [e for e in evidence if t - e.seen_at <= ACTIVE_WINDOW] or evidence
    near: tuple[float, float] = (
        sum(e.lat for e in active) / len(active),
        sum(e.lon for e in active) / len(active),
    )
    speed, dir_to = wind_at(wind, t, near)
    head_rate = BACKING_RATE_M_PER_MIN + HEAD_RATE_M_PER_MIN_PER_MS * speed

    out = []
    for cell in cells:
        lat, lon = h3.cell_to_latlng(cell)
        if any(_dist_m(lat, lon, e.lat, e.lon) <= e.radius_m for e in evidence):
            out.append(FireOutlook(t=t, h3=cell, p_1h=1, p_2h=1, p_3h=1,
                                   arrival_p10_min=0, burning=True))
            continue
        median = min(
            _arrival_min(e, lat, lon, t, head_rate, dir_to) for e in active
        )
        p1, p2, p3 = (_p_within(median, h) for h in (60, 120, 180))
        if p3 < MIN_P_TO_REPORT:
            continue
        p10 = median * math.exp(Z_P10 * SIGMA)
        out.append(FireOutlook(
            t=t, h3=cell, p_1h=round(p1, 4), p_2h=round(p2, 4), p_3h=round(p3, 4),
            arrival_p10_min=round(p10, 1) if p10 <= HORIZON_MIN else None,
        ))
    return out


def wind_at(
    wind: list[WindForecast],
    t: datetime,
    near: tuple[float, float] | None = None,
) -> tuple[float, float]:
    """(speed m/s, direction the wind blows TOWARD in degrees) from the latest forecast
    issued at or before t, for the valid time closest to t.

    All rows sharing that valid_at are used:
    - If *near* is given, pick the row geographically nearest to (lat, lon).
    - If *near* is None, return the vector mean over all rows.
    """
    if not wind:
        return 0.0, 0.0
    latest_issue = max(w.visible_from() for w in wind)
    run = [w for w in wind if w.visible_from() == latest_issue]
    best_valid = min(run, key=lambda w: abs((w.valid_at - t).total_seconds())).valid_at
    rows = [w for w in run if w.valid_at == best_valid]

    if near is not None:
        w = min(rows, key=lambda w: haversine_m(near, (w.lat, w.lon)))
        return w.speed_ms, (w.dir_from_deg + 180) % 360

    # Vector mean: u = -speed*sin(dir_from), v = -speed*cos(dir_from)
    u = sum(-w.speed_ms * math.sin(math.radians(w.dir_from_deg)) for w in rows) / len(rows)
    v = sum(-w.speed_ms * math.cos(math.radians(w.dir_from_deg)) for w in rows) / len(rows)
    speed = math.hypot(u, v)
    if speed == 0.0:
        return 0.0, 0.0
    # dir_from is the direction the vector points FROM (opposite to u,v)
    dir_from = math.degrees(math.atan2(-u, -v)) % 360
    return speed, (dir_from + 180) % 360


def _arrival_min(
    e: _Evidence, lat: float, lon: float, t: datetime, head_rate: float, dir_to: float
) -> float:
    dist = _dist_m(e.lat, e.lon, lat, lon)
    bearing = _bearing_deg(e.lat, e.lon, lat, lon)
    alignment = math.cos(math.radians(bearing - dir_to))  # 1 = straight downwind
    downwind_share = max(alignment, 0.0)
    rate = BACKING_RATE_M_PER_MIN + (head_rate - BACKING_RATE_M_PER_MIN) * downwind_share**2
    elapsed = (t - e.seen_at).total_seconds() / 60
    return max(dist / rate - elapsed, 1.0)


def _p_within(median_min: float, horizon_min: float) -> float:
    """P(arrival <= horizon) when arrival is log-normal around the median."""
    z = (math.log(horizon_min) - math.log(median_min)) / SIGMA
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Fast flat-earth distance; fine at city scale."""
    dy = (lat2 - lat1) * 110_540
    dx = (lon2 - lon1) * 111_320 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dy = lat2 - lat1
    dx = (lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    return math.degrees(math.atan2(dx, dy)) % 360
