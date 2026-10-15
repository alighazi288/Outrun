"""The stand-in evaluation: a pickup only counts if it beat the fire."""

from __future__ import annotations

from datetime import timedelta

from backend.replay import Replay
from evaluation.arrival_window import perfect_forecast
from evaluation.standin import arrival_windows, fire_arrival, outcome, score

from .conftest import pt


def test_pickup_counts_only_before_the_fire(store):
    person = next(r for r in store.population if r.needs != "none")
    arrival = {person.h3: pt("22:00")}
    assert score([person], {person.id: pt("21:50")}, arrival).saved == 1
    assert score([person], {person.id: pt("22:10")}, arrival).saved == 0, "too late"
    assert score([person], {}, arrival).saved == 0, "never picked up"


def test_only_people_the_fire_reached_count(store):
    person = next(r for r in store.population if r.needs != "none")
    assert score([person], {person.id: pt("21:50")}, {}).reached == 0


def test_people_with_no_needs_are_excluded(store):
    able = [r for r in store.population if r.needs == "none"]
    arrival = {r.h3: pt("22:00") for r in able}
    assert score(able, {}, arrival).reached == 0


def test_fire_arrives_where_it_was_detected(store):
    d = store.detections[0]
    arrival = fire_arrival(store, {d.h3})
    assert arrival[d.h3] <= d.observed_at


def test_the_perfect_forecast_knows_when_each_hex_burns(store):
    windows = arrival_windows(store)
    cell, w = next(iter(windows.items()))
    forecast = perfect_forecast(windows)
    before = {o.h3: o for o in forecast([], [], store.cells, w.earliest - timedelta(minutes=90))}
    assert before[cell].arrival_p10_min == 90 and not before[cell].burning
    assert (before[cell].p_1h, before[cell].p_2h) == (0, 1)
    at = {o.h3: o for o in forecast([], [], store.cells, w.earliest)}
    assert at[cell].burning
    assert set(at) <= set(windows), "a hex the fire never reached is never forecast"


def test_with_a_perfect_forecast_no_trip_goes_where_the_fire_never_came(store):
    windows = arrival_windows(store)
    final = Replay(store, forecast=perfect_forecast(windows)).run()[-1]
    o = outcome(store.population, final.picked_up, windows)
    assert o.in_time > 0
    assert o.fire_never_came == 0 and o.too_late == 0
    taken = sum(r.needs != "none" for r in store.population if r.id in final.picked_up)
    assert o.in_time + o.too_late + o.fire_never_came == taken
