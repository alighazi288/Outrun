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
