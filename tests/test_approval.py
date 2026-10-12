"""Manager mode: a plan only moves vehicles once a person approves (or edits) it."""

from __future__ import annotations

from datetime import timedelta

import pytest

from backend.replay import Replay
from backend.schemas import Decision, PlanChange


@pytest.fixture
def setup(store):
    decisions: list[Decision] = []
    replay = Replay(store, decisions=lambda: decisions)
    first = next(f for f in replay.run() if f.plan.routes)  # first plan that sends anyone
    return replay, decisions, first


def _decide(replay, decisions, frame, action="approve", changes=(), late_min=0):
    d = Decision(plan_id=frame.plan.plan_id, action=action, changes=list(changes),
                 t=frame.plan.t + timedelta(minutes=late_min))
    assert replay.check_decision(d) is None
    decisions.append(d)
    replay.invalidate_from(d.t)
    return d


def test_without_a_decision_nothing_moves(setup):
    replay, _, _ = setup
    frames = replay.run()
    assert all(not f.picked_up and not f.schedule for f in frames)
    assert {f.plan_status for f in frames} <= {"awaiting_decision", "expired"}
    assert len({f.plan.plan_id for f in frames}) == len(frames), "a fresh plan every step"


def test_approved_plan_is_followed(setup):
    replay, decisions, first = setup
    _decide(replay, decisions, first)
    f = replay.frame_at(first.plan.t)
    assert f.plan_status == "approved" and f.schedule
    later = replay.run()[-1]
    assert set(later.picked_up) & {s for r in first.plan.routes for s in r.stops}


def test_rejected_plan_sends_nobody(setup):
    replay, decisions, first = setup
    _decide(replay, decisions, first, "reject")
    f = replay.frame_at(first.plan.t)
    assert f.plan_status == "rejected" and not f.schedule


def test_held_vehicle_stays_put(setup):
    replay, decisions, first = setup
    held = first.plan.routes[0].vehicle
    _decide(replay, decisions, first, "modify", [PlanChange(kind="hold_vehicle", vehicle=held)])
    f = replay.frame_at(first.plan.t)
    assert f.plan_status == "modified"
    assert held not in {r.vehicle for r in f.schedule}


def test_removed_person_is_not_picked_up_on_that_plan(setup):
    replay, decisions, first = setup
    rid = next(s for s in first.plan.routes[0].stops if not s.startswith("shelter"))
    _decide(replay, decisions, first, "modify", [PlanChange(kind="remove_stop", resident=rid)])
    f = replay.frame_at(first.plan.t)
    assert rid not in {s for r in f.schedule for s in r.stops}


def test_a_vehicle_that_cant_carry_someone_is_refused(setup, store):
    replay, _, first = setup
    bedbound = next((r for r in store.residents if r.needs == "bedbound"), None)
    van = next((v for v in store.vehicles if v.type == "wheelchair_van"), None)
    if bedbound is None or van is None or bedbound.id not in {
            r.id for r in store.at(first.plan.t).residents}:
        pytest.skip("fixture has no known bedbound resident at this time")
    d = Decision(plan_id=first.plan.plan_id, action="modify", t=first.plan.t, changes=[
        PlanChange(kind="reassign", resident=bedbound.id, vehicle=van.id)])
    status, message = replay.check_decision(d)
    assert status == 422 and "can't carry" in message


def test_approval_later_in_the_step_starts_vehicles_later(setup):
    replay, decisions, first = setup
    _decide(replay, decisions, first, late_min=7)
    f = replay.frame_at(first.plan.t + timedelta(minutes=7))
    assert f.plan_takes_effect_at == first.plan.t + timedelta(minutes=7)
    for route in f.schedule:
        assert min(route.eta_min) >= 5, "nothing starts before approval plus the dispatch delay"


def test_an_undecided_new_plan_does_not_cancel_approved_work(setup):
    replay, decisions, first = setup
    _decide(replay, decisions, first)
    approved = {s for r in replay.frame_at(first.plan.t).schedule for s in r.stops}
    nxt = replay.frame_at(first.plan.t + replay.clock.step)
    assert nxt.plan_status == "awaiting_decision"
    still = {s for r in nxt.schedule for s in r.stops} | set(nxt.picked_up)
    assert approved <= still
