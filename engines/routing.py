"""Route optimizer: which vehicle picks up whom, in what order.

Two greedy planners live here, both obeying the same rules:
- `plan_routes` (STUB for ours): "closest first". Each free vehicle goes to the nearest waiting
  person it can carry and reach safely in time. Also the "closest first" baseline.
- `plan_routes_dispatcher`: the dispatcher rule, the bar ours must beat. Most urgent resident
  first (earliest deadline), then the nearest vehicle that can carry them and reach them
  safely. The ranking policy lives in `evaluation/heuristic.py`.

The real version of ours is OR-Tools pickup-and-delivery (seat, wheelchair and stretcher
capacities; deadlines as time windows; priority as the penalty for leaving someone out),
re-solved every step, keeping vehicles on their current run unless switching gains a lot.
It must keep the same signature and pass tests/test_engines.py.

Rules every planner must follow:
- Every at-risk resident ends up in exactly one route or in `unreachable`. Never dropped.
- Capacity is never exceeded, and a person only rides a vehicle type listed for them.
- Driver safety: for every hex a vehicle occupies (stops and the hexes between them),
  time it leaves + SAFETY_MARGIN_MIN <= that hex's arrival_p10_min from the forecast at plan
  time. Burning hexes are never entered; hexes with no forecast arrival within 3 h are open.
  The pickup deadline is this same rule at the pickup hex.
- Never pick someone up unless a safe way out to a shelter exists afterwards.
- Reasons are filled in from numbers. No LLM writes them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache

import h3

from backend.assumptions import HORIZON_MIN, SAFETY_MARGIN_MIN, UNLOAD_MIN
from backend.schemas import (
    H3_RES,
    FireOutlook,
    Plan,
    Resident,
    ResidentRisk,
    Route,
    Shelter,
    Vehicle,
    capacity_demand,
)
from engines.travel import LatLon, TravelTime

NEED_LABEL = {
    "wheelchair": "wheelchair user",
    "oxygen": "on oxygen",
    "bedbound": "bedbound",
    "no_car": "no car",
    "none": "no special needs",
}


def plan_id_for(t: datetime) -> str:
    """Plans are named after their time, so the same step always gets the same id."""
    return f"p_{t:%Y%m%dT%H%M}"


# --------------------------------------------------------------------------------------
# Driver safety
# --------------------------------------------------------------------------------------


@lru_cache(maxsize=200_000)
def _path(a: str, b: str) -> tuple[str, ...]:
    try:
        return tuple(h3.grid_path_cells(a, b))
    except Exception:  # far apart or across a pentagon: fall back to the endpoints
        return (a, b)


def path_cells(a: LatLon, b: LatLon) -> tuple[str, ...]:
    """Hexes on the straight line from a to b. The road router should replace this with the
    hexes of the real road path."""
    return _path(h3.latlng_to_cell(*a, H3_RES), h3.latlng_to_cell(*b, H3_RES))


class SafetyMap:
    """Answers "may a vehicle stay in this hex until minute m?" from the forecast at plan time."""

    def __init__(self, outlook: list[FireOutlook]):
        self.arrival = {o.h3: 0.0 if o.burning else o.arrival_p10_min for o in outlook}

    def hex_ok(self, cell: str, leave_min: float) -> bool:
        arrival = self.arrival.get(cell)
        return arrival is None or leave_min + SAFETY_MARGIN_MIN <= arrival

    def leg_ok(self, a: LatLon, b: LatLon, depart_min: float, minutes: float) -> bool:
        """Every hex on the way, left at its interpolated time, passes the rule."""
        cells = path_cells(a, b)
        n = len(cells)
        return all(
            self.hex_ok(c, depart_min + minutes * (i + 1) / n) for i, c in enumerate(cells)
        )


# --------------------------------------------------------------------------------------
# Greedy planners
# --------------------------------------------------------------------------------------


@dataclass
class _VehicleState:
    vehicle: Vehicle
    pos: LatLon
    clock: float = 0.0  # minutes after t when this vehicle is free again
    seats: int = 0
    wheelchair: int = 0
    stretcher: int = 0
    onboard: int = 0
    stops: list[str] = field(default_factory=list)
    etas: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._empty()

    def _empty(self) -> None:
        v = self.vehicle
        self.seats, self.wheelchair = v.seats, v.wheelchair_spaces
        self.stretcher = v.stretcher_spaces
        self.onboard = 0

    def fits(self, r: Resident) -> bool:
        s, w, x = capacity_demand(r)
        return (
            self.vehicle.type in r.vehicle_types
            and s <= self.seats and w <= self.wheelchair and x <= self.stretcher
        )

    def visit(self, stop_id: str, pos: LatLon, eta: float, service_min: float) -> None:
        self.stops.append(stop_id)
        self.etas.append(round(eta, 1))
        self.pos = pos
        self.clock = eta + service_min

    def pick_up(self, r: Resident, eta: float) -> None:
        s, w, x = capacity_demand(r)
        self.seats -= s
        self.wheelchair -= w
        self.stretcher -= x
        self.onboard += r.people
        self.visit(r.id, (r.lat, r.lon), eta, r.load_minutes)


@dataclass(frozen=True)
class _Option:
    resident_id: str
    eta: float
    leave: float
    deadline: float | None
    travel: float


class _Planner:
    def __init__(self, risks, residents, vehicles, shelters, outlook, travel):
        self.res = {r.id: r for r in residents}
        self.risk = {k.resident_id: k for k in risks}
        self.vehicles = vehicles
        self.shelters = shelters
        self.travel = travel
        self.safety = SafetyMap(outlook)
        self.strategy = ""

    def option(self, pos: LatLon, clock: float, fits: bool, rid: str) -> _Option | None:
        """Can a vehicle at `pos`, free at `clock`, safely pick up `rid` in time?"""
        r = self.res[rid]
        if not fits:
            return None
        here = (r.lat, r.lon)
        minutes = self.travel.minutes(pos, here)
        eta = clock + minutes
        leave = eta + r.load_minutes
        deadline = self.risk[rid].deadline_min
        if leave > HORIZON_MIN or (deadline is not None and leave > deadline):
            return None
        if not self.safety.leg_ok(pos, here, clock, minutes):
            return None
        if not self.safety.hex_ok(r.h3, leave) or self.escape(here, leave) is None:
            return None
        return _Option(rid, eta, leave, deadline, minutes)

    def escape(self, pos: LatLon, depart: float) -> Shelter | None:
        """Nearest shelter reachable from `pos` by a safe leg, leaving at `depart`."""
        for s in sorted(self.shelters, key=lambda s: self.travel.minutes(pos, (s.lat, s.lon))):
            there = (s.lat, s.lon)
            if self.safety.leg_ok(pos, there, depart, self.travel.minutes(pos, there)):
                return s
        return None

    def drop_off(self, vs: _VehicleState) -> None:
        shelter = self.escape(vs.pos, vs.clock) or min(
            self.shelters, key=lambda s: self.travel.minutes(vs.pos, (s.lat, s.lon))
        )
        eta = vs.clock + self.travel.minutes(vs.pos, (shelter.lat, shelter.lon))
        vs.visit(shelter.id, (shelter.lat, shelter.lon), eta, service_min=UNLOAD_MIN)
        vs._empty()

    def run(self, choose: Callable[[_Option], tuple], t: datetime, strategy: str) -> Plan:
        self.strategy = strategy
        pending = [
            k.resident_id for k in self.risk.values() if k.at_risk and k.resident_id in self.res
        ]
        pending.sort(key=lambda rid: -self.risk[rid].priority)
        states = [
            _VehicleState(v, (v.lat, v.lon), clock=v.available_in_min) for v in self.vehicles
        ]
        chosen: dict[str, tuple[str, _Option]] = {}

        progressed = True
        while pending and progressed:
            progressed = False
            for vs in sorted(states, key=lambda s: s.clock):
                options = [
                    o for rid in pending
                    if (o := self.option(vs.pos, vs.clock, vs.fits(self.res[rid]), rid))
                ]
                if options:
                    best = min(options, key=choose)
                    vs.pick_up(self.res[best.resident_id], best.eta)
                    chosen[best.resident_id] = (vs.vehicle.id, best)
                    pending.remove(best.resident_id)
                    progressed = True
                elif vs.onboard and self.shelters:
                    self.drop_off(vs)
                    progressed = True
        return self._finish(pending, states, chosen, t, strategy)

    def run_dispatcher(self, t: datetime) -> Plan:
        """Most urgent first, nearest suitable vehicle. See evaluation/heuristic.py."""
        from evaluation.heuristic import DispatchOption, assign_round

        self.strategy = "dispatcher_rule"
        pending = [
            k.resident_id for k in self.risk.values() if k.at_risk and k.resident_id in self.res
        ]
        states = [
            _VehicleState(v, (v.lat, v.lon), clock=v.available_in_min) for v in self.vehicles
        ]
        by_id = {s.vehicle.id: s for s in states}
        chosen: dict[str, tuple[str, _Option]] = {}

        while pending:
            cached: dict[tuple[str, str], _Option] = {}
            options = []
            for vs in states:
                for rid in pending:
                    fit = self.option(vs.pos, vs.clock, vs.fits(self.res[rid]), rid)
                    if fit is None:
                        continue
                    cached[(vs.vehicle.id, rid)] = fit
                    options.append(DispatchOption(
                        resident_id=rid,
                        vehicle_id=vs.vehicle.id,
                        deadline=fit.deadline,
                        travel_min=fit.travel,
                        eta=fit.eta,
                    ))
            if not options:
                loaded = [vs for vs in states if vs.onboard and self.shelters]
                if not loaded:
                    break
                for vs in loaded:
                    self.drop_off(vs)
                continue
            # Positions stay put until the whole round is chosen, so one vehicle cannot
            # take a second person before the other free vehicles have been offered one.
            for pick in assign_round(options):
                vs = by_id[pick.vehicle_id]
                fit = cached[(pick.vehicle_id, pick.resident_id)]
                vs.pick_up(self.res[pick.resident_id], fit.eta)
                chosen[pick.resident_id] = (pick.vehicle_id, fit)
                pending.remove(pick.resident_id)
        return self._finish(pending, states, chosen, t, "dispatcher_rule")

    def _finish(self, pending, states, chosen, t: datetime, strategy: str) -> Plan:
        for vs in states:
            if vs.onboard and self.shelters:
                self.drop_off(vs)
        reasons = {rid: self.routed_reason(rid, *chosen[rid]) for rid in chosen}
        fire_command = []
        for rid in pending:
            reasons[rid], to_fire_command = self.unreachable_reason(rid)
            if to_fire_command:
                fire_command.append(rid)
        return Plan(
            t=t,
            plan_id=plan_id_for(t),
            routes=[
                Route(vehicle=s.vehicle.id, stops=s.stops, eta_min=s.etas)
                for s in sorted(states, key=lambda s: s.vehicle.id) if s.stops
            ],
            unreachable=list(pending),
            reasons=reasons,
            escalated_fire_command=fire_command,
            strategy=strategy,
        )

    def routed_reason(self, rid: str, vehicle: str, o: _Option) -> str:
        r, k = self.res[rid], self.risk[rid]
        text = f"{k.p_3h:.0%} chance fire reaches this block within 3 h"
        if k.arrival_p10_min is not None:
            text += f" (could arrive in {k.arrival_p10_min:.0f} min)"
        text += f"; {NEED_LABEL[r.needs]}"
        if r.people > 1:
            text += f", {r.people} people"
        text += f". {vehicle} arrives in {o.eta:.0f} min"
        if o.deadline is not None:
            text += f" and leaves {o.deadline - o.leave:.0f} min before the deadline"
        if self.strategy == "dispatcher_rule":
            away = f"{o.travel:.0f} min away"
            if o.deadline is not None:
                text += (
                    f". Dispatcher rule: earliest deadline ({o.deadline:.0f} min), "
                    f"nearest suitable vehicle ({away})"
                )
            else:
                text += (
                    ". Dispatcher rule: no arrival inside the horizon, so this person waits "
                    f"behind anyone with a deadline; nearest suitable vehicle ({away})"
                )
        return text + "."

    def unreachable_reason(self, rid: str) -> tuple[str, bool]:
        """(reason, whether it goes to fire command rather than another vehicle)."""
        r = self.res[rid]
        compatible = [v for v in self.vehicles if v.type in r.vehicle_types]
        if not compatible:
            text = f"No vehicle in the fleet can carry a {NEED_LABEL[r.needs]} resident. Escalate."
            return text, False
        here = (r.lat, r.lon)
        deadline = self.risk[rid].deadline_min
        limit = min(deadline, HORIZON_MIN) if deadline is not None else HORIZON_MIN
        fastest = min(
            v.available_in_min + self.travel.minutes((v.lat, v.lon), here) + r.load_minutes
            for v in compatible
        )
        if fastest > limit:
            when = (
                f"the deadline passed {-limit:.0f} min ago" if limit < 0
                else f"must leave within {limit:.0f} min"
            )
            return (
                f"Too late for any vehicle: {when}, fastest direct pickup takes "
                f"{fastest:.0f} min. Escalate to fire command."
            ), True
        if not any(
            self.option((v.lat, v.lon), v.available_in_min, True, rid) for v in compatible
        ):
            return "Only reachable through danger. Escalate to fire command.", True
        return (
            f"All compatible vehicles are committed; must leave within {limit:.0f} min. "
            "Escalate: needs another vehicle or a change to the plan."
        ), False


def plan_routes(
    risks: list[ResidentRisk],
    residents: list[Resident],
    vehicles: list[Vehicle],
    shelters: list[Shelter],
    outlook: list[FireOutlook],
    travel: TravelTime,
    t: datetime,
    previous_plan: Plan | None = None,  # unused by the stub; the real version keeps runs stable
) -> Plan:
    """STUB for our planner: closest first, within the safety and deadline rules."""
    planner = _Planner(risks, residents, vehicles, shelters, outlook, travel)
    return planner.run(lambda o: (o.eta,), t, "closest_first_stub")


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
    """Rescue bar: earliest deadline, then the nearest vehicle that can carry them safely.

    `previous_plan` is accepted so the signature matches the other planners. The replay locks
    a vehicle's current leg before it calls this, and does not pass that plan through.
    """
    del previous_plan
    planner = _Planner(risks, residents, vehicles, shelters, outlook, travel)
    return planner.run_dispatcher(t)
