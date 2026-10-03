"""Travel time between two points.

The router only talks to the `TravelTime` protocol, so the straight-line stub below can be
swapped for a road-network version (OSMnx + closures) without touching the router.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from backend.assumptions import DETOUR_FACTOR, STUB_SPEED_KMH

LatLon = tuple[float, float]

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(a: LatLon, b: LatLon) -> float:
    """Great-circle distance in metres between two (lat, lon) points."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


class TravelTime(Protocol):
    def minutes(self, a: LatLon, b: LatLon) -> float:
        """Driving minutes from a to b under current conditions."""
        ...


@dataclass
class StraightLineTravel:
    """STUB. Straight-line distance, stretched by a detour factor, at a slow smoke speed.

    Real version: shortest path on the OSMnx drive network at SPEED_FACTOR x road speed,
    with blocked roads removed, cached per time step. It should also report the hexes a route
    passes through, so the safety rule checks real paths instead of straight lines.
    """

    speed_kmh: float = STUB_SPEED_KMH
    detour_factor: float = DETOUR_FACTOR

    def minutes(self, a: LatLon, b: LatLon) -> float:
        km = haversine_m(a, b) / 1000 * self.detour_factor
        return km / self.speed_kmh * 60
