"""Contract tests every engine implementation must pass.

When you build the real version of an engine, add it to the list at the top (e.g. the
OR-Tools router next to the stubs) and these tests run against it too.
"""

from __future__ import annotations

import pytest

from backend.assumptions import SAFETY_MARGIN_MIN, UNLOAD_MIN
from backend.schemas import capacity_demand
from engines import StraightLineTravel
from engines.nowcast import nowcast
from engines.risk import prioritize
from engines.routing import SafetyMap, plan_routes, plan_routes_dispatcher

from .conftest import pt

NOWCASTS = [nowcast]
ROUTERS = [plan_routes, plan_routes_dispatcher]  # add the OR-Tools router here
TIMES = ["19:00", "20:00", "21:00", "22:00"]


def _step(store, hhmm, router=plan_routes):
    t = pt(hhmm)
    snap = store.at(t)
    outlook = nowcast(snap.detections, snap.wind, store.cells, t, snap.reports)
    risks = prioritize(snap.residents, outlook, t)
    plan = router(risks, snap.residents, snap.vehicles, snap.shelters, outlook,
                  StraightLineTravel(), t)
    return snap, outlook, risks, plan


@pytest.mark.parametrize("impl", NOWCASTS)
@pytest.mark.parametrize("hhmm", TIMES)
def test_nowcast_outputs_are_valid_probabilities(store, impl, hhmm):
    t = pt(hhmm)
    snap = store.at(t)
    out = impl(snap.detections, snap.wind, store.cells, t, snap.reports)
    assert out, "fire exists at this time, so some cells should be threatened"
    cells = set(store.cells)
    for o in out:
        assert o.t == t and o.h3 in cells
        assert 0 <= o.p_1h <= o.p_2h <= o.p_3h <= 1
        if o.burning:
            assert o.p_1h == 1


@pytest.mark.parametrize("impl", NOWCASTS)
def test_nowcast_without_fire_is_empty(store, impl):
    t = pt("18:05")
    snap = store.at(t)
    assert impl(snap.detections, snap.wind, store.cells, t, snap.reports) == []


@pytest.mark.parametrize("impl", NOWCASTS)
def test_nowcast_uses_fire_reports(store, impl):
    """Reports alone (no satellite data yet) must still produce a forecast."""
    t = pt("19:00")
    snap = store.at(t)
    assert snap.reports, "fixture has reports by 19:00"
    assert impl([], snap.wind, store.cells, t, snap.reports)


def test_risk_deadline_and_ordering(store):
    _, _, risks, _ = _step(store, "21:00")
    assert [k.priority for k in risks] == sorted((k.priority for k in risks), reverse=True)
    for k in risks:
        if k.arrival_p10_min is not None:
            assert k.deadline_min == pytest.approx(k.arrival_p10_min - SAFETY_MARGIN_MIN)
    needs = {r.id: r.needs for r in store.residents}
    assert not any(k.at_risk and needs[k.resident_id] == "none" for k in risks)


@pytest.mark.parametrize("router", ROUTERS)
@pytest.mark.parametrize("hhmm", TIMES)
def test_router_invariants(store, router, hhmm):
    snap, outlook, risks, plan = _step(store, hhmm, router)
    res = {r.id: r for r in snap.residents}
    veh = {v.id: v for v in snap.vehicles}
    shelters = {s.id: s for s in snap.shelters}
    at_risk = {k.resident_id for k in risks if k.at_risk}
    routed = [s for route in plan.routes for s in route.stops if s in res]

    # Never dropped silently: every at-risk person is routed exactly once or escalated.
    assert len(routed) == len(set(routed)), "someone is picked up twice"
    assert set(routed) | set(plan.unreachable) == at_risk
    assert not set(routed) & set(plan.unreachable)
    assert at_risk <= set(plan.reasons), "every decision has a plain-language reason"
    # Fire-command escalations are a subset of unreachable, and say so in their reason.
    assert set(plan.escalated_fire_command) <= set(plan.unreachable)
    assert all("fire command" in plan.reasons[r] for r in plan.escalated_fire_command)

    for route in plan.routes:
        v = veh[route.vehicle]
        assert route.eta_min == sorted(route.eta_min), "ETAs must not go back in time"
        seats = wheel = stretch = 0
        for stop in route.stops:
            if stop in shelters:
                seats = wheel = stretch = 0  # everyone gets off
                continue
            r = res[stop]
            assert v.type in r.vehicle_types, f"{r.id} can't ride a {v.type}"
            s, w, x = capacity_demand(r)
            seats, wheel, stretch = seats + s, wheel + w, stretch + x
            assert seats <= v.seats and wheel <= v.wheelchair_spaces
            assert stretch <= v.stretcher_spaces
        assert route.stops[-1] in shelters, "every run ends at a shelter"


@pytest.mark.parametrize("router", ROUTERS)
@pytest.mark.parametrize("hhmm", TIMES)
def test_router_driver_safety(store, router, hhmm):
    """For every hex a vehicle occupies: time it leaves + margin <= plausible fire arrival."""
    snap, outlook, risks, plan = _step(store, hhmm, router)
    res = {r.id: r for r in snap.residents}
    shelters = {s.id: s for s in snap.shelters}
    veh = {v.id: v for v in snap.vehicles}
    risk = {k.resident_id: k for k in risks}
    safety = SafetyMap(outlook)
    travel = StraightLineTravel()

    for route in plan.routes:
        v = veh[route.vehicle]
        pos, depart = (v.lat, v.lon), v.available_in_min
        for stop, eta in zip(route.stops, route.eta_min, strict=True):
            here_obj = res.get(stop) or shelters[stop]
            here = (here_obj.lat, here_obj.lon)
            assert safety.leg_ok(pos, here, depart, travel.minutes(pos, here)), (
                f"{route.vehicle} drives through danger on the way to {stop}"
            )
            if stop in res:
                leave = eta + res[stop].load_minutes
                assert safety.hex_ok(res[stop].h3, leave), f"{stop} picked up too late"
                deadline = risk[stop].deadline_min
                assert deadline is None or leave <= deadline + 0.1
            else:
                leave = eta + UNLOAD_MIN
            pos, depart = here, leave
