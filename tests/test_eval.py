"""The stand-in evaluation: a pickup only counts if it beat the fire."""

from __future__ import annotations

from evaluation.standin import fire_arrival, score

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
