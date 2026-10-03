"""The replay over time: vehicles move, pick people up, and never break the rules doing it."""

from __future__ import annotations

from datetime import timedelta

import pytest

from backend.replay import Replay
from engines.routing import plan_routes_dispatcher

from .conftest import pt


@pytest.fixture
def frames(store):
    return Replay(store).run()


def test_people_get_picked_up(frames):
    assert len(frames[-1].picked_up) > 0
    counts = [len(f.picked_up) for f in frames]
    assert counts == sorted(counts), "a pickup is never undone"


def test_only_known_people_are_picked_up_after_they_were_known(store, frames):
    known = {r.id: r.known_at for r in store.residents}
    for rid, when in frames[-1].picked_up.items():
        assert rid in known
        assert known[rid] is None or known[rid] <= when


def test_vehicles_move(frames):
    positions = {(v.id, v.lat, v.lon) for f in frames for v in f.vehicles}
    assert len(positions) > len(frames[0].vehicles), "vehicles never left the depot"


def test_nobody_is_planned_twice(frames):
    for f in frames:
        planned = [s for r in f.plan.routes for s in r.stops if not s.startswith("shelter")]
        on_runs = [s for r in f.schedule for s in r.stops if not s.startswith("shelter")]
        assert len(planned) == len(set(planned))
        assert len(on_runs) == len(set(on_runs)), "two vehicles are heading to the same person"
        assert not set(on_runs) & set(f.picked_up), "someone is picked up twice"


def test_plans_wait_for_approval(store):
    replay = Replay(store, approval_delay_min=20)
    frames = replay.run()
    plan_times = {f.plan.t for f in frames}
    assert len(plan_times) < len(frames), "with a 20-min delay, not every step makes a plan"
    for f in frames:
        assert f.plan_takes_effect_at == f.plan.t + timedelta(minutes=20)


def test_between_steps_matches_known_people(store):
    replay = Replay(store)
    a = replay.frame_at(pt("21:00"))
    b = replay.frame_at(pt("21:05"))
    assert b.snapshot.t == pt("21:05")
    assert set(a.picked_up) <= set(b.picked_up)


def test_any_planner_can_drive_the_replay(store):
    frames = Replay(store, planner=plan_routes_dispatcher).run()
    assert frames[-1].plan.strategy == "dispatcher_rule"
    assert len(frames[-1].picked_up) > 0


def test_replay_is_deterministic(store):
    a = Replay(store).run()[-1].picked_up
    b = Replay(store).run()[-1].picked_up
    assert a == b
