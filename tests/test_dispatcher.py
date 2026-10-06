"""The rescue bar: most urgent first, nearest suitable vehicle.

These tests lock the ranking itself. tests/test_engines.py still checks that this planner
obeys the same safety, capacity, and "never drop anyone" rules as the other routers.
"""

from __future__ import annotations

import h3

from backend.assumptions import NEED_PROFILES, SAFETY_MARGIN_MIN
from backend.clock import parse_t
from backend.schemas import H3_RES, FireOutlook, Resident, ResidentRisk, Shelter, Vehicle
from engines.routing import plan_routes
from engines.routing import plan_routes_dispatcher as engine_dispatcher
from engines.travel import StraightLineTravel
from evaluation.heuristic import DispatchOption, assign_round, choose_assignment
from evaluation.heuristic import plan_routes_dispatcher as eval_dispatcher

T = parse_t("2025-01-07T21:00:00-08:00")
TRAVEL = StraightLineTravel()


def _cell(lat: float, lon: float) -> str:
    return h3.latlng_to_cell(lat, lon, H3_RES)


def _resident(rid: str, lat: float, lon: float, needs: str = "no_car") -> Resident:
    types, _load = NEED_PROFILES[needs]
    return Resident(
        id=rid, lat=lat, lon=lon, h3=_cell(lat, lon), needs=needs,
        vehicle_types=list(types), load_minutes=5, people=1,
    )


def _vehicle(
    vid: str, lat: float, lon: float, kind: str = "wheelchair_van", *, available: float = 0,
    seats: int = 8, wheelchair: int = 2, stretcher: int = 0,
) -> Vehicle:
    return Vehicle(
        id=vid, type=kind, seats=seats, wheelchair_spaces=wheelchair,
        stretcher_spaces=stretcher, lat=lat, lon=lon, available_in_min=available,
    )


def _risk(rid: str, deadline: float | None, *, priority: float = 0.5) -> ResidentRisk:
    arrival = None if deadline is None else deadline + SAFETY_MARGIN_MIN
    return ResidentRisk(
        resident_id=rid, t=T, p_1h=0.2, p_2h=0.4, p_3h=0.6,
        arrival_p10_min=arrival, deadline_min=deadline, priority=priority, at_risk=True,
    )


def _shelter() -> Shelter:
    return Shelter(id="shelter", name="Pasadena High", lat=34.16, lon=-118.13)


def _plan(residents, vehicles, risks, outlook=None):
    return engine_dispatcher(
        risks, residents, vehicles, [_shelter()], outlook or [], TRAVEL, T,
    )


def _first(plan, vehicle_id: str) -> str:
    route = next(route for route in plan.routes if route.vehicle == vehicle_id)
    return route.stops[0]


def test_policy_picks_earlier_deadline_before_a_closer_person():
    urgent = DispatchOption("urgent", "van", deadline=20, travel_min=25, eta=25)
    close = DispatchOption("close", "van", deadline=90, travel_min=2, eta=2)
    assert choose_assignment([close, urgent]).resident_id == "urgent"


def test_policy_picks_the_near_vehicle_even_if_the_far_one_is_free_sooner():
    far = DispatchOption("a", "far", deadline=40, travel_min=18, eta=18)
    near = DispatchOption("a", "near", deadline=40, travel_min=3, eta=14)
    assert choose_assignment([far, near]).vehicle_id == "near"


def test_policy_uses_nearest_to_break_a_deadline_tie():
    west = DispatchOption("west", "van", deadline=40, travel_min=12, eta=12)
    east = DispatchOption("east", "van", deadline=40, travel_min=4, eta=4)
    assert choose_assignment([west, east]).resident_id == "east"


def test_policy_ignores_nothing_about_weights_because_weights_are_not_inputs():
    """The rank is deadline and travel only. A higher vulnerability weight cannot enter."""
    low_weight_shape = DispatchOption("sooner", "van", deadline=10, travel_min=30, eta=30)
    high_weight_shape = DispatchOption("later", "van", deadline=80, travel_min=1, eta=1)
    assert choose_assignment([high_weight_shape, low_weight_shape]).resident_id == "sooner"


def test_round_gives_each_free_vehicle_one_person():
    options = [
        DispatchOption("urgent", "near_urgent", 20, 1, 1),
        DispatchOption("urgent", "near_other", 20, 15, 15),
        DispatchOption("other", "near_urgent", 70, 12, 12),
        DispatchOption("other", "near_other", 70, 1, 1),
    ]
    assigned = {(pick.resident_id, pick.vehicle_id) for pick in assign_round(options)}
    assert assigned == {("urgent", "near_urgent"), ("other", "near_other")}


def test_earlier_deadline_is_the_first_stop_even_when_someone_else_is_closer():
    van = _vehicle("van", 34.20, -118.13)
    close = _resident("close", 34.202, -118.13)
    urgent = _resident("urgent", 34.26, -118.13)
    plan = _plan(
        [close, urgent], [van],
        [_risk("close", 160, priority=5), _risk("urgent", 50, priority=0.1)],
    )
    assert _first(plan, "van") == "urgent"
    closest = plan_routes(
        [_risk("close", 160, priority=5), _risk("urgent", 50, priority=0.1)],
        [close, urgent], [van], [_shelter()], [], TRAVEL, T,
    )
    assert _first(closest, "van") == "close"


def test_nearest_vehicle_gets_the_person_not_the_one_that_is_free_earlier():
    person = _resident("a", 34.190, -118.130)
    far = _vehicle("far", 34.250, -118.130, available=0)
    near = _vehicle("near", 34.192, -118.130, available=8)
    plan = _plan([person], [far, near], [_risk("a", 120)])
    assert _first(plan, "near") == "a"
    assert all(route.vehicle != "far" or "a" not in route.stops for route in plan.routes)


def test_two_vehicles_split_the_list_in_one_round():
    urgent = _resident("urgent", 34.19, -118.13)
    other = _resident("other", 34.23, -118.13)
    south = _vehicle("south", 34.19, -118.13)
    north = _vehicle("north", 34.23, -118.13)
    plan = _plan(
        [urgent, other], [south, north],
        [_risk("urgent", 40), _risk("other", 150)],
    )
    assert _first(plan, "south") == "urgent"
    assert _first(plan, "north") == "other"


def test_a_bus_does_not_take_a_bedbound_resident():
    person = _resident("bed", 34.19, -118.13, needs="bedbound")
    bus = _vehicle("bus", 34.19, -118.13, kind="bus", wheelchair=0)
    ambulance = _vehicle(
        "amb", 34.24, -118.13, kind="ambulance", seats=2, wheelchair=0, stretcher=1,
    )
    plan = _plan([person], [bus, ambulance], [_risk("bed", 120)])
    assert _first(plan, "amb") == "bed"
    assert all("bed" not in route.stops for route in plan.routes if route.vehicle == "bus")


def test_a_person_with_no_deadline_waits_behind_one_who_has_one():
    van = _vehicle("van", 34.20, -118.13)
    open_hex = _resident("open", 34.201, -118.13)
    timed = _resident("timed", 34.25, -118.13)
    plan = _plan(
        [open_hex, timed], [van],
        [_risk("open", None, priority=9), _risk("timed", 100, priority=0.1)],
    )
    assert _first(plan, "van") == "timed"


def test_burning_home_is_escalated_to_fire_command():
    person = _resident("a", 34.19, -118.13)
    van = _vehicle("van", 34.192, -118.13)
    outlook = [FireOutlook(
        t=T, h3=person.h3, p_1h=1, p_2h=1, p_3h=1, arrival_p10_min=0, burning=True,
    )]
    plan = _plan([person], [van], [_risk("a", 5)], outlook)
    assert plan.unreachable == ["a"]
    assert plan.escalated_fire_command == ["a"]
    assert "fire command" in plan.reasons["a"]


def test_too_late_is_escalated_to_fire_command():
    person = _resident("a", 34.30, -118.13)
    van = _vehicle("van", 34.19, -118.13)
    plan = _plan([person], [van], [_risk("a", 5)])
    assert "a" in plan.unreachable
    assert "a" in plan.escalated_fire_command
    assert "fire command" in plan.reasons["a"]


def test_routed_reason_names_the_deadline_and_the_vehicle():
    person = _resident("a", 34.191, -118.13)
    van = _vehicle("van", 34.190, -118.13)
    plan = _plan([person], [van], [_risk("a", 80)])
    reason = plan.reasons["a"]
    assert "Dispatcher rule" in reason
    assert "80 min" in reason
    assert "van" in reason


def test_same_inputs_make_the_same_plan():
    person = _resident("a", 34.19, -118.13)
    other = _resident("b", 34.22, -118.14)
    vans = [_vehicle("v1", 34.18, -118.12), _vehicle("v2", 34.23, -118.15, available=3)]
    risks = [_risk("a", 45), _risk("b", 45)]
    first = _plan([person, other], vans, risks)
    second = _plan([other, person], list(reversed(vans)), list(reversed(risks)))
    assert first.routes == second.routes
    assert first.unreachable == second.unreachable


def test_eval_entry_point_matches_the_engine():
    person = _resident("a", 34.19, -118.13)
    van = _vehicle("van", 34.18, -118.13)
    risks = [_risk("a", 60)]
    args = (risks, [person], [van], [_shelter()], [], TRAVEL, T)
    assert eval_dispatcher(*args) == engine_dispatcher(*args)
