"""A manager's edits to a plan: take someone off, hold a vehicle, move someone to a vehicle.

Every changed route is re-timed on the travel engine and checked like the planner's own
routes: the vehicle must be able to carry the person, have room, and pass the driver-safety
rule on every leg. An edit that breaks a rule is refused with a reason written for the agent
to read back to the manager. Unchanged routes keep their times.
"""

from __future__ import annotations

from backend.assumptions import UNLOAD_MIN
from backend.schemas import FireOutlook, Plan, PlanChange, Resident, Route, Shelter, Vehicle
from engines.routing import NEED_LABEL, SafetyMap, _VehicleState
from engines.travel import TravelTime


class DecisionError(ValueError):
    """An edit the rules don't allow. The message says why, in plain words."""


def apply_changes(
    plan: Plan,
    changes: list[PlanChange],
    residents: dict[str, Resident],
    vehicles: dict[str, Vehicle],
    shelters: list[Shelter],
    outlook: list[FireOutlook],
    travel: TravelTime,
) -> Plan:
    """The plan with the edits applied, or DecisionError."""
    if not changes:
        raise DecisionError("A modify decision needs at least one change.")
    stops = {r.vehicle: list(r.stops) for r in plan.routes}
    reasons = dict(plan.reasons)
    shelter_ids = {s.id for s in shelters}
    changed: set[str] = set()

    def where(rid: str) -> str | None:
        return next((v for v, ss in stops.items() if rid in ss), None)

    def take_off(rid: str) -> None:
        v = where(rid)
        if v is not None:
            stops[v] = _tidy([s for s in stops[v] if s != rid], shelter_ids)
            changed.add(v)

    for c in changes:
        if c.kind == "hold_vehicle":
            _need(c.vehicle in vehicles, f"There's no vehicle {c.vehicle}.")
            for rid in stops.pop(c.vehicle, []):
                if rid not in shelter_ids:
                    reasons[rid] = f"{c.vehicle} was held by the emergency manager."
            changed.discard(c.vehicle)
        elif c.kind == "remove_stop":
            _need(c.resident is not None and where(c.resident) is not None,
                  f"{c.resident} isn't on this plan.")
            take_off(c.resident)
            reasons[c.resident] = "Taken off this plan by the emergency manager."
        else:  # reassign / add_stop: give this person a run on that vehicle
            _need(c.resident in residents, f"{c.resident} isn't known to the plan yet.")
            _need(c.vehicle in vehicles, f"There's no vehicle {c.vehicle}.")
            take_off(c.resident)
            stops.setdefault(c.vehicle, []).append(c.resident)
            changed.add(c.vehicle)

    safety = SafetyMap(outlook, getattr(travel, "cells", None))
    routes = {r.vehicle: r for r in plan.routes if r.vehicle in stops}
    for v in changed:
        if not stops.get(v):
            routes.pop(v, None)
            continue
        routes[v] = _retime(vehicles[v], stops[v], residents, shelters, safety, travel)
    for c in changes:
        if c.kind in ("reassign", "add_stop"):
            route = routes[c.vehicle]
            eta = route.eta_min[route.stops.index(c.resident)]
            reasons[c.resident] = (f"Moved to {c.vehicle} by the emergency manager; "
                                   f"arrives in {eta:.0f} min.")
    planned = {s for r in routes.values() for s in r.stops}
    return plan.model_copy(update={
        "routes": [routes[v] for v in sorted(routes)],
        "unreachable": [r for r in plan.unreachable if r not in planned],
        "escalated_fire_command": [r for r in plan.escalated_fire_command if r not in planned],
        "reasons": reasons,
        "strategy": f"{plan.strategy}+manager_edits",
    })


def _retime(v: Vehicle, stop_ids: list[str], residents: dict[str, Resident],
            shelters: list[Shelter], safety: SafetyMap, travel: TravelTime) -> Route:
    """Drive the stops in order from where the vehicle is free, checking every rule."""
    vs = _VehicleState(v, (v.lat, v.lon), clock=v.available_in_min)
    by_id = {s.id: s for s in shelters}
    for sid in stop_ids:
        if sid in by_id:
            _drop_off(vs, by_id[sid], safety, travel)
            continue
        r = residents[sid]
        _need(v.type in r.vehicle_types,
              f"{v.id} can't carry {r.id}: a {NEED_LABEL[r.needs]} resident needs a "
              f"{' or '.join(t.replace('_', ' ') for t in r.vehicle_types)}.")
        _need(vs.fits(r), f"{v.id} has no room left for {r.id} on that run.")
        here = (r.lat, r.lon)
        minutes = travel.minutes(vs.pos, here)
        eta = vs.clock + minutes
        _need(safety.leg_ok(vs.pos, here, vs.clock, minutes)
              and safety.hex_ok(r.h3, eta + r.load_minutes),
              f"Sending {v.id} to {r.id} breaks the driver-safety rule: fire could reach the "
              "route or the pickup before the vehicle is safely past. Choose another vehicle "
              "or escalate to fire command.")
        vs.pick_up(r, eta)
    if vs.onboard:
        nearest = min(shelters, key=lambda s: travel.minutes(vs.pos, (s.lat, s.lon)))
        _drop_off(vs, nearest, safety, travel)
    return Route(vehicle=v.id, stops=vs.stops, eta_min=vs.etas)


def _drop_off(vs: _VehicleState, s: Shelter, safety: SafetyMap, travel: TravelTime) -> None:
    there = (s.lat, s.lon)
    minutes = travel.minutes(vs.pos, there)
    _need(safety.leg_ok(vs.pos, there, vs.clock, minutes),
          f"{vs.vehicle.id} has no safe road to {s.name} from its last pickup.")
    vs.visit(s.id, there, vs.clock + minutes, UNLOAD_MIN)
    vs._empty()


def _tidy(stops: list[str], shelter_ids: set[str]) -> list[str]:
    """Drop shelter stops that no longer follow a pickup."""
    out: list[str] = []
    for s in stops:
        if s in shelter_ids and (not out or out[-1] in shelter_ids):
            continue
        out.append(s)
    return out


def _need(ok: bool, message: str) -> None:
    if not ok:
        raise DecisionError(message)
