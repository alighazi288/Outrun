"""Real roads: travel minutes and the cells a route passes through (engines/travel.py)."""

from __future__ import annotations

from array import array

import h3
import pytest

from backend.assumptions import SPEED_FACTOR
from backend.store import DATASETS
from engines.routing import SafetyMap
from engines.travel import ROAD_UNREACHABLE, RoadTravel, StraightLineTravel

YARD = (34.150791, -118.113256)
CONVENTION_CENTER = (34.14365, -118.14521)
LINCOLN = (34.198279, -118.159000)


def _toy() -> tuple[RoadTravel, list[tuple[float, float]]]:
    """Three places in a row: a -> c goes through b; c is cut off going back."""
    pts = [(34.180, -118.150), (34.180, -118.140), (34.180, -118.130)]
    cells = [h3.latlng_to_cell(lat, lon, 9) for lat, lon in pts]
    free = array("f", [0, 2, 5,
                       2, 0, 3,
                       ROAD_UNREACHABLE, 3, 0])
    nxt = array("H", [0, 1, 1,
                      0, 1, 2,
                      2, 1, 2])
    return RoadTravel(places=cells, free_flow=free, next_hop=nxt), pts


def test_minutes_are_free_flow_slowed_by_the_speed_factor():
    roads, (a, b, c) = _toy()
    assert roads.minutes(a, c) == pytest.approx(5 / SPEED_FACTOR)
    assert roads.minutes(c, a) == float("inf")


def test_route_walks_through_every_cell_on_the_way():
    roads, (a, _, c) = _toy()
    route = roads.cells(a, c)
    assert route[0] == roads.places[0] and route[-1] == roads.places[2]
    assert all(h3.grid_distance(x, y) <= 1 for x, y in zip(route, route[1:], strict=False))


def test_places_outside_the_file_fall_back_to_the_stub():
    roads, (a, _, _) = _toy()
    far = (34.30, -118.30)
    assert roads.minutes(a, far) == pytest.approx(StraightLineTravel().minutes(a, far))


def test_safety_rule_checks_the_road_route():
    """A burning cell on the road between a and c blocks the trip."""
    roads, (a, b, c) = _toy()
    from backend.clock import parse_t
    from backend.schemas import FireOutlook
    t = parse_t("2025-01-07T22:00:00-08:00")
    burning = FireOutlook(t=t, h3=roads.places[1], p_1h=1, p_2h=1, p_3h=1,
                          arrival_p10_min=0, burning=True)
    safety = SafetyMap([burning], roads.cells)
    assert not safety.leg_ok(a, c, 0, roads.minutes(a, c))


@pytest.mark.skipif(not (DATASETS["eaton"] / "roads.json.gz").exists(), reason="no road file")
def test_real_roads_give_sensible_trips():
    roads = RoadTravel.load(DATASETS["eaton"] / "roads.json.gz")
    free = roads.minutes(YARD, CONVENTION_CENTER) * SPEED_FACTOR
    assert 2 < free < 10  # 3 km across Pasadena
    route = roads.cells(LINCOLN, CONVENTION_CENTER)
    assert 5 < len(route) < 40
    assert all(h3.grid_distance(x, y) <= 1 for x, y in zip(route, route[1:], strict=False))
