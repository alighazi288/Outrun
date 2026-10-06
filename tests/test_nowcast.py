"""Unit tests for engines.nowcast.wind_at."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.schemas import WindForecast
from engines.nowcast import wind_at

_ISSUED = datetime(2025, 1, 7, 20, 0, tzinfo=UTC)
_VALID = datetime(2025, 1, 7, 21, 0, tzinfo=UTC)


def _w(lat: float, lon: float, speed: float, dir_from: float) -> WindForecast:
    return WindForecast(
        issued_at=_ISSUED,
        valid_at=_VALID,
        lat=lat,
        lon=lon,
        speed_ms=speed,
        dir_from_deg=dir_from,
    )


# ---------------------------------------------------------------------------
# Test 1: near picks the geographically closer of two rows at the same valid_at
# ---------------------------------------------------------------------------

def test_near_picks_closest_point():
    """When near is given, wind_at returns the row nearest to that point."""
    # Two grid points at the same valid_at with *different* wind values.
    # Point A: (34.0, -118.0), blowing from north  → dir_to = 180°
    # Point B: (34.5, -118.0), blowing from south  → dir_to = 0°
    point_a = _w(34.0, -118.0, speed=5.0, dir_from=0.0)
    point_b = _w(34.5, -118.0, speed=5.0, dir_from=180.0)

    # Query point is very close to A (34.01 vs 34.5)
    speed, dir_to = wind_at([point_a, point_b], _VALID, near=(34.01, -118.0))
    assert speed == 5.0
    assert abs(dir_to - 180.0) < 1e-6, f"Expected dir_to≈180°, got {dir_to}"

    # Query point is very close to B
    speed2, dir_to2 = wind_at([point_a, point_b], _VALID, near=(34.49, -118.0))
    assert speed2 == 5.0
    assert abs(dir_to2 - 0.0) < 1e-6, f"Expected dir_to≈0°, got {dir_to2}"


# ---------------------------------------------------------------------------
# Test 2: near=None vector-averages two winds to produce a diagonal result
# ---------------------------------------------------------------------------

def test_near_none_averages_wind_vectors():
    """near=None averages a northward and an eastward wind of equal speed to 45°.

    dir_from=180° → blowing toward north  (dir_to = 0°)
    dir_from=270° → blowing toward east   (dir_to = 90°)
    Vector mean    → blowing toward 45° NE
    """
    speed_val = 6.0
    northward = _w(34.0, -118.0, speed=speed_val, dir_from=180.0)
    eastward  = _w(34.0, -118.1, speed=speed_val, dir_from=270.0)

    speed, dir_to = wind_at([northward, eastward], _VALID, near=None)

    # The magnitude should be speed * cos(45°) = speed / sqrt(2)
    import math
    assert abs(speed - speed_val / math.sqrt(2)) < 1e-6, (
        f"Expected speed≈{speed_val/math.sqrt(2):.4f}, got {speed:.4f}"
    )
    assert abs(dir_to - 45.0) < 1e-6, f"Expected dir_to≈45°, got {dir_to}"


# ---------------------------------------------------------------------------
# Test 3: nowcast() uses the centroid of active evidence to pick the wind point
# ---------------------------------------------------------------------------

def test_nowcast_uses_centroid_for_wind():
    """nowcast() must compute the centroid of active evidence and pass it to wind_at.

    Setup
    -----
    Two active fire detections at opposite ends of a two-point wind field so
    the centroid is at a different grid point from either individual detection:

      det_south  (34.0, -118.1)  — more recent (the "latest" item old logic would use)
      det_north  (34.2, -118.1)  — older but still within ACTIVE_WINDOW
      centroid   (34.1, -118.1)

    Two-point wind field (same valid_at), deliberately straddling the centroid:
      wind_A  (34.02, -118.1) — nearest to det_south; blows FROM east → dir_to=270° (west)
      wind_B  (34.08, -118.1) — nearest to centroid;  blows FROM west → dir_to= 90° (east)

    Geometry check
    --------------
    dist(centroid 34.1, wind_A 34.02) = 0.08° > dist(centroid 34.1, wind_B 34.08) = 0.02°
    → centroid picks wind_B (dir_to=90°, fire spreads east).

    dist(det_south 34.0, wind_A 34.02) = 0.02° < dist(det_south 34.0, wind_B 34.08) = 0.08°
    → det_south picks wind_A (dir_to=270°, fire spreads west).

    Assertion
    ---------
    We place a target cell 1.2 km due east of det_south.  With wind_B (centroid logic)
    that cell is downwind → p_3h ≈ 0.90.  With wind_A (old single-latest logic) that
    cell is upwind → p_3h ≈ 0.03.  The test asserts p_3h > 0.5, a threshold only
    reachable when wind_at receives the centroid.
    """
    import math
    from datetime import timedelta

    import h3 as h3lib

    from backend.schemas import H3_RES, FireDetection
    from engines.nowcast import ACTIVE_WINDOW, nowcast

    t = datetime(2025, 1, 8, 2, 0, tzinfo=UTC)
    # det_south is MORE recent so old logic (max by seen_at) would use it as "latest"
    seen_newer = t - timedelta(minutes=10)
    seen_older = t - ACTIVE_WINDOW / 2  # still within the active window

    det_south = FireDetection(
        id="det_south",
        lat=34.0, lon=-118.1,
        h3=h3lib.latlng_to_cell(34.0, -118.1, H3_RES),
        observed_at=seen_newer,
        available_at=seen_newer,
        source="VIIRS_SNPP",
    )
    det_north = FireDetection(
        id="det_north",
        lat=34.2, lon=-118.1,
        h3=h3lib.latlng_to_cell(34.2, -118.1, H3_RES),
        observed_at=seen_older,
        available_at=seen_older,
        source="VIIRS_SNPP",
    )

    # centroid = ((34.0+34.2)/2, -118.1) = (34.1, -118.1)
    # wind_a nearest det_south → dir_to=270° (fire spreads west)
    # wind_b nearest centroid  → dir_to= 90° (fire spreads east)
    wind_a = _w(34.02, -118.1, speed=10.0, dir_from=90.0)   # nearest det_south; toward west
    wind_b = _w(34.08, -118.1, speed=10.0, dir_from=270.0)  # nearest centroid;  toward east

    # Target: 1.2 km due east of det_south — downwind under wind_b, upwind under wind_a
    deg_per_m_lon = 1 / (111_320 * math.cos(math.radians(34.0)))
    east_lon = -118.1 + 1200 * deg_per_m_lon
    east_cell = h3lib.latlng_to_cell(34.0, east_lon, H3_RES)

    south_cell = h3lib.latlng_to_cell(34.0, -118.1, H3_RES)
    cells = list(set(list(h3lib.grid_disk(south_cell, 2)) + [east_cell]))

    outlook = nowcast(
        detections=[det_south, det_north],
        wind=[wind_a, wind_b],
        cells=cells,
        t=t,
    )

    outlook_map = {o.h3: o for o in outlook}

    # Centroid logic → wind_b → fire spreads east → east cell has p_3h ≈ 0.90
    # Old single-latest logic → wind_a → fire spreads west → east cell has p_3h ≈ 0.03
    assert east_cell in outlook_map, (
        f"east cell {east_cell} not in outlook (got {len(outlook)} cells); "
        "wind_at likely did not use the centroid"
    )
    east_p3h = outlook_map[east_cell].p_3h
    assert east_p3h > 0.5, (
        f"east cell p_3h={east_p3h:.4f}; expected > 0.5 (downwind under centroid wind). "
        "wind_at likely used the single-latest detection instead of the centroid."
    )
