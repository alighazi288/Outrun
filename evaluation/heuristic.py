"""Rescue bar: most urgent resident first, then the nearest suitable vehicle.

This is the dispatcher heuristic in the PRD and in EVAL_SPEC section 6.
`engines.routing.plan_routes_dispatcher` runs it on a live fleet. The functions here are
only the ranking, so the rule can be tested without a map.

Urgency is the earliest deadline, the latest safe time to leave the pickup. A resident
with no forecast arrival inside the horizon waits behind anyone who has a deadline.
Vulnerability weights do not change this order. They stay on the risk record for the
screen, and for our own planner's penalty for leaving someone out.

Suitable means the vehicle type can carry them, the spare capacity fits, and the safety
rule says the vehicle can reach them and still get to a shelter. Among suitable
vehicles, nearest is the shortest travel time. An earlier arrival breaks a travel tie,
then the vehicle id, so the same inputs always make the same plan.

One round gives every free vehicle at most one new pickup, from the positions at the
start of the round. That stops one close vehicle from taking the whole list while
another suitable vehicle is still free. The engine then moves those vehicles and may
run another round: a second passenger, or another trip after the shelter drop-off.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from backend.schemas import FireOutlook, Plan, Resident, ResidentRisk, Shelter, Vehicle
from engines.travel import TravelTime


@dataclass(frozen=True)
class DispatchOption:
    """One resident a specific vehicle can pick up safely from where it is now."""

    resident_id: str
    vehicle_id: str
    deadline: float | None
    travel_min: float
    eta: float


def _urgency(deadline: float | None, nearest_travel: float, resident_id: str) -> tuple:
    """Earlier deadline first. Same deadline: the one a vehicle can reach sooner. Then id."""
    when = deadline if deadline is not None else math.inf
    return (when, nearest_travel, resident_id)


def choose_assignment(options: list[DispatchOption]) -> DispatchOption:
    """The single next assignment: most urgent resident, nearest suitable vehicle."""
    if not options:
        raise ValueError("choose_assignment needs at least one feasible option")
    # One pass over the options: each resident's deadline and nearest suitable vehicle.
    nearest: dict[str, float] = {}
    deadline: dict[str, float | None] = {}
    for option in options:
        deadline[option.resident_id] = option.deadline
        if option.travel_min < nearest.get(option.resident_id, math.inf):
            nearest[option.resident_id] = option.travel_min
    resident_id = min(nearest, key=lambda rid: _urgency(deadline[rid], nearest[rid], rid))
    mine = [option for option in options if option.resident_id == resident_id]
    return min(mine, key=lambda option: (option.travel_min, option.eta, option.vehicle_id))


def assign_round(options: list[DispatchOption]) -> list[DispatchOption]:
    """One parallel round. Each vehicle and each resident is chosen at most once."""
    chosen: list[DispatchOption] = []
    taken_people: set[str] = set()
    taken_vehicles: set[str] = set()
    while True:
        pool = [
            option for option in options
            if option.resident_id not in taken_people and option.vehicle_id not in taken_vehicles
        ]
        if not pool:
            return chosen
        best = choose_assignment(pool)
        chosen.append(best)
        taken_people.add(best.resident_id)
        taken_vehicles.add(best.vehicle_id)


def plan_routes_dispatcher(
    risks: list[ResidentRisk],
    residents: list[Resident],
    vehicles: list[Vehicle],
    shelters: list[Shelter],
    outlook: list[FireOutlook],
    travel: TravelTime,
    t: datetime,
    previous_plan: Plan | None = None,
) -> Plan:
    """Same function as `engines.routing.plan_routes_dispatcher`. This is the eval entry point."""
    from engines.routing import plan_routes_dispatcher as impl

    return impl(
        risks, residents, vehicles, shelters, outlook, travel, t, previous_plan,
    )
