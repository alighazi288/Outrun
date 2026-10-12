"""Travel time between two points.

The router only talks to the `TravelTime` protocol. `RoadTravel` uses real roads (built by
scripts/build_roads.py); `StraightLineTravel` is the stub for datasets without a road file.
"""

from __future__ import annotations

import base64
import gzip
import json
import math
import sys
from array import array
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import h3

from backend.assumptions import DETOUR_FACTOR, SPEED_FACTOR, STUB_SPEED_KMH
from backend.schemas import H3_RES

LatLon = tuple[float, float]
ROAD_UNREACHABLE = 1e9  # minutes, for places with no road between them

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


@dataclass
class RoadTravel:
    """Driving minutes on real roads between map cells, slowed to SPEED_FACTOR x free flow.

    Built by scripts/build_roads.py from OpenStreetMap. Points in the same cell, or outside the
    places the file covers, fall back to the straight-line stub. `cells(a, b)` walks the road
    route, so the driver-safety rule checks the cells the road really passes through.
    """

    places: list[str]
    free_flow: array
    next_hop: array
    speed_factor: float = SPEED_FACTOR
    stub: StraightLineTravel = field(default_factory=StraightLineTravel)

    def __post_init__(self) -> None:
        self.index = {c: i for i, c in enumerate(self.places)}
        self.n = len(self.places)
        self._cell = lru_cache(maxsize=65536)(lambda lat, lon: h3.latlng_to_cell(lat, lon, H3_RES))
        self._route = lru_cache(maxsize=262144)(self._walk)

    @classmethod
    def load(cls, path: Path) -> RoadTravel:
        with gzip.open(path, "rt") as f:
            data = json.load(f)
        free_flow = array("f", base64.b64decode(data["minutes_f32_le"]))
        next_hop = array("H", base64.b64decode(data["next_u16_le"]))
        if sys.byteorder == "big":
            free_flow.byteswap()
            next_hop.byteswap()
        return cls(places=data["cells"], free_flow=free_flow, next_hop=next_hop)

    def _pair(self, a: LatLon, b: LatLon) -> tuple[int, int] | None:
        i = self.index.get(self._cell(a[0], a[1]))
        j = self.index.get(self._cell(b[0], b[1]))
        return None if i is None or j is None or i == j else (i, j)

    def minutes(self, a: LatLon, b: LatLon) -> float:
        pair = self._pair(a, b)
        if pair is None:
            return self.stub.minutes(a, b)
        free = self.free_flow[pair[0] * self.n + pair[1]]
        return math.inf if free >= ROAD_UNREACHABLE else free / self.speed_factor

    def cells(self, a: LatLon, b: LatLon) -> tuple[str, ...]:
        """Cells the road route passes through, start and end included."""
        pair = self._pair(a, b)
        if pair is None:
            return _straight(self._cell(a[0], a[1]), self._cell(b[0], b[1]))
        return self._route(*pair)

    def _walk(self, i: int, j: int) -> tuple[str, ...]:
        route, k = [self.places[i]], i
        for _ in range(self.n):  # follow next hops; the cap stops any loop
            if k == j:
                break
            k = self.next_hop[k * self.n + j]
            route.append(self.places[k])
        if route[-1] != self.places[j]:
            route.append(self.places[j])
        # A hop can jump a cell (fast roads, or a cell outside the study area). Fill each gap
        # with the cells in between so the safety rule never skips one.
        out = [route[0]]
        for a, b in zip(route, route[1:], strict=False):
            out += _straight(a, b)[1:]
        return tuple(out)


def _straight(a: str, b: str) -> tuple[str, ...]:
    """Cells on the straight line from a to b (just the ends if h3 can't draw it)."""
    try:
        return tuple(h3.grid_path_cells(a, b))
    except h3.H3BaseException:
        return (a, b) if a != b else (a,)


def travel_for(folder: Path) -> TravelTime:
    """Real roads when the dataset has them, else the straight-line stub."""
    roads = folder / "roads.json.gz"
    return RoadTravel.load(roads) if roads.exists() else StraightLineTravel()
